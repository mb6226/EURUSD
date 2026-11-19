from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3


class RegimeConditionedOutcomeEvaluator:
    """Read-only descriptive MFE/MAE segmentation using immutable setup-time context."""

    def __init__(self, database_path: str | Path, *, minimum_group_samples: int = 30) -> None:
        if isinstance(minimum_group_samples, bool) or not isinstance(minimum_group_samples, int):
            raise TypeError("minimum_group_samples must be an integer")
        if minimum_group_samples < 1:
            raise ValueError("minimum_group_samples must be positive")
        self._path = Path(database_path)
        self._minimum = minimum_group_samples

    def build_report(self, *, evaluated_at_utc: datetime) -> dict:
        if not isinstance(evaluated_at_utc, datetime) or evaluated_at_utc.tzinfo is None:
            raise ValueError("evaluated_at_utc must be timezone-aware")
        base = {
            "report_type": "REGIME_CONDITIONED_PRICE_EXCURSION_STATISTICS",
            "evaluated_at_utc": evaluated_at_utc.astimezone(timezone.utc).isoformat(),
            "minimum_group_samples": self._minimum,
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        if not self._path.is_file():
            return {**base, "status": "UNAVAILABLE",
                    "reason_code": "OBSERVATION_DATABASE_NOT_FOUND",
                    "total_observations": 0, "groups": []}
        uri = self._path.resolve().as_uri() + "?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
                db.row_factory = sqlite3.Row
                tables = {r["name"] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                required = {"setup_observations", "observation_candles",
                            "observation_regime_context"}
                if not required.issubset(tables):
                    return {**base, "status": "DEGRADED",
                            "reason_code": "REGIME_CONTEXT_SCHEMA_UNAVAILABLE",
                            "total_observations": 0, "groups": []}
                rows = db.execute("""
                    SELECT o.*,
                           (SELECT COUNT(*) FROM observation_candles c
                            WHERE c.setup_key=o.setup_key) AS evidence_count,
                           r.context_status,r.regime,r.volatility_state,
                           r.trend_direction,r.lower_timeframe_alignment,
                           r.algorithm_version,r.m5_window_end_utc
                    FROM setup_observations o
                    LEFT JOIN observation_regime_context r ON r.setup_key=o.setup_key
                    ORDER BY o.session_date,o.session_name,o.setup_key
                """).fetchall()
        except sqlite3.Error as exc:
            return {**base, "status": "DEGRADED",
                    "reason_code": f"REGIME_CONTEXT_READ_FAILED:{type(exc).__name__}",
                    "total_observations": 0, "groups": []}

        statuses = Counter(str(r["status"]) for r in rows)
        context_statuses = Counter(
            str(r["context_status"] or "MISSING") for r in rows
            if r["status"] == "COMPLETED"
        )
        usable = []
        integrity_errors = 0
        no_evidence = 0
        excluded_context = 0
        completed_with_evidence = 0
        for row in rows:
            if row["status"] != "COMPLETED":
                continue
            try:
                mfe, mae = Decimal(str(row["mfe_pips"])), Decimal(str(row["mae_pips"]))
                processed, evidence = int(row["candles_processed"]), int(row["evidence_count"])
                if (not mfe.is_finite() or not mae.is_finite() or mfe < 0 or mae < 0
                        or processed <= 0 or processed != evidence):
                    if processed == 0:
                        no_evidence += 1
                    else:
                        integrity_errors += 1
                    continue
            except (InvalidOperation, TypeError, ValueError):
                integrity_errors += 1
                continue
            completed_with_evidence += 1
            if row["context_status"] != "AVAILABLE":
                excluded_context += 1
                continue
            try:
                end = datetime.fromisoformat(str(row["m5_window_end_utc"]).replace("Z", "+00:00"))
                reference = datetime.fromisoformat(str(row["reference_at_utc"]).replace("Z", "+00:00"))
                if end.tzinfo is None or reference.tzinfo is None or end > reference:
                    integrity_errors += 1
                    continue
            except (TypeError, ValueError):
                integrity_errors += 1
                continue
            if (row["regime"] not in {"TRENDING", "RANGING", "TRANSITIONAL"}
                    or row["volatility_state"] not in {"HIGH", "NORMAL", "LOW"}
                    or row["trend_direction"] not in {"UP", "DOWN", "UNKNOWN"}
                    or row["lower_timeframe_alignment"] not in {
                        "ALIGNED", "OPPOSED", "NEUTRAL", "UNAVAILABLE"
                    }):
                integrity_errors += 1
                continue
            usable.append({
                "session": str(row["session_name"]),
                "direction": str(row["direction"]),
                "regime": str(row["regime"]),
                "volatility": str(row["volatility_state"]),
                "m1_alignment": str(row["lower_timeframe_alignment"]),
                "mfe": mfe, "mae": mae,
            })

        groups = []
        dimensions = (
            ("REGIME", lambda x: x["regime"]),
            ("VOLATILITY", lambda x: x["volatility"]),
            ("REGIME_VOLATILITY", lambda x: (x["regime"], x["volatility"])),
            ("SESSION_REGIME", lambda x: (x["session"], x["regime"])),
            ("DIRECTION_REGIME", lambda x: (x["direction"], x["regime"])),
            ("SESSION_DIRECTION_REGIME",
             lambda x: (x["session"], x["direction"], x["regime"])),
            ("M1_ALIGNMENT", lambda x: x["m1_alignment"]),
        )
        for dimension, key_fn in dimensions:
            buckets = defaultdict(list)
            for item in usable:
                buckets[key_fn(item)].append(item)
            for key in sorted(buckets, key=lambda value: str(value)):
                groups.append(self._summarize(dimension, key, buckets[key]))

        status = "AVAILABLE" if usable else "INSUFFICIENT_DATA"
        if integrity_errors:
            status = "DEGRADED"
        return {
            **base, "status": status,
            "total_observations": len(rows),
            "status_counts": dict(sorted(statuses.items())),
            "completed_observations": statuses.get("COMPLETED", 0),
            "usable_regime_conditioned_observations": len(usable),
            "excluded_active": statuses.get("ACTIVE", 0),
            "excluded_data_conflict": statuses.get("DATA_CONFLICT", 0),
            "excluded_without_candle_evidence": no_evidence,
            "excluded_integrity_errors": integrity_errors,
            "excluded_without_valid_setup_time_regime": excluded_context,
            "context_status_counts": dict(sorted(context_statuses.items())),
            "context_coverage_ratio": self._ratio(len(usable), max(1, completed_with_evidence)),
            "groups": groups,
            "interpretation_limits": [
                "Regime and volatility are captured once at setup confirmation and never backfilled.",
                "Only M5 candle evidence ending at or before the M1 retest close is accepted.",
                "Observations without valid contemporaneous context are excluded from conditioned groups.",
                "MFE and MAE are price excursions, not realized trade returns or evidence of profitability.",
                "Intrabar ordering is unknown; no win rate, expectancy, P/L, or SL/TP hit rate is inferred.",
                "Groups are descriptive; minimum sample size is not a significance test and no causality is claimed.",
                "No automatic learning, threshold optimization, strategy mutation, entry, or order authority is provided.",
            ],
        }

    def _summarize(self, dimension: str, key, items: list[dict]) -> dict:
        if not isinstance(key, tuple):
            key = (key,)
        mfe = sorted(x["mfe"] for x in items)
        mae = sorted(x["mae"] for x in items)
        return {
            "dimension": dimension,
            "segments": list(key),
            "sample_size": len(items),
            "sample_quality": ("MINIMUM_SAMPLE_REACHED" if len(items) >= self._minimum
                               else "LOW_SAMPLE_DESCRIPTIVE_ONLY"),
            "mfe_pips": self._distribution(mfe),
            "mae_pips": self._distribution(mae),
        }

    @staticmethod
    def _distribution(values):
        n = len(values)
        def rank(percent):
            return values[max(0, (percent * n + 99) // 100 - 1)]
        return {
            "mean": format((sum(values, Decimal("0")) / Decimal(n)).normalize(), "f"),
            "median": format(rank(50).normalize(), "f"),
            "p25": format(rank(25).normalize(), "f"),
            "p75": format(rank(75).normalize(), "f"),
            "min": format(values[0].normalize(), "f"),
            "max": format(values[-1].normalize(), "f"),
        }

    @staticmethod
    def _ratio(numerator, denominator):
        return format(Decimal(numerator) / Decimal(denominator), "f")
