from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import FetchRequest, FetchResult


@runtime_checkable
class FetchAdapter(Protocol):
    def fetch(self, request: FetchRequest) -> FetchResult:
        """Return observations; the execution layer stamps retrieval time."""
        ...
