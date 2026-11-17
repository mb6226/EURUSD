class FetchAdapterError(Exception):
    """Base exception for adapter failures."""


class FetchTransportError(FetchAdapterError):
    """Raised when a source cannot be reached or returns a transport error."""


class FetchParseError(FetchAdapterError):
    """Raised when raw source data cannot be parsed."""


class FetchValidationError(FetchAdapterError, ValueError):
    """Raised when parsed or normalized data violates its contract."""
