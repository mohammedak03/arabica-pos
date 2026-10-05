import hashlib
from decimal import Decimal

from arabica_pos.payments.exceptions import PaymentProviderError
from arabica_pos.payments.providers.base import PaymentProvider, PaymentRequest, PaymentResult

_ALLOWED_SCENARIOS = {"approved", "declined", "timeout"}


class MockPaymentProvider(PaymentProvider):
    """Deterministic fake terminal used before any real provider is connected."""

    def initiate_payment(self, request: PaymentRequest, **kwargs) -> PaymentResult:
        scenario = str(kwargs.get("scenario") or "approved").strip().lower()
        if scenario not in _ALLOWED_SCENARIOS:
            raise PaymentProviderError(f"Unsupported mock scenario: {scenario}")

        fingerprint = self._fingerprint(request, scenario)
        transaction_id = f"MOCK-{scenario.upper()}-{fingerprint}"

        status = {
            "approved": "APPROVED",
            "declined": "DECLINED",
            "timeout": "TIMEOUT",
        }[scenario]

        message = {
            "approved": "Mock terminal approved the payment.",
            "declined": "Mock terminal declined the payment.",
            "timeout": "Mock terminal did not return a final result.",
        }[scenario]

        return PaymentResult(
            status=status,
            provider_transaction_id=transaction_id,
            amount=request.amount,
            currency=request.currency,
            message=message,
            rrn=self._mock_rrn(fingerprint) if status == "APPROVED" else None,
        )

    def check_status(self, provider_transaction_id: str) -> PaymentResult:
        scenario, _ = self._parse_transaction_id(provider_transaction_id)
        status = {
            "approved": "APPROVED",
            "declined": "DECLINED",
            "timeout": "TIMEOUT",
        }.get(scenario)

        if not status:
            raise PaymentProviderError("Unsupported mock transaction status.")

        return PaymentResult(
            status=status,
            provider_transaction_id=provider_transaction_id,
            message="Mock transaction status returned.",
        )

    def cancel_payment(self, provider_transaction_id: str) -> PaymentResult:
        self._parse_transaction_id(provider_transaction_id)
        return PaymentResult(
            status="CANCELLED",
            provider_transaction_id=provider_transaction_id,
            message="Mock payment cancelled.",
        )

    def refund_payment(
        self,
        provider_transaction_id: str,
        amount: Decimal | None = None,
    ) -> PaymentResult:
        _, fingerprint = self._parse_transaction_id(provider_transaction_id)
        return PaymentResult(
            status="REFUNDED",
            provider_transaction_id=f"MOCK-REFUND-{fingerprint}",
            amount=amount,
            message="Mock payment refunded.",
            rrn=self._mock_rrn(f"refund-{fingerprint}"),
        )

    @staticmethod
    def _fingerprint(request: PaymentRequest, scenario: str) -> str:
        payload = (
            f"{request.idempotency_key}|{request.amount}|"
            f"{request.currency}|{scenario}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    @staticmethod
    def _parse_transaction_id(provider_transaction_id: str) -> tuple[str, str]:
        parts = str(provider_transaction_id or "").split("-", 2)
        if len(parts) != 3 or parts[0] != "MOCK":
            raise PaymentProviderError("Invalid mock provider transaction id.")
        return parts[1].lower(), parts[2]

    @staticmethod
    def _mock_rrn(value: str) -> str:
        digest = hashlib.sha256(value.encode()).hexdigest()
        return str(int(digest[:12], 16)).zfill(12)[-12:]