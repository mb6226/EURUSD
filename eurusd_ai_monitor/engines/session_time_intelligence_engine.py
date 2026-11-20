from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

SESSION_TIME_ALGORITHM_VERSION = "session-time-intelligence-v1"
_ZONES = {
    "SYDNEY": ("Australia/Sydney", time(8, 0), time(17, 0)),
    "TOKYO": ("Asia/Tokyo", time(9, 0), time(18, 0)),
    "LONDON": ("Europe/London", time(8, 0), time(17, 0)),
    "NEW_YORK": ("America/New_York", time(8, 0), time(17, 0)),
}
_TIMEFRAME_MINUTES = {"M1": 1, "M5": 5}


def _dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(timezone.utc)


class SessionTimeIntelligenceEngine:
    """Deterministic timezone/session annotations over strict PIT evidence only.

    Session windows are local financial-centre clock windows, not claims that a
    venue is open or that a session has predictive/trading advantage.
    """

    def assess(self, snapshot: Mapping[str, Any], *, calendar_events=()) -> dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            raise TypeError("snapshot must be a unified data-plane mapping")
        cutoff = _dt(snapshot.get("as_of_utc"))
        base = {
            "report_type": "POINT_IN_TIME_SESSION_TIME_INTELLIGENCE",
            "algorithm_version": SESSION_TIME_ALGORITHM_VERSION,
            "as_of_utc": cutoff.isoformat().replace("+00:00", "Z") if cutoff else None,
            "snapshot_sha256": snapshot.get("snapshot_sha256"),
            "registry_sha256": snapshot.get("registry_sha256"),
            "read_mode": snapshot.get("read_mode"),
            "decision_authority": "CONTEXT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
        if cutoff is None:
            return {**base, "status": "INSUFFICIENT_EVIDENCE",
                    "reason_codes": ["INVALID_OR_MISSING_AS_OF_TIMESTAMP"]}
        if snapshot.get("read_mode") != "STRICT_SYSTEM_KNOWLEDGE":
            return {**base, "status": "BLOCKED",
                    "reason_codes": ["NON_STRICT_READ_MODE_BLOCKED"]}
        local = {}
        active = []
        for name, (zone_name, start, end) in _ZONES.items():
            zone = ZoneInfo(zone_name)
            local_dt = cutoff.astimezone(zone)
            is_active = start <= local_dt.time().replace(tzinfo=None) < end
            local[name] = {
                "timezone": zone_name,
                "local_time": local_dt.isoformat(),
                "utc_offset": local_dt.strftime("%z"),
                "dst_active": bool(local_dt.dst() and local_dt.dst().total_seconds()),
                "window_start_local": start.isoformat(),
                "window_end_local": end.isoformat(),
                "within_reference_window": is_active,
            }
            if is_active:
                active.append(name)
        overlap = "LONDON_NEW_YORK_OVERLAP" if {"LONDON", "NEW_YORK"}.issubset(active) else None
        active_overlaps = [
            f"{left}_{right}"
            for index, left in enumerate(_ZONES)
            for right in list(_ZONES)[index + 1:]
            if left in active and right in active
        ]
        archive = snapshot.get("spot_market_archive")
        stream_reports = {}
        exclusions = {}
        streams = archive.get("streams", []) if isinstance(archive, Mapping) else []
        for tf in ("M1", "M5"):
            candidates = [s for s in streams if isinstance(s, Mapping)
                          and s.get("symbol") == "EURUSD" and s.get("timeframe") == tf]
            eligible = [s for s in candidates if s.get("status") == "PASS"
                        and s.get("eligible_for_analytics") is True]
            if len(eligible) != 1:
                exclusions[tf] = ("STREAM_NOT_REGISTERED" if not candidates else
                                   "NO_QUALITY_ELIGIBLE_STREAM" if not eligible else
                                   "AMBIGUOUS_MULTIPLE_ELIGIBLE_STREAMS")
                continue
            rows = eligible[0].get("candles")
            if not isinstance(rows, list):
                exclusions[tf] = "CANDLE_HISTORY_UNAVAILABLE"
                continue
            counts = {name: 0 for name in _ZONES}
            overlap_count = 0
            valid = 0
            invalid = 0
            last_open = None
            for row in rows:
                if not isinstance(row, Mapping):
                    invalid += 1
                    continue
                opened = _dt(row.get("candle_open_time_utc"))
                observed = _dt(row.get("observed_at_utc"))
                as_of = _dt(row.get("as_of_utc"))
                closed = _dt(row.get("candle_close_time_utc"))
                if (opened is None or observed is None or as_of is None or closed is None
                        or opened >= closed or observed > cutoff or as_of > cutoff
                        or closed > cutoff or (last_open is not None and opened <= last_open)):
                    invalid += 1
                    continue
                last_open = opened
                valid += 1
                active_for_bar = set()
                for name, (zone_name, start, end) in _ZONES.items():
                    local_bar = opened.astimezone(ZoneInfo(zone_name))
                    if start <= local_bar.time().replace(tzinfo=None) < end:
                        counts[name] += 1
                        active_for_bar.add(name)
                if {"LONDON", "NEW_YORK"}.issubset(active_for_bar):
                    overlap_count += 1
            if invalid:
                exclusions[tf] = "INVALID_OR_NON_POINT_IN_TIME_CANDLES"
                continue
            stream_reports[tf] = {
                "source_id": eligible[0].get("source_id"),
                "broker_server": eligible[0].get("broker_server"),
                "sample_count": valid,
                "session_bar_counts": counts,
                "london_new_york_overlap_bars": overlap_count,
                "interpretation": "DESCRIPTIVE_COVERAGE_ONLY",
            }
        events = self._calendar_context(calendar_events, cutoff)
        status = "AVAILABLE" if stream_reports and not exclusions else (
            "PARTIAL" if stream_reports else "INSUFFICIENT_EVIDENCE")
        reasons = []
        if not stream_reports:
            reasons.append("NO_QUALITY_ELIGIBLE_SPOT_HISTORY")
        if exclusions:
            reasons.append("ONE_OR_MORE_TIMEFRAMES_EXCLUDED")
        return {
            **base,
            "status": status,
            "calendar_day_utc": cutoff.date().isoformat(),
            "utc_weekday": cutoff.strftime("%A").upper(),
            "saturday_calendar_flag": cutoff.weekday() == 5,
            "active_reference_sessions": active,
            "london_new_york_overlap_active": overlap is not None,
            "active_session_overlaps": active_overlaps,
            "overlap_label": overlap,
            "session_clock_context": local,
            "historical_session_coverage": stream_reports,
            "excluded_timeframes": exclusions,
            "calendar_event_context": events,
            "reason_codes": reasons,
            "policy": {
                "timezone_database": "IANA_ZONEINFO",
                "dst_handling": "CONVERT_AWARE_UTC_INSTANT_TO_LOCAL_ZONE",
                "session_windows_are_reference_clock_windows": True,
                "broker_weekly_open_close": "UNKNOWN_UNLESS_BROKER_CALENDAR_IS_VERIFIED",
                "date_only_events_are_not_assigned_intraday_times": True,
                "no_lookahead": True,
                "no_forecast_or_trading_signal": True,
            },
            "interpretation_limits": [
                "Session labels describe local financial-centre clock windows, not exchange or broker open status.",
                "Session bar counts describe data coverage only; they do not measure volatility, liquidity, returns, or profitability.",
                "No intraday session edge is inferred from missing or insufficient spot history.",
                "DST is handled by IANA timezone rules for each UTC instant; no fixed UTC offset is assumed.",
                "Weekly FX open/close and holidays are broker- and instrument-specific and remain unknown without verified schedules.",
                "Calendar events without an exact timezone-aware scheduled timestamp remain date-only and are not placed into intraday event windows.",
            ],
            "decision_authority": "CONTEXT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @staticmethod
    def _calendar_context(events, cutoff):
        if events is None:
            events = ()
        if not isinstance(events, (list, tuple)):
            return {"status": "BLOCKED", "reason_codes": ["CALENDAR_EVENTS_MUST_BE_A_SEQUENCE"],
                    "timed_events": [], "date_only_events": 0}
        timed = []
        date_only = 0
        excluded = 0
        for event in events:
            if not isinstance(event, Mapping):
                excluded += 1
                continue
            published = _dt(event.get("published_at_utc"))
            retrieved = _dt(event.get("retrieved_at_utc"))
            scheduled = _dt(event.get("scheduled_at_utc"))
            if published is None or retrieved is None or published > cutoff or retrieved > cutoff:
                excluded += 1
                continue
            if not scheduled:
                date_only += 1
                continue
            if str(event.get("status", "")).upper() == "CANCELLED":
                excluded += 1
                continue
            timed.append({
                "event_id": event.get("event_id"),
                "source_id": event.get("source_id"),
                "title": event.get("title"),
                "currency_codes": list(event.get("currency_codes", [])),
                "impact": event.get("impact", "UNKNOWN"),
                "status": event.get("status", "UNKNOWN"),
                "scheduled_at_utc": scheduled.isoformat().replace("+00:00", "Z"),
                "minutes_from_cutoff": round((scheduled - cutoff).total_seconds() / 60, 1),
            })
        timed.sort(key=lambda item: (item["scheduled_at_utc"], str(item["event_id"])))
        return {
            "status": "AVAILABLE" if timed or date_only else "NO_VERIFIED_EVENTS",
            "timed_events": timed,
            "date_only_events": date_only,
            "excluded_unverified_or_cancelled_events": excluded,
            "publication_and_retrieval_cutoff_enforced": True,
        }
