"""Deribit API error types."""


class DeribitError(Exception):
    """Base exception for Deribit errors."""


class DeribitAPIError(DeribitError):
    """Error returned by the Deribit API."""

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"Deribit API error {code}: {message}")


class DeribitConnectionError(DeribitError):
    """Connection-related error."""


class DeribitTimeoutError(DeribitError):
    """Request timeout error."""


class DeribitAuthError(DeribitError):
    """Authentication error."""


# Common error codes
RATE_LIMITED = 10028
AUTHORIZATION_REQUIRED = 10000
UNAUTHORIZED = 13009
NOT_ENOUGH_FUNDS = 10009
