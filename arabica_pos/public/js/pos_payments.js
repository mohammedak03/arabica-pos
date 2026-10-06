/*
 * Arabica POS card-terminal checkout integration.
 *
 * Milestone scope:
 * - generic POS mode-of-payment name: "Card"
 * - provider: mock
 * - default mock scenario: approved
 *
 * ERPNext's own Complete Order validation remains untouched. This file wraps
 * Payment.events.submit_invoice so a positive Card payment must be approved
 * before ERPNext's original invoice submission callback is allowed to run.
 */

(function () {
	const CARD_MODE_OF_PAYMENT = "Card";
	const DEFAULT_PROVIDER = "mock";
	const DEFAULT_MOCK_SCENARIO = "approved";

	function get_card_amount(doc) {
		return (doc.payments || [])
			.filter(
				(payment) =>
					payment.mode_of_payment === CARD_MODE_OF_PAYMENT &&
					flt(payment.amount) > 0
			)
			.reduce((total, payment) => total + flt(payment.amount), 0);
	}

	function get_attempt_signature(doc, card_amount) {
		const items = (doc.items || []).map((item) => ({
			item_code: item.item_code,
			qty: flt(item.qty),
			rate: flt(item.rate),
			amount: flt(item.amount),
		}));

		return JSON.stringify({
			invoice: doc.name || "new-pos-invoice",
			currency: doc.currency || "JOD",
			card_amount: flt(card_amount),
			grand_total: flt(doc.grand_total),
			items,
		});
	}

	function clear_attempt(payment) {
		payment._arabica_card_attempt = null;
	}

	function ensure_attempt(payment, doc, card_amount) {
		const signature = get_attempt_signature(doc, card_amount);
		const existing = payment._arabica_card_attempt;

		if (existing?.signature === signature) {
			return existing;
		}

		const random_part =
			typeof crypto !== "undefined" && crypto.randomUUID
				? crypto.randomUUID()
				: `${Date.now()}-${Math.random().toString(16).slice(2)}`;

		const attempt = {
			signature,
			idempotency_key: `pos-card:${doc.name || "new-pos-invoice"}:${card_amount}:${random_part}`,
			status: "CREATED",
			result: null,
		};

		payment._arabica_card_attempt = attempt;
		return attempt;
	}

	function show_declined(result) {
		frappe.msgprint({
			title: __("Card Payment Declined"),
			indicator: "red",
			message: frappe.utils.escape_html(
				result.message || __("The card payment was declined.")
			),
		});
		frappe.utils.play_sound("error");
	}

	function show_timeout(result) {
		frappe.msgprint({
			title: __("Card Payment Status Unknown"),
			indicator: "orange",
			message: __(
				"The terminal did not return a final result. Do not charge the card again until the transaction status is checked."
			),
		});
		frappe.utils.play_sound("error");
		console.warn("Arabica card payment timeout:", result);
	}

	async function request_card_payment(attempt, doc, amount) {
		const response = await frappe.call({
			method: "arabica_pos.payments.api.initiate_payment",
			args: {
				amount: amount.toFixed(3),
				currency: doc.currency || "JOD",
				idempotency_key: attempt.idempotency_key,
				provider: DEFAULT_PROVIDER,
				scenario: window.arabicaMockCardScenario || DEFAULT_MOCK_SCENARIO,
				reference: doc.name || "POS Invoice",
			},
			freeze: true,
			freeze_message: __("Waiting for card terminal..."),
		});

		return response.message;
	}

	function patch_payment_submit(Payment) {
		if (Payment.prototype.__arabica_card_submit_patched) return;
		Payment.prototype.__arabica_card_submit_patched = true;

		const original_bind_events = Payment.prototype.bind_events;

		Payment.prototype.bind_events = function () {
			if (!this.__arabica_submit_invoice_wrapped) {
				this.__arabica_submit_invoice_wrapped = true;

				const original_submit_invoice = this.events.submit_invoice;

				this.events.submit_invoice = async (...args) => {
					const doc = this.events.get_frm().doc;
					const card_amount = get_card_amount(doc);

					if (card_amount <= 0) {
						clear_attempt(this);
						return original_submit_invoice(...args);
					}

					const attempt = ensure_attempt(this, doc, card_amount);

					// If the terminal already approved this exact invoice/payment
					// attempt, never charge again. Re-run only ERPNext submission.
					// This protects against a save/submit failure after approval.
					if (attempt.status === "APPROVED") {
						return original_submit_invoice(...args);
					}

					// TIMEOUT/PENDING is intentionally sticky. The next milestone
					// will resolve it with check_status; never auto-initiate again.
					if (attempt.status === "TIMEOUT" || attempt.status === "PENDING") {
						show_timeout(attempt.result || {});
						return;
					}

					if (this._arabica_card_payment_in_flight) {
						frappe.show_alert({
							message: __("Card payment is already in progress."),
							indicator: "orange",
						});
						return;
					}

					this._arabica_card_payment_in_flight = true;

					try {
						const result = await request_card_payment(attempt, doc, card_amount);

						if (!result || !result.status) {
							throw new Error("Card provider returned an invalid response.");
						}

						attempt.status = result.status;
						attempt.result = result;

						if (result.status === "APPROVED") {
							frappe.show_alert({
								message: __("Card payment approved."),
								indicator: "green",
							});

							// Do not clear the approved attempt here. ERPNext's
							// current submit_invoice callback does not return its
							// savesubmit Promise. Keeping this marker prevents a
							// second charge if invoice submission later fails.
							return original_submit_invoice(...args);
						}

						if (result.status === "DECLINED") {
							show_declined(result);
							// A cashier retry after a real decline is a fresh
							// terminal attempt and receives a new idempotency key.
							clear_attempt(this);
							return;
						}

						if (result.status === "TIMEOUT" || result.status === "PENDING") {
							show_timeout(result);
							return;
						}

						frappe.msgprint({
							title: __("Card Payment Failed"),
							indicator: "red",
							message: frappe.utils.escape_html(
								result.message ||
									__("The card payment could not be completed.")
							),
						});
						clear_attempt(this);
					} catch (error) {
						console.error("Arabica card payment error:", error);
						frappe.msgprint({
							title: __("Card Payment Error"),
							indicator: "red",
							message: __(
								"Could not communicate with the card-payment service. The invoice was not submitted."
							),
						});

						// Keep the same attempt/idempotency key after a transport
						// error because the provider may have received the request.
						// A later milestone will resolve ambiguous outcomes through
						// check_status instead of creating a new charge.
						attempt.status = "PENDING";
						attempt.result = {
							status: "PENDING",
							message: "Payment status must be checked before retrying.",
						};
					} finally {
						this._arabica_card_payment_in_flight = false;
					}
				};
			}

			return original_bind_events.call(this);
		};
	}

	const original_on_page_load = frappe.pages["point-of-sale"].on_page_load;

	frappe.pages["point-of-sale"].on_page_load = function (wrapper) {
		frappe.require("point-of-sale.bundle.js").then(function () {
			patch_payment_submit(erpnext.PointOfSale.Payment);
			original_on_page_load(wrapper);
		});
	};
})();