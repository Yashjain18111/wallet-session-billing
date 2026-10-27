class DomainError(Exception):
    """Business-rule violation. Rendered as {"error": "..."} with `status_code`."""

    status_code = 400

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class InvalidTransition(DomainError):
    status_code = 400


class InsufficientBalance(DomainError):
    status_code = 400


class Forbidden(DomainError):
    status_code = 403
