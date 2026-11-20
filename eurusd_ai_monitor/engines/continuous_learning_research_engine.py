from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

_REQUIRED_PIT_FLAGS = (
    "forecast_inputs_filtered_by_observed_and_as_of_at_each_cutoff",
    "only_closed_candles_used",
    "target_outcome_uses_first_closed_version_observed_after_target_close",
    "later_revisions_never_rewrite_forecast_or_target_version",
    "future_outcomes_excluded_from_forecast_snapshot",
    "system_knowledge_replay_only",
)
_HORIZONS = ("15M", "1H", "4H")


def _canonical_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


class ContinuousLearningResearchEngine:
    """Governed research-cycle assessment; it never trains or promotes live models."""

    VERSION = "continuous-learning-research-v1"

    def __init__(self, *, minimum_oos_folds: int = 2, minimum_oos_samples: int = 100):
        if isinstance(minimum_oos_folds, bool) or not isinstance(minimum_oos_folds, int) or minimum_oos_folds < 2:
            raise ValueError("minimum_oos_folds must be an integer >= 2")
        if isinstance(minimum_oos_samples, bool) or not isinstance(minimum_oos_samples, int) or minimum_oos_samples < 30:
            raise ValueError("minimum_oos_samples must be an integer >= 30")
        self.minimum_oos_folds = minimum_oos_folds
        self.minimum_oos_samples = minimum_oos_samples

    def assess(
        self, replay: Mapping[str, Any], walk_forward: Mapping[str, Any],
        attribution: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not all(isinstance(x, Mapping) for x in (replay, walk_forward, attribution)):
            raise TypeError("research inputs must be mappings")
        if replay.get("report_type") != "EURUSD_POINT_IN_TIME_FORECAST_REPLAY":
            raise ValueError("UNSUPPORTED_REPLAY_REPORT_TYPE")
        if walk_forward.get("report_type") != "EURUSD_WALK_FORWARD_VALIDATION":
            raise ValueError("UNSUPPORTED_WALK_FORWARD_REPORT_TYPE")
        if attribution.get("report_type") != "EURUSD_CROSS_DOMAIN_ATTRIBUTION":
            raise ValueError("UNSUPPORTED_ATTRIBUTION_REPORT_TYPE")

        blockers: list[str] = []
        if replay.get("status") != "COMPLETE":
            blockers.append("COMPLETE_POINT_IN_TIME_REPLAY_REQUIRED")
        policy = replay.get("integrity_policy")
        if not isinstance(policy, Mapping) or any(policy.get(k) is not True for k in _REQUIRED_PIT_FLAGS):
            blockers.append("REPLAY_INTEGRITY_POLICY_UNVERIFIED")
        replay_id = replay.get("replay_id")
        source_hash = replay.get("source_history_sha256")
        if not replay_id or not isinstance(source_hash, str):
            blockers.append("REPLAY_IDENTITY_OR_SOURCE_HASH_MISSING")
        elif len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash.lower()):
            blockers.append("REPLAY_SOURCE_HASH_INVALID")
        if replay.get("symbol") not in (None, "EURUSD") or replay.get("timeframe") not in (None, "M5"):
            blockers.append("REPLAY_STREAM_IDENTITY_UNSUPPORTED")
        for label, report in (("WALK_FORWARD", walk_forward), ("ATTRIBUTION", attribution)):
            if report.get("replay_id") != replay_id or report.get("source_history_sha256") != source_hash:
                blockers.append(f"{label}_REPLAY_OR_SOURCE_MISMATCH")
            if report.get("symbol") not in (None, "EURUSD") or report.get("timeframe") not in (None, "M5"):
                blockers.append(f"{label}_STREAM_IDENTITY_UNSUPPORTED")
        if walk_forward.get("status") not in {"AVAILABLE", "PARTIAL"}:
            blockers.append("WALK_FORWARD_EVIDENCE_UNAVAILABLE")
        if attribution.get("status") not in {"AVAILABLE", "PARTIAL"}:
            blockers.append("CROSS_DOMAIN_ATTRIBUTION_UNAVAILABLE")

        horizon_gate = {}
        for horizon in _HORIZONS:
            wf = (walk_forward.get("by_horizon") or {}).get(horizon, {})
            at = (attribution.get("by_horizon") or {}).get(horizon, {})
            folds = wf.get("folds", []) if isinstance(wf, Mapping) else []
            fold_count = wf.get("fold_count", len(folds) if isinstance(folds, list) else 0) if isinstance(wf, Mapping) else 0
            sample_count = wf.get("completed_outcome_count", wf.get("accepted_completed_records", 0)) if isinstance(wf, Mapping) else 0
            try:
                sample_count = int(sample_count or 0)
                fold_count = int(fold_count or 0)
            except (TypeError, ValueError):
                sample_count = 0
                fold_count = 0
            passed = (
                wf.get("status") == "WALK_FORWARD_EVALUATED"
                and fold_count >= self.minimum_oos_folds
                and sample_count >= self.minimum_oos_samples
                and at.get("status") == "ATTRIBUTION_AVAILABLE"
                and int(at.get("sample_count", 0) or 0) >= self.minimum_oos_samples
            )
            horizon_gate[horizon] = {
                "status": "RESEARCH_EVIDENCE_READY" if passed else "BLOCKED_OR_INSUFFICIENT",
                "walk_forward_status": wf.get("status"),
                "walk_forward_fold_count": fold_count,
                "walk_forward_sample_count": sample_count,
                "attribution_status": at.get("status"),
                "attribution_sample_count": int(at.get("sample_count", 0) or 0) if isinstance(at, Mapping) else 0,
                "live_promotion": "PROHIBITED",
            }
            if not passed:
                blockers.append(f"{horizon}_OOS_RESEARCH_GATE_NOT_MET")

        ready_count = sum(v["status"] == "RESEARCH_EVIDENCE_READY" for v in horizon_gate.values())
        status = "READY_FOR_GOVERNED_RESEARCH_REVIEW" if not blockers and ready_count == len(_HORIZONS) else "BLOCKED"
        identity = {
            "engine": self.VERSION, "replay_id": replay_id, "source_history_sha256": source_hash,
            "horizon_gate": horizon_gate, "blockers": sorted(set(blockers)),
            "minimum_oos_folds": self.minimum_oos_folds,
            "minimum_oos_samples": self.minimum_oos_samples,
        }
        return {
            "report_type": "EURUSD_CONTINUOUS_LEARNING_RESEARCH",
            "engine_version": self.VERSION, "status": status,
            "research_cycle_id": _canonical_hash(identity),
            "replay_id": replay_id, "source_history_sha256": source_hash,
            "inputs": {
                "replay_status": replay.get("status"),
                "walk_forward_status": walk_forward.get("status"),
                "attribution_status": attribution.get("status"),
                "same_replay_and_source_required": True,
            },
            "horizon_gates": horizon_gate,
            "blocker_codes": sorted(set(blockers)),
            "research_loop": [
                "REGISTER_VERSIONED_HYPOTHESIS",
                "PIN_CODE_PARAMETER_AND_SOURCE_HASHES",
                "RUN_STRICT_POINT_IN_TIME_REPLAY",
                "EVALUATE_WALK_FORWARD_OUT_OF_SAMPLE",
                "ASSESS_CONTEMPORANEOUS_CROSS_DOMAIN_CONTEXT",
                "COMPARE_AGAINST_IDENTICAL_BASELINE_AND_DATA",
                "RECORD_REPRODUCIBLE_FINDINGS",
                "HUMAN_REVIEW_REQUIRED_FOR_ANY_FUTURE_PROMOTION",
            ],
            "learning_policy": {
                "automatic_training": False,
                "automatic_parameter_tuning": False,
                "automatic_model_promotion": False,
                "live_model_mutation": False,
                "candidate_state": "RESEARCH_ONLY",
                "promotion_authority": "NONE",
                "probabilities_or_confidence_synthesized": False,
                "replay_integrity_required": True,
                "same_source_history_required_for_comparison": True,
                "horizons_pooled": False,
            },
            "limitations": [
                "This phase governs repeatable research; it does not train a model or claim continuous improvement.",
                "A completed replay, walk-forward evidence and contemporaneous attribution are prerequisites for a research-ready horizon.",
                "Model comparisons must pin identical replay/source history, horizon, evaluation window and immutable candidate code/parameter hashes.",
                "Research evidence is not live-trading evidence and cannot authorize orders or alter risk.",
                "Human review and a separate explicitly authorized deployment process are required before any future promotion.",
            ],
            "decision_authority": "RESEARCH_GOVERNANCE_ONLY",
            "trade_authority": "NONE", "order_execution": "DISABLED",
        }

    @staticmethod
    def build_experiment_manifest(
        *, experiment_name: str, hypothesis: str, engine_id: str, engine_version: str,
        code_sha256: str, parameter_sha256: str, replay_id: str,
        source_history_sha256: str, created_at_utc: str,
    ) -> dict[str, Any]:
        if not all(isinstance(x, str) and x.strip() for x in (
            experiment_name, hypothesis, engine_id, engine_version, replay_id, source_history_sha256
        )):
            raise ValueError("EXPERIMENT_IDENTITY_FIELDS_REQUIRED")
        for name, value in (("code_sha256", code_sha256), ("parameter_sha256", parameter_sha256),
                            ("source_history_sha256", source_history_sha256)):
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        try:
            timestamp = datetime.fromisoformat(created_at_utc.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise ValueError("created_at_utc must be an offset-aware ISO timestamp")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("created_at_utc must be timezone-aware")
        manifest = {
            "experiment_name": experiment_name.strip(), "hypothesis": hypothesis.strip(),
            "engine_id": engine_id.strip(), "engine_version": engine_version.strip(),
            "code_sha256": code_sha256.lower(), "parameter_sha256": parameter_sha256.lower(),
            "replay_id": replay_id, "source_history_sha256": source_history_sha256.lower(),
            "created_at_utc": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "candidate_state": "RESEARCH_ONLY",
        }
        manifest["experiment_id"] = _canonical_hash(manifest)
        return manifest
