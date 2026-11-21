from scripts.run_stage9_expert_validation import validate_record, kappa


def valid_expert_review():
    return {
        "candidate_id": "H1:impulse:100-140",
        "timeframe": "H1",
        "verdict": "accepted",
        "label": "impulse",
        "notes": "Wave structure independently reviewed.",
        "candidate": {"score": 72.5, "pivots": [{"price": 1.1}, {"price": 1.2}, {"price": 1.15}]},
        "reviewed_at": "2026-11-20T12:00:00+00:00",
        "reviewer_id": "reviewer_A",
        "reviewer_role": "expert",
        "reviewer_qualification": "Ten years of Elliott Wave chart analysis.",
        "independent_review": True,
    }


def test_stage9_accepts_complete_expert_review():
    assert validate_record(valid_expert_review()) == []


def test_stage9_rejects_nonexpert_as_ground_truth():
    row = valid_expert_review()
    row["reviewer_role"] = "non_expert"
    assert "not_expert_role" in validate_record(row)


def test_stage9_requires_independent_judgment_and_qualification():
    row = valid_expert_review()
    row["independent_review"] = False
    row["reviewer_qualification"] = "new"
    errors = validate_record(row)
    assert "not_independent_review" in errors
    assert "qualification_statement_too_short" in errors


def test_stage9_requires_two_distinct_raters_for_agreement():
    assert kappa([1, 0, 1, 0], [1, 0, 0, 0]) == 0.5


def test_stage9_kappa_handles_perfect_agreement():
    assert kappa([1, 0, 1], [1, 0, 1]) == 1.0
