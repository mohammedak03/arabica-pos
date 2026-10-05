from decimal import Decimal, InvalidOperation

from arabica_pos.payments.exceptions import PaymentProviderError, PaymentValidationError
from arabica_pos.payments.providers.base import PaymentRequest
from arabica_pos.payments.providers.mock import MockPaymentProvider

_PROVIDERS = {
    "mock": MockPaymentProvider,
}


def get_provider(provider_name: str = "mock"):
    provider_key = str(provider_name or "").strip().lower()
    provider_class = _PROVIDERS.get(provider_key)

    if not provider_class:
        raise PaymentProviderError(f"Unsupported payment provider: {provider_key}")

    return provider_class()


def build_request(
    amount,
    currency: str,
    idempotency_key: str,
    reference: str | None = None,
) -> PaymentRequest:
    try:
        decimal_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaymentValidationError("Amount must be a valid number.") from exc

    if decimal_amount <= 0:
        raise PaymentValidationError("Amount must be greater than zero.")

    normalized_currency = str(currency or "").strip().upper()
    if len(normalized_currency) != 3 or not normalized_currency.isalpha():
        raise PaymentValidationError("Currency must be a 3-letter code.")

    normalized_key = str(idempotency_key or "").strip()
    if not normalized_key:
        raise PaymentValidationError("Idempotency key is required.")
    if len(normalized_key) > 128:
        raise PaymentValidationError(
            "Idempotency key must be 128 characters or fewer."
        )

    return PaymentRequest(
        amount=decimal_amount,
        currency=normalized_currency,
        idempotency_key=normalized_key,
        reference=str(reference).strip() if reference else None,
    )


def initiate_payment(
    amount,
    currency: str,
    idempotency_key: str,
    provider_name: str = "mock",
    reference: str | None = None,
    **provider_kwargs,
) -> dict:
    provider = get_provider(provider_name)
    request = build_request(amount, currency, idempotency_key, reference)
    return provider.initiate_payment(request, **provider_kwargs).as_dict()


def check_status(
    provider_transaction_id: str,
    provider_name: str = "mock",
) -> dict:
    provider = get_provider(provider_name)
    return provider.check_status(provider_transaction_id).as_dict()