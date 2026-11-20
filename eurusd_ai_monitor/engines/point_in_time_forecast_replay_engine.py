from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
from statistics import mean
from typing import Any, Mapping

from eurusd_ai_monitor.engines.multi_horizon_forecasting_engine import (
    HORIZONS, MultiHorizonForecastingEngine,
)


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _close(row: Mapping[str, Any]) -> float | None:
    try:
        value = float(row["values"]["close"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


class PointInTimeForecastReplayEngine:
    """Replay Phase 44 forecasts using only candle versions visible at each cutoff."""

    VERSION = "pit-forecast-replay-v1"

    def __init__(
        self, *, forecast_engine: MultiHorizonForecastingEngine | None = None,
        lookback_bars: int = 120, pip_size: float = 0.0001,
    ):
        if isinstance(lookback_bars, bool) or not isinstance(lookback_bars, int) or lookback_bars < 60:
            raise ValueError("lookback_bars must be an integer >= 60")
        if not isfinite(float(pip_size)) or float(pip_size) <= 0:
            raise ValueError("pip_size must be finite and positive")
        self.forecast_engine = forecast_engine or MultiHorizonForecastingEngine(
            lookback_bars=lookback_bars, minimum_bars=min(60, lookback_bars),
            pip_size=pip_size,
        )
        self.lookback_bars = lookback_bars
        self.pip_size = float(pip_size)

    def run(
        self, market_store: Any, *, broker_server: str, symbol: str = "EURUSD",
        start_utc: datetime, end_utc: datetime,
        evaluation_cutoff_utc: datetime | None = None,
    ) -> dict[str, Any]:
        start, end = _utc(start_utc, "start_utc"), _utc(end_utc, "end_utc")
        if end < start:
            raise ValueError("end_utc must not precede start_utc")
        evaluation_cutoff = _utc(
            evaluation_cutoff_utc or (end + timedelta(minutes=max(HORIZONS.values()) * 5 + 5)),
            "evaluation_cutoff_utc",
        )
        if evaluation_cutoff < end:
            raise ValueError("evaluation_cutoff_utc must be >= end_utc")
        if getattr(market_store, "_read_only", False) is not True:
            raise RuntimeError("HISTORICAL_REPLAY_REQUIRES_READ_ONLY_MARKET_STORE")
        metadata = market_store.get_history_metadata()
        if not metadata.get("version_ledger_available"):
            return self._blocked("CANDLE_VERSION_LEDGER_UNAVAILABLE", start, end, evaluation_cutoff)
        streams = metadata.get("streams", [])
        if not any(s.get("broker_server") == broker_server and s.get("symbol") == symbol
                   and s.get("timeframe") == "M5" for s in streams):
            return self._blocked("M5_STREAM_NOT_REGISTERED", start, end, evaluation_cutoff)

        history_start = start - timedelta(minutes=5 * (self.lookback_bars + 4), seconds=1)
        history_end = evaluation_cutoff
        history = market_store.get_candle_version_history(
            broker_server, symbol, "M5", start_utc=history_start,
            end_utc=history_end, observed_at_or_before_utc=evaluation_cutoff,
        )
        if not history:
            return self._blocked("NO_VERSIONED_CANDLE_HISTORY", start, end, evaluation_cutoff)

        # A replay timestamp is the first system-knowledge moment at which a
        # closed candle version was observed. It is never backdated to bar time.
        schedule = set()
        first_closed_versions = {}
        for row in history:
            opened = _parse_time(row.get("candle_open_time_utc"))
            observed = _parse_time(row.get("observed_at_utc"))
            as_of = _parse_time(row.get("as_of_utc"))
            closed_at = _parse_time(row.get("candle_close_time_utc"))
            if None in (opened, observed, as_of, closed_at) or row.get("is_closed") is not True:
                continue
            if observed < closed_at or as_of < closed_at:
                continue
            prior = first_closed_versions.get(opened)
            rank = (max(observed, as_of, closed_at), observed, int(row.get("version_id", 0)))
            if prior is None or rank < prior[0]:
                first_closed_versions[opened] = (rank, row)
        for _, row in first_closed_versions.values():
            observed = _parse_time(row["observed_at_utc"])
            as_of = _parse_time(row["as_of_utc"])
            closed_at = _parse_time(row["candle_close_time_utc"])
            cutoff = max(observed, as_of, closed_at)
            if start <= cutoff <= end:
                schedule.add(cutoff)
        ordered_cutoffs = sorted(schedule)

        rows_by_open: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
        for row in history:
            opened = _parse_time(row.get("candle_open_time_utc"))
            if opened is not None:
                rows_by_open[opened].append(row)

        source_history_sha256 = sha256(json.dumps([
            (row["version_id"], row["candle_open_time_utc"], row["observed_at_utc"],
             row["as_of_utc"], row["values_sha256"], row["source_id"])
            for row in history
        ], separators=(",", ":")).encode("utf-8")).hexdigest()
        replay_identity = {
            "engine": self.VERSION, "broker_server": broker_server, "symbol": symbol,
            "start": start.isoformat(), "end": end.isoformat(),
            "evaluation_cutoff": evaluation_cutoff.isoformat(),
            "source_history_sha256": source_history_sha256,
        }
        replay_id = sha256(json.dumps(replay_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        records: list[dict[str, Any]] = []
        skipped: Counter[str] = Counter()
        sorted_opens = sorted(rows_by_open)
        events = []
        for row in history:
            if row.get("is_closed") is not True:
                continue
            opened = _parse_time(row.get("candle_open_time_utc"))
            observed = _parse_time(row.get("observed_at_utc"))
            as_of = _parse_time(row.get("as_of_utc"))
            closed_at = _parse_time(row.get("candle_close_time_utc"))
            if None in (opened, observed, as_of, closed_at):
                continue
            if observed < closed_at or as_of < closed_at:
                continue
            events.append((max(observed, as_of, closed_at), observed,
                           int(row["version_id"]), opened, row))
        events.sort(key=lambda item: (item[0], item[1], item[2]))
        latest_by_open: dict[datetime, dict[str, Any]] = {}
        event_index = 0
        for cutoff in ordered_cutoffs:
            while event_index < len(events) and events[event_index][0] <= cutoff:
                _, observed, version_id, opened, row = events[event_index]
                current = latest_by_open.get(opened)
                if current is None or (observed, version_id) > (
                    _parse_time(current["observed_at_utc"]), int(current["version_id"])
                ):
                    latest_by_open[opened] = row
                event_index += 1
            latest_index = bisect_right(sorted_opens, cutoff - timedelta(minutes=5))
            selected = []
            while latest_index > 0 and len(selected) < self.lookback_bars:
                opened = sorted_opens[latest_index - 1]
                version = latest_by_open.get(opened)
                if version is not None:
                    selected.append(version)
                latest_index -= 1
            visible = list(reversed(selected))
            candles = [self._to_forecast_candle(row) for row in visible]
            visible_bases = {self._price_basis(row) for row in visible}
            if len(visible_bases) > 1:
                skipped["MIXED_PRICE_BASIS_IN_FORECAST_WINDOW"] += 1
                continue
            visible_ids = [(c["version_id"], c["values_sha256"]) for c in candles]
            snapshot_hash = sha256(json.dumps({
                "cutoff": cutoff.isoformat(), "stream": [broker_server, symbol, "M5"],
                "visible_versions": visible_ids,
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            snapshot = {
                "read_mode": "STRICT_SYSTEM_KNOWLEDGE",
                "as_of_utc": cutoff.isoformat().replace("+00:00", "Z"),
                "snapshot_sha256": snapshot_hash,
                "registry_sha256": None,
                "spot_market_archive": {"status": "AVAILABLE", "streams": [{
                    "symbol": symbol, "timeframe": "M5", "broker_server": broker_server,
                    "source_id": "VERSIONED_MT5_HISTORY", "price_basis": "PER_CANDLE_PROVENANCE",
                    "status": "PASS", "eligible_for_analytics": True, "candles": candles,
                }]},
            }
            forecast = self.forecast_engine.assess(snapshot)
            if forecast.get("status") != "AVAILABLE":
                for code in forecast.get("reason_codes", ["FORECAST_NOT_AVAILABLE"]):
                    skipped[code] += 1
                continue
            anchor_version = str(forecast["provenance"]["candle_version_ids"][-1])
            anchor = next((r for r in candles if r["version_id"] == anchor_version), None)
            if anchor is None:
                skipped["FORECAST_ANCHOR_VERSION_NOT_FOUND"] += 1
                continue
            anchor_open = _parse_time(anchor["candle_open_time_utc"])
            anchor_close = _close(anchor)
            if anchor_open is None or anchor_close is None:
                skipped["FORECAST_ANCHOR_INVALID"] += 1
                continue
            for horizon, horizon_forecast in forecast["forecasts"].items():
                bars = int(horizon_forecast["horizon_bars"])
                target_open = anchor_open + timedelta(minutes=5 * bars)
                target_close = target_open + timedelta(minutes=5)
                outcome = self._first_closed_outcome(
                    rows_by_open.get(target_open, []), target_close, evaluation_cutoff,
                    expected_price_basis=self._price_basis(anchor),
                )
                actual_move = None
                outcome_direction = None
                direction_hit = None
                absolute_error = None
                signed_error = None
                target_version_id = None
                target_close_price = None
                if outcome is not None:
                    target_close_price = _close(outcome)
                    if target_close_price is not None:
                        actual_move = (target_close_price - anchor_close) / self.pip_size
                        outcome_direction = "UP" if actual_move > 0 else "DOWN" if actual_move < 0 else "NEUTRAL"
                        direction_hit = horizon_forecast["direction"] == outcome_direction
                        expected = float(horizon_forecast["expected_move_pips_baseline"])
                        signed_error = actual_move - expected
                        absolute_error = abs(signed_error)
                        target_version_id = str(outcome["version_id"])
                identity = {
                    "cutoff": cutoff.isoformat(), "horizon": horizon,
                    "engine_version": forecast.get("engine_version"),
                    "anchor_version": anchor_version, "snapshot_sha256": snapshot_hash,
                }
                forecast_id = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                records.append({
                    "forecast_id": forecast_id, "replay_id": replay_id,
                    "forecast_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
                    "horizon": horizon, "horizon_minutes": int(horizon_forecast["horizon_minutes"]),
                    "forecast_status": "AVAILABLE", "forecast_direction": horizon_forecast["direction"],
                    "expected_move_pips": float(horizon_forecast["expected_move_pips_baseline"]),
                    "anchor_open_time_utc": anchor["candle_open_time_utc"],
                    "anchor_close_price": anchor_close, "anchor_version_id": anchor_version,
                    "target_open_time_utc": target_open.isoformat().replace("+00:00", "Z"),
                    "target_close_time_utc": target_close.isoformat().replace("+00:00", "Z"),
                    "target_close_price": target_close_price, "target_version_id": target_version_id,
                    "actual_move_pips": actual_move, "outcome_direction": outcome_direction,
                    "direction_hit": direction_hit, "absolute_error_pips": absolute_error,
                    "signed_error_pips": signed_error, "snapshot_sha256": snapshot_hash,
                    "registry_sha256": None, "scenario_context": "NOT_SUPPLIED_FOR_HISTORICAL_CUTOFF",
                    "forecast_json": horizon_forecast,
                })

        return {
            "report_type": "EURUSD_POINT_IN_TIME_FORECAST_REPLAY",
            "engine_version": self.VERSION, "phase": 45, "status": "COMPLETE" if records else "INSUFFICIENT_EVIDENCE",
            "replay_id": replay_id, "source_history_sha256": source_history_sha256,
            "symbol": symbol, "broker_server": broker_server,
            "timeframe": "M5", "start_utc": start.isoformat().replace("+00:00", "Z"),
            "end_utc": end.isoformat().replace("+00:00", "Z"),
            "evaluation_cutoff_utc": evaluation_cutoff.isoformat().replace("+00:00", "Z"),
            "forecast_cutoff_count": len(ordered_cutoffs), "forecast_record_count": len(records),
            "outcome_available_count": sum(r["actual_move_pips"] is not None for r in records),
            "skipped_cutoff_reasons": dict(sorted(skipped.items())),
            "horizon_metrics": self._metrics(records),
            "records": records,
            "integrity_policy": {
                "forecast_inputs_filtered_by_observed_and_as_of_at_each_cutoff": True,
                "only_closed_candles_used": True,
                "target_outcome_uses_first_closed_version_observed_after_target_close": True,
                "later_revisions_never_rewrite_forecast_or_target_version": True,
                "future_outcomes_excluded_from_forecast_snapshot": True,
                "system_knowledge_replay_only": True,
            },
            "limitations": [
                "This is historical system-knowledge replay, not public-information replay.",
                "No central scenario report is backfilled or synthesized; historical scenario context is unavailable unless independently archived at each cutoff.",
                "Directional and error metrics are descriptive; no profitability, calibration or trading performance is claimed.",
                "Only strict versioned EURUSD M5 candle evidence is eligible.",
            ],
        }

    @staticmethod
    def _to_forecast_candle(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "candle_open_time_utc": row["candle_open_time_utc"],
            "observed_at_utc": row["observed_at_utc"], "as_of_utc": row["as_of_utc"],
            "is_closed": row["is_closed"], "version_id": str(row["version_id"]),
            "source_id": row["source_id"], "provenance": row["provenance"],
            "values": row["values"], "values_sha256": row["values_sha256"],
        }

    @staticmethod
    def _price_basis(row: Mapping[str, Any]) -> str | None:
        provenance = row.get("provenance")
        price = provenance.get("price_basis") if isinstance(provenance, Mapping) else None
        return price.get("price_basis") if isinstance(price, Mapping) else None

    @staticmethod
    def _valid_provenance(row: Mapping[str, Any]) -> bool:
        provenance = row.get("provenance")
        if not isinstance(provenance, Mapping):
            return False
        basis = PointInTimeForecastReplayEngine._price_basis(row)
        return (row.get("source_id") in {"MT5_COPY_RATES", "MT5_COPY_RATES_RANGE"}
                and basis in {"BID", "LAST"} and provenance.get("bar_time_basis") == "UTC")

    @staticmethod
    def _first_closed_outcome(
        versions: list[dict[str, Any]], target_close: datetime, evaluation_cutoff: datetime,
        *, expected_price_basis: str | None,
    ) -> dict[str, Any] | None:
        eligible = []
        for row in versions:
            observed, as_of = _parse_time(row.get("observed_at_utc")), _parse_time(row.get("as_of_utc"))
            closed_at = _parse_time(row.get("candle_close_time_utc"))
            if (row.get("is_closed") is True and observed is not None and as_of is not None
                and closed_at == target_close and observed >= target_close and as_of >= target_close
                and observed <= evaluation_cutoff and as_of <= evaluation_cutoff
                and PointInTimeForecastReplayEngine._valid_provenance(row)
                and PointInTimeForecastReplayEngine._price_basis(row) == expected_price_basis
                and _close(row) is not None):
                eligible.append(row)
        return min(eligible, key=lambda r: (_parse_time(r["observed_at_utc"]), int(r["version_id"]))) if eligible else None

    @staticmethod
    def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
        result = {}
        for horizon in HORIZONS:
            rows = [r for r in records if r["horizon"] == horizon]
            evaluated = [r for r in rows if r["actual_move_pips"] is not None]
            result[horizon] = {
                "forecast_count": len(rows), "outcome_available_count": len(evaluated),
                "directional_accuracy": (
                    mean(1.0 if r["direction_hit"] else 0.0 for r in evaluated) if evaluated else None
                ),
                "mean_absolute_error_pips": (
                    mean(r["absolute_error_pips"] for r in evaluated) if evaluated else None
                ),
                "mean_signed_error_pips": (
                    mean(r["signed_error_pips"] for r in evaluated) if evaluated else None
                ),
                "probability_metrics": "NOT_AVAILABLE_NO_CALIBRATED_PROBABILITIES",
            }
        return result

    def _blocked(self, reason: str, start: datetime, end: datetime, cutoff: datetime) -> dict[str, Any]:
        return {
            "report_type": "EURUSD_POINT_IN_TIME_FORECAST_REPLAY",
            "engine_version": self.VERSION, "phase": 45,
            "status": "BLOCKED", "reason_codes": [reason],
            "start_utc": start.isoformat().replace("+00:00", "Z"),
            "end_utc": end.isoformat().replace("+00:00", "Z"),
            "evaluation_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
            "forecast_record_count": 0, "outcome_available_count": 0,
            "records": [], "horizon_metrics": self._metrics([]),
        }
