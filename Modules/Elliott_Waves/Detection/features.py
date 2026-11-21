"""Numerical descriptors for a six-pivot, five-leg candidate."""
from __future__ import annotations
from .detector import Pivot

FEATURE_NAMES = ("direction", "wave1_pips", "wave2_retrace", "wave3_pips", "wave4_retrace", "wave5_pips", "wave3_vs_wave1", "wave3_vs_wave5", "total_bars", "wave1_bars", "wave2_bars", "wave3_bars", "wave4_bars", "wave5_bars")

def candidate_features(pivots: tuple[Pivot, ...] | list[Pivot], pip_size: float = 0.0001) -> dict[str, float]:
    if len(pivots) != 6 or pip_size <= 0:
        raise ValueError("Expected exactly six pivots and a positive pip_size")
    legs = [pivots[i+1].price - pivots[i].price for i in range(5)]
    bars = [float(pivots[i+1].index - pivots[i].index) for i in range(5)]
    direction = 1.0 if legs[0] > 0 else -1.0
    a = [abs(x) / pip_size for x in legs]
    return {
        "direction": direction, "wave1_pips": a[0], "wave2_retrace": a[1] / a[0] if a[0] else 0.0,
        "wave3_pips": a[2], "wave4_retrace": a[3] / a[2] if a[2] else 0.0,
        "wave5_pips": a[4], "wave3_vs_wave1": a[2] / a[0] if a[0] else 0.0,
        "wave3_vs_wave5": a[2] / a[4] if a[4] else 0.0,
        "total_bars": sum(bars), **{f"wave{i+1}_bars": bars[i] for i in range(5)}
    }
