from typing import Any


class LMSError(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: Any = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class NotFoundError(LMSError):
    status_code = 404
    error_code = "NOT_FOUND"


class DuplicatePaymentError(LMSError):
    status_code = 409
    error_code = "DUPLICATE_PAYMENT"


class CoolingOffExpiredError(LMSError):
    status_code = 403
    error_code = "COOLING_OFF_EXPIRED"


class LoanNotActiveError(LMSError):
    status_code = 422
    error_code = "LOAN_NOT_ACTIVE"


class ValidationError(LMSError):
    status_code = 422
    error_code = "VALIDATION_ERROR"


class TenantMismatchError(LMSError):
    status_code = 403
    error_code = "TENANT_MISMATCH"
