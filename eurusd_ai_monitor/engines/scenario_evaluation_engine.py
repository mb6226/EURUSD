from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

REPORT_TYPE = "CENTRAL_MULTI_DOMAIN_SCENARIO_INTELLIGENCE"
OUTCOMES = ("EURUSD_UP_CONTINUATION", "EURUSD_DOWN_CONTINUATION", "RANGE_OR_TRANSITION")

def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field}_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(timezone.utc)

def _canonical_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return sha256(raw.encode("utf-8")).hexdigest()

class ScenarioEvaluationEngine:
    """Score only contemporaneously archived, explicitly horizon-scoped Phase43 scenarios."""
    VERSION = "scenario-evaluation-v1"

    def evaluate(self, archived_scenarios: Iterable[Mapping[str, Any]],
                 outcome_records: Iterable[Mapping[str, Any]], *,
                 broker_server: str, symbol: str = "EURUSD",
                 evaluation_cutoff_utc: datetime) -> dict[str, Any]:
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if isinstance(archived_scenarios, (str, bytes, Mapping)) or isinstance(outcome_records, (str, bytes, Mapping)):
            raise TypeError("scenario and outcome inputs must be iterables")
        if not isinstance(evaluation_cutoff_utc, datetime) or evaluation_cutoff_utc.tzinfo is None:
            raise ValueError("evaluation_cutoff_utc must be timezone-aware")
        cutoff = evaluation_cutoff_utc.astimezone(timezone.utc)
        scenarios, outcomes = list(archived_scenarios), list(outcome_records)
        rejected = Counter()
        valid_outcomes: dict[tuple[str, int], Mapping[str, Any]] = {}

        for row in outcomes:
            try:
                if not isinstance(row, Mapping):
                    raise ValueError("OUTCOME_NOT_A_MAPPING")
                if row.get("broker_server") != broker_server or row.get("symbol") != symbol:
                    raise ValueError("OUTCOME_IDENTITY_MISMATCH")
                if row.get("outcome_label") not in OUTCOMES:
                    raise ValueError("OUTCOME_LABEL_INVALID")
                horizon = row.get("horizon_minutes")
                if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
                    raise ValueError("OUTCOME_HORIZON_INVALID")
                start = _time(row.get("window_start_utc"), "OUTCOME_WINDOW_START")
                end = _time(row.get("window_end_utc"), "OUTCOME_WINDOW_END")
                observed = _time(row.get("observed_at_utc"), "OUTCOME_OBSERVED_AT")
                as_of = _time(row.get("as_of_utc"), "OUTCOME_AS_OF")
                if end <= start or end - start != timedelta(minutes=horizon):
                    raise ValueError("OUTCOME_WINDOW_HORIZON_MISMATCH")
                if end > observed or end > as_of:
                    raise ValueError("OUTCOME_NOT_CLOSED_OR_NOT_OBSERVED")
                if observed > cutoff or as_of > cutoff:
                    raise ValueError("OUTCOME_AFTER_EVALUATION_CUTOFF")
                if row.get("classification_method") != "CLOSED_BAR_CLOSE_TO_CLOSE_CLASSIFICATION":
                    raise ValueError("OUTCOME_CLASSIFICATION_METHOD_UNVERIFIED")
                if row.get("price_basis") not in {"BID", "ASK", "MID", "LAST"}:
                    raise ValueError("OUTCOME_PRICE_BASIS_UNVERIFIED")
                if row.get("bar_time_basis") != "UTC":
                    raise ValueError("OUTCOME_TIME_BASIS_UNVERIFIED")
                versions = row.get("source_version_ids")
                if not isinstance(versions, list) or not versions or any(not isinstance(x, str) or not x for x in versions):
                    raise ValueError("OUTCOME_SOURCE_VERSIONS_MISSING")
                digest = row.get("evidence_sha256")
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
                    raise ValueError("OUTCOME_EVIDENCE_HASH_INVALID")
                key = (start.isoformat(), horizon)
                if key in valid_outcomes:
                    raise ValueError("DUPLICATE_OUTCOME_WINDOW")
                valid_outcomes[key] = row
            except ValueError as exc:
                rejected[str(exc)] += 1

        scored = []
        for envelope in scenarios:
            try:
                if not isinstance(envelope, Mapping):
                    raise ValueError("SCENARIO_ENVELOPE_NOT_A_MAPPING")
                report = envelope.get("report")
                if not isinstance(report, Mapping) or report.get("report_type") != REPORT_TYPE:
                    raise ValueError("SCENARIO_REPORT_TYPE_INVALID")
                if report.get("broker_server") != broker_server or report.get("symbol") != symbol:
                    raise ValueError("SCENARIO_IDENTITY_MISMATCH")
                evaluated = _time(report.get("evaluated_at_utc"), "SCENARIO_EVALUATED_AT")
                available = _time(envelope.get("available_at_utc"), "SCENARIO_AVAILABLE_AT")
                if available > evaluated:
                    raise ValueError("SCENARIO_NOT_ARCHIVED_AT_ISSUANCE")
                if evaluated > cutoff or available > cutoff:
                    raise ValueError("SCENARIO_AFTER_EVALUATION_CUTOFF")
                if envelope.get("report_sha256") != _canonical_hash(report):
                    raise ValueError("SCENARIO_ARCHIVE_HASH_MISMATCH")
                if report.get("status") in {"DEGRADED", "AUTHORITY_VIOLATION"}:
                    raise ValueError("SCENARIO_REPORT_DEGRADED")
                spec = report.get("scenario_evaluation_spec")
                if not isinstance(spec, Mapping):
                    raise ValueError("SCENARIO_EVALUATION_SPEC_MISSING")
                horizon = spec.get("horizon_minutes")
                if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
                    raise ValueError("SCENARIO_HORIZON_NOT_EXPLICIT")
                if spec.get("outcome_classifier") != "CLOSED_BAR_CLOSE_TO_CLOSE_CLASSIFICATION":
                    raise ValueError("SCENARIO_OUTCOME_CLASSIFIER_UNSUPPORTED")
                if not isinstance(spec.get("invalidation_rules_version"), str) or not spec["invalidation_rules_version"].strip():
                    raise ValueError("SCENARIO_INVALIDATION_RULES_VERSION_MISSING")
                hypotheses = report.get("scenario_hypotheses")
                if not isinstance(hypotheses, list):
                    raise ValueError("SCENARIO_HYPOTHESES_MISSING")
                leaders = [x for x in hypotheses if isinstance(x, Mapping) and x.get("status") == "LEADING_HYPOTHESIS"]
                if len(leaders) != 1:
                    raise ValueError("SCENARIO_LEADING_HYPOTHESIS_NOT_UNIQUE")
                scenario_id = leaders[0].get("scenario_id")
                if scenario_id not in OUTCOMES:
                    raise ValueError("SCENARIO_LEADING_HYPOTHESIS_INVALID")
                outcome = valid_outcomes.get((evaluated.isoformat(), horizon))
                if outcome is None:
                    rejected["MATCHING_VERIFIED_OUTCOME_UNAVAILABLE"] += 1
                    continue
                if _time(outcome.get("window_start_utc"), "OUTCOME_WINDOW_START") != evaluated:
                    raise ValueError("OUTCOME_START_DOES_NOT_MATCH_SCENARIO_CUTOFF")
                if _time(outcome.get("window_end_utc"), "OUTCOME_WINDOW_END") != evaluated + timedelta(minutes=horizon):
                    raise ValueError("OUTCOME_END_DOES_NOT_MATCH_DECLARED_HORIZON")
                scored.append({
                    "scenario_report_sha256": envelope["report_sha256"],
                    "scenario_evaluated_at_utc": evaluated.isoformat().replace("+00:00", "Z"),
                    "horizon_minutes": horizon, "predicted_leading_scenario": scenario_id,
                    "realized_outcome": outcome["outcome_label"],
                    "match": scenario_id == outcome["outcome_label"],
                    "outcome_evidence_sha256": outcome["evidence_sha256"],
                    "outcome_source_version_ids": list(outcome["source_version_ids"]),
                })
            except ValueError as exc:
                rejected[str(exc)] += 1

        confusion = {p: {a: 0 for a in OUTCOMES} for p in OUTCOMES}
        for row in scored:
            confusion[row["predicted_leading_scenario"]][row["realized_outcome"]] += 1
        count = len(scored)
        from collections import Counter as _Counter
        horizon_counts = _Counter(str(row["horizon_minutes"]) for row in scored)
        return {
            "report_type": "CENTRAL_SCENARIO_EVALUATION", "engine_version": self.VERSION,
            "status": "AVAILABLE" if count else ("NO_ARCHIVED_SCENARIOS" if not scenarios else "BLOCKED"),
            "evaluation_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
            "broker_server": broker_server, "symbol": symbol,
            "scenario_envelopes_received": len(scenarios), "outcome_records_received": len(outcomes),
            "scored_scenario_count": count,
            "scenario_match_rate": (str(sum(x["match"] for x in scored) / count) if count else None),
            "horizon_sample_counts": dict(sorted(horizon_counts.items(), key=lambda x: int(x[0]))),
            "confusion_matrix_predicted_rows_realized_columns": confusion,
            "rejected_counts": dict(sorted(rejected.items())), "scored_records": scored,
            "methodology": {
                "matching": "Exact broker/symbol, issue cutoff and explicitly declared horizon; no nearest-time matching.",
                "prediction": "The single contemporaneously archived LEADING_HYPOTHESIS in the Phase43 qualitative scenario set.",
                "outcome": "Separately supplied verified closed-bar outcome with exact matching window and source-version evidence.",
                "horizon": "No default horizon; reports without a contemporaneous scenario_evaluation_spec are not scoreable.",
                "archive": "Canonical report hash and available_at_utc must prove archival no later than issue timestamp.",
            },
            "limitations": [
                "Qualitative scenario match rate is not trading profitability, expectancy, win rate, or realized P/L.",
                "No probabilities, Brier score, calibration, confidence score, or model promotion are produced.",
                "A leading hypothesis is evaluated categorically, not probabilistically.",
                "Missing Phase43 reports are never reconstructed; horizon and invalidation rules are never inferred after the fact.",
                "Outcome evidence must come from immutable, point-in-time closed-bar versions.",
                "Current Phase43 reports do not carry scenario_evaluation_spec and are intentionally ineligible.",
            ],
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE", "order_execution": "DISABLED",
        }
