"""Deribit API error types."""


class DeribitError(Exception):
    """Base exception for Deribit errors."""


class DeribitAPIError(DeribitError):
    """Error returned by the Deribit API.

    The Deribit JSON-RPC error payload has three fields: ``code`` (numeric),
    ``message`` (often generic, e.g. "Invalid params"), and ``data`` which
    is where the *specific* reason lives ("size_must_be_multiple_of_min_trade_amount",
    "param_below_min", actual min/max bounds, the offending param name, etc.).

    The string form intentionally surfaces ``data`` so that downstream
    consumers — including the AI agent — can self-correct from a single
    error without us hardcoding every Deribit rule in the system prompt.
    """

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        base = f"Deribit API error {code}: {message}"
        if data:
            try:
                import json as _json
                base = f"{base} (data: {_json.dumps(data, default=str)})"
            except Exception:  # noqa: BLE001
                base = f"{base} (data: {data!r})"
        super().__init__(base)


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
