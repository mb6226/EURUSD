"""Rule-guided Elliott Wave candidate generation and ranking.

Scores are heuristic research rankings, NOT calibrated probabilities or trade signals.
The engine returns competing counts rather than asserting one truth.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Sequence
from .detector import Pivot


@dataclass(frozen=True)
class WaveCandidate:
    pattern: str
    direction: str
    pivots: tuple[Pivot, ...]
    score: float
    hard_valid: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        row = asdict(self)
        row["pivots"] = [asdict(p) for p in self.pivots]
        row["score"] = round(self.score, 2)
        return row


class ElliottEngine:
    """Generate impulse and basic ABC correction hypotheses from swing pivots."""

    def __init__(self, pip_size: float = 0.0001, min_score: float = 25.0,
                 impulse_w2_soft_max: float = 0.90,
                 impulse_w4_soft_max: float = 0.75,
                 abc_b_max_ratio: float = 1.0,
                 abc_c_min_ratio: float = 0.50):
        if pip_size <= 0 or min_score < 0:
            raise ValueError("pip_size must be positive and min_score non-negative")
        if not (0 < impulse_w2_soft_max <= 1.5 and 0 < impulse_w4_soft_max <= 1.5
                and 0 < abc_b_max_ratio <= 2.0 and 0 <= abc_c_min_ratio <= 2.0):
            raise ValueError("morphology thresholds are outside supported bounds")
        self.pip_size = pip_size
        self.min_score = min_score
        self.impulse_w2_soft_max = impulse_w2_soft_max
        self.impulse_w4_soft_max = impulse_w4_soft_max
        self.abc_b_max_ratio = abc_b_max_ratio
        self.abc_c_min_ratio = abc_c_min_ratio

    @staticmethod
    def _alternating(seq: Sequence[Pivot]) -> bool:
        return all(seq[i].kind != seq[i + 1].kind for i in range(len(seq) - 1))

    def analyze_pivots(self, pivots: Sequence[Pivot]) -> list[WaveCandidate]:
        found: list[WaveCandidate] = []
        for i in range(max(0, len(pivots) - 5)):
            seq = tuple(pivots[i:i + 6])
            if self._alternating(seq):
                item = self._score_impulse(seq)
                if item.score >= self.min_score:
                    found.append(item)
        for i in range(max(0, len(pivots) - 3)):
            seq = tuple(pivots[i:i + 4])
            if self._alternating(seq):
                item = self._score_correction(seq)
                if item.score >= self.min_score:
                    found.append(item)
        found.sort(key=lambda x: (x.score, x.pivots[-1].index), reverse=True)
        return found

    def _score_impulse(self, seq: tuple[Pivot, ...]) -> WaveCandidate:
        d = [seq[i + 1].price - seq[i].price for i in range(5)]
        direction = 1 if d[0] > 0 else -1
        up = direction > 0
        reasons: list[str] = []
        score = 82.0
        hard = True
        eps = self.pip_size * 0.05
        if any(x * direction <= 0 for x in (d[0], d[2], d[4])) or any(x * direction >= 0 for x in (d[1], d[3])):
            return WaveCandidate("impulse", "up" if up else "down", seq, 0.0, False, ("Leg directions do not alternate as an impulse.",))
        w1, w2, w3, w4, w5 = map(abs, d)
        # Wave 2 must not move beyond the origin of wave 1.
        if (seq[2].price - seq[0].price) * direction <= 0 or w2 >= w1 - eps:
            hard = False; score -= 100; reasons.append("Wave 2 retraces the full start of wave 1.")
        # Wave 3 must move beyond the end of wave 1 and cannot be the shortest motive wave.
        if (seq[3].price - seq[1].price) * direction <= 0:
            hard = False; score -= 100; reasons.append("Wave 3 does not move beyond the end of wave 1.")
        if w3 + eps < min(w1, w5):
            hard = False; score -= 100; reasons.append("Wave 3 is the shortest motive wave.")
        # Standard impulse non-overlap; diagonal structures are a separate pattern family.
        wave1_end, wave4_end = seq[1].price, seq[4].price
        overlap = (wave4_end <= wave1_end + eps) if up else (wave4_end >= wave1_end - eps)
        if overlap:
            hard = False; score -= 100; reasons.append("Wave 4 overlaps wave 1; diagonal exception is not modelled here.")
        # Soft morphology checks. These affect ranking, not hard validity.
        if w2 / w1 > self.impulse_w2_soft_max:
            score -= 10; reasons.append("Wave 2 retracement is unusually deep.")
        if w4 / w3 > self.impulse_w4_soft_max:
            score -= 6; reasons.append("Wave 4 retracement is relatively deep.")
        if (seq[5].price - seq[3].price) * direction <= 0:
            score -= 12; reasons.append("Wave 5 is truncated relative to the wave-3 extreme.")
        if w3 > w1 * 1.618:
            score += 5; reasons.append("Wave 3 shows strong extension relative to wave 1.")
        if not reasons:
            reasons.append("Motive and corrective legs satisfy the implemented basic impulse checks.")
        return WaveCandidate("impulse", "up" if up else "down", seq, max(0.0, min(100.0, score)), hard, tuple(reasons))

    def _score_correction(self, seq: tuple[Pivot, ...]) -> WaveCandidate:
        d = [seq[i + 1].price - seq[i].price for i in range(3)]
        direction = 1 if d[0] > 0 else -1
        if d[0] * direction <= 0 or d[1] * direction >= 0 or d[2] * direction <= 0:
            return WaveCandidate("abc", "down" if direction > 0 else "up", seq, 0.0, False, ("A-B-C legs do not form an alternating correction.",))
        a, b, c = map(abs, d)
        b_ratio = b / a if a else 0.0
        c_ratio = c / a if a else 0.0
        score = 62.0
        reasons = []
        if b_ratio >= self.abc_b_max_ratio:
            score -= 22; reasons.append("B retraces all or more of A; this is not a standard zigzag.")
        else:
            reasons.append("B retraces part of A.")
        if c_ratio < self.abc_c_min_ratio:
            score -= 12; reasons.append("C is short relative to A.")
        if c_ratio >= 0.9:
            score += 10; reasons.append("C is close to or exceeds A in length.")
        subtype = "zigzag"
        if 0.85 <= b_ratio <= 1.15 and c_ratio >= 0.5:
            subtype = "flat_candidate"
            score = min(score, 72.0)
            reasons.append("B retracement is consistent with a possible flat; more context is needed.")
        return WaveCandidate(subtype, "down" if direction > 0 else "up", seq, max(0.0, min(100.0, score)), True, tuple(reasons))


def analyze_pivots(pivots: Sequence[Pivot], pip_size: float = 0.0001) -> list[WaveCandidate]:
    return ElliottEngine(pip_size=pip_size).analyze_pivots(pivots)
