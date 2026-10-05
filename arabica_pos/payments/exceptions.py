class PaymentError(Exception):
    """Base error for card-terminal payment operations."""


class PaymentValidationError(PaymentError):
    """Raised when a payment request is invalid."""


class PaymentProviderError(PaymentError):
    """Raised when a payment provider cannot complete an operation."""