"""Shared contracts for source data fetch adapters."""

from .base import FetchAdapter
from .exceptions import (
    FetchAdapterError,
    FetchParseError,
    FetchTransportError,
    FetchValidationError,
)
from .models import DecimalRange, FetchRequest, FetchResult, Observation
from .macro_series import OfficialMacroSeriesAdapter

__all__ = [
    "FetchAdapter",
    "FetchAdapterError",
    "FetchParseError",
    "FetchRequest",
    "FetchResult",
    "FetchTransportError",
    "FetchValidationError",
    "DecimalRange",
    "Observation",
    "OfficialMacroSeriesAdapter",
]
