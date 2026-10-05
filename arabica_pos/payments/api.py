import frappe
from frappe import _

from arabica_pos.payments.exceptions import PaymentError
from arabica_pos.payments.service import check_status as _check_status
from arabica_pos.payments.service import initiate_payment as _initiate_payment


@frappe.whitelist()
def initiate_payment(
    amount,
    currency="JOD",
    idempotency_key=None,
    provider="mock",
    scenario="approved",
    reference=None,
):
    """Start a card-payment attempt through the selected provider.

    Milestone 1 registers only the deterministic mock provider.
    This method never submits a POS Invoice.
    """
    try:
        return _initiate_payment(
            amount=amount,
            currency=currency,
            idempotency_key=idempotency_key,
            provider_name=provider,
            reference=reference,
            scenario=scenario,
        )
    except PaymentError as exc:
        frappe.throw(str(exc), title=_("Payment Error"))


@frappe.whitelist()
def check_status(provider_transaction_id, provider="mock"):
    """Query a provider transaction without creating a new payment attempt."""
    try:
        return _check_status(
            provider_transaction_id,
            provider_name=provider,
        )
    except PaymentError as exc:
        frappe.throw(str(exc), title=_("Payment Error"))