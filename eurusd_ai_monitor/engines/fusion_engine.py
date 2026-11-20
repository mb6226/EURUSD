from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable


class EvidenceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class FusionStatus(str, Enum):
    READY_FOR_RULES = "READY_FOR_RULES"
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    CONFLICT = "CONFLICT"


class DirectionalAgreement(str, Enum):
    ALIGNED = "ALIGNED"
    CONFLICT = "CONFLICT"
    INSUFFICIENT = "INSUFFICIENT"


_DIRECTIONAL_SPECIALISTS = frozenset({"technical", "price_action"})
_CONTEXT_ONLY_SPECIALISTS = frozenset({"macro_calendar", "news", "visual"})
_OPTIONAL_SPECIALISTS = frozenset({"visual"})
_REQUIRED_SPECIALISTS = (
    "technical",
    "price_action",
    "macro_calendar",
    "news",
)
_SUPPORTED_SPECIALISTS = frozenset(_REQUIRED_SPECIALISTS) | _OPTIONAL_SPECIALISTS


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _strings(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{field} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must not contain duplicates")
    return values


@dataclass(frozen=True)
class SpecialistEvidence:
    """Normalized, provenance-aware output from one specialist.

    Direction is permitted only for technical and price-action evidence.
    Macro, news, and visual observations are context-only and cannot vote.
    """

    specialist: str
    status: EvidenceStatus
    direction: EvidenceDirection
    evaluated_at_utc: datetime
    source_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    context_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.specialist not in _SUPPORTED_SPECIALISTS:
            raise ValueError("unsupported specialist")
        if not isinstance(self.status, EvidenceStatus):
            raise TypeError("status must be EvidenceStatus")
        if not isinstance(self.direction, EvidenceDirection):
            raise TypeError("direction must be EvidenceDirection")
        if self.specialist in _CONTEXT_ONLY_SPECIALISTS and self.direction is not EvidenceDirection.NEUTRAL:
            raise ValueError("context-only specialists cannot express market direction")
        if self.specialist in _DIRECTIONAL_SPECIALISTS and self.direction is EvidenceDirection.NEUTRAL:
            # Neutral is valid when an algorithm explicitly reports range/no setup.
            pass
        object.__setattr__(self, "evaluated_at_utc", _utc(self.evaluated_at_utc, "evaluated_at_utc"))
        for field in ("source_ids", "evidence_ids", "reason_codes", "context_flags"):
            object.__setattr__(self, field, _strings(getattr(self, field), field))


@dataclass(frozen=True)
class FusionAssessment:
    evaluated_at_utc: datetime
    status: FusionStatus
    directional_agreement: DirectionalAgreement
    directional_bias: EvidenceDirection
    available_specialists: tuple[str, ...]
    blocked_specialists: tuple[str, ...]
    missing_specialists: tuple[str, ...]
    reason_codes: tuple[str, ...]
    context_flags: tuple[str, ...]
    specialist_evidence: tuple[SpecialistEvidence, ...]
    decision: str = "WAIT"
    direction: str = "NONE"
    decision_authority: str = "ASSESSMENT_ONLY"
    trade_authority: str = "NONE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at_utc", _utc(self.evaluated_at_utc, "evaluated_at_utc"))
        for field in ("available_specialists", "blocked_specialists", "missing_specialists", "reason_codes", "context_flags"):
            object.__setattr__(self, field, _strings(getattr(self, field), field))
        if not isinstance(self.specialist_evidence, tuple) or any(
            not isinstance(item, SpecialistEvidence) for item in self.specialist_evidence
        ):
            raise TypeError("specialist_evidence must be a tuple of SpecialistEvidence")
        if self.decision != "WAIT" or self.direction != "NONE":
            raise ValueError("Phase 6 fusion is assessment-only and must remain WAIT")
        if self.trade_authority != "NONE" or self.decision_authority != "ASSESSMENT_ONLY":
            raise ValueError("fusion cannot grant decision or trade authority")

    def to_dict(self) -> dict:
        return {
            "evaluated_at_utc": self.evaluated_at_utc.isoformat(),
            "status": self.status.value,
            "directional_agreement": self.directional_agreement.value,
            "directional_bias": self.directional_bias.value,
            "available_specialists": list(self.available_specialists),
            "blocked_specialists": list(self.blocked_specialists),
            "missing_specialists": list(self.missing_specialists),
            "reason_codes": list(self.reason_codes),
            "context_flags": list(self.context_flags),
            "specialists": [
                {
                    "specialist": item.specialist,
                    "status": item.status.value,
                    "direction": item.direction.value,
                    "evaluated_at_utc": item.evaluated_at_utc.isoformat(),
                    "source_ids": list(item.source_ids),
                    "evidence_ids": list(item.evidence_ids),
                    "reason_codes": list(item.reason_codes),
                    "context_flags": list(item.context_flags),
                }
                for item in self.specialist_evidence
            ],
            "decision": self.decision,
            "direction": self.direction,
            "decision_authority": self.decision_authority,
            "trade_authority": self.trade_authority,
        }


class FusionEngine:
    """Deterministic evidence gate; it does not generate or authorize trades."""

    def __init__(self, max_evidence_age_seconds: int = 300) -> None:
        if isinstance(max_evidence_age_seconds, bool) or not isinstance(max_evidence_age_seconds, int):
            raise TypeError("max_evidence_age_seconds must be an integer")
        if max_evidence_age_seconds <= 0:
            raise ValueError("max_evidence_age_seconds must be positive")
        self.max_evidence_age_seconds = max_evidence_age_seconds

    def assess(
        self,
        evaluated_at_utc: datetime,
        evidence: Iterable[SpecialistEvidence],
    ) -> FusionAssessment:
        now = _utc(evaluated_at_utc, "evaluated_at_utc")
        items = tuple(evidence)
        if any(not isinstance(item, SpecialistEvidence) for item in items):
            raise TypeError("evidence must contain SpecialistEvidence values")
        names = [item.specialist for item in items]
        if len(names) != len(set(names)):
            raise ValueError("each specialist may contribute at most once")

        by_name = {item.specialist: item for item in items}
        missing = tuple(name for name in _REQUIRED_SPECIALISTS if name not in by_name)
        blocked: list[str] = []
        available: list[str] = []
        reasons: list[str] = []

        for name in _REQUIRED_SPECIALISTS:
            item = by_name.get(name)
            if item is None:
                reasons.append(f"{name.upper()}_EVIDENCE_MISSING")
                continue
            age = (now - item.evaluated_at_utc).total_seconds()
            if age < 0:
                blocked.append(name)
                reasons.append(f"{name.upper()}_EVIDENCE_FROM_FUTURE")
            elif age > self.max_evidence_age_seconds:
                blocked.append(name)
                reasons.append(f"{name.upper()}_EVIDENCE_STALE")
            elif item.status is not EvidenceStatus.AVAILABLE:
                blocked.append(name)
                reasons.append(f"{name.upper()}_EVIDENCE_{item.status.value}")
            else:
                available.append(name)
            reasons.extend(item.reason_codes)

        technical = by_name.get("technical")
        price_action = by_name.get("price_action")
        directional_votes = []
        if technical is not None and "technical" in available:
            if technical.direction in (EvidenceDirection.UP, EvidenceDirection.DOWN):
                directional_votes.append(technical.direction)
        if price_action is not None and "price_action" in available:
            if price_action.direction in (EvidenceDirection.UP, EvidenceDirection.DOWN):
                directional_votes.append(price_action.direction)

        if len(directional_votes) < 2:
            agreement = DirectionalAgreement.INSUFFICIENT
            bias = EvidenceDirection.UNKNOWN
            reasons.append("DIRECTIONAL_EVIDENCE_INSUFFICIENT")
        elif directional_votes[0] is not directional_votes[1]:
            agreement = DirectionalAgreement.CONFLICT
            bias = EvidenceDirection.UNKNOWN
            reasons.append("TECHNICAL_PRICE_ACTION_CONFLICT")
        else:
            agreement = DirectionalAgreement.ALIGNED
            bias = directional_votes[0]

        context_flags = tuple(sorted({
            flag for item in items for flag in item.context_flags
        }))
        if missing or blocked:
            status = FusionStatus.BLOCKED
        elif agreement is DirectionalAgreement.CONFLICT:
            status = FusionStatus.CONFLICT
        elif agreement is DirectionalAgreement.INSUFFICIENT:
            status = FusionStatus.INCOMPLETE
        else:
            status = FusionStatus.READY_FOR_RULES
            reasons.append("EVIDENCE_ALIGNED_AWAITING_VALIDATED_STRATEGY_RULES")

        # Stable order, no duplicate reason codes.
        reason_codes = tuple(dict.fromkeys(reasons))
        return FusionAssessment(
            evaluated_at_utc=now,
            status=status,
            directional_agreement=agreement,
            directional_bias=bias,
            available_specialists=tuple(available),
            blocked_specialists=tuple(blocked),
            missing_specialists=missing,
            reason_codes=reason_codes,
            context_flags=context_flags,
            specialist_evidence=items,
        )
