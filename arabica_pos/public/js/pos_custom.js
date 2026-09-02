// Arabica POS customization: size-picker for grouped Item Template cards.
//
// The product-card grouping itself (showing one "Latte" card instead of
// Latte-S / Latte-M / Latte-L) happens server-side - see
// arabica_pos.overrides.pos.get_items, hooked in via
// override_whitelisted_methods in hooks.py. erpnext's own (unmodified)
// pos_item_selector.js renders whatever get_items returns, so once the
// server sends one merged card per template, core code already renders it
// as a single card with no JS changes needed for that part.
//
// This file only adds the click behaviour for that merged card: instead
// of adding it to the cart directly (it's an Item Template, ERPNext would
// reject that), a small dialog opens with one button per size. Choosing a
// size calls cur_pos.on_cart_update(...) with the real variant item_code
// - the exact same call erpnext.PointOfSale.ItemSelector's own click
// handler makes for an ordinary card - so pricing, tax, Product Bundle
// behaviour, and stock all go through the standard POS cart flow.
//
// Loaded on the "point-of-sale" page only, via the page_js hook in
// hooks.py. No core ERPNext/Frappe file is modified or monkey-patched.

frappe.provide("arabica_pos.pos");

// Item codes of Item Templates grouped into one POS card. Must match
// arabica_pos.overrides.pos.POS_GROUPED_TEMPLATES on the server.
// First iteration: only "Latte" (FG-LATTE).
arabica_pos.pos.GROUPED_TEMPLATE_ITEM_CODES = ["FG-LATTE"];

(function () {
	function get_active_item_selector() {
		if (!window.cur_pos || !cur_pos.item_selector) return null;
		if (!cur_pos.item_selector.$component || !cur_pos.item_selector.$component.length) return null;
		return cur_pos.item_selector;
	}

	function find_card_data(item_selector, item_code) {
		return (item_selector.items || []).find((i) => i.item_code === item_code);
	}

	function add_variant_to_cart(variant) {
		if (!variant.rate) {
			frappe.show_alert({ message: __("Price is not set for the item."), indicator: "orange" });
			frappe.utils.play_sound("error");
			return;
		}

		// Same shape ItemSelector's own click handler passes to
		// events.item_selected -> Controller.on_cart_update. This adds a
		// real POS Invoice Item row for the chosen variant, no different
		// from clicking a normal product card.
		cur_pos.on_cart_update({
			field: "qty",
			value: "+1",
			item: {
				item_code: variant.item_code,
				batch_no: variant.batch_no,
				serial_no: variant.serial_no,
				uom: variant.uom,
				rate: variant.rate,
				stock_uom: variant.stock_uom,
			},
		});
	}

	function open_size_dialog(card_data) {
		const options = card_data.pos_variant_options || [];
		if (!options.length) {
			frappe.show_alert({ message: __("No sizes available for this item."), indicator: "orange" });
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: card_data.item_name || __("Select Size"),
			fields: [{ fieldtype: "HTML", fieldname: "arabica_pos_sizes" }],
		});

		const $wrapper = dialog.fields_dict.arabica_pos_sizes.$wrapper;
		options.forEach((variant) => {
			const $btn = $(`<button type="button" class="btn btn-default btn-block"
				style="margin-bottom: 8px; text-align: left;"></button>`).text(variant.label);
			$btn.on("click", () => {
				dialog.hide();
				add_variant_to_cart(variant);
			});
			$wrapper.append($btn);
		});

		dialog.show();
	}

	// Bound on `document` in the CAPTURE phase, which always runs before
	// any bubble-phase listener on a descendant element - including
	// ItemSelector's own `this.$component.on("click", ".item-wrapper", ...)`
	// delegate (bound in bubble phase on `.items-selector`). That makes
	// interception deterministic regardless of exactly when the POS
	// bundle finishes loading relative to this script, without needing to
	// monkey-patch erpnext.PointOfSale.ItemSelector at all.
	document.addEventListener(
		"click",
		function (evt) {
			if (!arabica_pos.pos.GROUPED_TEMPLATE_ITEM_CODES.length) return;

			const item_selector = get_active_item_selector();
			if (!item_selector) return;

			const $item_wrapper = evt.target.closest && evt.target.closest(".item-wrapper");
			if (!$item_wrapper) return;
			if (!item_selector.$component[0].contains($item_wrapper)) return;

			const item_code = $item_wrapper.getAttribute("data-item-code");
			if (!arabica_pos.pos.GROUPED_TEMPLATE_ITEM_CODES.includes(item_code)) return;

			// Stop this specific click here; everything else (search,
			// other product cards, scanning, ...) is left untouched.
			evt.stopPropagation();
			evt.preventDefault();

			const card_data = find_card_data(item_selector, item_code);
			if (!card_data) return;

			open_size_dialog(card_data);
		},
		true
	);
})();
