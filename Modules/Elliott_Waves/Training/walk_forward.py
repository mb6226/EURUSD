"""Leakage-safe daily EURUSD multi-timeframe Elliott walk-forward backtest.

At each New York 17:00 close, features use only fully closed M5/M15/H1/H4/D1 bars.
The next NY session's close/high/low are labels. Each daily model is fit only on
earlier forecasts whose outcomes were already observable at that cutoff.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import csv
import json
import math
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from eurusd_ai.data_catalog import PROJECT_ROOT, EURUSD_TIMEFRAMES
from eurusd_ai.market_data import Candle, load_ohlcv_csv
from Modules.Elliott_Waves.Detection.detector import detect_pivots
from Modules.Elliott_Waves.Detection.engine import ElliottEngine

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
PIP = 0.0001
TIMEFRAMES = ("M5", "M15", "H1", "H4", "D1")
DURATION_MIN = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}
PIVOT_PIPS = {"M5": 8.0, "M15": 15.0, "H1": 25.0, "H4": 40.0, "D1": 60.0}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def session_cutoffs(candles: list[Candle]) -> list[datetime]:
    first = parse_time(candles[0].time).astimezone(NY).date()
    last = parse_time(candles[-1].time).astimezone(NY).date()
    day = first
    result = []
    m5_times = [parse_time(c.time) for c in candles]
    while day <= last:
        if day.weekday() < 5:
            cutoff = datetime.combine(day, time(17, 0), NY).astimezone(UTC)
            # Skip weekdays with no completed FX session (e.g. market holidays).
            right = bisect_right(m5_times, cutoff - timedelta(minutes=5))
            left = bisect_right(m5_times, cutoff - timedelta(hours=24))
            if right > left:
                result.append(cutoff)
        day += timedelta(days=1)
    return result


def _safe_div(a: float, b: float) -> float:
    return float(a / b) if abs(b) > 1e-12 else 0.0


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    diff = np.diff(closes[-(period + 1):])
    gains = np.maximum(diff, 0).mean()
    losses = np.maximum(-diff, 0).mean()
    if losses <= 1e-12:
        return 100.0 if gains > 0 else 50.0
    return float(100 - 100 / (1 + gains / losses))


def _timeframe_features(tf: str, bars: list[Candle]) -> dict[str, float]:
    prefix = tf.lower()
    out: dict[str, float] = {}
    if not bars:
        return {f"{prefix}_{k}": 0.0 for k in (
            "bars", "ret1", "ret3", "ret6", "ret12", "ret24", "ret48",
            "range12", "range48", "atr14", "vol20", "rsi14", "body1",
            "wick_balance1", "up_fraction20", "trend_slope20", "pivot_count",
            "last_swing_pips", "last_swing_dir", "impulse_score", "abc_score",
            "hard_valid_count"
        )}
    o = np.array([x.open for x in bars], dtype=float)
    h = np.array([x.high for x in bars], dtype=float)
    l = np.array([x.low for x in bars], dtype=float)
    c = np.array([x.close for x in bars], dtype=float)
    n = len(c)
    for k in (1, 3, 6, 12, 24, 48):
        out[f"{prefix}_ret{k}"] = (c[-1] - c[-1-k]) / PIP if n > k else 0.0
    for k in (12, 48):
        sl = slice(max(0, n-k), n)
        out[f"{prefix}_range{k}"] = (h[sl].max() - l[sl].min()) / PIP
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1]))) if n > 1 else np.array([])
    out[f"{prefix}_atr14"] = float(np.mean(tr[-14:]) / PIP) if len(tr) else 0.0
    rets = np.diff(c[-21:]) / PIP if n > 1 else np.array([])
    out[f"{prefix}_vol20"] = float(np.std(rets)) if len(rets) else 0.0
    out[f"{prefix}_rsi14"] = _rsi(c)
    candle_range = max(h[-1] - l[-1], 1e-9)
    out[f"{prefix}_body1"] = (c[-1] - o[-1]) / PIP
    out[f"{prefix}_wick_balance1"] = ((h[-1] - max(o[-1], c[-1])) - (min(o[-1], c[-1]) - l[-1])) / PIP
    out[f"{prefix}_up_fraction20"] = float(np.mean(c[-20:] >= o[-20:]))
    if n >= 20:
        y = c[-20:]
        x = np.arange(20, dtype=float)
        out[f"{prefix}_trend_slope20"] = float(np.polyfit(x, y, 1)[0] / PIP)
    else:
        out[f"{prefix}_trend_slope20"] = 0.0
    # Elliott structure features are derived from confirmed swings only.
    tail = bars[-min(n, 1600 if tf == "M5" else 900):]
    pivots = detect_pivots(tail, PIVOT_PIPS[tf], include_provisional=False)
    out[f"{prefix}_pivot_count"] = float(len(pivots))
    out[f"{prefix}_last_swing_pips"] = abs(pivots[-1].price - pivots[-2].price) / PIP if len(pivots) >= 2 else 0.0
    out[f"{prefix}_last_swing_dir"] = 1.0 if len(pivots) >= 2 and pivots[-1].price > pivots[-2].price else (-1.0 if len(pivots) >= 2 else 0.0)
    candidates = ElliottEngine(min_score=25).analyze_pivots(pivots)
    impulses = [x for x in candidates if x.pattern == "impulse"]
    abcs = [x for x in candidates if x.pattern in ("zigzag", "flat_candidate")]
    out[f"{prefix}_impulse_score"] = max((x.score for x in impulses), default=0.0)
    out[f"{prefix}_abc_score"] = max((x.score for x in abcs), default=0.0)
    out[f"{prefix}_hard_valid_count"] = float(sum(x.hard_valid for x in candidates))
    out[f"{prefix}_bars"] = float(n)
    return out


def build_feature_rows(data: dict[str, list[Candle]]) -> tuple[list[dict], list[datetime]]:
    cutoffs = session_cutoffs(data["M5"])
    parsed = {tf: [(parse_time(c.time), c) for c in data[tf]] for tf in TIMEFRAMES}
    parsed_times = {tf: [item[0] for item in parsed[tf]] for tf in TIMEFRAMES}
    rows = []
    for cutoff_index, cutoff in enumerate(cutoffs):
        if cutoff_index % 40 == 0:
            print(f"Feature engineering: {cutoff_index + 1}/{len(cutoffs)} NY sessions", flush=True)
        row: dict[str, float] = {}
        for tf in TIMEFRAMES:
            # Binary search: only bars whose full duration elapsed by cutoff are visible.
            duration = timedelta(minutes=DURATION_MIN[tf])
            end_idx = bisect_right(parsed_times[tf], cutoff - duration)
            usable = [c for _, c in parsed[tf][max(0, end_idx - 1600):end_idx]]
            row.update(_timeframe_features(tf, usable))
        # Cross-timeframe agreement and dispersion.
        dirs = [np.sign(row[f"{tf.lower()}_ret12"]) for tf in TIMEFRAMES]
        row["mtf_direction_agreement"] = float(abs(sum(dirs)) / len(dirs))
        row["mtf_net_direction"] = float(np.sign(sum(dirs)))
        row["mtf_volatility_spread"] = float(max(row[f"{tf.lower()}_atr14"] for tf in TIMEFRAMES) -
                                                   min(row[f"{tf.lower()}_atr14"] for tf in TIMEFRAMES))
        rows.append(row)
    return rows, cutoffs


def build_labels(data: dict[str, list[Candle]], cutoffs: list[datetime]) -> list[dict | None]:
    m5 = [(parse_time(c.time), c) for c in data["M5"]]
    m5_times = [item[0] for item in m5]
    labels: list[dict | None] = []
    for i, start in enumerate(cutoffs):
        if i + 1 >= len(cutoffs):
            labels.append(None)
            continue
        end = cutoffs[i + 1]
        left = bisect_right(m5_times, start - timedelta(microseconds=1))
        right = bisect_right(m5_times, end - timedelta(minutes=5))
        before_idx = bisect_right(m5_times, start - timedelta(minutes=5))
        session = [c for _, c in m5[left:right]]
        if right <= left or before_idx == 0:
            labels.append(None)
            continue
        entry = m5[before_idx - 1][1].close
        close_ret = (session[-1].close - entry) / PIP
        high_exc = (max(c.high for c in session) - entry) / PIP
        low_exc = (min(c.low for c in session) - entry) / PIP
        labels.append({
            "close_return_pips": float(close_ret),
            "high_excursion_pips": float(high_exc),
            "low_excursion_pips": float(low_exc),
            "direction": "UP" if close_ret >= 5 else ("DOWN" if close_ret <= -5 else "FLAT"),
            "next_cutoff": end.isoformat(),
        })
    return labels




def add_stage4_reasoning_features(features: list[dict], cutoffs: list[datetime],
                                  snapshots_path: Path, max_age_hours: float = 48.0) -> None:
    """Causally join the latest Stage-4 snapshot available at each NY cutoff."""
    snapshots = []
    if snapshots_path.is_file():
        with snapshots_path.open(encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                stamp = parse_time(item["as_of"])
                snapshots.append((stamp, item))
    snapshots.sort(key=lambda item: item[0])
    stamps = [item[0] for item in snapshots]
    for row, cutoff in zip(features, cutoffs):
        idx = bisect_right(stamps, cutoff) - 1
        snap = snapshots[idx][1] if idx >= 0 else None
        age = (cutoff - stamps[idx]).total_seconds() / 3600 if idx >= 0 else float("inf")
        usable = snap is not None and 0 <= age <= max_age_hours
        row["stage4_snapshot_available"] = float(usable)
        row["stage4_snapshot_age_hours"] = min(age, max_age_hours * 2) if usable else max_age_hours * 2
        row["stage4_timeframes_represented"] = float(snap.get("timeframes_represented", 0)) if usable else 0.0
        row["stage4_candidate_count"] = float(snap.get("candidate_count", 0)) if usable else 0.0
        row["stage4_abstain"] = float(bool(snap.get("abstain", True))) if usable else 1.0
        row["stage4_conflict_count"] = float(len(snap.get("conflicts", []))) if usable else 0.0
        scenarios = snap.get("scenarios", []) if usable else []
        by_direction = {x.get("direction"): x for x in scenarios}
        for direction in ("up", "down"):
            scenario = by_direction.get(direction, {})
            row[f"stage4_{direction}_coverage"] = float(scenario.get("timeframes_represented", 0))
            row[f"stage4_{direction}_score"] = float(scenario.get("mean_reasoning_score_not_probability", 0))
            row[f"stage4_{direction}_aligned_links"] = float(scenario.get("aligned_parent_child_links", 0))
        row["stage4_scenario_score_gap"] = row["stage4_up_score"] - row["stage4_down_score"]
        leaders = snap.get("timeframe_leaders", {}) if usable else {}
        for tf in ("D1", "H4", "H1", "M15", "M5"):
            leader = leaders.get(tf) or {}
            row[f"stage4_{tf.lower()}_direction"] = (
                1.0 if leader.get("direction") == "up" else
                -1.0 if leader.get("direction") == "down" else 0.0
            )

def run_backtest(output_dir: Path, min_train_days: int = 180, retrain_every: int = 5) -> dict:
    try:
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.metrics import accuracy_score, mean_absolute_error
        import joblib
    except ImportError as exc:
        raise RuntimeError("Install ML dependencies: py -3 -m pip install -e .[ml]") from exc

    data = {tf: load_ohlcv_csv(EURUSD_TIMEFRAMES[tf]) for tf in TIMEFRAMES}
    features, cutoffs = build_feature_rows(data)
    stage4_path = PROJECT_ROOT / "Modules/Elliott_Waves/Evaluation/stage4/multitimeframe_scenarios.jsonl"
    add_stage4_reasoning_features(features, cutoffs, stage4_path)
    labels = build_labels(data, cutoffs)
    usable = [i for i, label in enumerate(labels) if label is not None]
    if len(usable) < min_train_days + 10:
        raise RuntimeError(f"Not enough labelled sessions: {len(usable)}; need at least {min_train_days + 10}")

    feature_names = sorted(features[0])
    predictions = []
    y_true, y_pred = [], []
    reg_true, reg_pred = [], []
    latest_model = None
    latest_regressor = None
    latest_classes = []

    for i, cutoff in enumerate(cutoffs):
        if i % 40 == 0:
            print(f"Walk-forward training: session {i + 1}/{len(cutoffs)}", flush=True)
        # Training labels must have been fully observed before this forecast cutoff.
        train_idx = [j for j in range(i) if labels[j] is not None]
        if len(train_idx) < min_train_days:
            continue
        X_now = np.asarray([[features[i][k] for k in feature_names]], dtype=float)
        refit = latest_model is None or (i % max(1, retrain_every) == 0)
        if refit:
            X_train = np.asarray([[features[j][k] for k in feature_names] for j in train_idx], dtype=float)
            y_train = np.asarray([labels[j]["direction"] for j in train_idx])
            Y_train = np.asarray([[labels[j]["close_return_pips"], labels[j]["high_excursion_pips"],
                                   labels[j]["low_excursion_pips"]] for j in train_idx], dtype=float)
            clf = RandomForestClassifier(
                n_estimators=48, max_depth=5, min_samples_leaf=4,
                class_weight="balanced_subsample", random_state=20261120, n_jobs=1
            )
            reg = RandomForestRegressor(
                n_estimators=48, max_depth=5, min_samples_leaf=4,
                random_state=20261120, n_jobs=1
            )
            clf.fit(X_train, y_train)
            reg.fit(X_train, Y_train)
            latest_model, latest_regressor = clf, reg
            latest_classes = list(clf.classes_)
            latest_training_sessions = len(train_idx)

        probs = latest_model.predict_proba(X_now)[0]
        prob_map = {str(k): float(v) for k, v in zip(latest_model.classes_, probs)}
        direction = str(latest_model.predict(X_now)[0])
        reg_values = latest_regressor.predict(X_now)[0]
        next_session_date = cutoff.astimezone(NY).date() + timedelta(days=1)
        while next_session_date.weekday() >= 5:
            next_session_date += timedelta(days=1)
        forecast = {
            "forecast_cutoff_ny": cutoff.isoformat(),
            "forecast_for_next_ny_session": cutoffs[i + 1].astimezone(NY).date().isoformat() if i + 1 < len(cutoffs) else next_session_date.isoformat(),
            "direction": "CONFLICT" if (
                (direction == "UP" and reg_values[0] < 0) or
                (direction == "DOWN" and reg_values[0] > 0) or
                (direction == "FLAT" and abs(reg_values[0]) >= 5)
            ) else direction,
            "classifier_direction": direction,
            "model_vote_share_not_calibrated_probability": prob_map,
            "predicted_close_return_pips": round(float(reg_values[0]), 2),
            "classifier_regressor_direction_disagreement": bool(
                (direction == "UP" and reg_values[0] < 0) or
                (direction == "DOWN" and reg_values[0] > 0) or
                (direction == "FLAT" and abs(reg_values[0]) >= 5)
            ),
            "predicted_high_excursion_pips": round(float(reg_values[1]), 2),
            "predicted_low_excursion_pips": round(float(reg_values[2]), 2),
            "training_sessions": latest_training_sessions,
            "model_refit_at_this_cutoff": refit,
            "retrain_every_sessions": retrain_every,
            "timeframes": list(TIMEFRAMES),
            "feature_count": len(feature_names),
            "training_cutoff": cutoff.isoformat(),
            "lookahead_bias_control": "Only prior sessions with fully observed next-session labels are used.",
            "stage4_context": {k: round(float(v), 4) for k, v in features[i].items() if k.startswith("stage4_")},
        }
        if labels[i] is not None:
            actual = labels[i]
            forecast["actual"] = actual
            forecast["direction_correct"] = direction == actual["direction"]
            forecast["close_return_error_pips"] = round(float(reg_values[0]) - actual["close_return_pips"], 2)
            forecast["high_excursion_error_pips"] = round(float(reg_values[1]) - actual["high_excursion_pips"], 2)
            forecast["low_excursion_error_pips"] = round(float(reg_values[2]) - actual["low_excursion_pips"], 2)
            y_true.append(actual["direction"])
            y_pred.append(direction)
            reg_true.append([actual["close_return_pips"], actual["high_excursion_pips"], actual["low_excursion_pips"]])
            reg_pred.append(reg_values.tolist())
        predictions.append(forecast)

    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / "daily_walk_forward_predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as f:
        for item in predictions:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    evaluated = [p for p in predictions if "actual" in p]
    from sklearn.metrics import balanced_accuracy_score, f1_score, precision_recall_fscore_support, confusion_matrix
    published = [p for p in evaluated if p.get("direction") != "CONFLICT"]
    class_labels = ["DOWN", "FLAT", "UP"]
    class_precision, class_recall, class_f1, class_support = precision_recall_fscore_support(
        y_true, y_pred, labels=class_labels, zero_division=0
    ) if y_true else ([], [], [], [])
    stage4_available = [x.get("stage4_snapshot_available", 0.0) for x in features]
    metrics = {
        "symbol": "EURUSD", "method": "five_year_expanding_window_walk_forward_with_stage4_context",
        "stage4_snapshot_source": str(stage4_path.relative_to(PROJECT_ROOT)),
        "retrain_every_sessions": retrain_every,
        "stage4_features": [k for k in feature_names if k.startswith("stage4_")],
        "cutoff": "17:00 America/New_York; timezone/DST aware",
        "timeframes": list(TIMEFRAMES), "source_rows": {tf: len(data[tf]) for tf in TIMEFRAMES},
        "sessions_available": len(cutoffs), "warmup_sessions": min_train_days,
        "forecast_count": len(predictions), "evaluated_forecasts": len(evaluated),
        "direction_accuracy": float(np.mean(np.asarray(y_true) == np.asarray(y_pred))) if y_true else None,
        "direction_baseline_accuracy": float(max((y_true.count(c) / len(y_true) for c in set(y_true)), default=0.0)) if y_true else None,
        "direction_balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)) if y_true else None,
        "direction_macro_f1": float(f1_score(y_true, y_pred, labels=class_labels, average="macro", zero_division=0)) if y_true else None,
        "direction_confusion_matrix_labels_down_flat_up": confusion_matrix(y_true, y_pred, labels=class_labels).tolist() if y_true else [],
        "per_class_metrics_down_flat_up": {
            label: {"precision": float(class_precision[i]), "recall": float(class_recall[i]),
                    "f1": float(class_f1[i]), "support": int(class_support[i])}
            for i, label in enumerate(class_labels)
        } if y_true else {},
        "published_forecast_coverage_excluding_conflict": len(published) / len(evaluated) if evaluated else None,
        "published_direction_accuracy_when_not_conflict": (
            float(np.mean([p["classifier_direction"] == p["actual"]["direction"] for p in published]))
            if published else None
        ),
        "published_conflict_count": sum(p.get("direction") == "CONFLICT" for p in evaluated),
        "stage4_snapshot_coverage": float(np.mean(stage4_available)) if stage4_available else 0.0,
        "regression_mae_pips": {
            "close_return": float(mean_absolute_error(np.asarray(reg_true)[:, 0], np.asarray(reg_pred)[:, 0])) if reg_true else None,
            "high_excursion": float(mean_absolute_error(np.asarray(reg_true)[:, 1], np.asarray(reg_pred)[:, 1])) if reg_true else None,
            "low_excursion": float(mean_absolute_error(np.asarray(reg_true)[:, 2], np.asarray(reg_pred)[:, 2])) if reg_true else None,
        },
        "last_forecast": predictions[-1] if predictions else None,
        "feature_names": feature_names,
        "limitations": [
            "Daily forecasts are dependent observations; uncertainty intervals and regime-stratified validation are still required.",
            "The current Elliott engine supports basic impulse/ABC heuristics, not complete Elliott theory.",
            "Classifier vote shares are not calibrated probabilities.",
            "Stage-4 inputs are weak-rule structural hypotheses and heuristic rankings, not expert-confirmed labels.",
            "This is a forecasting research model, not a trading recommendation."
        ],
    }
    (output_dir / "walk_forward_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "walk_forward_report.md").write_text(
        "# EURUSD Daily Elliott Walk-Forward Backtest\n\n"
        f"- Forecasts: {metrics['forecast_count']}\n- Evaluated forecasts: {metrics['evaluated_forecasts']}\n"
        f"- Direction accuracy: {metrics['direction_accuracy']}\n"
        f"- Baseline accuracy: {metrics['direction_baseline_accuracy']}\n"
        f"- Balanced accuracy: {metrics['direction_balanced_accuracy']}\n"
        f"- Macro F1: {metrics['direction_macro_f1']}\n"
        f"- Non-conflict forecast coverage: {metrics['published_forecast_coverage_excluding_conflict']}\n"
        f"- MAE close return (pips): {metrics['regression_mae_pips']['close_return']}\n"
        f"- MAE high excursion (pips): {metrics['regression_mae_pips']['high_excursion']}\n"
        f"- MAE low excursion (pips): {metrics['regression_mae_pips']['low_excursion']}\n\n"
        "Every forecast is generated using only earlier completed sessions. Vote shares are not calibrated probabilities.\n"
        "If classifier direction and regression sign disagree, the published direction is CONFLICT (abstain).\n",
        encoding="utf-8"
    )
    if latest_model is not None:
        model_dir = PROJECT_ROOT / "Modules" / "Elliott_Waves" / "Models"
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "classifier": latest_model, "regressor": latest_regressor,
            "feature_names": feature_names, "classes": latest_classes,
            "timeframes": list(TIMEFRAMES), "trained_through": predictions[-1]["training_cutoff"],
            "method": "expanding_window_walk_forward"
        }, model_dir / "daily_elliott_forecaster.joblib")
    print(json.dumps({k: v for k, v in metrics.items() if k not in ("feature_names",)}, ensure_ascii=False, indent=2))
    print(f"Predictions: {pred_path}")
    print(f"Report: {output_dir / 'walk_forward_report.md'}")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="EURUSD multi-timeframe daily Elliott walk-forward training/backtest")
    parser.add_argument("--min-train-days", type=int, default=180)
    parser.add_argument("--retrain-every", type=int, default=5)
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "Modules/Elliott_Waves/Evaluation/stage5"))
    args = parser.parse_args()
    run_backtest(Path(args.output_dir), args.min_train_days, args.retrain_every)


if __name__ == "__main__":
    main()

