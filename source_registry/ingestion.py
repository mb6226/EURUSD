from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .adapters.base import FetchAdapter
from .adapters.models import FetchRequest, FetchResult
from .observation_store import PersistSummary, PointInTimeObservationStore


class SourceIngestionError(RuntimeError):
    """Base error for controlled source-to-store ingestion."""


class SourceNotRegisteredError(SourceIngestionError):
    """The requested source is absent from the validated registry."""


class ProductNotRegisteredError(SourceIngestionError):
    """The requested product is absent from its registered source."""


class SourceDisabledError(SourceIngestionError):
    """The requested source is disabled in the registry."""


class AdapterNotRegisteredError(SourceIngestionError):
    """No adapter is explicitly registered for the requested source/product."""


class IngestionValidationError(SourceIngestionError):
    """An adapter returned data that violates the ingestion contract."""


@dataclass(frozen=True)
class IngestionSummary:
    source_id: str
    product_id: str
    retrieved_at_utc: datetime
    observations_received: int
    persistence: PersistSummary


class SourceObservationIngestion:
    """Manually execute one registered adapter and persist its point-in-time data.

    The registry document must already have passed load_registry validation.
    Adapter selection is explicit and keyed by (source_id, product_id). This
    service does not perform network I/O itself, schedule work, retry failures,
    or enable registry auto-fetch. The adapter owns transport/parsing; this
    layer validates identity, stamps retrieval time, and persists the result.
    """

    def __init__(
        self,
        *,
        registry: Mapping[str, Any],
        adapters: Mapping[tuple[str, str], FetchAdapter],
        store: PointInTimeObservationStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(registry, Mapping):
            raise TypeError("registry must be a validated registry mapping")
        sources = registry.get("sources")
        if not isinstance(sources, list):
            raise ValueError("registry must contain a sources list")

        self._sources: dict[str, Mapping[str, Any]] = {}
        for source in sources:
            if not isinstance(source, Mapping):
                raise ValueError("registry sources must contain objects")
            source_id = source.get("source_id")
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("registry source_id values must be non-empty")
            if source_id in self._sources:
                raise ValueError(f"duplicate registry source_id: {source_id}")
            self._sources[source_id] = source

        self._adapters = dict(adapters)
        for key, adapter in self._adapters.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or not all(isinstance(part, str) and part.strip() for part in key)
            ):
                raise ValueError("adapter keys must be (source_id, product_id)")
            if not callable(getattr(adapter, "fetch", None)):
                raise TypeError(f"adapter for {key!r} must provide fetch(request)")

        if not callable(getattr(store, "persist_fetch_result", None)):
            raise TypeError("store must provide persist_fetch_result(result)")
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def ingest(
        self,
        source_id: str,
        product_id: str,
        *,
        since: datetime | None = None,
    ) -> IngestionSummary:
        source = self._sources.get(source_id)
        if source is None:
            raise SourceNotRegisteredError(f"source is not registered: {source_id}")

        if source.get("enabled") is not True:
            raise SourceDisabledError(f"source is disabled: {source_id}")

        products = source.get("products")
        if not isinstance(products, list) or not any(
            isinstance(product, Mapping)
            and product.get("product_id") == product_id
            for product in products
        ):
            raise ProductNotRegisteredError(
                f"product {product_id!r} is not registered for {source_id!r}"
            )

        adapter = self._adapters.get((source_id, product_id))
        if adapter is None:
            raise AdapterNotRegisteredError(
                f"no adapter registered for {source_id}/{product_id}"
            )

        request = FetchRequest(
            source_id=source_id,
            product_id=product_id,
            since=since,
        )
        result = adapter.fetch(request)
        if not isinstance(result, FetchResult):
            raise IngestionValidationError(
                "adapter must return a FetchResult instance"
            )
        try:
            result.validate()
        except (TypeError, ValueError) as exc:
            raise IngestionValidationError(
                f"adapter returned an invalid FetchResult: {exc}"
            ) from exc

        if result.source_id != source_id or result.product_id != product_id:
            raise IngestionValidationError(
                "adapter result source/product identity does not match request"
            )

        retrieved_at = self._clock()
        if not isinstance(retrieved_at, datetime):
            raise TypeError("ingestion clock must return a datetime")
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("ingestion clock must return a timezone-aware datetime")
        retrieved_at = retrieved_at.astimezone(timezone.utc)

        stamped_result = result.with_retrieved_at(retrieved_at)
        if any(
            observation.published_at_utc is not None
            and observation.published_at_utc > retrieved_at
            for observation in stamped_result.observations
        ):
            raise IngestionValidationError(
                "adapter returned an observation published after its retrieval time"
            )
        persistence = self._store.persist_fetch_result(stamped_result)
        return IngestionSummary(
            source_id=source_id,
            product_id=product_id,
            retrieved_at_utc=retrieved_at,
            observations_received=len(stamped_result.observations),
            persistence=persistence,
        )
