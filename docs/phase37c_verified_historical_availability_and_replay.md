# Phase 37C ? Verified Historical Availability & Replay Integration

## Objective

Add a separate, auditable reconstruction mode for what public market participants could have known by a historical cutoff. Preserve the existing strict system-knowledge mode without changing its retrieval-time rule.

## Two non-interchangeable replay modes

1. **System-knowledge as-of** (`PointInTimeObservationStore.get_as_of` / `get_many_as_of`): an observation is visible only when its effective, publication, and local retrieval timestamps satisfy the cutoff. This answers what this running system had actually retrieved.
2. **Reconstructed public-availability as-of** (`HistoricalAvailabilityLedger.read_public_availability_as_of`): local retrieval may occur later, but a specific observation version is eligible only with an append-only attestation tying its exact observation payload hash and original publication timestamp to archived evidence snapshots. This answers what was publicly available, not what this system knew.

Never backdate `retrieved_at_utc`, relax the existing strict query, or silently substitute one mode for the other.

## Attestation contract

Each attestation is per observation version and binds:
- source/product, observation key and version;
- exact canonical observation payload SHA-256 and publication timestamp;
- at least two immutable raw evidence snapshots, including snapshot IDs, source URLs, retrieval timestamps and payload hashes;
- explicit `AS_RELEASED_VALUE_VERIFIED` vintage status;
- attestor, method version, attestation time, and limitations.

The ledger rejects missing or mismatched observations, unknown evidence IDs, invalid snapshot hashes, missing publication time, non-verified/latest-only vintages, naive timestamps, and attestations dated before local retrieval. Attestations are append-only. Version 1 of the contract excludes revised observation versions until each revision has its own verified public-availability timestamp. Public replay returns the original local retrieval timestamp and labels every row `RECONSTRUCTED_PUBLIC_AVAILABILITY`.

The explicit vintage status is an accountable evidence-review assertion; merely archiving a current API response and a release calendar is not proof that the value equals the original as-released value. A revision-prone/current-latest observation must remain excluded until the original value vintage is independently demonstrated.

## Phase 37B evidence disposition

- CFTC TFF: official report-date/publication-date mappings and raw source snapshots exist. However, the current Socrata dataset response does not by itself prove every historical row is byte-for-byte the originally released value. Therefore **no production CFTC observations are attested by this phase**; they remain excluded from reconstructed public replay until value-vintage proof is reviewed.
- BLS CPI: API-only response where the official archive/schedule endpoints were blocked in the local acquisition attempt. No public-availability attestation.
- FRED/ALFRED, ECB SDMX, Eurostat, LBMA and other products: no attestations; do not infer historic vintages from latest values.

## Safety and scope

- No network requests or provider activation.
- No registry changes, source `auto_fetch` changes, observation DB migration, or edits to existing observations.
- No monitor restart, live order execution, risk-setting changes, or RAG mutation.
- The new attestation ledger is a separate file and is created only by an explicit attestation action; this phase's tests use temporary databases only.

## Acceptance tests

`tests/test_historical_availability.py` covers later local retrieval with earlier public publication, strict-mode preservation, unattested exclusion, publication cutoff, latest-only rejection, missing/unknown evidence, and timezone validation. Full-suite results are recorded after the phase acceptance run.
