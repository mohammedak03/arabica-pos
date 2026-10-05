from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

PaymentStatus = Literal[
    "CREATED",
    "PENDING",
    "APPROVED",
    "DECLINED",
    "TIMEOUT",
    "FAILED",
    "CANCELLED",
    "REFUNDED",
    "PARTIALLY_REFUNDED",
]


@dataclass(frozen=True)
class PaymentRequest:
    amount: Decimal
    currency: str
    idempotency_key: str
    reference: str | None = None


@dataclass(frozen=True)
class PaymentResult:
    status: PaymentStatus
    provider_transaction_id: str
    amount: Decimal | None = None
    currency: str | None = None
    message: str = ""
    rrn: str | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "provider_transaction_id": self.provider_transaction_id,
            "amount": str(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "message": self.message,
            "rrn": self.rrn,
        }


class PaymentProvider(ABC):
    @abstractmethod
    def initiate_payment(self, request: PaymentRequest, **kwargs) -> PaymentResult:
        pass

    @abstractmethod
    def check_status(self, provider_transaction_id: str) -> PaymentResult:
        pass

    @abstractmethod
    def cancel_payment(self, provider_transaction_id: str) -> PaymentResult:
        pass

    @abstractmethod
    def refund_payment(
        self,
        provider_transaction_id: str,
        amount: Decimal | None = None,
    ) -> PaymentResult:
        pass