from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

from eurusd_ai_monitor.engines.central_scenario_intelligence_engine import (
    CentralScenarioIntelligenceEngine,
)
from eurusd_ai_monitor.storage.market_data_store import (
    TIMEFRAME_SECONDS,
    Candle,
    MarketDataStore,
)
from source_registry.observation_store import PointInTimeObservationStore


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    return _utc(parsed, field)


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _read_only(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    connection = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


class PointInTimeReconstructionEngine:
    """Reconstruct available EURUSD evidence using source-specific as-of rules.

    This engine never creates a historical report from current data. It reads
    existing append-only/versioned evidence and returns explicit gaps where the
    store cannot prove that a value was available at the requested instant.
    """

    VERSION = "1.0.0"
    MAX_REVISION_SCAN = 100000

    def __init__(
        self,
        market_data_store: MarketDataStore,
        *,
        observation_store: Any | None = None,
        news_store: Any | None = None,
        macro_calendar_store: Any | None = None,
        central_engine: CentralScenarioIntelligenceEngine | None = None,
        max_revision_scan: int = MAX_REVISION_SCAN,
    ) -> None:
        if not isinstance(market_data_store, MarketDataStore):
            raise TypeError("market_data_store must be a MarketDataStore")
        if observation_store is not None:
            if not isinstance(observation_store, PointInTimeObservationStore):
                raise TypeError("observation_store must be a PointInTimeObservationStore")
            if not getattr(observation_store, "_read_only", False):
                raise ValueError("observation_store must be opened with open_read_only")
        if isinstance(max_revision_scan, bool) or not isinstance(max_revision_scan, int) or max_revision_scan <= 0:
            raise ValueError("max_revision_scan must be a positive integer")
        self._market = market_data_store
        self._observations = observation_store
        self._news = news_store
        self._calendar = macro_calendar_store
        self._central = central_engine or CentralScenarioIntelligenceEngine(
            max_report_age_seconds=86400
        )
        self._revision_limit = max_revision_scan

    def reconstruct(
        self,
        *,
        as_of_utc: datetime,
        broker_server: str,
        symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
        observation_requests: Mapping[str, Iterable[tuple[str, str]]] | None = None,
        calendar_start_utc: datetime | None = None,
        calendar_end_utc: datetime | None = None,
    ) -> dict[str, Any]:
        as_of = _utc(as_of_utc, "as_of_utc")
        if as_of > datetime.now(timezone.utc):
            raise ValueError("as_of_utc cannot be in the future")
        start = _utc(start_utc, "start_utc")
        end = _utc(end_utc, "end_utc")
        if start >= end:
            raise ValueError("start_utc must be earlier than end_utc")
        if end > as_of:
            raise ValueError("end_utc cannot exceed as_of_utc")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError("timeframe must be M1 or M5")
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if observation_requests is not None and not isinstance(observation_requests, Mapping):
            raise TypeError("observation_requests must be a mapping")

        market = self._market_as_of(
            as_of=as_of, broker=broker_server, symbol=symbol,
            timeframe=timeframe, start=start, end=end,
        )
        observations = self._observations_as_of(as_of, observation_requests or {})
        news = self._news_as_of(as_of)
        calendar_start = _utc(calendar_start_utc, "calendar_start_utc") if calendar_start_utc else start
        calendar_end = _utc(calendar_end_utc, "calendar_end_utc") if calendar_end_utc else end
        if calendar_start > calendar_end:
            raise ValueError("calendar_start_utc must not exceed calendar_end_utc")
        calendar = self._calendar_as_of(
            as_of=as_of, start=calendar_start, end=calendar_end,
        )

        components = {
            "market_candles": market["status"],
            "source_observations": observations["status"],
            "news": news["status"],
            "macro_calendar": calendar["status"],
        }
        status = "AVAILABLE" if all(value == "AVAILABLE" for value in components.values()) else (
            "PARTIAL" if any(value in {"AVAILABLE", "PARTIAL"} for value in components.values()) else "UNAVAILABLE"
        )
        return {
            "report_type": "POINT_IN_TIME_MULTI_DOMAIN_RECONSTRUCTION",
            "engine_version": self.VERSION,
            "status": status,
            "as_of_utc": as_of.isoformat(),
            "identity": {"broker_server": broker_server, "symbol": symbol, "timeframe": timeframe},
            "requested_window": {"start_utc": start.isoformat(), "end_utc": end.isoformat()},
            "components": components,
            "market_candles": market,
            "source_observations": observations,
            "news": news,
            "macro_calendar": calendar,
            "integrity_contract": {
                "future_publication_excluded": True,
                "future_retrieval_excluded": True,
                "future_effective_observation_excluded": True,
                "candle_revisions_after_as_of_reversed": market.get("revision_history_complete", False),
                "source_files_modified": False,
                "databases_modified": False,
            },
            "limitations": [
                "Only source-registry observations with known publication and retrieval timestamps are eligible.",
                "Current news storage does not preserve every unchanged refresh as an append-only version; items without provable pre-as-of retrieval are excluded.",
                "Calendar source-state health is mutable and has no event history, so it is not reconstructed as historical source health.",
                "CFTC/intermarket/macro/positioning coverage exists only for explicitly requested products present in the point-in-time observation store.",
                "This reconstructs evidence; it does not recompute historical specialist algorithms or infer missing specialist reports.",
                "Candle closure is provable only when first-seen or last-seen metadata demonstrates the bar was observed closed by the as-of time.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    def replay(
        self,
        replay_points: Iterable[Mapping[str, Any]],
        *,
        broker_server: str,
        symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
        observation_requests: Mapping[str, Iterable[tuple[str, str]]] | None = None,
    ) -> dict[str, Any]:
        if isinstance(replay_points, (str, bytes, Mapping)):
            raise TypeError("replay_points must be an iterable of mappings")
        points = list(replay_points)
        output = []
        rejected = Counter()
        for index, point in enumerate(points):
            if not isinstance(point, Mapping):
                rejected["REPLAY_POINT_NOT_A_MAPPING"] += 1
                continue
            try:
                as_of = _parse_time(point.get("evaluated_at_utc"), "evaluated_at_utc")
                if as_of < _utc(start_utc, "start_utc") or as_of > _utc(end_utc, "end_utc"):
                    raise ValueError("REPLAY_POINT_OUTSIDE_REQUESTED_WINDOW")
                reconstruction = self.reconstruct(
                    as_of_utc=as_of, broker_server=broker_server, symbol=symbol,
                    timeframe=timeframe, start_utc=start_utc, end_utc=as_of,
                    observation_requests=observation_requests,
                )
                raw_sources = point.get("specialist_reports", {})
                if not isinstance(raw_sources, Mapping):
                    raise ValueError("SPECIALIST_REPORTS_NOT_A_MAPPING")
                sources: dict[str, Mapping[str, Any]] = {}
                rejected_sources = {}
                for name, report in raw_sources.items():
                    if not isinstance(name, str) or not isinstance(report, Mapping):
                        rejected_sources[str(name)] = "INVALID_REPORT"
                        continue
                    try:
                        report_time = _parse_time(report.get("evaluated_at_utc"), f"{name}.evaluated_at_utc")
                        if report_time > as_of:
                            raise ValueError("FUTURE_REPORT")
                        if report.get("broker_server") not in (None, broker_server):
                            raise ValueError("BROKER_IDENTITY_MISMATCH")
                        if report.get("symbol") not in (None, symbol):
                            raise ValueError("SYMBOL_IDENTITY_MISMATCH")
                        sources[name] = report
                    except ValueError as exc:
                        rejected_sources[name] = str(exc)
                scenario = self._central.assess(
                    evaluated_at_utc=as_of,
                    broker_server=broker_server,
                    symbol=symbol,
                    sources=sources,
                )
                output.append({
                    "point_index": index,
                    "evaluated_at_utc": as_of.isoformat(),
                    "reconstruction": reconstruction,
                    "scenario_assessment": scenario,
                    "archived_specialist_report_count": len(sources),
                    "rejected_specialist_reports": rejected_sources,
                    "replay_mode": "ARCHIVED_SPECIALIST_REPORTS_REASSESSED_ALONGSIDE_RECONSTRUCTED_EVIDENCE",
                    "historical_specialists_recomputed": False,
                    "reconstructed_evidence_fed_as_specialist_reports": False,
                })
            except (ValueError, TypeError) as exc:
                rejected[str(exc)] += 1

        available = sum(
            item["reconstruction"]["status"] == "AVAILABLE" for item in output
        )
        return {
            "report_type": "MULTI_DOMAIN_POINT_IN_TIME_HISTORICAL_REPLAY",
            "engine_version": self.VERSION,
            "status": "AVAILABLE" if output and available == len(output) else (
                "PARTIAL" if output else "INSUFFICIENT_DATA"
            ),
            "broker_server": broker_server,
            "symbol": symbol,
            "timeframe": timeframe,
            "replay_points_received": len(points),
            "replay_points_processed": len(output),
            "fully_reconstructed_points": available,
            "rejected_counts": dict(sorted(rejected.items())),
            "points": output,
            "methodology": [
                "Every point is reconstructed independently at its original timezone-aware evaluation timestamp.",
                "Observation visibility requires publication, retrieval and effective timestamps no later than the replay timestamp.",
                "Candle values are rolled back through append-only revision records detected after the replay timestamp.",
                "News and calendar payloads are rolled back through recorded revisions where the stores retain sufficient history.",
                "Only archived specialist reports are reassessed; specialist algorithms are not recomputed from historical inputs in this phase.",
                "Missing, unprovable or future evidence remains explicitly missing or excluded; no current value is backdated.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    def _market_as_of(self, *, as_of: datetime, broker: str, symbol: str,
                      timeframe: str, start: datetime, end: datetime) -> dict[str, Any]:
        path = self._market.db_path
        seconds = TIMEFRAME_SECONDS[timeframe]
        rows_out = []
        excluded = Counter()
        with closing(_read_only(path)) as connection:
            rows = connection.execute(
                """SELECT * FROM candles
                   WHERE broker_server=? AND symbol=? AND timeframe=?
                     AND candle_open_time_utc>=? AND candle_open_time_utc<?
                     AND is_closed=1
                   ORDER BY candle_open_time_utc""",
                (broker, symbol, timeframe, _stamp(start), _stamp(end)),
            ).fetchall()
            watermark = connection.execute(
                """SELECT COALESCE(MAX(revision_id),0) FROM candle_revisions
                   WHERE broker_server=? AND symbol=? AND timeframe=?""",
                (broker, symbol, timeframe),
            ).fetchone()[0]
            revision_rows = connection.execute(
                """SELECT revision_id,candle_open_time_utc,detected_at_utc,old_values_json
                   FROM candle_revisions
                   WHERE broker_server=? AND symbol=? AND timeframe=? AND revision_id<=?
                     AND candle_open_time_utc>=? AND candle_open_time_utc<?
                   ORDER BY revision_id ASC LIMIT ?""",
                (broker, symbol, timeframe, watermark, _stamp(start), _stamp(end),
                 self._revision_limit + 1),
            ).fetchall()
        revision_complete = len(revision_rows) <= self._revision_limit
        if not revision_complete:
            return {
                "status": "UNAVAILABLE", "reason_codes": ["CANDLE_REVISION_SCAN_LIMIT_REACHED"],
                "candles": [], "observed_count": 0, "excluded_counts": {},
                "revision_watermark": int(watermark), "revision_scan_complete": False,
                "revision_history_complete": False,
            }
        revision_history: dict[str, list[Any]] = defaultdict(list)
        for revision in revision_rows:
            revision_history[revision["candle_open_time_utc"]].append(revision)
        rollback: dict[str, dict[str, Any]] = defaultdict(dict)
        revision_counts = Counter()
        invalid_revision_keys = set()
        for key, history in revision_history.items():
            revision_times = [
                _parse_time(revision["detected_at_utc"], "candle_revision_time")
                for revision in history
            ]
            if any(right < left for left, right in zip(revision_times, revision_times[1:])):
                invalid_revision_keys.add(key)
                continue
            for revision in reversed(history):
                if _parse_time(revision["detected_at_utc"], "candle_revision_time") > as_of:
                    rollback[key] = json.loads(revision["old_values_json"])
                    revision_counts[key] += 1
        for row in rows:
            open_time = datetime.fromisoformat(row["candle_open_time_utc"].replace("Z", "+00:00"))
            close_time = open_time + timedelta(seconds=seconds)
            first_seen = datetime.fromisoformat(row["first_seen_at_utc"].replace("Z", "+00:00"))
            last_seen = datetime.fromisoformat(row["last_seen_at_utc"].replace("Z", "+00:00"))
            if close_time > as_of:
                excluded["CANDLE_NOT_CLOSED_AT_AS_OF"] += 1
                continue
            if first_seen > as_of:
                excluded["CANDLE_FIRST_SEEN_AFTER_AS_OF"] += 1
                continue
            if row["candle_open_time_utc"] in invalid_revision_keys:
                excluded["NON_MONOTONIC_CANDLE_REVISION_TIMELINE"] += 1
                continue
            if first_seen < close_time and (last_seen > as_of or last_seen < close_time):
                excluded["CANDLE_CLOSED_STATE_NOT_PROVABLE_AS_OF"] += 1
                continue
            values = {
                "open": row["open"], "high": row["high"], "low": row["low"],
                "close": row["close"], "tick_volume": row["tick_volume"],
                "spread": row["spread"], "real_volume": row["real_volume"],
            }
            values.update(rollback.get(row["candle_open_time_utc"], {}))
            try:
                candle = Candle(
                    broker_server=broker, symbol=symbol, timeframe=timeframe,
                    candle_open_time_utc=open_time,
                    open=Decimal(str(values["open"])), high=Decimal(str(values["high"])),
                    low=Decimal(str(values["low"])), close=Decimal(str(values["close"])),
                    tick_volume=int(values["tick_volume"]), spread=int(values["spread"]),
                    real_volume=int(values["real_volume"]),
                )
            except (ValueError, TypeError, KeyError) as exc:
                excluded["RECONSTRUCTED_CANDLE_INVALID"] += 1
                continue
            rows_out.append({
                "candle_open_time_utc": candle.candle_open_time_utc.isoformat(),
                "open": format(candle.open, "f"),
                "high": format(candle.high, "f"),
                "low": format(candle.low, "f"),
                "close": format(candle.close, "f"),
                "tick_volume": candle.tick_volume,
                "spread": candle.spread,
                "real_volume": candle.real_volume,
                "first_seen_at_utc": first_seen.isoformat(),
                "last_seen_at_utc": last_seen.isoformat(),
                "revisions_rolled_back": revision_counts.get(row["candle_open_time_utc"], 0),
                "value_sha256": __import__("hashlib").sha256(
                    json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            })
        return {
            "status": "AVAILABLE" if rows_out and not excluded else "PARTIAL",
            "reason_codes": [] if rows_out else ["NO_PROVABLE_CLOSED_CANDLES_AS_OF"],
            "candles": rows_out,
            "observed_count": len(rows),
            "reconstructed_count": len(rows_out),
            "excluded_counts": dict(sorted(excluded.items())),
            "revision_watermark": int(watermark),
            "revision_scan_count": len(revision_rows),
            "revision_scan_complete": True,
            "revision_history_complete": True,
            "revision_timeline_valid": not invalid_revision_keys,
        }

    def _observations_as_of(self, as_of: datetime,
                            requests: Mapping[str, Iterable[tuple[str, str]]]) -> dict[str, Any]:
        if not requests:
            return {"status": "NOT_REQUESTED", "domains": {}, "record_count": 0}
        if self._observations is None:
            return {"status": "UNAVAILABLE", "reason_codes": ["OBSERVATION_STORE_NOT_CONFIGURED"], "domains": {}}
        normalized = {}
        all_pairs = []
        try:
            for domain, pairs in requests.items():
                if not isinstance(domain, str) or not domain.strip():
                    raise ValueError("observation domain names must be non-empty")
                pair_list = tuple(pairs)
                normalized[domain] = pair_list
                all_pairs.extend(pair_list)
            data = self._observations.get_many_as_of(all_pairs, as_of)
        except Exception as exc:
            return {"status": "UNAVAILABLE", "reason_codes": ["OBSERVATION_AS_OF_READ_FAILED"], "error_type": type(exc).__name__, "domains": {}}
        domains = {}
        for domain, pairs in normalized.items():
            entries = []
            for source_id, product_id in pairs:
                entries.append({
                    "source_id": source_id,
                    "product_id": product_id,
                    "observations": data.get((source_id, product_id), []),
                })
            domains[domain] = {
                "status": "AVAILABLE" if any(item["observations"] for item in entries) else "MISSING",
                "products": entries,
            }
        count = sum(
            len(product["observations"])
            for domain in domains.values() for product in domain["products"]
        )
        return {"status": "AVAILABLE" if count else "PARTIAL", "domains": domains, "record_count": count}

    def _news_as_of(self, as_of: datetime) -> dict[str, Any]:
        if self._news is None:
            return {"status": "NOT_CONFIGURED", "items": [], "reason_codes": ["NEWS_STORE_NOT_CONFIGURED"]}
        path = getattr(self._news, "path", None)
        if path is None:
            return {"status": "UNAVAILABLE", "items": [], "reason_codes": ["NEWS_STORE_PATH_UNAVAILABLE"]}
        try:
            with closing(_read_only(path)) as connection:
                current = connection.execute("SELECT item_id,payload_json FROM news_items").fetchall()
                revisions = connection.execute(
                    """SELECT revision_id,item_id,observed_at_utc,
                              previous_payload_json,new_payload_json
                       FROM news_revisions
                       ORDER BY revision_id ASC LIMIT ?""",
                    (self._revision_limit + 1,),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return {"status": "UNAVAILABLE", "items": [], "reason_codes": ["NEWS_ARCHIVE_READ_FAILED"]}
        if len(revisions) > self._revision_limit:
            return {"status": "UNAVAILABLE", "items": [], "reason_codes": ["NEWS_REVISION_SCAN_LIMIT_REACHED"]}
        history = defaultdict(list)
        for revision in revisions:
            history[revision["item_id"]].append(revision)
        for item_id, versions in history.items():
            observed_times = [
                _parse_time(item["observed_at_utc"], "news_revision_time")
                for item in versions
            ]
            if any(right < left for left, right in zip(observed_times, observed_times[1:])):
                return {
                    "status": "UNAVAILABLE", "items": [],
                    "reason_codes": ["NEWS_REVISION_TIMELINE_NON_MONOTONIC"],
                    "invalid_item_id_count": 1,
                }
        items = []
        excluded = Counter()
        for row in current:
            versions = history.get(row["item_id"], [])
            before = [
                revision for revision in versions
                if _parse_time(revision["observed_at_utc"], "news_revision_time") <= as_of
            ]
            after = [
                revision for revision in versions
                if _parse_time(revision["observed_at_utc"], "news_revision_time") > as_of
            ]
            if before:
                payload = json.loads(before[-1]["new_payload_json"])
            elif after:
                payload = json.loads(after[0]["previous_payload_json"])
            else:
                payload = json.loads(row["payload_json"])
            try:
                published = _parse_time(payload.get("published_at_utc"), "published_at_utc")
                retrieved = _parse_time(payload.get("retrieved_at_utc"), "retrieved_at_utc")
            except ValueError:
                excluded["NEWS_TIMESTAMP_INVALID"] += 1
                continue
            if published > as_of or retrieved > as_of:
                excluded["NEWS_NOT_AVAILABLE_AS_OF"] += 1
                continue
            items.append(payload)
        return {
            "status": "AVAILABLE" if items else "PARTIAL",
            "items": sorted(items, key=lambda item: (item["published_at_utc"], item["item_id"])),
            "reconstructed_count": len(items),
            "excluded_counts": dict(sorted(excluded.items())),
            "revision_scan_complete": True,
            "limitations": ["Unchanged news refreshes are not append-only versions; if the latest retrieval timestamp is after as-of and no later semantic revision preserves the prior payload, the item is excluded."],
        }

    def _calendar_as_of(self, *, as_of: datetime, start: datetime,
                        end: datetime) -> dict[str, Any]:
        if self._calendar is None:
            return {"status": "NOT_CONFIGURED", "events": [], "reason_codes": ["MACRO_CALENDAR_STORE_NOT_CONFIGURED"]}
        path = getattr(self._calendar, "db_path", None)
        if path is None:
            return {"status": "UNAVAILABLE", "events": [], "reason_codes": ["MACRO_CALENDAR_STORE_PATH_UNAVAILABLE"]}
        try:
            with closing(_read_only(path)) as connection:
                current = connection.execute(
                    "SELECT event_id,first_seen_at_utc,payload_json FROM macro_events"
                ).fetchall()
                revisions = connection.execute(
                    """SELECT revision_id,event_id,changed_at_utc,previous_payload_json
                       FROM macro_event_revisions
                       ORDER BY revision_id ASC LIMIT ?""",
                    (self._revision_limit + 1,),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return {"status": "UNAVAILABLE", "events": [], "reason_codes": ["CALENDAR_ARCHIVE_READ_FAILED"]}
        if len(revisions) > self._revision_limit:
            return {"status": "UNAVAILABLE", "events": [], "reason_codes": ["CALENDAR_REVISION_SCAN_LIMIT_REACHED"]}
        revision_history = defaultdict(list)
        for revision in revisions:
            revision_history[revision["event_id"]].append(revision)
        for event_id, history in revision_history.items():
            changed_times = [
                _parse_time(item["changed_at_utc"], "calendar_revision_time")
                for item in history
            ]
            if any(right < left for left, right in zip(changed_times, changed_times[1:])):
                return {
                    "status": "UNAVAILABLE", "events": [],
                    "reason_codes": ["CALENDAR_REVISION_TIMELINE_NON_MONOTONIC"],
                    "invalid_event_id_count": 1,
                }
        rollback = {}
        for history in revision_history.values():
            for revision in reversed(history):
                if _parse_time(revision["changed_at_utc"], "calendar_revision_time") > as_of:
                    rollback[revision["event_id"]] = json.loads(revision["previous_payload_json"])
        events = []
        excluded = Counter()
        for row in current:
            first_seen = _parse_time(row["first_seen_at_utc"], "first_seen_at_utc")
            if first_seen > as_of:
                excluded["EVENT_FIRST_SEEN_AFTER_AS_OF"] += 1
                continue
            payload = rollback.get(row["event_id"], json.loads(row["payload_json"]))
            # first_seen_at_utc is the immutable availability boundary. Calendar
            # upserts may refresh retrieved_at without semantic changes; those
            # refreshes do not invalidate the original event payload.
            scheduled_raw = payload.get("scheduled_at_utc")
            scheduled = _parse_time(scheduled_raw, "scheduled_at_utc") if scheduled_raw else None
            if scheduled is not None and not (start <= scheduled <= end):
                continue
            if scheduled is None:
                event_date = datetime.fromisoformat(payload["scheduled_date"]).date()
                if not (start.date() - timedelta(days=1) <= event_date <= end.date() + timedelta(days=1)):
                    continue
            events.append(payload)
        return {
            "status": "AVAILABLE" if events else "PARTIAL",
            "events": sorted(events, key=lambda item: (item.get("scheduled_at_utc") or item.get("scheduled_date", ""), item["event_id"])),
            "reconstructed_count": len(events),
            "excluded_counts": dict(sorted(excluded.items())),
            "revision_scan_complete": True,
            "source_health": "NOT_RECONSTRUCTABLE_SOURCE_STATE_IS_MUTABLE",
        }
