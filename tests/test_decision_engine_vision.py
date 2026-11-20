from __future__ import annotations

import unittest

from eurusd_ai_monitor.engines.decision_engine import evaluate


class DecisionEngineVisionGateTests(unittest.TestCase):
    def test_vision_analysis_never_grants_trade_authority(self):
        result = evaluate(
            {"status": "OK"},
            {"status": "OK"},
            {"spread_pips": 0.8},
            {
                "M1": {
                    "status": "IMAGE_READY",
                    "semantic_analysis_available": True,
                    "analysis_status": "ANALYZED_RECENT_FRAME",
                },
                "M5": {
                    "status": "IMAGE_READY",
                    "semantic_analysis_available": True,
                    "analysis_status": "ANALYZED_CURRENT_IMAGE",
                },
            },
        )
        self.assertEqual(result["decision"], "WAIT")
        self.assertEqual(result["direction"], "NONE")
        self.assertEqual(result["trade_execution"], "DISABLED")
        self.assertIn(
            "User's complete Trend-Correction-Rejection-Pullback rules not yet encoded",
            result["reasons"],
        )

    def test_pending_visual_analysis_keeps_decision_blocked(self):
        result = evaluate(
            {"status": "OK"},
            {"status": "OK"},
            {"spread_pips": 0.8},
            {
                "M1": {
                    "status": "IMAGE_READY",
                    "semantic_analysis_available": False,
                    "analysis_status": "PENDING",
                },
            },
        )
        self.assertEqual(result["decision"], "WAIT")
        self.assertIn("M1 visual analysis pending", result["reasons"])


if __name__ == "__main__":
    unittest.main()
