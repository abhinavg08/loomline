class LoomlineError(Exception):
    """Safe HTTP error. No request, response payload or secret is retained."""
    def __init__(self, code="REQUEST_FAILED", status_code=0, operation_id=None):
        self.code=code;self.status_code=status_code;self.operation_id=operation_id
        super().__init__(f"{code} (HTTP {status_code})")

class AuthenticationError(LoomlineError):pass
class AuthorizationError(LoomlineError):pass
class NotFoundError(LoomlineError):pass
class ConflictError(LoomlineError):pass
class ValidationError(LoomlineError):pass
class RateLimitError(LoomlineError):pass
class CommitOutcomeUnknown(LoomlineError):pass
class ServiceUnavailable(LoomlineError):pass

ERRORS={400:ValidationError,401:AuthenticationError,403:AuthorizationError,404:NotFoundError,409:ConflictError,422:ValidationError,429:RateLimitError,503:ServiceUnavailable,504:CommitOutcomeUnknown}
