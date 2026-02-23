"""Custom exception classes for the Pharmacy Auditor application."""


class AppError(Exception):
    """Base exception for application errors. Carries an HTTP status code and error code."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", status: int = 500):
        super().__init__(message)
        self.code = code
        self.status = status


class AuditNotFoundError(AppError):
    """Raised when an audit entry cannot be found or has been soft-deleted."""

    def __init__(self, audit_id=None):
        msg = f"Audit entry {audit_id} not found" if audit_id else "Audit entry not found"
        super().__init__(msg, code="NOT_FOUND", status=404)
        self.audit_id = audit_id


class DuplicateEntryError(AppError):
    """Raised when an insert would violate a uniqueness constraint."""

    def __init__(self, date: str = "", store: str = "", reg: str = ""):
        msg = f"Duplicate: a record for {date} / {store} / {reg} already exists."
        super().__init__(msg, code="DUPLICATE", status=409)


class StoreMismatchError(AppError):
    """Raised when a user tries to access/modify data from another store."""

    def __init__(self, user_store: str = "", target_store: str = ""):
        msg = "Not authorized to access entries from another store"
        super().__init__(msg, code="STORE_MISMATCH", status=403)
        self.user_store = user_store
        self.target_store = target_store


class ValidationError(AppError):
    """Raised when input data fails validation."""

    def __init__(self, message: str):
        super().__init__(message, code="INVALID_INPUT", status=400)


class DatabaseUnavailableError(AppError):
    """Raised when the database is unreachable and offline queue is not available."""

    def __init__(self):
        super().__init__(
            "Database is currently unavailable. Please try again shortly.",
            code="DB_UNAVAILABLE",
            status=503,
        )


class ReviewConflictError(AppError):
    """Raised when a Z-report review operation conflicts with current state."""

    def __init__(self, message: str):
        super().__init__(message, code="CONFLICT", status=409)
