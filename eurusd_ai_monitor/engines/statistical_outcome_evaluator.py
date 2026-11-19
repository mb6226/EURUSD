from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3


class StatisticalOutcomeEvaluator:
    """Read-only descriptive statistics over completed Phase 9 observations."""

    def __init__(self, database_path: str | Path, *, minimum_group_samples: int = 30) -> None:
        if isinstance(minimum_group_samples, bool) or not isinstance(minimum_group_samples, int):
            raise TypeError("minimum_group_samples must be an integer")
        if minimum_group_samples < 1:
            raise ValueError("minimum_group_samples must be positive")
        self._path = Path(database_path)
        self._minimum_group_samples = minimum_group_samples

    def build_report(self, *, evaluated_at_utc: datetime) -> dict:
        if not isinstance(evaluated_at_utc, datetime) or evaluated_at_utc.tzinfo is None:
            raise ValueError("evaluated_at_utc must be timezone-aware")
        evaluated = evaluated_at_utc.astimezone(timezone.utc).isoformat()
        base = {
            "report_type": "DESCRIPTIVE_PRICE_EXCURSION_STATISTICS",
            "evaluated_at_utc": evaluated,
            "minimum_group_samples": self._minimum_group_samples,
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        if not self._path.is_file():
            return {**base, "status": "UNAVAILABLE", "reason_code": "OBSERVATION_DATABASE_NOT_FOUND",
                    "total_observations": 0, "groups": []}

        uri = self._path.resolve().as_uri() + "?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
                db.row_factory = sqlite3.Row
                tables = {
                    row["name"] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                required = {"setup_observations", "observation_candles"}
                if not required.issubset(tables):
                    return {**base, "status": "DEGRADED",
                            "reason_code": "OBSERVATION_SCHEMA_INCOMPLETE",
                            "total_observations": 0, "groups": []}
                rows = db.execute("""
                    SELECT o.*,
                           (SELECT COUNT(*) FROM observation_candles c
                            WHERE c.setup_key=o.setup_key) AS evidence_count
                    FROM setup_observations o
                    ORDER BY o.session_date, o.session_name, o.setup_key
                """).fetchall()
        except sqlite3.Error as exc:
            return {**base, "status": "DEGRADED",
                    "reason_code": f"OBSERVATION_DATABASE_READ_FAILED:{type(exc).__name__}",
                    "total_observations": 0, "groups": []}

        status_counts = Counter(str(row["status"]) for row in rows)
        usable = []
        integrity_errors = 0
        no_evidence = 0
        for row in rows:
            if row["status"] != "COMPLETED":
                continue
            try:
                mfe = Decimal(str(row["mfe_pips"]))
                mae = Decimal(str(row["mae_pips"]))
                processed = int(row["candles_processed"])
                evidence_count = int(row["evidence_count"])
                if (not mfe.is_finite() or not mae.is_finite() or mfe < 0 or mae < 0
                        or processed < 0 or processed != evidence_count):
                    integrity_errors += 1
                    continue
            except (InvalidOperation, TypeError, ValueError):
                integrity_errors += 1
                continue
            if processed == 0:
                no_evidence += 1
                continue
            usable.append({
                "session": str(row["session_name"]),
                "direction": str(row["direction"]),
                "mfe": mfe,
                "mae": mae,
            })

        groups = []
        if usable:
            groups.append(self._summarize("ALL", "ALL", usable))
            for session in ("LONDON", "NEW_YORK"):
                selected = [item for item in usable if item["session"] == session]
                if selected:
                    groups.append(self._summarize(session, "ALL", selected))
            for direction in ("UP", "DOWN"):
                selected = [item for item in usable if item["direction"] == direction]
                if selected:
                    groups.append(self._summarize("ALL", direction, selected))
            for session in ("LONDON", "NEW_YORK"):
                for direction in ("UP", "DOWN"):
                    selected = [item for item in usable
                                if item["session"] == session and item["direction"] == direction]
                    if selected:
                        groups.append(self._summarize(session, direction, selected))

        status = "AVAILABLE" if usable else "INSUFFICIENT_DATA"
        if integrity_errors:
            status = "DEGRADED"
        return {
            **base,
            "status": status,
            "total_observations": len(rows),
            "status_counts": dict(sorted(status_counts.items())),
            "completed_observations": status_counts.get("COMPLETED", 0),
            "usable_completed_observations": len(usable),
            "excluded_active": status_counts.get("ACTIVE", 0),
            "excluded_data_conflict": status_counts.get("DATA_CONFLICT", 0),
            "excluded_without_candle_evidence": no_evidence,
            "excluded_integrity_errors": integrity_errors,
            "groups": groups,
            "interpretation_limits": [
                "MFE and MAE are independent price excursions, not trade returns.",
                "Intrabar order between favorable and adverse extremes is unknown.",
                "No win rate, expectancy, realized P/L, or SL/TP hit rate is calculated.",
                "Only completed observations with consistent immutable candle counts are included.",
                "Only session and direction are available for grouping; market regime and news context were not persisted in Phase 9.",
                "The minimum sample threshold is a reporting convention, not a significance test.",
            ],
        }

    def _summarize(self, session: str, direction: str, items: list[dict]) -> dict:
        mfe = sorted(item["mfe"] for item in items)
        mae = sorted(item["mae"] for item in items)
        count = len(items)
        return {
            "session": session,
            "direction": direction,
            "sample_size": count,
            "sample_quality": (
                "MINIMUM_SAMPLE_REACHED" if count >= self._minimum_group_samples
                else "LOW_SAMPLE_DESCRIPTIVE_ONLY"
            ),
            "mfe_pips": self._distribution(mfe),
            "mae_pips": self._distribution(mae),
        }

    @staticmethod
    def _distribution(values: list[Decimal]) -> dict:
        count = len(values)
        def rank(percent: int) -> Decimal:
            # Nearest-rank percentile: deterministic and does not interpolate.
            index = max(0, (percent * count + 99) // 100 - 1)
            return values[index]
        mean = sum(values, Decimal("0")) / Decimal(count)
        return {
            "mean": format(mean.normalize(), "f"),
            "median": format(rank(50).normalize(), "f"),
            "p25": format(rank(25).normalize(), "f"),
            "p75": format(rank(75).normalize(), "f"),
            "min": format(values[0].normalize(), "f"),
            "max": format(values[-1].normalize(), "f"),
        }
