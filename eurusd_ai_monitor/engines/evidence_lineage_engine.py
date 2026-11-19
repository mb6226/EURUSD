from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Mapping, Sequence


_SOURCE_TIMEFRAMES = {
    "technical_analysis": {"M5"},
    "fusion_assessment": {"M5"},
    "market_regime_intelligence": {"M1", "M5"},
    "price_action_lifecycle": {"M1", "M5"},
    "setup_assessment": {"M1"},
}


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_time(value, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is missing")
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")), field)


def candle_evidence_id(*, broker_server: str, symbol: str, timeframe: str,
                       open_time_utc: datetime) -> str:
    opened = _utc(open_time_utc, "open_time_utc")
    return (
        f"{broker_server}|{symbol}|{timeframe}|"
        f"{opened.isoformat().replace('+00:00', 'Z')}"
    )


def build_candle_inventory(candles: Sequence, *, evaluated_at_utc: datetime) -> list[dict]:
    evaluated = _utc(evaluated_at_utc, "evaluated_at_utc")
    inventory = []
    for candle in candles:
        timeframe = getattr(candle, "timeframe", None)
        seconds = {"M1": 60, "M5": 300}.get(timeframe)
        if seconds is None:
            raise ValueError("unsupported candle timeframe")
        opened = _utc(candle.candle_open_time_utc, "candle_open_time_utc")
        closed = opened + timedelta(seconds=seconds)
        inventory.append({
            "candle_id": candle_evidence_id(
                broker_server=candle.broker_server,
                symbol=candle.symbol,
                timeframe=timeframe,
                open_time_utc=opened,
            ),
            "broker_server": candle.broker_server,
            "symbol": candle.symbol,
            "timeframe": timeframe,
            "open_time_utc": opened.isoformat(),
            "close_time_utc": closed.isoformat(),
        })
    return inventory


class EvidenceLineageEngine:
    """Pure audit of specialist candle references against one closed-candle snapshot."""

    def audit(self, *, evaluated_at_utc: datetime, broker_server: str, symbol: str,
              candle_inventory: Sequence[Mapping],
              sources: Mapping[str, Mapping]) -> dict:
        evaluated = _utc(evaluated_at_utc, "evaluated_at_utc")
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if not isinstance(candle_inventory, Sequence) or isinstance(candle_inventory, (str, bytes)):
            raise TypeError("candle_inventory must be a sequence")
        if not isinstance(sources, Mapping):
            raise TypeError("sources must be a mapping")

        index = {}
        inventory_errors = []
        for position, item in enumerate(candle_inventory):
            if not isinstance(item, Mapping):
                inventory_errors.append(f"INVENTORY_ITEM_{position}_MALFORMED")
                continue
            candle_id = item.get("candle_id")
            if not isinstance(candle_id, str) or not candle_id:
                inventory_errors.append(f"INVENTORY_ITEM_{position}_ID_MISSING")
                continue
            if candle_id in index:
                inventory_errors.append("DUPLICATE_CANDLE_ID")
                continue
            try:
                opened = _parse_time(item.get("open_time_utc"), "open_time_utc")
                closed = _parse_time(item.get("close_time_utc"), "close_time_utc")
            except (TypeError, ValueError):
                inventory_errors.append("INVENTORY_TIMESTAMP_INVALID")
                continue
            timeframe = item.get("timeframe")
            if timeframe not in {"M1", "M5"}:
                inventory_errors.append("INVENTORY_TIMEFRAME_INVALID")
                continue
            if item.get("broker_server") != broker_server or item.get("symbol") != symbol:
                inventory_errors.append("INVENTORY_IDENTITY_MISMATCH")
                continue
            if closed <= opened or closed > evaluated:
                inventory_errors.append("INVENTORY_CANDLE_NOT_CLOSED_AT_CYCLE")
                continue
            expected_id = candle_evidence_id(
                broker_server=broker_server, symbol=symbol,
                timeframe=timeframe, open_time_utc=opened,
            )
            if expected_id != candle_id:
                inventory_errors.append("INVENTORY_CANDLE_ID_MISMATCH")
                continue
            index[candle_id] = {
                "timeframe": timeframe,
                "open_time_utc": opened,
                "close_time_utc": closed,
            }

        manifests = []
        all_references = set()
        all_missing = []
        for source in sorted(_SOURCE_TIMEFRAMES):
            payload = sources.get(source)
            if not isinstance(payload, Mapping):
                manifests.append({
                    "source": source, "status": "SOURCE_UNAVAILABLE",
                    "reference_count": 0, "resolved_count": 0,
                    "missing_candle_ids": [], "references": [],
                })
                continue
            references, evidence_objects = self._collect(payload)
            unique = sorted(references)
            raw_source_status = str(payload.get("status", "")).upper()
            unavailable = raw_source_status in {"UNAVAILABLE", "SKIPPED", "NOT_CONNECTED", "NOT_CONFIGURED"}
            source_degraded = raw_source_status == "DEGRADED"
            all_references.update(unique)
            missing = [item for item in unique if item not in index]
            all_missing.extend((source, item) for item in missing)
            invalid_timeframes = [
                item for item in unique
                if item in index and index[item]["timeframe"] not in _SOURCE_TIMEFRAMES[source]
            ]
            invalid_confirmations = self._validate_evidence_objects(
                evidence_objects, index, evaluated
            )
            errors = []
            if source_degraded:
                errors.append("SPECIALIST_SOURCE_DEGRADED")
            if missing:
                errors.append("REFERENCED_CANDLE_NOT_IN_SNAPSHOT")
            if invalid_timeframes:
                errors.append("REFERENCE_TIMEFRAME_CONTRACT_VIOLATION")
            if invalid_confirmations:
                errors.extend(invalid_confirmations)
            manifests.append({
                "source": source,
                "status": "DEGRADED" if errors else (
                    "SOURCE_UNAVAILABLE" if unavailable else
                    ("TRACEABLE" if unique else "NO_REFERENCES")
                ),
                "reference_count": len(unique),
                "resolved_count": len([item for item in unique if item in index]),
                "missing_candle_ids": missing,
                "invalid_timeframe_candle_ids": invalid_timeframes,
                "reason_codes": sorted(set(errors)),
                "references": [
                    {
                        "candle_id": item,
                        "timeframe": index[item]["timeframe"],
                        "open_time_utc": index[item]["open_time_utc"].isoformat(),
                    }
                    for item in unique if item in index
                ],
            })

        total_refs = len(all_references)
        resolved_refs = sum(1 for item in all_references if item in index)
        used_inventory = all_references.intersection(index)
        orphaned = sorted(set(index).difference(used_inventory))
        reasons = list(inventory_errors)
        if all_missing:
            reasons.append("REFERENCED_CANDLE_NOT_IN_SNAPSHOT")
        if any(item["status"] == "DEGRADED" for item in manifests):
            reasons.append("SOURCE_LINEAGE_CONTRACT_VIOLATION")
        status = "DEGRADED" if reasons else ("PARTIAL" if any(
            item["status"] == "SOURCE_UNAVAILABLE" for item in manifests
        ) else "TRACEABLE")
        digest_input = "\n".join(sorted(index)).encode("utf-8")
        return {
            "status": status,
            "evaluated_at_utc": evaluated.isoformat(),
            "broker_server": broker_server,
            "symbol": symbol,
            "inventory": {
                "total_candles": len(index),
                "m1_candles": sum(1 for item in index.values() if item["timeframe"] == "M1"),
                "m5_candles": sum(1 for item in index.values() if item["timeframe"] == "M5"),
                "inventory_sha256": sha256(digest_input).hexdigest(),
                "invalid_items": len(inventory_errors),
            },
            "reference_coverage": {
                "unique_references": total_refs,
                "resolved_references": resolved_refs,
                "missing_references": len(all_missing),
                "coverage_ratio": (
                    format(resolved_refs / total_refs, ".6f") if total_refs else "1.000000"
                ),
                "orphaned_inventory_count": len(orphaned),
                "orphaned_candle_ids": orphaned,
            },
            "source_manifest": manifests,
            "reason_codes": sorted(set(reasons)),
            "interpretation_limits": [
                "Lineage confirms that referenced candle IDs exist in this cycle snapshot; it does not validate the trading merit of the pattern.",
                "Only M1 and M5 closed-candle identity and temporal traceability are audited.",
                "An orphaned inventory candle is not a defect; it may simply be unused by a specialist.",
                "Traceable evidence does not grant entry, trade, or order authority.",
            ],
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    @classmethod
    def _collect(cls, payload):
        references = set()
        evidence_objects = []

        def walk(value):
            if isinstance(value, Mapping):
                candle_id = value.get("candle_id")
                if isinstance(candle_id, str) and candle_id:
                    references.add(candle_id)
                    if isinstance(value.get("candle"), Mapping):
                        evidence_objects.append(value)
                for key, child in value.items():
                    if key.endswith("_candle_id") and isinstance(child, str) and child:
                        references.add(child)
                    if key.endswith("_candle_ids") or key in {
                        "evidence_candle_ids", "supporting_candle_ids", "evidence_ids"
                    }:
                        if isinstance(child, (list, tuple)):
                            references.update(
                                item for item in child
                                if isinstance(item, str) and item
                            )
                    walk(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    walk(child)

        walk(payload)
        return references, evidence_objects

    @staticmethod
    def _validate_evidence_objects(objects, index, evaluated):
        errors = []
        for item in objects:
            candle_id = item.get("candle_id")
            known = index.get(candle_id)
            if known is None:
                continue
            candle = item.get("candle", {})
            try:
                opened = _parse_time(candle.get("open_time_utc"), "evidence.open_time_utc")
                confirmed = _parse_time(item.get("confirmed_at_utc"), "evidence.confirmed_at_utc")
            except (TypeError, ValueError):
                errors.append("EVIDENCE_CONFIRMATION_TIMESTAMP_INVALID")
                continue
            timeframe = candle.get("timeframe")
            seconds = {"M1": 60, "M5": 300}.get(timeframe)
            if seconds is None or timeframe != known["timeframe"] or opened != known["open_time_utc"]:
                errors.append("EVIDENCE_METADATA_MISMATCH")
                continue
            if confirmed < known["close_time_utc"] or confirmed > evaluated:
                errors.append("EVIDENCE_CONFIRMATION_OUT_OF_BOUNDS")
        return errors
