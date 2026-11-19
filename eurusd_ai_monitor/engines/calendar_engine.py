from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from typing import Callable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from eurusd_ai_monitor.models.macro_event import MacroEvent, MacroEventStatus, MacroImpact
from eurusd_ai_monitor.storage.macro_calendar_store import MacroCalendarStore


class CalendarSourceError(ValueError):
    """Raised when an official calendar payload cannot be safely normalized."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _unfold_ics(contents: str) -> list[str]:
    physical = contents.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    logical: list[str] = []
    for line in physical:
        if line.startswith((" ", "\t")) and logical:
            logical[-1] += line[1:]
        elif line:
            logical.append(line)
    return logical


def _unescape_ics(value: str) -> str:
    return (value.replace("\\n", "\n").replace("\\N", "\n")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def _parse_ics_datetime(value: str, params: dict[str, str], default_timezone: str):
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value[:8], "%Y%m%d").date(), None
    if value.endswith("Z"):
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    else:
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%S")
        tz_name = params.get("TZID", default_timezone)
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
        except ZoneInfoNotFoundError as exc:
            raise CalendarSourceError(f"unknown iCalendar timezone: {tz_name}") from exc
    return parsed.date(), parsed.astimezone(timezone.utc)


def parse_ics_events(contents: str, source_timezone: str) -> list[dict]:
    if not isinstance(contents, str) or not contents.strip():
        raise CalendarSourceError("iCalendar response is empty")
    events: list[dict] = []
    current: dict[str, tuple[dict[str, str], str]] | None = None
    for line in _unfold_ics(contents):
        if line == "BEGIN:VEVENT":
            if current is not None:
                raise CalendarSourceError("nested VEVENT is not supported")
            current = {}
            continue
        if line == "END:VEVENT":
            if current is None:
                raise CalendarSourceError("VEVENT end without start")
            events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        left, value = line.split(":", 1)
        parts = left.split(";")
        name = parts[0].upper()
        params = {}
        for part in parts[1:]:
            if "=" in part:
                key, item = part.split("=", 1)
                params[key.upper()] = item.strip('"')
        if name in {"UID", "SUMMARY", "DESCRIPTION", "DTSTART", "STATUS", "URL", "LAST-MODIFIED"}:
            current[name] = (params, _unescape_ics(value))
    if current is not None:
        raise CalendarSourceError("unterminated VEVENT")
    if not events:
        raise CalendarSourceError("iCalendar feed contains no VEVENT records")

    normalized = []
    for index, item in enumerate(events):
        if "DTSTART" not in item or "SUMMARY" not in item:
            raise CalendarSourceError(f"VEVENT {index} is missing DTSTART or SUMMARY")
        params, start_value = item["DTSTART"]
        scheduled_date, scheduled_at = _parse_ics_datetime(start_value, params, source_timezone)
        uid = item.get("UID", ({}, f"{scheduled_date.isoformat()}|{item['SUMMARY'][1]}"))[1]
        status = item.get("STATUS", ({}, "CONFIRMED"))[1].upper()
        updated = None
        if "LAST-MODIFIED" in item:
            _, raw = item["LAST-MODIFIED"]
            _, updated = _parse_ics_datetime(raw, {}, "UTC")
        normalized.append({
            "source_event_id": uid,
            "title": item["SUMMARY"][1].strip(),
            "description": item.get("DESCRIPTION", ({}, ""))[1].strip(),
            "scheduled_date": scheduled_date,
            "scheduled_at_utc": scheduled_at,
            "status": status,
            "url": item.get("URL", ({}, ""))[1].strip(),
            "source_updated_at_utc": updated,
            "reference_period": None,
        })
    return normalized


def parse_bea_release_dates(contents: str) -> list[dict]:
    try:
        document = json.loads(contents)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CalendarSourceError("BEA release-date JSON is invalid") from exc
    if not isinstance(document, dict):
        raise CalendarSourceError("BEA release-date JSON root must be an object")
    records: dict[tuple[str, str], dict] = {}
    for title, payload in document.items():
        if title == "file_last_updated":
            continue
        if not isinstance(title, str) or not isinstance(payload, dict):
            raise CalendarSourceError("BEA release-date entry has an invalid shape")
        dates = payload.get("release_dates")
        if not isinstance(dates, list):
            raise CalendarSourceError(f"BEA entry {title!r} has no release_dates array")
        for raw in dates:
            if not isinstance(raw, str):
                raise CalendarSourceError("BEA release timestamp must be a string")
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as exc:
                raise CalendarSourceError(f"invalid BEA release timestamp: {raw}") from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise CalendarSourceError("BEA release timestamp must include an offset")
            scheduled = parsed.astimezone(timezone.utc)
            key = (title, scheduled.isoformat())
            records[key] = {
                "source_event_id": f"{title}|{scheduled.isoformat()}",
                "title": title,
                "description": "",
                "scheduled_date": scheduled.date(),
                "scheduled_at_utc": scheduled,
                "status": "CONFIRMED",
                "url": "",
                "source_updated_at_utc": None,
                "reference_period": None,
            }
    if not records:
        raise CalendarSourceError("BEA response contains no release events")
    return list(records.values())


def parse_ecb_meeting_calendar_html(contents: str) -> list[dict]:
    if not isinstance(contents, str) or not contents.strip():
        raise CalendarSourceError("ECB calendar response is empty")
    parser = _TextExtractor()
    parser.feed(contents)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    matches = list(re.finditer(r"\b(\d{2}/\d{2}/\d{4})\b", text))
    records = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.end():end].strip(" :-|")
        if not re.search(r"Governing Council|General Council", segment, re.IGNORECASE):
            continue
        title = re.split(r"\b(?:More|Related content|Previous|Next)\b", segment, maxsplit=1)[0].strip()[:240]
        if not title:
            continue
        scheduled_date = datetime.strptime(match.group(1), "%d/%m/%Y").date()
        records.append({
            "source_event_id": f"{scheduled_date.isoformat()}|{title}",
            "title": title,
            "description": "Official ECB meeting calendar. The page provides a date; no release time is inferred.",
            "scheduled_date": scheduled_date,
            "scheduled_at_utc": None,
            "status": "CONFIRMED",
            "url": "",
            "source_updated_at_utc": None,
            "reference_period": None,
        })
    if not records:
        raise CalendarSourceError("ECB calendar structure changed or no meeting records were found")
    return records


def parse_fomc_calendar_html(contents: str, as_of_date=None) -> list[dict]:
    """Extract second-day FOMC decision dates from the official year-section calendar."""
    if not isinstance(contents, str) or not contents.strip():
        raise CalendarSourceError("Federal Reserve FOMC calendar response is empty")
    parser = _TextExtractor()
    parser.feed(contents)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    sections = list(re.finditer(r"\b(20\d{2})\s+FOMC Meetings\b", text, re.IGNORECASE))
    if not sections:
        raise CalendarSourceError("Federal Reserve FOMC year sections were not found")
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    meeting_pattern = re.compile(
        r"\b(" + "|".join(months) + r")\s+(\d{1,2})\s*[-–]\s*(\d{1,2})(\*)?",
        re.IGNORECASE,
    )
    today = as_of_date or datetime.now(timezone.utc).date()
    records = []
    for section_index, section in enumerate(sections):
        section_end = sections[section_index + 1].start() if section_index + 1 < len(sections) else len(text)
        year = int(section.group(1))
        body = text[section.end():section_end]
        meetings = list(meeting_pattern.finditer(body))
        for meeting_index, match in enumerate(meetings):
            month = months[match.group(1).casefold()]
            decision_day = int(match.group(3))
            try:
                scheduled_date = date(year, month, decision_day)
            except ValueError as exc:
                raise CalendarSourceError("invalid date in Federal Reserve FOMC calendar") from exc
            detail_end = meetings[meeting_index + 1].start() if meeting_index + 1 < len(meetings) else len(body)
            detail = body[match.end():detail_end]
            strategy_only = bool(re.search(r"Monetary Policy Strategy Meeting", detail, re.IGNORECASE))
            title = (
                "FOMC monetary policy strategy meeting (no policy decision expected)"
                if strategy_only else "FOMC policy decision (meeting day 2)"
            )
            status = "TENTATIVE" if scheduled_date >= today else "CONFIRMED"
            records.append({
                "source_event_id": f"FOMC|{scheduled_date.isoformat()}",
                "title": title,
                "description": (
                    "Official FOMC calendar lists a two-day meeting. The event is dated on day 2; "
                    "the calendar does not provide a release time. Future dates are tentative."
                ),
                "scheduled_date": scheduled_date,
                "scheduled_at_utc": None,
                "status": status,
                "url": "",
                "source_updated_at_utc": None,
                "reference_period": None,
            })
    if not records:
        raise CalendarSourceError("Federal Reserve FOMC calendar contains no meeting date ranges")
    return records


def _impact(title: str, rules: dict[str, list[str]]) -> tuple[MacroImpact, str]:
    normalized = title.casefold()
    for level in ("HIGH", "MEDIUM", "LOW"):
        for phrase in rules.get(level, []):
            if phrase.casefold() in normalized:
                return MacroImpact(level), f"title matched configured {level} rule: {phrase}"
    return MacroImpact.UNKNOWN, "no configured impact rule matched; importance is unknown"


def _event_id(source_id: str, source_event_id: str) -> str:
    digest = hashlib.sha256(f"{source_id}|{source_event_id}".encode("utf-8")).hexdigest()
    return f"{source_id}:{digest[:32]}"


def _http_fetch(url: str, timeout_seconds: int = 12, max_bytes: int = 4_000_000) -> str:
    request = Request(url, headers={
        "User-Agent": "EURUSD-Market-Brain/1.0 (official public calendar ingestion)",
        "Accept": "text/calendar, application/json, text/html;q=0.9, */*;q=0.5",
    })
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise CalendarSourceError("calendar response exceeds maximum size")
            charset = response.headers.get_content_charset() or "utf-8"
    except CalendarSourceError:
        raise
    except Exception as exc:
        raise CalendarSourceError(f"calendar transport failed: {type(exc).__name__}: {exc}") from exc
    try:
        return data.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise CalendarSourceError("calendar response is not valid text") from exc


class MacroCalendarEngine:
    """Official-source event calendar; it annotates context and never creates trade signals."""

    def __init__(
        self,
        store: MacroCalendarStore,
        sources: list[dict],
        fetcher: Callable[[str], str] = _http_fetch,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.store = store
        self.sources = tuple(sources)
        self.fetcher = fetcher
        self.clock = clock
        self._validate_sources()

    @classmethod
    def from_config(
        cls,
        store: MacroCalendarStore,
        config_path: str | Path,
        fetcher: Callable[[str], str] = _http_fetch,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> "MacroCalendarEngine":
        try:
            config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalendarSourceError(f"cannot load calendar source config: {exc}") from exc
        if not isinstance(config, dict) or config.get("schema_version") != 1:
            raise CalendarSourceError("calendar source config schema_version must be 1")
        sources = config.get("sources")
        if not isinstance(sources, list):
            raise CalendarSourceError("calendar source config requires a sources array")
        return cls(store, sources, fetcher=fetcher, clock=clock)

    def _validate_sources(self) -> None:
        seen = set()
        for source in self.sources:
            required = {
                "source_id", "name", "url", "format", "currency_codes",
                "category", "timezone", "enabled", "refresh_interval_seconds",
                "stale_after_seconds", "impact_rules",
            }
            if not isinstance(source, dict) or required - set(source):
                raise CalendarSourceError("calendar source definition is incomplete")
            source_id = source["source_id"]
            if not isinstance(source_id, str) or not source_id.strip() or source_id in seen:
                raise CalendarSourceError("calendar source ids must be unique non-empty strings")
            seen.add(source_id)
            if source["format"] not in {"ICS", "BEA_JSON", "ECB_HTML", "FED_HTML"}:
                raise CalendarSourceError(f"unsupported calendar format for {source_id}")
            if not isinstance(source["url"], str) or not source["url"].startswith("https://"):
                raise CalendarSourceError("calendar source URL must use HTTPS")
            if not isinstance(source["enabled"], bool):
                raise CalendarSourceError("enabled must be boolean")
            for key in ("refresh_interval_seconds", "stale_after_seconds"):
                if type(source[key]) is not int or source[key] <= 0:
                    raise CalendarSourceError(f"{key} must be a positive integer")
            if not isinstance(source["currency_codes"], list) or not source["currency_codes"]:
                raise CalendarSourceError("currency_codes must be a non-empty list")
            try:
                ZoneInfo(source["timezone"])
            except (ZoneInfoNotFoundError, TypeError) as exc:
                raise CalendarSourceError(f"invalid source timezone for {source_id}") from exc

    def refresh_due(self) -> dict[str, dict]:
        now = self.clock().astimezone(timezone.utc)
        states = self.store.get_source_states()
        results = {}
        for source in self.sources:
            source_id = source["source_id"]
            if not source["enabled"]:
                results[source_id] = {"status": "DISABLED", "event_count": 0}
                continue
            previous = states.get(source_id, {})
            last_attempt = previous.get("last_attempt_at_utc")
            if last_attempt and (now - last_attempt).total_seconds() < source["refresh_interval_seconds"]:
                results[source_id] = {"status": previous["status"], "skipped": True}
                continue
            try:
                raw = self.fetcher(source["url"])
                records = self._parse_source(source, raw)
                events = tuple(self._to_event(source, record, now) for record in records)
                revisions = self.store.upsert_events(events, now)
                self.store.record_source_state(source_id, "ACTIVE", now, now, len(events))
                results[source_id] = {
                    "status": "ACTIVE", "event_count": len(events), "revisions": revisions,
                }
            except Exception as exc:
                self.store.record_source_state(
                    source_id, "FAILED", now, None, 0,
                    type(exc).__name__.upper(), str(exc)[:500],
                )
                results[source_id] = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
        return results

    def _parse_source(self, source: dict, raw: str) -> list[dict]:
        if source["format"] == "ICS":
            return parse_ics_events(raw, source["timezone"])
        if source["format"] == "BEA_JSON":
            return parse_bea_release_dates(raw)
        if source["format"] == "ECB_HTML":
            return parse_ecb_meeting_calendar_html(raw)
        if source["format"] == "FED_HTML":
            return parse_fomc_calendar_html(
                raw, as_of_date=self.clock().astimezone(timezone.utc).date()
            )
        raise CalendarSourceError("unsupported source format")

    def _to_event(self, source: dict, record: dict, retrieved_at: datetime) -> MacroEvent:
        title = record["title"]
        impact, reason = _impact(title, source["impact_rules"])
        raw_status = record.get("status", "CONFIRMED").upper()
        status = {
            "CANCELLED": MacroEventStatus.CANCELLED,
            "TENTATIVE": MacroEventStatus.TENTATIVE,
            "CONFIRMED": MacroEventStatus.SCHEDULED,
        }.get(raw_status, MacroEventStatus.UNKNOWN)
        source_url = record.get("url") or source["url"]
        if not source_url.startswith(("https://", "http://")):
            source_url = source["url"]
        return MacroEvent(
            event_id=_event_id(source["source_id"], record["source_event_id"]),
            source_id=source["source_id"],
            source_name=source["name"],
            source_url=source_url,
            source_event_id=record["source_event_id"],
            title=title,
            description=record.get("description", ""),
            currency_codes=tuple(source["currency_codes"]),
            category=source["category"],
            impact=impact,
            impact_reason=reason,
            scheduled_date=record["scheduled_date"],
            scheduled_at_utc=record.get("scheduled_at_utc"),
            source_timezone=source["timezone"],
            status=status,
            reference_period=record.get("reference_period"),
            actual=None, forecast=None, previous=None, result_unit=None,
            source_updated_at_utc=record.get("source_updated_at_utc"),
            retrieved_at_utc=retrieved_at,
        )

    def build_context(
        self,
        now_utc: datetime | None = None,
        horizon_hours: int = 72,
        currencies: tuple[str, ...] = ("EUR", "USD"),
    ) -> dict:
        now = (now_utc or self.clock()).astimezone(timezone.utc)
        if horizon_hours <= 0 or horizon_hours > 24 * 31:
            raise ValueError("horizon_hours must be between 1 and 744")
        events = self.store.list_events(
            now - timedelta(hours=24), now + timedelta(hours=horizon_hours),
            currencies=currencies, limit=500,
        )
        states = self.store.get_source_states()
        stale_sources = []
        source_payload = {}
        for source in self.sources:
            state = states.get(source["source_id"])
            if state is None:
                status, age = "NOT_CONNECTED", None
            else:
                last_success = state["last_success_at_utc"]
                age = (now - last_success).total_seconds() if last_success else None
                status = state["status"]
                if age is None or age > source["stale_after_seconds"]:
                    status = "STALE" if last_success else "FAILED"
            if status in {"STALE", "FAILED", "NOT_CONNECTED"}:
                stale_sources.append(source["source_id"])
            source_payload[source["source_id"]] = {
                "status": status,
                "last_success_at_utc": (
                    state["last_success_at_utc"].isoformat()
                    if state and state["last_success_at_utc"] else None
                ),
                "age_seconds": age,
                "event_count": state["event_count"] if state else 0,
                "last_error_code": state["last_error_code"] if state else None,
            }
        serialized = []
        for event in events:
            item = event.to_dict()
            item["minutes_until_release"] = (
                round((event.scheduled_at_utc - now).total_seconds() / 60, 1)
                if event.scheduled_at_utc is not None else None
            )
            serialized.append(item)
        serialized.sort(key=lambda item: (
            item["scheduled_at_utc"] is None,
            item["scheduled_at_utc"] or item["scheduled_date"],
            item["event_id"],
        ))
        return {
            "status": "DEGRADED" if stale_sources else "AVAILABLE",
            "evaluated_at_utc": now.isoformat(),
            "horizon_hours": horizon_hours,
            "currencies": list(currencies),
            "source_states": source_payload,
            "stale_sources": stale_sources,
            "upcoming_events": serialized,
            "event_count": len(serialized),
            "high_impact_count": sum(item["impact"] == "HIGH" for item in serialized),
            "trade_authority": "NONE",
            "decision_authority": "CONTEXT_ONLY",
        }
