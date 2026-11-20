from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from eurusd_ai_monitor.engines.fusion_engine import (
    EvidenceDirection,
    FusionEngine,
    FusionStatus,
)
from eurusd_ai_monitor.main import _build_fusion_assessment


NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


class MainVisualFusionIntegrationTests(unittest.TestCase):
    def test_chart_observations_enter_fusion_as_context_only_evidence(self):
        snapshot = SimpleNamespace(
            timestamp_utc=NOW,
            broker_server="Headway-Live",
        )
        technical = {
            "status": "AVAILABLE",
            "evaluated_at_utc": NOW.isoformat(),
            "source_id": "Headway-Live",
            "trend": {
                "direction": "UP",
                "swing_highs": [{"candle_id": "m5-high-1"}],
                "swing_lows": [{"candle_id": "m5-low-1"}],
            },
        }
        price_action = {
            "status": "PROCESSED",
            "broker_server": "Headway-Live",
            "evaluated_at_utc": NOW.isoformat(),
            "lifecycle_snapshot": {
                "state": "CONFIRMED",
                "trend_direction": "UP",
                "evidence_candle_ids": ["pa-candle-1"],
            },
        }
        macro = {
            "status": "AVAILABLE",
            "evaluated_at_utc": NOW.isoformat(),
            "source_id": "calendar",
            "high_impact_count": 0,
        }
        news = {
            "status": "AVAILABLE",
            "evaluated_at_utc": NOW.isoformat(),
            "source_id": "news",
            "article_count": 0,
        }
        screenshots = {
            tf: {
                "evidence_id": f"mt5-screenshot:{tf}:abc123",
                "latest_analysis": {
                    "status": "ANALYZED",
                    "is_recent": True,
                    "provider": "ollama-local",
                    "model": "qwen2.5vl:7b",
                    "image_sha256": f"sha-{tf}",
                    "evaluated_at_utc": NOW.isoformat(),
                    "analysis": {
                        "observed_direction": "DOWN",
                        "chart_quality": "GOOD",
                    },
                },
            }
            for tf in ("M1", "M5")
        }

        result = _build_fusion_assessment(
            FusionEngine(),
            snapshot,
            technical,
            None,
            price_action,
            macro,
            news,
            screenshots=screenshots,
        )

        self.assertEqual(result.status, FusionStatus.READY_FOR_RULES)
        self.assertEqual(result.directional_bias, EvidenceDirection.UP)
        visual = next(
            item for item in result.specialist_evidence
            if item.specialist == "visual"
        )
        self.assertEqual(visual.direction, EvidenceDirection.NEUTRAL)
        self.assertIn("VISUAL_M1_DIRECTION_DOWN", result.context_flags)
        self.assertIn("VISUAL_M5_DIRECTION_DOWN", result.context_flags)
        self.assertIn("VISUAL_TECHNICAL_DIRECTION_DISAGREEMENT", result.context_flags)
        self.assertIn("VISUAL_PRICE_ACTION_DIRECTION_DISAGREEMENT", result.context_flags)


if __name__ == "__main__":
    unittest.main()
