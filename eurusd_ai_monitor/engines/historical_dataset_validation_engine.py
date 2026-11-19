from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from eurusd_ai_monitor.storage.market_data_store import (
    TIMEFRAME_SECONDS,
    MarketDataStore,
)


def _aware_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


class HistoricalDatasetValidationEngine:
    """Read-only market archive audit and leakage-resistant chronological splits."""

    VERSION = "1.0.0"

    def __init__(self, store: MarketDataStore) -> None:
        if not isinstance(store, MarketDataStore):
            raise TypeError("store must be a MarketDataStore")
        self._store = store

    def audit(
        self,
        *,
        broker_server: str,
        symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
        max_revision_scan: int = 100000,
    ) -> dict[str, Any]:
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError("timeframe must be M1 or M5")
        start = _aware_utc(start_utc, "start_utc")
        end = _aware_utc(end_utc, "end_utc")
        if start >= end:
            raise ValueError("start_utc must be earlier than end_utc")
        if int(start.timestamp()) % TIMEFRAME_SECONDS[timeframe]:
            raise ValueError("start_utc must align to the timeframe boundary")
        if isinstance(max_revision_scan, bool) or not isinstance(max_revision_scan, int) or max_revision_scan <= 0:
            raise ValueError("max_revision_scan must be a positive integer")

        seconds = TIMEFRAME_SECONDS[timeframe]
        interval = timedelta(seconds=seconds)
        first_slot = int(start.timestamp()) // seconds
        last_slot = (int(end.timestamp()) - 1) // seconds
        expected = max(0, last_slot - first_slot + 1)
        candles = self._store.get_closed_candles(
            broker_server, symbol, timeframe, start_utc=start, end_utc=end
        )
        times = [c.candle_open_time_utc for c in candles]
        duplicates = len(times) - len(set(times))
        unaligned = sum(int(int(c.candle_open_time_utc.timestamp()) % seconds != 0) for c in candles)
        gaps: list[dict[str, Any]] = []
        for left, right in zip(times, times[1:]):
            delta = right - left
            if delta > interval:
                missing = int(delta.total_seconds() // seconds) - 1
                gaps.append({
                    "after_utc": left.isoformat(),
                    "before_utc": right.isoformat(),
                    "missing_bars": missing,
                })
        observed_slots = {
            int(c.candle_open_time_utc.timestamp()) // seconds for c in candles
        }
        expected_slots = set(range(first_slot, last_slot + 1))
        missing_slots = sorted(expected_slots - observed_slots)
        leading_trailing_missing = len(missing_slots) - sum(
            gap["missing_bars"] for gap in gaps
        )
        watermark = self._store.get_candle_revision_watermark(
            broker_server, symbol, timeframe
        )
        revisions = self._store.get_candle_revisions(
            broker_server, symbol, timeframe,
            after_revision_id=0, through_revision_id=watermark,
            limit=max_revision_scan,
        )
        revision_scan_complete = len(revisions) < max_revision_scan
        revised_keys = {revision.candle_open_time_utc for revision in revisions}
        in_range_revisions = [
            revision for revision in revisions
            if start <= revision.candle_open_time_utc < end
        ]
        status = "PASS"
        reasons = []
        if not candles:
            status = "INSUFFICIENT_DATA"
            reasons.append("NO_CLOSED_CANDLES_IN_REQUESTED_RANGE")
        if missing_slots:
            status = "DEGRADED" if candles else status
            reasons.append("CANDLE_COVERAGE_GAPS")
        if duplicates or unaligned:
            status = "DEGRADED"
            reasons.append("CANDLE_TIMESTAMP_INTEGRITY_FAILURE")
        if not revision_scan_complete:
            status = "DEGRADED"
            reasons.append("REVISION_SCAN_LIMIT_REACHED")
        if in_range_revisions:
            status = "DEGRADED"
            reasons.append("HISTORICAL_CANDLE_REVISIONS_PRESENT")

        return {
            "report_type": "HISTORICAL_DATASET_INTEGRITY_AUDIT",
            "engine_version": self.VERSION,
            "status": status,
            "broker_server": broker_server,
            "symbol": symbol,
            "timeframe": timeframe,
            "requested_start_utc": start.isoformat(),
            "requested_end_utc": end.isoformat(),
            "expected_bar_slots": expected,
            "observed_closed_bars": len(candles),
            "coverage_ratio": format(
                len(observed_slots & expected_slots) / expected, ".6f"
            ) if expected else None,
            "missing_bar_count": len(missing_slots),
            "missing_ranges": gaps,
            "leading_or_trailing_missing_bar_count": max(0, leading_trailing_missing),
            "duplicate_timestamp_count": duplicates,
            "unaligned_timestamp_count": unaligned,
            "revision_watermark": watermark,
            "revision_scan_count": len(revisions),
            "revision_scan_complete": revision_scan_complete,
            "revision_event_count_in_range": len(in_range_revisions),
            "distinct_revised_candle_count_in_range": len({revision.candle_open_time_utc for revision in in_range_revisions}),
            "revised_candle_timestamps_utc": sorted(
                {revision.candle_open_time_utc.isoformat() for revision in in_range_revisions}
            ),
            "price_domain_checks": {
                "invalid_ohlc_rows": 0,
                "note": "Candle construction and MarketDataStore schema enforce finite positive OHLC and OHLC consistency; raw rejected ingestion attempts are not available from this read-only archive.",
            },
            "limitations": [
                "The archive stores current canonical candle values plus revision deltas, not a complete first-seen as-of candle snapshot API.",
                "Coverage is measured over every expected timeframe slot in the requested interval; market closures and feed outages are not distinguished automatically.",
                "A revision outside the requested candle range can still affect downstream replay windows if a requested horizon crosses the boundary; audit the full replay window.",
                "This audit does not validate scenario archive coverage or upstream specialist source completeness.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def walk_forward_split(
        scenario_reports: Iterable[Mapping[str, Any]],
        *,
        max_horizon_bars: int,
        timeframe: str,
        train_fraction: float = 0.60,
        validation_fraction: float = 0.20,
        minimum_samples_per_partition: int = 1,
    ) -> dict[str, Any]:
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError("timeframe must be M1 or M5")
        if isinstance(max_horizon_bars, bool) or not isinstance(max_horizon_bars, int) or max_horizon_bars <= 0:
            raise ValueError("max_horizon_bars must be a positive integer")
        if not (0 < train_fraction < 1 and 0 < validation_fraction < 1
                and train_fraction + validation_fraction < 1):
            raise ValueError("train and validation fractions must be positive and sum to less than one")
        if (isinstance(minimum_samples_per_partition, bool)
                or not isinstance(minimum_samples_per_partition, int)
                or minimum_samples_per_partition <= 0):
            raise ValueError("minimum_samples_per_partition must be a positive integer")
        if isinstance(scenario_reports, (str, bytes, Mapping)):
            raise TypeError("scenario_reports must be an iterable of report mappings")

        accepted = []
        rejected = Counter()
        for index, report in enumerate(scenario_reports):
            if not isinstance(report, Mapping):
                rejected["REPORT_NOT_A_MAPPING"] += 1
                continue
            value = report.get("evaluated_at_utc")
            if not isinstance(value, str):
                rejected["MISSING_EVALUATION_TIMESTAMP"] += 1
                continue
            try:
                timestamp = _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")), "evaluated_at_utc")
            except (ValueError, TypeError):
                rejected["INVALID_EVALUATION_TIMESTAMP"] += 1
                continue
            accepted.append((timestamp, index, report))

        accepted.sort(key=lambda row: (row[0], row[1]))
        total = len(accepted)
        train_end = int(total * train_fraction)
        validation_end = int(total * (train_fraction + validation_fraction))
        embargo = timedelta(seconds=max_horizon_bars * TIMEFRAME_SECONDS[timeframe])
        raw_train = accepted[:train_end]
        raw_validation = accepted[train_end:validation_end]
        raw_test = accepted[validation_end:]

        # Purge observations whose forward outcome windows could cross a later
        # partition boundary. This is stricter than merely sorting timestamps.
        train_boundary = raw_validation[0][0] if raw_validation else (
            raw_test[0][0] if raw_test else None
        )
        validation_boundary = raw_test[0][0] if raw_test else None
        train = [
            row for row in raw_train
            if train_boundary is None or row[0] + embargo < train_boundary
        ]
        validation = [
            row for row in raw_validation
            if validation_boundary is None or row[0] + embargo < validation_boundary
        ]
        test = list(raw_test)
        purged = (len(raw_train) - len(train)) + (len(raw_validation) - len(validation))

        def describe(rows: list[tuple[datetime, int, Mapping[str, Any]]]) -> dict[str, Any]:
            return {
                "sample_count": len(rows),
                "start_utc": rows[0][0].isoformat() if rows else None,
                "end_utc": rows[-1][0].isoformat() if rows else None,
                "report_indices": [row[1] for row in rows],
            }

        enough = all(
            len(rows) >= minimum_samples_per_partition
            for rows in (train, validation, test)
        )
        return {
            "report_type": "CHRONOLOGICAL_WALK_FORWARD_PARTITION",
            "status": "READY" if enough else "INSUFFICIENT_DATA",
            "timeframe": timeframe,
            "max_horizon_bars": max_horizon_bars,
            "embargo_seconds": int(embargo.total_seconds()),
            "input_reports": total + sum(rejected.values()),
            "timestamped_reports": total,
            "rejected_counts": dict(sorted(rejected.items())),
            "purged_boundary_reports": purged,
            "partitions": {
                "train": describe(train),
                "validation": describe(validation),
                "test": describe(test),
            },
            "minimum_samples_per_partition": minimum_samples_per_partition,
            "leakage_controls": [
                "Strict chronological ordering; no random shuffling.",
                "Outcome-horizon embargo purges train/validation reports whose forward windows could cross the next partition boundary.",
                "All horizons must be configured no longer than max_horizon_bars.",
                "This creates a single chronological holdout, not rolling multi-fold walk-forward validation.",
                "Dataset and source-integrity audit must pass separately before interpreting metrics.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
