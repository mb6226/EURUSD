import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from decimal import Decimal

from eurusd_ai_monitor.engines.macro_fundamentals_engine import MacroFundamentalsEngine
from eurusd_ai_monitor.engines.policy_rate_differential_engine import PolicyRateDifferentialEngine
from eurusd_ai_monitor.engines.intermarket_intelligence_engine import IntermarketIntelligenceEngine
from eurusd_ai_monitor.engines.positioning_sentiment_intelligence_engine import PositioningSentimentIntelligenceEngine
from eurusd_ai_monitor.engines.multi_domain_runtime import (
    build_live_specialist_reports, build_live_fundamental_reports,
)


NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


class FakeQuantitativeEngine:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def assess(self, snapshot):
        self.calls.append(snapshot)
        if self.error:
            raise self.error
        return {
            "status": "AVAILABLE",
            "evaluated_at_utc": snapshot.timestamp_utc.isoformat(),
            "broker_server": snapshot.broker_server,
            "symbol": snapshot.symbol,
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }


class FakeLiquidityEngine:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {
            "status": "PARTIAL",
            "evaluated_at_utc": kwargs["evaluated_at_utc"].isoformat(),
            "broker_server": kwargs["broker_server"],
            "symbol": kwargs["symbol"],
            "reason_codes": ["SPREAD_HISTORY_NOT_SUPPLIED"],
            "decision_authority": "CONTEXT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }


def snapshot():
    candle = object()
    return SimpleNamespace(
        timestamp_utc=NOW,
        broker_server="Broker-Demo",
        symbol="EURUSD",
        m1_candles=(candle,),
        m5_candles=(),
    )


class FakeObservationStore:
    def __init__(self, error=None):
        self.error = error
        self.requests = []
        self.as_of = None

    def get_many_as_of(self, requests, as_of_utc):
        self.requests = list(requests)
        self.as_of = as_of_utc
        if self.error:
            raise self.error
        return {pair: [{"requested_pair": pair}] for pair in requests}


class EmptyObservationStore(FakeObservationStore):
    def get_many_as_of(self, requests, as_of_utc):
        self.requests = list(requests)
        self.as_of = as_of_utc
        return {pair: [] for pair in requests}


class FakeDomainEngine:
    def __init__(self, report_type):
        self.report_type = report_type
        self.calls = []

    def assess(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "report_type": self.report_type,
            "status": "PARTIAL",
            "evaluated_at_utc": kwargs["as_of_utc"].isoformat(),
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        }


class MultiDomainRuntimeTests(unittest.TestCase):
    def test_runs_quant_and_liquidity_from_cycle_snapshot(self):
        snap = snapshot()
        quant = FakeQuantitativeEngine()
        liquidity = FakeLiquidityEngine()

        reports = build_live_specialist_reports(
            snap,
            quantitative_engine=quant,
            liquidity_engine=liquidity,
            pip_size=Decimal("0.0001"),
        )

        self.assertEqual(quant.calls, [snap])
        self.assertEqual(reports["quantitative_market_statistics"]["status"], "AVAILABLE")
        self.assertEqual(len(liquidity.calls), 1)
        sample = liquidity.calls[0]["samples"][0]
        self.assertIs(sample["candle"], snap.m1_candles[0])
        self.assertEqual(sample["pip_size"], Decimal("0.0001"))
        self.assertIsNone(sample["spread_pips"])
        self.assertEqual(sample["retrieved_at_utc"], NOW)
        self.assertEqual(
            reports["liquidity_microstructure_intelligence"]["status"], "PARTIAL"
        )

    def test_quantitative_failure_isolated_and_fails_closed(self):
        snap = snapshot()
        reports = build_live_specialist_reports(
            snap,
            quantitative_engine=FakeQuantitativeEngine(RuntimeError("quant failed")),
            liquidity_engine=FakeLiquidityEngine(),
            pip_size=Decimal("0.0001"),
        )
        report = reports["quantitative_market_statistics"]
        self.assertEqual(report["status"], "DEGRADED")
        self.assertEqual(report["trade_authority"], "NONE")
        self.assertEqual(report["order_execution"], "DISABLED")
        self.assertEqual(
            report["reason_codes"], ["QUANTITATIVE_MARKET_STATISTICS_RUNTIME_ERROR:RuntimeError"]
        )
        self.assertEqual(
            reports["liquidity_microstructure_intelligence"]["status"], "PARTIAL"
        )

    def test_four_fundamental_specialists_share_one_point_in_time_read(self):
        snap = snapshot()
        store = FakeObservationStore()
        macro = FakeDomainEngine("MACRO")
        policy = FakeDomainEngine("POLICY")
        intermarket = FakeDomainEngine("INTERMARKET")
        positioning = FakeDomainEngine("POSITIONING")

        reports = build_live_fundamental_reports(
            snap,
            observation_store=store,
            macro_engine=macro,
            policy_engine=policy,
            intermarket_engine=intermarket,
            positioning_engine=positioning,
        )

        self.assertEqual(store.as_of, NOW)
        self.assertEqual(len(store.requests), 15)
        self.assertEqual(len(set(store.requests)), 15)
        self.assertEqual(set(reports), {
            "macro_fundamentals_intelligence",
            "policy_rate_differential_intelligence",
            "intermarket_intelligence",
            "positioning_sentiment_intelligence",
        })
        self.assertEqual(len(macro.calls), 1)
        self.assertEqual(len(policy.calls), 1)
        self.assertEqual(len(intermarket.calls), 1)
        self.assertEqual(len(positioning.calls), 1)
        self.assertEqual(
            macro.calls[0]["us_cpi_observations"],
            [{"requested_pair": ("US_BLS_MACRO", "US_CPI_ALL_ITEMS_INDEX")}],
        )
        self.assertEqual(
            policy.calls[0]["fed_observations"],
            [{"requested_pair": ("FED_FOMC_POLICY", "FED_TARGET_RANGE")}],
        )
        self.assertEqual(
            intermarket.calls[0]["eurusd_observations"],
            [{"requested_pair": ("BROKER_SPOT_REFERENCE", "EURUSD_SPOT_REFERENCE")}],
        )
        self.assertEqual(
            positioning.calls[0]["observations"]["EURO_FX_LEVERAGED_MONEY_NET_OI_PCT"],
            [{"requested_pair": ("CFTC_TFF_POSITIONING", "EURO_FX_LEVERAGED_MONEY_NET_OI_PCT")}],
        )
        self.assertEqual(
            reports["macro_fundamentals_intelligence"]["broker_server"],
            "Broker-Demo",
        )
        self.assertEqual(
            reports["positioning_sentiment_intelligence"]["trade_authority"],
            "NONE",
        )

    def test_real_specialists_run_from_empty_point_in_time_store_without_fabricating_data(self):
        snap = snapshot()
        reports = build_live_fundamental_reports(
            snap,
            observation_store=EmptyObservationStore(),
            macro_engine=MacroFundamentalsEngine(),
            policy_engine=PolicyRateDifferentialEngine(
                max_observation_age=timedelta(days=60)
            ),
            intermarket_engine=IntermarketIntelligenceEngine(),
            positioning_engine=PositioningSentimentIntelligenceEngine(),
        )
        self.assertEqual(
            {name: report["status"] for name, report in reports.items()},
            {
                "macro_fundamentals_intelligence": "UNAVAILABLE",
                "policy_rate_differential_intelligence": "UNAVAILABLE",
                "intermarket_intelligence": "UNAVAILABLE",
                "positioning_sentiment_intelligence": "UNAVAILABLE",
            },
        )
        self.assertTrue(all(report["trade_authority"] == "NONE" for report in reports.values()))
        self.assertTrue(all(report["order_execution"] == "DISABLED" for report in reports.values()))

    def test_missing_observation_store_is_explicit_without_creating_data(self):
        engines = [FakeDomainEngine(name) for name in ("M", "P", "I", "S")]
        reports = build_live_fundamental_reports(
            snapshot(),
            observation_store=None,
            macro_engine=engines[0],
            policy_engine=engines[1],
            intermarket_engine=engines[2],
            positioning_engine=engines[3],
        )
        self.assertEqual({item["status"] for item in reports.values()}, {"NOT_CONFIGURED"})
        self.assertTrue(all(item["trade_authority"] == "NONE" for item in reports.values()))
        self.assertTrue(all(not engine.calls for engine in engines))

    def test_observation_store_failure_isolated_as_degraded_for_all_domains(self):
        engines = [FakeDomainEngine(name) for name in ("M", "P", "I", "S")]
        reports = build_live_fundamental_reports(
            snapshot(),
            observation_store=FakeObservationStore(RuntimeError("read failed")),
            macro_engine=engines[0],
            policy_engine=engines[1],
            intermarket_engine=engines[2],
            positioning_engine=engines[3],
        )
        self.assertEqual({item["status"] for item in reports.values()}, {"DEGRADED"})
        self.assertTrue(all(item["order_execution"] == "DISABLED" for item in reports.values()))

    def test_liquidity_failure_does_not_hide_quantitative_report(self):
        reports = build_live_specialist_reports(
            snapshot(),
            quantitative_engine=FakeQuantitativeEngine(),
            liquidity_engine=FakeLiquidityEngine(RuntimeError("liquidity failed")),
            pip_size=Decimal("0.0001"),
        )
        self.assertEqual(reports["quantitative_market_statistics"]["status"], "AVAILABLE")
        report = reports["liquidity_microstructure_intelligence"]
        self.assertEqual(report["status"], "DEGRADED")
        self.assertEqual(report["trade_authority"], "NONE")
        self.assertEqual(report["order_execution"], "DISABLED")


if __name__ == "__main__":
    unittest.main()
