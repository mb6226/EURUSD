"""Stage 8: nested walk-forward tuning of Elliott pivot and morphology parameters.

The objective is structural consistency/coverage, NOT expert-count accuracy or profitability.
All candidate selection occurs on an inner chronological validation segment; the outer
segment is scored only after selection. The baseline is retained for comparison.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from eurusd_ai.data_catalog import PROJECT_ROOT, EURUSD_TIMEFRAMES
from eurusd_ai.market_data import load_ohlcv_csv
from Modules.Elliott_Waves.Detection.detector import detect_pivots
from Modules.Elliott_Waves.Detection.engine import ElliottEngine

OUT = PROJECT_ROOT / "Modules/Elliott_Waves/Evaluation/stage8"
BASELINE = {"M5": 8.0, "M15": 15.0, "H1": 25.0, "H4": 40.0, "D1": 60.0}
FACTORS = (0.70, 0.85, 1.00, 1.20, 1.45)
MIN_SCORES = (15.0, 25.0, 35.0)
W2_MAX = (0.80, 0.90, 0.98)
ABC_B_MAX = (0.85, 1.00, 1.15)
TIMEFRAMES = ("M5", "M15", "H1", "H4", "D1")
OUTER_STARTS = (0.60, 0.70, 0.80)
PIP = 0.0001

def quality(candles, threshold, min_score, w2_max, abc_b_max, reference=None):
    pivots = detect_pivots(candles, threshold, include_provisional=False)
    engine = ElliottEngine(min_score=min_score, impulse_w2_soft_max=w2_max,
                           abc_b_max_ratio=abc_b_max)
    candidates = engine.analyze_pivots(pivots)
    impulses = [c for c in candidates if c.pattern == "impulse"]
    abcs = [c for c in candidates if c.pattern in ("zigzag", "flat_candidate", "abc")]
    valid = [c for c in candidates if c.hard_valid]
    n = len(candles)
    pivot_density = len(pivots) / max(1, n) * 1000.0
    candidate_density = len(candidates) / max(1, len(pivots)) * 100.0
    valid_rate = len(valid) / max(1, len(candidates))
    mean_score = float(np.mean([c.score for c in candidates]) / 100.0) if candidates else 0.0
    median_w2 = float(np.median([
        abs(c.pivots[2].price-c.pivots[1].price) /
        max(abs(c.pivots[1].price-c.pivots[0].price), 1e-12)
        for c in impulses
    ])) if impulses else None
    # Match validation structure to a baseline measured strictly on inner training data.
    # This avoids arbitrary fixed pivot-density targets across different timeframes.
    if reference:
        density_score = float(np.exp(-abs(np.log(max(pivot_density, 1e-9) /
                                                   max(reference["pivot_density_per_1000_bars"], 1e-9)))))
        candidate_score = float(np.exp(-abs(np.log(max(candidate_density, 1e-9) /
                                                     max(reference["candidate_density_per_100_pivots"], 1e-9)))))
        if median_w2 is not None and reference.get("median_w2_w1") is not None:
            retracement_score = float(np.exp(-abs(median_w2-reference["median_w2_w1"]) / 0.25))
        else:
            retracement_score = 0.5
    else:
        density_score = candidate_score = retracement_score = 1.0
    objective = (0.30 * density_score + 0.20 * candidate_score +
                 0.20 * valid_rate + 0.20 * mean_score + 0.10 * retracement_score)
    return {
        "objective": float(objective), "candles": n, "pivots": len(pivots),
        "pivot_density_per_1000_bars": pivot_density, "candidates": len(candidates),
        "candidate_density_per_100_pivots": candidate_density,
        "hard_valid_rate": valid_rate, "mean_candidate_score": mean_score,
        "impulse_candidates": len(impulses), "abc_candidates": len(abcs),
        "median_w2_w1": median_w2,
        "density_match_score": density_score,
        "candidate_density_match_score": candidate_score,
        "retracement_match_score": retracement_score,
    }

def candidate_grid(base):
    for factor in FACTORS:
        for min_score in MIN_SCORES:
            for w2_max in W2_MAX:
                for abc_b_max in ABC_B_MAX:
                    yield {
                        "pivot_threshold_pips": round(base * factor, 3),
                        "min_score": min_score,
                        "impulse_w2_soft_max": w2_max,
                        "abc_b_max_ratio": abc_b_max,
                    }

def evaluate(candles, params, reference=None):
    return quality(candles, params["pivot_threshold_pips"], params["min_score"],
                   params["impulse_w2_soft_max"], params["abc_b_max_ratio"], reference)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "experiment": "stage8_nested_walk_forward_parameter_optimization_v1",
         "objective_note": "Training-referenced structural stability proxy only; not expert Elliott truth, predictive edge, or trading profitability.",
        "objective_formula": "0.30 density match + 0.20 candidate-density match + 0.20 hard-valid rate + 0.20 mean heuristic score + 0.10 W2 retracement-distribution match; reference measured only on inner training.",

        "split_policy": "3 expanding outer folds; inner chronological validation chooses parameters; outer next segment evaluates selected parameters.",
        "candidate_count_per_inner_fold": len(tuple(candidate_grid(1.0))),
        "timeframes": {},
    }
    for tf in TIMEFRAMES:
        print(f"Loading {tf}...", flush=True)
        candles = load_ohlcv_csv(EURUSD_TIMEFRAMES[tf])
        base = BASELINE[tf]
        folds = []
        for fold_no, outer_start in enumerate(OUTER_STARTS, 1):
            outer_end = min(1.0, outer_start + 0.10)
            train_end = int(len(candles) * (outer_start - 0.15))
            val_start = train_end
            val_end = int(len(candles) * outer_start)
            test_end = int(len(candles) * outer_end)
            inner_train = candles[:train_end]
            validation = candles[val_start:val_end]
            outer_test = candles[int(len(candles)*outer_start):test_end]
            if min(len(inner_train), len(validation), len(outer_test)) < 100:
                continue
            # Inner training is used for diagnostics and to enforce a chronological warm-up.
            train_baseline = evaluate(inner_train, {
                "pivot_threshold_pips": base, "min_score": 25.0,
                "impulse_w2_soft_max": 0.90, "abc_b_max_ratio": 1.0})
            baseline_params = {"pivot_threshold_pips": base, "min_score": 25.0,
                               "impulse_w2_soft_max": 0.90, "abc_b_max_ratio": 1.0}
            train_reference = evaluate(inner_train, baseline_params)
            best = None
            for params in candidate_grid(base):
                stats = evaluate(validation, params, train_reference)
                row = {"params": params, "validation": stats}
                if best is None or stats["objective"] > best["validation"]["objective"]:
                    best = row
            baseline_val = evaluate(validation, baseline_params, train_reference)
            selected_test = evaluate(outer_test, best["params"], train_reference)
            baseline_test = evaluate(outer_test, baseline_params, train_reference)
            folds.append({
                "fold": fold_no, "train_bars": len(inner_train),
                "validation_bars": len(validation), "outer_test_bars": len(outer_test),
                "selected_params": best["params"],
                "inner_train_baseline_diagnostics": train_baseline,
                "validation_selected": best["validation"],
                "validation_baseline": baseline_val,
                "outer_test_selected": selected_test,
                "outer_test_baseline": baseline_test,
                "outer_test_objective_delta": selected_test["objective"] - baseline_test["objective"],
            })
            print(f"{tf} fold {fold_no}: selected={best['params']} "
                  f"val={best['validation']['objective']:.3f} "
                  f"test_delta={selected_test['objective']-baseline_test['objective']:+.3f}", flush=True)
        report["timeframes"][tf] = {
            "candles": len(candles), "baseline_threshold_pips": base,
            "folds": folds,
            "mean_outer_test_delta": float(np.mean([x["outer_test_objective_delta"] for x in folds])) if folds else None,
            "selection_warning": "Parameters vary by fold; do not promote a single setting without a fresh prospective holdout.",
        }
    (OUT / "stage8_parameter_optimization.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Stage 8 — Elliott Parameter Optimization", "",
        "**Purpose:** nested chronological tuning of pivot and morphology parameters.",
        "**Important:** the objective is a structural-consistency proxy, not expert Elliott accuracy, forecasting edge, or profitability.",
        "",
        "| TF | Fold | Selected pivot (pips) | Min score | W2 soft max | ABC B max | Test Δ objective |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for tf, item in report["timeframes"].items():
        for f in item["folds"]:
            p = f["selected_params"]
            lines.append(f"| {tf} | {f['fold']} | {p['pivot_threshold_pips']} | {p['min_score']} | {p['impulse_w2_soft_max']} | {p['abc_b_max_ratio']} | {f['outer_test_objective_delta']:+.4f} |")
    lines += ["", "## Interpretation", "",
              "- Positive outer-test deltas mean the selected settings improved this structural proxy on that fold only.",
              "- Negative or inconsistent deltas mean the tuning is not robust.",
              "- The proxy uses the implemented Elliott rules themselves, so it cannot independently validate Elliott wave labels.",
              "- Training-referenced stability replaces a fixed arbitrary pivot-density target; this is still a proxy, not ground truth.",
              "- No live trading settings or Stage 1 defaults are changed by this experiment.",
              "- A prospective holdout and expert-labelled chart set are required before any parameter promotion."]
    (OUT / "stage8_parameter_optimization.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"SAVED {OUT}", flush=True)

if __name__ == "__main__":
    main()
