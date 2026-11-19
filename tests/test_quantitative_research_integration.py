import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.engines.quantitative_market_statistics_engine import (
    QuantitativeMarketStatisticsEngine,
)
from eurusd_ai_monitor.engines.research_intelligence_engine import ResearchIntelligenceEngine
from eurusd_ai_monitor.engines.research_intelligence_sources import (
    RESEARCH_SOURCE_NAMES,
    build_research_intelligence_sources,
)
from eurusd_ai_monitor.models.context_quality import ContextQuality
from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.market_data_store import Candle


NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def candles(timeframe, count):
    minutes = 1 if timeframe == "M1" else 5
    start = NOW - timedelta(minutes=minutes * count)
    values = []
    previous = Decimal("1.10000")
    for index in range(count):
        close = previous + Decimal("0.0001")
        values.append(Candle(
            "Broker", "EURUSD", timeframe,
            start + timedelta(minutes=minutes * index),
            previous, close + Decimal("0.00005"),
            previous - Decimal("0.00005"), close, 10, 1, 0,
        ))
        previous = close
    return tuple(values)


class QuantitativeResearchIntegrationTests(unittest.TestCase):
    def test_snapshot_statistics_reach_central_research_with_provenance_and_limits(self):
        snapshot = MarketSnapshot(
            "EURUSD", NOW, "Broker", candles("M1", 40), candles("M5", 40),
            None, None, ContextQuality(is_valid=True),
        )
        quantitative = QuantitativeMarketStatisticsEngine().assess(snapshot)
        self.assertEqual(quantitative["status"], "AVAILABLE")

        payloads = {
            name: {
                "status": "AVAILABLE",
                "evaluated_at_utc": NOW.isoformat(),
                "broker_server": "Broker",
                "symbol": "EURUSD",
            }
            for name in RESEARCH_SOURCE_NAMES
        }
        payloads["quantitative_market_statistics"] = quantitative
        payloads["fusion_assessment"]["status"] = "READY_FOR_RULES"
        payloads["market_regime_intelligence"]["regime"] = "TRANSITIONAL"
        payloads["price_action_lifecycle"]["status"] = "NO_LIFECYCLE"
        payloads["setup_assessment"]["stage"] = "WAIT"
        payloads["session_eligibility"]["status"] = "RESEARCH_ELIGIBLE"
        payloads["setup_outcome_observation"]["status"] = "ACTIVE"
        payloads["statistical_outcome_evaluation"]["status"] = "INSUFFICIENT_DATA"
        payloads["regime_conditioned_outcome_evaluation"]["status"] = "INSUFFICIENT_DATA"

        sources = build_research_intelligence_sources(
            payloads, broker_server="Broker", symbol="EURUSD"
        )
        report = ResearchIntelligenceEngine().build_report(
            evaluated_at_utc=NOW,
            broker_server="Broker",
            symbol="EURUSD",
            sources=sources,
        )

        self.assertEqual(report["status"], "COHERENT")
        state = report["current_context"]["quantitative_market_statistics"]
        self.assertEqual(state["source_status"], "AVAILABLE")
        self.assertEqual(state["timeframes"]["M1"]["return_count"], 39)
        self.assertEqual(len(state["provenance"]["m5_candle_ids"]), 40)
        self.assertEqual(report["trade_authority"], "NONE")
        self.assertEqual(report["order_execution"], "DISABLED")


if __name__ == "__main__":
    unittest.main()
