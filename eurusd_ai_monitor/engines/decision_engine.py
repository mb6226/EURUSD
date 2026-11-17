from __future__ import annotations

def evaluate(m1: dict, m5: dict, tick: dict, screenshots: dict) -> dict:
    """
    Safety-first placeholder. Until the user-defined rules and vision model
    are implemented and validated, this engine must never issue BUY or SELL.
    """
    reasons = []
    if m1.get("status") != "OK":
        reasons.append("M1 data unavailable")
    if m5.get("status") != "OK":
        reasons.append("M5 data unavailable")
    if tick.get("spread_pips", 999) > 2.0:
        reasons.append("Spread exceeds provisional 2-pip warning threshold")
    for tf, result in screenshots.items():
        if result.get("status") != "IMAGE_READY":
            reasons.append(f"{tf} chart screenshot not fresh/ready")
        else:
            reasons.append(f"{tf} visual model not connected")

    reasons.append("User's complete Trend-Correction-Rejection-Pullback rules not yet encoded")
    return {
        "decision": "WAIT",
        "direction": "NONE",
        "reasons": reasons,
        "trade_execution": "DISABLED",
    }
