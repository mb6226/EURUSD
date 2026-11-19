# Phase 15 — Point-in-Time Canonical Observation Store

## North Star capability advanced

Gate 1 — reliable canonical data plane. This phase establishes a shared, append-only persistence and as-of retrieval boundary for economic and other source-registry observations. It is intended to support quantitative/statistical, macro/fundamental, intermarket, positioning, and later sentiment specialists without coupling them to one provider.

## Repository gap addressed

The repository already has separate market-candle, macro-calendar, and news stores, plus a source registry and typed `Observation` / `FetchResult` adapter contracts. Those foundations do not yet provide a common persisted observation history with a strict historical-availability query. A current-value table alone is insufficient for reproducible research because source records can be revised and publication/retrieval times differ from effective dates.

## Deliverable

`source_registry/observation_store.py` adds a dependency-free SQLite store that accepts the existing source-registry `FetchResult` contract and records:

- source and product identity;
- effective, publication, and retrieval timestamps;
- decimal scalar/range value and unit;
- source record identity and source URL;
- immutable payload hash and append-only version history;
- fetch-batch provenance.

Repeated identical observations are idempotent. A changed payload for the same source/product/record identity appends a new version rather than overwriting history.

## Point-in-time semantics

A default `get_as_of(as_of_utc)` result is eligible only when:

1. retrieval time is known and no later than the requested cutoff;
2. publication time is known and no later than the cutoff;
3. effective time is no later than the cutoff.

Unknown publication time is excluded by default because historical public availability cannot be proven. Future-effective records can be requested explicitly for use cases such as published schedules. For each observation identity, the query selects the latest version that was both published and retrieved by the cutoff; a revision retrieved later cannot leak into an earlier replay.

All timestamps must be timezone-aware and are normalized to UTC. Values are serialized without binary floating-point conversion. Observation and fetch-batch rows are protected by SQLite append-only triggers.

## Integration boundary

The store consumes the existing `FetchResult` produced by source adapters. It does not introduce a second provider framework or scheduler. The next integration step is to connect the source execution/orchestration layer to this sink and then map approved macro/fundamental/intermarket feeds into registered products. Existing MT5 candle storage, macro-calendar storage, news storage, runtime orchestration, and RAG/knowledge databases are deliberately untouched in this phase.

## Acceptance criteria

- Store initialization is idempotent and schema-version guarded.
- Persisted values retain exact decimal text and complete source provenance.
- Identical fetches do not create duplicate observation versions.
- Revisions append and historical as-of queries return the version available at that cutoff.
- Records fetched or published after the cutoff are excluded.
- Unknown publication timestamps are excluded by default.
- Naive timestamps, invalid fetch results, and source/product identity violations fail closed.
- Append-only triggers reject update/delete operations.
- Full existing regression suite plus focused observation-store tests pass on the exact PR head SHA.

## Explicit non-goals

- No automatic network fetching, scheduler, retries, or source activation.
- No new macro/fundamental/intermarket interpretation or directional scoring.
- No modification of existing market, calendar, news, or RAG databases.
- No MT5 runtime behavior, strategy parameters, BUY/SELL authority, risk changes, or order execution.
- No claim that this store alone completes the canonical data plane.
