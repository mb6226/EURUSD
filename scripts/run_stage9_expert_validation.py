"""Stage 9: audit expert Elliott reviews and calibrate heuristic scores only when justified.

This module never treats OCR, external chart mappings, or ordinary human reviews as
expert ground truth. Two distinct self-identified expert reviewers must agree on a
candidate before it enters the consensus set. Reviewer credentials are not verified
by software and must be checked by the project owner.
"""
from __future__ import annotations
import json, math
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "Modules/Elliott_Waves/Dataset"
LABELS = DATASET / "reviewed_labels.jsonl"
OUT = ROOT / "Modules/Elliott_Waves/Evaluation/stage9"
MIN_CONSENSUS = 100
MIN_PER_CLASS = 30
MIN_REVIEWERS = 2
VALID_TF = {"M5", "M15", "H1", "H4", "D1"}
VALID_VERDICTS = {"accepted", "rejected", "needs_correction"}

def parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None

def validate_record(row: dict[str, Any]) -> list[str]:
    errors = []
    required = ("candidate_id", "timeframe", "verdict", "label", "candidate",
                "reviewed_at", "reviewer_id", "reviewer_role",
                "independent_review", "reviewer_qualification")
    for key in required:
        if key not in row:
            errors.append("missing_" + key)
    if row.get("timeframe") not in VALID_TF:
        errors.append("invalid_timeframe")
    if row.get("verdict") not in VALID_VERDICTS:
        errors.append("invalid_verdict")
    if row.get("reviewer_role") != "expert":
        errors.append("not_expert_role")
    if not str(row.get("reviewer_id", "")).strip():
        errors.append("missing_reviewer_id")
    if row.get("independent_review") is not True:
        errors.append("not_independent_review")
    if len(str(row.get("reviewer_qualification", "")).strip()) < 12:
        errors.append("qualification_statement_too_short")
    if parse_time(row.get("reviewed_at")) is None:
        errors.append("invalid_reviewed_at")
    candidate = row.get("candidate")
    if not isinstance(candidate, dict) or not isinstance(candidate.get("pivots"), list):
        errors.append("missing_candidate_pivots")
    elif len(candidate["pivots"]) < 3:
        errors.append("too_few_candidate_pivots")
    if not isinstance(candidate, dict) or not isinstance(candidate.get("score"), (int, float)):
        errors.append("missing_numeric_candidate_score")
    if row.get("verdict") == "needs_correction" and len(str(row.get("notes", "")).strip()) < 10:
        errors.append("correction_requires_detailed_notes")
    return errors

def read_rows(path: Path) -> tuple[list[dict], int]:
    rows, malformed = [], 0
    if not path.exists():
        return rows, malformed
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                malformed += 1
        except json.JSONDecodeError:
            malformed += 1
    return rows, malformed

def kappa(a: list[int], b: list[int]) -> float | None:
    if not a or len(a) != len(b):
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa = Counter(a); pb = Counter(b)
    expected = sum(pa[k] * pb[k] for k in (0, 1)) / (n * n)
    return (observed - expected) / (1 - expected) if expected < 1 else (1.0 if observed == 1 else 0.0)

def reliability_bins(scores: list[float], labels: list[int], bins: int = 10) -> list[dict]:
    result = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        ix = [j for j, s in enumerate(scores) if lo <= s < hi or (i == bins-1 and s == 1)]
        if ix:
            result.append({"bin_low": lo, "bin_high": hi, "count": len(ix),
                           "mean_score": sum(scores[j] for j in ix) / len(ix),
                           "observed_acceptance_rate": sum(labels[j] for j in ix) / len(ix)})
    return result

def calibration_metrics(scores: list[float], labels: list[int]) -> dict:
    try:
        from sklearn.isotonic import IsotonicRegression
        from sklearn.metrics import roc_auc_score, brier_score_loss
        import numpy as np
    except Exception as exc:
        return {"status": "dependency_unavailable", "reason": str(exc)}
    n = len(labels)
    cut = int(n * 0.70)
    train_y, test_y = labels[:cut], labels[cut:]
    train_s, test_s = scores[:cut], scores[cut:]
    if (len(test_y) < 30 or len(set(train_y)) < 2 or len(set(test_y)) < 2
            or min(sum(train_y), len(train_y)-sum(train_y)) < 20):
        return {"status": "insufficient_chronological_calibration_split",
                "train_n": len(train_y), "test_n": len(test_y)}
    model = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
    model.fit(train_s, train_y)
    calibrated = [float(x) for x in model.predict(test_s)]
    base = sum(train_y) / len(train_y)
    return {
        "status": "evaluated_on_chronological_holdout",
        "train_n": len(train_y), "test_n": len(test_y),
        "train_positive_rate": base,
        "raw_score_brier": float(brier_score_loss(test_y, test_s)),
        "calibrated_brier": float(brier_score_loss(test_y, calibrated)),
        "base_rate_brier": float(brier_score_loss(test_y, [base] * len(test_y))),
        "raw_score_roc_auc": float(roc_auc_score(test_y, test_s)),
        "calibrated_reliability_bins": reliability_bins(calibrated, test_y),
        "calibrator": "isotonic regression fitted on first 70% of chronological consensus labels",
        "warning": "Only valid if labels are genuinely expert-reviewed and chronologically independent; never infer credentials from the self-declared role field."
    }

def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    rows, malformed = read_rows(LABELS)
    valid, invalid = [], []
    duplicate_keys = set()
    seen = set()
    for row in rows:
        errs = validate_record(row)
        key = (row.get("candidate_id"), row.get("reviewer_id"))
        if key in seen:
            errs.append("duplicate_candidate_reviewer_pair")
            duplicate_keys.add(key)
        seen.add(key)
        if errs:
            invalid.append({"candidate_id": row.get("candidate_id"),
                            "reviewer_id": row.get("reviewer_id"),
                            "errors": sorted(set(errs))})
        else:
            valid.append(row)
    by_candidate = defaultdict(list)
    for row in valid:
        by_candidate[row["candidate_id"]].append(row)
    consensus, disagreements = [], []
    pair_ratings = []
    for cid, group in by_candidate.items():
        unique_reviewers = {r["reviewer_id"] for r in group}
        binary = [r for r in group if r["verdict"] in ("accepted", "rejected")]
        if len(unique_reviewers) < MIN_REVIEWERS or len(binary) < MIN_REVIEWERS:
            continue
        # Latest rating per reviewer, preventing repeat votes from one reviewer.
        latest = {}
        for r in sorted(binary, key=lambda x: parse_time(x["reviewed_at"])):
            latest[r["reviewer_id"]] = r
        votes = list(latest.values())
        if len(votes) < MIN_REVIEWERS:
            continue
        decisions = [1 if r["verdict"] == "accepted" else 0 for r in votes]
        if len(votes) >= 2:
            pair_ratings.append((decisions[0], decisions[1]))
        if len(set(decisions)) != 1:
            disagreements.append(cid)
            continue
        representative = votes[-1]
        score = float(representative["candidate"]["score"])
        if not math.isfinite(score):
            continue
        consensus.append({
            "candidate_id": cid, "timeframe": representative["timeframe"],
            "reviewed_at": max(r["reviewed_at"] for r in votes),
            "score": max(0.0, min(100.0, score)) / 100.0,
            "accepted": decisions[0], "reviewers": sorted(latest),
            "label": representative["label"],
        })
    consensus.sort(key=lambda x: x["reviewed_at"])
    ys = [r["accepted"] for r in consensus]
    scores = [r["score"] for r in consensus]
    positives = sum(ys)
    negatives = len(ys) - positives
    eligible = len(consensus) >= MIN_CONSENSUS and min(positives, negatives) >= MIN_PER_CLASS
    calibration = calibration_metrics(scores, ys) if eligible else {
        "status": "blocked_insufficient_expert_consensus",
        "required_consensus": MIN_CONSENSUS,
        "required_per_class": MIN_PER_CLASS,
        "consensus_n": len(consensus), "accepted": positives, "rejected": negatives,
    }
    result = {
        "stage": 9, "name": "Expert-Label Calibration & Elliott Validation",
        "label_file": str(LABELS.relative_to(ROOT)),
        "raw_records": len(rows), "malformed_records": malformed,
        "valid_expert_reviews": len(valid), "invalid_or_nonexpert_reviews": len(invalid),
        "duplicate_candidate_reviewer_pairs": len(duplicate_keys),
        "candidates_with_two_or_more_expert_reviews": sum(
            len({r["reviewer_id"] for r in g}) >= 2 for g in by_candidate.values()),
        "consensus_candidates": len(consensus), "reviewer_disagreements": len(disagreements),
        "accepted_consensus": positives, "rejected_consensus": negatives,
        "inter_rater_kappa_first_two": kappa(
            [a for a, _ in pair_ratings], [b for _, b in pair_ratings]),
        "calibration": calibration,
        "promotion_status": "BLOCKED" if calibration["status"] != "evaluated_on_chronological_holdout" else "REQUIRES_MANUAL_GOVERNANCE_REVIEW",
        "safety_note": "External OCR/chart mappings and unreviewed references are excluded. Self-declared expert status is not credential verification. No Stage 1 or production model is changed.",
        "invalid_examples": invalid[:100],
        "disagreement_candidate_ids": disagreements[:100],
        "consensus_preview": consensus[:20],
    }
    (OUT / "stage9_validation.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    report = [
        "# Stage 9 — Expert-Label Calibration & Elliott Validation", "",
        f"- Raw review records: {len(rows)} (malformed: {malformed})",
        f"- Valid expert reviews: {len(valid)}",
        f"- Invalid/non-expert reviews: {len(invalid)}",
        f"- Candidates with at least two expert reviewers: {result['candidates_with_two_or_more_expert_reviews']}",
        f"- Consensus candidates: {len(consensus)} (accepted {positives}, rejected {negatives})",
        f"- Reviewer disagreements: {len(disagreements)}",
        f"- Inter-rater Cohen's kappa: {result['inter_rater_kappa_first_two']}",
        "", f"## Calibration status: {calibration['status']}", "",
        f"**Promotion status: {result['promotion_status']}**", "",
        "Calibration is blocked until there are at least 100 two-reviewer consensus candidates, including at least 30 accepted and 30 rejected. Isotonic calibration, when permitted, is fitted on the first 70% of chronological consensus records and scored on the final 30%.",
        "", "## Data integrity rules", "",
        "- OCR output and chart-to-candle approximations are never ground truth.",
        "- Reviews must identify an expert reviewer, reviewer ID, qualification statement, and independent judgment.",
        "- Two distinct reviewers must agree before a candidate enters consensus.",
        "- Credentials must be checked by a human project owner; the pipeline cannot verify them.",
        "- No model or Stage 1 defaults are modified by this stage.",
    ]
    if calibration.get("status") == "evaluated_on_chronological_holdout":
        report += ["", "## Chronological holdout metrics", "",
                   f"- Raw score Brier: {calibration['raw_score_brier']:.4f}",
                   f"- Calibrated Brier: {calibration['calibrated_brier']:.4f}",
                   f"- Training base-rate Brier: {calibration['base_rate_brier']:.4f}",
                   f"- Raw score ROC AUC: {calibration['raw_score_roc_auc']:.4f}"]
    (OUT / "stage9_validation_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "raw_records", "valid_expert_reviews", "invalid_or_nonexpert_reviews",
        "consensus_candidates", "reviewer_disagreements", "calibration",
        "promotion_status")}, indent=2))
    return result

if __name__ == "__main__":
    run()
