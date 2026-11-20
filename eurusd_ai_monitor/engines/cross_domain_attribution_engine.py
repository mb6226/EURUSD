from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite, sqrt
from statistics import mean
import json
from typing import Any, Mapping

HORIZONS = ("15M", "1H", "4H")
DOMAINS = (
    "spot_fx", "macro_fundamentals", "monetary_policy", "intermarket",
    "positioning_sentiment", "news_event", "market_regime", "session_time",
    "liquidity_microstructure", "cross_domain_relationship",
)
DEPENDENCY_GROUPS = {
    "EURUSD_PRICE_DERIVED_LINEAGE": ("spot_fx", "market_regime", "session_time", "liquidity_microstructure"),
    "MACRO_POLICY_LINEAGE": ("macro_fundamentals", "monetary_policy"),
    "INTERMARKET_LINEAGE": ("intermarket",),
    "POSITIONING_LINEAGE": ("positioning_sentiment",),
    "NEWS_EVENT_LINEAGE": ("news_event",),
    "DERIVED_CROSS_DOMAIN_LINEAGE": ("cross_domain_relationship",),
}


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


class CrossDomainAttributionEngine:
    """Descriptive, point-in-time conditional attribution; never causal feature importance."""

    VERSION = "cross-domain-attribution-v1"

    def __init__(self, *, minimum_state_samples: int = 30):
        if isinstance(minimum_state_samples, bool) or not isinstance(minimum_state_samples, int) or minimum_state_samples < 5:
            raise ValueError("minimum_state_samples must be an integer >= 5")
        self.minimum_state_samples = minimum_state_samples

    def analyze(self, replay: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(replay, Mapping):
            raise TypeError("replay must be a mapping")
        if replay.get("report_type") != "EURUSD_POINT_IN_TIME_FORECAST_REPLAY":
            raise ValueError("UNSUPPORTED_REPLAY_REPORT_TYPE")
        if replay.get("status") != "COMPLETE":
            return self._blocked(replay, "REPLAY_NOT_COMPLETE")
        if replay.get("symbol") != "EURUSD" or replay.get("timeframe") != "M5":
            raise ValueError("REPLAY_STREAM_IDENTITY_UNSUPPORTED")
        if not replay.get("replay_id") or not replay.get("source_history_sha256"):
            raise ValueError("REPLAY_IDENTITY_OR_SOURCE_HASH_MISSING")
        policy = replay.get("integrity_policy")
        required = (
            "forecast_inputs_filtered_by_observed_and_as_of_at_each_cutoff",
            "only_closed_candles_used",
            "target_outcome_uses_first_closed_version_observed_after_target_close",
            "later_revisions_never_rewrite_forecast_or_target_version",
            "future_outcomes_excluded_from_forecast_snapshot",
            "system_knowledge_replay_only",
        )
        if not isinstance(policy, Mapping) or any(policy.get(k) is not True for k in required):
            raise ValueError("REPLAY_POINT_IN_TIME_INTEGRITY_POLICY_UNVERIFIED")
        records = replay.get("records")
        if not isinstance(records, list):
            raise ValueError("REPLAY_RECORDS_MISSING")

        accepted = {h: [] for h in HORIZONS}
        rejected = Counter()
        seen = set()
        domain_coverage = Counter()
        for row in records:
            if not isinstance(row, Mapping):
                rejected["RECORD_NOT_A_MAPPING"] += 1
                continue
            horizon = row.get("horizon")
            if horizon not in HORIZONS:
                rejected["HORIZON_UNSUPPORTED"] += 1
                continue
            forecast_id = row.get("forecast_id")
            if not isinstance(forecast_id, str) or not forecast_id:
                rejected["FORECAST_ID_MISSING"] += 1
                continue
            if forecast_id in seen:
                rejected["DUPLICATE_FORECAST_ID"] += 1
                continue
            seen.add(forecast_id)
            if row.get("replay_id") != replay["replay_id"]:
                rejected["REPLAY_ID_MISMATCH"] += 1
                continue
            if row.get("forecast_status") != "AVAILABLE":
                rejected["FORECAST_NOT_AVAILABLE"] += 1
                continue
            if not row.get("snapshot_sha256") or not row.get("anchor_version_id") or not row.get("target_version_id"):
                rejected["FORECAST_OR_TARGET_PROVENANCE_MISSING"] += 1
                continue
            cutoff = _time(row.get("forecast_cutoff_utc"))
            target_close = _time(row.get("target_close_time_utc"))
            if cutoff is None or target_close is None or target_close <= cutoff:
                rejected["FORECAST_TARGET_TIME_INVALID"] += 1
                continue
            expected = _finite(row.get("expected_move_pips"))
            actual = _finite(row.get("actual_move_pips"))
            if expected is None or actual is None:
                rejected["COMPLETED_OUTCOME_MISSING_OR_INVALID"] += 1
                continue
            if row.get("forecast_direction") not in {"UP", "DOWN", "NEUTRAL"} or row.get("outcome_direction") not in {"UP", "DOWN", "NEUTRAL"}:
                rejected["DIRECTION_LABEL_INVALID"] += 1
                continue
            context = row.get("domain_context")
            if not isinstance(context, Mapping):
                rejected["CONTEMPORANEOUS_DOMAIN_CONTEXT_MISSING"] += 1
                continue
            valid_context = {}
            for domain, feature in context.items():
                if domain not in DOMAINS:
                    rejected["DOMAIN_UNSUPPORTED"] += 1
                    continue
                if not isinstance(feature, Mapping):
                    rejected["DOMAIN_FEATURE_INVALID"] += 1
                    continue
                status = feature.get("status")
                state = feature.get("state")
                evaluated = _time(feature.get("evaluated_at_utc"))
                available = _time(feature.get("available_at_utc"))
                as_of = _time(feature.get("as_of_utc"))
                if not isinstance(state, str) or not state.strip():
                    rejected["DOMAIN_STATE_MISSING"] += 1
                    continue
                if (evaluated is None or available is None or as_of is None
                    or evaluated > cutoff or available > cutoff or as_of > cutoff):
                    rejected["DOMAIN_CONTEXT_LOOKAHEAD_OR_TIME_INVALID"] += 1
                    continue
                if feature.get("bound_forecast_snapshot_sha256") != row["snapshot_sha256"]:
                    rejected["DOMAIN_CONTEXT_FORECAST_SNAPSHOT_MISMATCH"] += 1
                    continue
                context_hash = feature.get("context_snapshot_sha256")
                if not isinstance(context_hash, str) or len(context_hash) != 64 or any(c not in "0123456789abcdef" for c in context_hash.lower()):
                    rejected["DOMAIN_CONTEXT_HASH_INVALID"] += 1
                    continue
                lineage = feature.get("source_lineage_ids")
                refs = feature.get("evidence_refs")
                if status == "AVAILABLE":
                    if (not isinstance(lineage, list) or not lineage or any(not isinstance(x, str) or not x for x in lineage)
                        or not isinstance(refs, list) or not refs or any(not isinstance(x, str) or not x for x in refs)):
                        rejected["DOMAIN_EVIDENCE_LINEAGE_MISSING"] += 1
                        continue
                    valid_context[domain] = {
                        "state": state.strip().upper(),
                        "lineage": tuple(sorted(set(lineage))),
                        "context_hash": context_hash,
                    }
                    domain_coverage[domain] += 1
                elif status in {"MISSING", "BLOCKED", "INSUFFICIENT_EVIDENCE", "UNAVAILABLE"}:
                    valid_context[domain] = {"state": "UNAVAILABLE", "lineage": (), "context_hash": context_hash}
                    domain_coverage[domain] += 1
                else:
                    rejected["DOMAIN_STATUS_UNSUPPORTED"] += 1
            if not valid_context:
                rejected["NO_VALID_DOMAIN_CONTEXT"] += 1
                continue
            accepted[horizon].append({
                "forecast_id": forecast_id, "cutoff": cutoff,
                "expected": expected, "actual": actual,
                "error": actual - expected, "absolute_error": abs(actual - expected),
                "direction_hit": row["forecast_direction"] == row["outcome_direction"],
                "domains": valid_context,
            })

        by_horizon = {}
        for horizon, rows in accepted.items():
            by_horizon[horizon] = self._analyze_horizon(rows, horizon)
        accepted_count = sum(len(v) for v in accepted.values())
        evaluated_horizons = sum(v["status"] == "ATTRIBUTION_AVAILABLE" for v in by_horizon.values())
        status = "AVAILABLE" if evaluated_horizons == len(HORIZONS) else "PARTIAL" if evaluated_horizons else "BLOCKED"
        identity = {
            "engine": self.VERSION, "replay_id": replay["replay_id"],
            "source_history_sha256": replay["source_history_sha256"],
            "minimum_state_samples": self.minimum_state_samples,
            "by_horizon": by_horizon,
        }
        return {
            "report_type": "EURUSD_CROSS_DOMAIN_ATTRIBUTION",
            "engine_version": self.VERSION, "status": status,
            "attribution_id": sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
            "replay_id": replay["replay_id"], "source_history_sha256": replay["source_history_sha256"],
            "symbol": "EURUSD", "timeframe": "M5",
            "minimum_state_samples": self.minimum_state_samples,
            "replay_records_received": len(records),
            "accepted_completed_records": accepted_count,
            "rejected_counts": dict(sorted(rejected.items())),
            "domain_context_coverage": dict(sorted(domain_coverage.items())),
            "by_horizon": by_horizon,
            "dependency_lineage_policy": {
                group: {"domains": list(members), "independent_confirmation_count": 0}
                for group, members in DEPENDENCY_GROUPS.items()
            },
            "interpretation_contract": {
                "method": "CONDITIONAL_STRATIFICATION_OF_OUT_OF_SAMPLE_FORECAST_ERRORS_BY_CONTEMPORANEOUS_DOMAIN_STATE",
                "causality": "NOT_ESTABLISHED",
                "feature_importance": "NOT_ESTIMATED",
                "incremental_predictive_contribution": "NOT_ESTIMATED",
                "shared_lineage": "RELATED_DOMAIN_VIEWS_ARE_NOT_INDEPENDENT_CONFIRMATIONS",
                "cross_domain_relationships": "DERIVED_CONTEXT_ONLY_NOT_AN_INDEPENDENT_CAUSAL_DRIVER",
                "horizon_pooling": False,
                "missing_context_imputation": False,
                "lookahead_permitted": False,
            },
            "limitations": [
                "Conditional differences describe association only and do not establish causation or incremental predictive value.",
                "Unmeasured confounding, selection effects, overlapping forecast horizons and serial dependence may influence results.",
                "Small state groups are reported as insufficient and are not ranked.",
                "Domain context must have been archived and available no later than its forecast cutoff; absent historical context is never reconstructed.",
                "Forecast outcomes are descriptive market moves, not trade P/L or profitability.",
                "No feature selection, model tuning, probability, calibrated confidence or live decision authority is produced.",
            ],
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }

    def _analyze_horizon(self, rows, horizon):
        if not rows:
            return {"status": "BLOCKED_NO_VALID_COMPLETED_CONTEXT_RECORDS", "sample_count": 0, "domains": {}}
        baseline = {
            "sample_count": len(rows),
            "mean_absolute_error_pips": mean(r["absolute_error"] for r in rows),
            "root_mean_squared_error_pips": sqrt(mean(r["error"] ** 2 for r in rows)),
            "mean_signed_error_pips": mean(r["error"] for r in rows),
            "directional_accuracy": mean(1.0 if r["direction_hit"] else 0.0 for r in rows),
        }
        results = {}
        for domain in DOMAINS:
            groups = defaultdict(list)
            for row in rows:
                feature = row["domains"].get(domain)
                if feature is not None:
                    groups[feature["state"]].append((row, feature))
            states = {}
            for state, items in sorted(groups.items()):
                count = len(items)
                if state == "UNAVAILABLE" or count < self.minimum_state_samples:
                    states[state] = {
                        "status": "UNAVAILABLE" if state == "UNAVAILABLE" else "INSUFFICIENT_SAMPLE",
                        "sample_count": count,
                        "metrics": None,
                    }
                    continue
                subset = [item[0] for item in items]
                lineage_sets = sorted({item[1]["lineage"] for item in items if item[1]["lineage"]})
                states[state] = {
                    "status": "DESCRIPTIVE_ASSOCIATION_AVAILABLE",
                    "sample_count": count,
                    "metrics": {
                        "mean_absolute_error_pips": mean(r["absolute_error"] for r in subset),
                        "root_mean_squared_error_pips": sqrt(mean(r["error"] ** 2 for r in subset)),
                        "mean_signed_error_pips": mean(r["error"] for r in subset),
                        "directional_accuracy": mean(1.0 if r["direction_hit"] else 0.0 for r in subset),
                        "mae_delta_vs_horizon_baseline_pips": mean(r["absolute_error"] for r in subset) - baseline["mean_absolute_error_pips"],
                        "directional_accuracy_delta_vs_horizon_baseline": mean(1.0 if r["direction_hit"] else 0.0 for r in subset) - baseline["directional_accuracy"],
                    },
                    "distinct_source_lineage_sets": len(lineage_sets),
                    "independent_confirmation_count": 0,
                }
            results[domain] = {
                "observed_state_count": len(groups),
                "state_results": states,
                "association_ranking": "NOT_PROVIDED",
            }
        return {"status": "ATTRIBUTION_AVAILABLE", "sample_count": len(rows), "baseline": baseline, "domains": results}

    def _blocked(self, replay, reason):
        return {
            "report_type": "EURUSD_CROSS_DOMAIN_ATTRIBUTION",
            "engine_version": self.VERSION, "status": "BLOCKED",
            "reason_codes": [reason], "replay_id": replay.get("replay_id"),
            "accepted_completed_records": 0,
            "by_horizon": {h: {"status": "BLOCKED_NO_VALID_REPLAY"} for h in HORIZONS},
            "decision_authority": "ASSESSMENT_ONLY", "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }
