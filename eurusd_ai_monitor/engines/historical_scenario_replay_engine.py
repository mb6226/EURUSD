from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from eurusd_ai_monitor.storage.market_data_store import (
    TIMEFRAME_SECONDS,
    Candle,
    MarketDataStore,
)


_SCENARIO_REPORT_TYPE = "CENTRAL_MULTI_DOMAIN_SCENARIO_INTELLIGENCE"
_VALID_FORECASTS = {"UP", "DOWN", "RANGE"}
_OUTCOME_LABELS = ("UP", "DOWN", "RANGE")


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    return _utc(parsed, field)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal value") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


class HistoricalScenarioReplayEngine:
    """Evaluate archived Phase 28 scenario reports against later closed candles.

    This is an evaluator/replayer of timestamped scenario outputs, not a model
    trainer and not a reconstruction of specialist state. It deliberately
    refuses reports without an explicit point-in-time identity and timestamp.
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        market_data_store: MarketDataStore,
        *,
        pip_size: Decimal | str,
        timeframe: str = "M1",
        horizons_bars: Iterable[int] = (5, 15, 30, 60),
        neutral_band_pips: Decimal | str = "2",
    ) -> None:
        if not isinstance(market_data_store, MarketDataStore):
            raise TypeError("market_data_store must be a MarketDataStore")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError("timeframe must be M1 or M5")
        self._store = market_data_store
        self._pip_size = _decimal(pip_size, "pip_size")
        if self._pip_size <= 0:
            raise ValueError("pip_size must be positive")
        self._neutral_band = _decimal(neutral_band_pips, "neutral_band_pips")
        if self._neutral_band < 0:
            raise ValueError("neutral_band_pips must be non-negative")
        horizons = tuple(horizons_bars)
        if (not horizons or any(isinstance(x, bool) or not isinstance(x, int) or x <= 0
                                 for x in horizons) or len(set(horizons)) != len(horizons)):
            raise ValueError("horizons_bars must contain unique positive integers")
        self._horizons = tuple(sorted(horizons))
        self._timeframe = timeframe
        self._seconds = TIMEFRAME_SECONDS[timeframe]

    def replay(
        self,
        scenario_reports: Iterable[Mapping[str, Any]],
        *,
        broker_server: str,
        symbol: str,
    ) -> dict[str, Any]:
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if isinstance(scenario_reports, (str, bytes, Mapping)):
            raise TypeError("scenario_reports must be an iterable of report mappings")

        reports = list(scenario_reports)
        parsed: list[dict[str, Any]] = []
        rejected = Counter()
        for index, report in enumerate(reports):
            try:
                if not isinstance(report, Mapping):
                    raise ValueError("REPORT_NOT_A_MAPPING")
                if report.get("report_type") != _SCENARIO_REPORT_TYPE:
                    raise ValueError("UNSUPPORTED_REPORT_TYPE")
                if report.get("broker_server") != broker_server or report.get("symbol") != symbol:
                    raise ValueError("REPORT_IDENTITY_MISMATCH")
                evaluated = _parse_time(report.get("evaluated_at_utc"), "evaluated_at_utc")
                assessment = report.get("directional_assessment")
                if not isinstance(assessment, Mapping):
                    raise ValueError("DIRECTIONAL_ASSESSMENT_MISSING")
                forecast = assessment.get("state")
                if forecast not in _VALID_FORECASTS:
                    rejected["UNRESOLVED_OR_CONFLICTED_FORECAST"] += 1
                    continue
                if report.get("status") in {"DEGRADED", "AUTHORITY_VIOLATION"}:
                    raise ValueError("REPORT_DEGRADED")
                parsed.append({"index": index, "time": evaluated, "forecast": forecast})
            except ValueError as exc:
                rejected[str(exc)] += 1

        if not parsed:
            return self._empty_report(
                broker_server, symbol, len(reports), rejected, "NO_VALID_RESOLVED_SCENARIOS"
            )

        parsed.sort(key=lambda item: (item["time"], item["index"]))
        interval = timedelta(seconds=self._seconds)
        first_start = min(item["time"] for item in parsed) - interval * 2
        final_end = max(item["time"] for item in parsed) + interval * (max(self._horizons) + 2)
        candles = self._store.get_closed_candles(
            broker_server, symbol, self._timeframe,
            start_utc=first_start, end_utc=final_end,
        )
        candles = sorted(candles, key=lambda candle: candle.candle_open_time_utc)
        candle_times = [candle.candle_open_time_utc for candle in candles]

        # Current canonical rows can contain later revisions. If a candle used
        # in a replay window was revised after the forecast timestamp, exclude
        # that sample rather than leak the revised value into historical replay.
        watermark = self._store.get_candle_revision_watermark(
            broker_server, symbol, self._timeframe
        )
        revisions = self._store.get_candle_revisions(
            broker_server, symbol, self._timeframe,
            after_revision_id=0, through_revision_id=watermark, limit=100000,
        )
        revision_times: dict[datetime, list[datetime]] = defaultdict(list)
        for revision in revisions:
            revision_times[revision.candle_open_time_utc].append(revision.detected_at_utc)
        revision_history_complete = len(revisions) < 100000

        by_horizon: dict[int, list[dict[str, Any]]] = {h: [] for h in self._horizons}
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        for item in parsed:
            evaluation_time = item["time"]
            anchor_index = bisect_right(candle_times, evaluation_time - interval) - 1
            if anchor_index < 0:
                rejected["NO_CLOSED_ANCHOR_CANDLE"] += 1
                continue
            anchor = candles[anchor_index]
            future_start = bisect_left(candle_times, evaluation_time)
            future = candles[future_start:]
            elapsed = evaluation_time - epoch
            slots, remainder = divmod(elapsed, interval)
            expected_first_open = epoch + (slots + (1 if remainder else 0)) * interval
            for horizon in self._horizons:
                if len(future) < horizon:
                    rejected[f"INSUFFICIENT_FUTURE_CANDLES_H{horizon}"] += 1
                    continue
                window = future[:horizon]
                if window[0].candle_open_time_utc != expected_first_open or any(
                    right.candle_open_time_utc - left.candle_open_time_utc != interval
                    for left, right in zip(window, window[1:])
                ):
                    rejected[f"NON_CONTIGUOUS_FUTURE_WINDOW_H{horizon}"] += 1
                    continue
                if not revision_history_complete:
                    rejected[f"REVISION_HISTORY_LIMIT_REACHED_H{horizon}"] += 1
                    continue
                replay_window = [anchor, *window]
                if any(
                    detected > evaluation_time
                    for candle in replay_window
                    for detected in revision_times.get(candle.candle_open_time_utc, ())
                ):
                    rejected[f"POST_FORECAST_CANDLE_REVISION_H{horizon}"] += 1
                    continue
                future_close = window[-1].close
                move_pips = (future_close - anchor.close) / self._pip_size
                realized = (
                    "UP" if move_pips > self._neutral_band
                    else "DOWN" if move_pips < -self._neutral_band
                    else "RANGE"
                )
                by_horizon[horizon].append({
                    "forecast": item["forecast"],
                    "realized": realized,
                    "move_pips": move_pips,
                })

        summaries = {
            str(horizon): self._summarize(by_horizon[horizon])
            for horizon in self._horizons
        }
        return {
            "report_type": "HISTORICAL_CENTRAL_SCENARIO_REPLAY_EVALUATION",
            "engine_version": self.VERSION,
            "status": "AVAILABLE" if any(by_horizon.values()) else "INSUFFICIENT_DATA",
            "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
            "broker_server": broker_server,
            "symbol": symbol,
            "timeframe": self._timeframe,
            "pip_size": format(self._pip_size, "f"),
            "neutral_band_pips": format(self._neutral_band, "f"),
            "scenario_reports_received": len(reports),
            "valid_resolved_scenario_reports": len(parsed),
            "rejected_counts": dict(sorted(rejected.items())),
            "horizons": summaries,
            "methodology": {
                "anchor": "Latest closed candle whose close time is no later than the scenario evaluation timestamp.",
                "outcome": "Close-to-close pip movement from the anchor close to the close of the Nth subsequent timeframe candle.",
                "classification": "UP/DOWN only outside the configured neutral band; otherwise RANGE.",
                "scenario_forecast": "The Phase 28 directional_assessment.state; unresolved/conflicted reports are excluded.",
                "revision_policy": "A sample is excluded if any future candle in its horizon was revised after the scenario timestamp. Replay fails closed when the revision query reaches its safety limit.",
                "point_in_time_limit": "This evaluates archived Phase 28 outputs; it does not regenerate missing historical specialist reports or prove that all upstream sources were archived point-in-time.",
            },
            "interpretation_limits": [
                "Scenario classification accuracy is not trading profitability, win rate, expectancy, or realized P/L.",
                "No intrabar path, spread, slippage, executable entry, stop, or target is modeled.",
                "The neutral band is an explicit evaluation parameter, not a learned threshold.",
                "No probabilities, Brier score, confidence calibration, or model promotion are produced.",
                "Only reports with a resolved UP/DOWN/RANGE directional state are scored; unresolved and conflicted reports are counted as excluded.",
                "Historical reports must have been captured at the time; current reports must never be relabeled as historical forecasts.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    def _summarize(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        matrix = {forecast: {actual: 0 for actual in _OUTCOME_LABELS}
                  for forecast in _OUTCOME_LABELS}
        for sample in samples:
            matrix[sample["forecast"]][sample["realized"]] += 1
        total = len(samples)
        directional = [x for x in samples if x["forecast"] in {"UP", "DOWN"}]
        correct = sum(x["forecast"] == x["realized"] for x in samples)
        directional_correct = sum(x["forecast"] == x["realized"] for x in directional)
        moves = sorted(x["move_pips"] for x in samples)
        return {
            "sample_size": total,
            "scenario_accuracy": format(Decimal(correct) / Decimal(total), "f") if total else None,
            "directional_sample_size": len(directional),
            "directional_accuracy": (
                format(Decimal(directional_correct) / Decimal(len(directional)), "f")
                if directional else None
            ),
            "confusion_matrix_forecast_rows_realized_columns": matrix,
            "mean_forward_move_pips": (
                format(sum(moves, Decimal("0")) / Decimal(total), "f") if total else None
            ),
            "median_forward_move_pips": (
                format(moves[(total - 1) // 2], "f") if total else None
            ),
        }

    def _empty_report(self, broker: str, symbol: str, received: int,
                      rejected: Counter, reason: str) -> dict[str, Any]:
        return {
            "report_type": "HISTORICAL_CENTRAL_SCENARIO_REPLAY_EVALUATION",
            "engine_version": self.VERSION,
            "status": "INSUFFICIENT_DATA",
            "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
            "broker_server": broker,
            "symbol": symbol,
            "timeframe": self._timeframe,
            "scenario_reports_received": received,
            "valid_resolved_scenario_reports": 0,
            "rejected_counts": dict(sorted(rejected.items())),
            "reason_code": reason,
            "horizons": {str(h): self._summarize([]) for h in self._horizons},
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
