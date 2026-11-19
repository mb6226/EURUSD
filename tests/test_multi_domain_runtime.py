import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from decimal import Decimal

from eurusd_ai_monitor.engines.multi_domain_runtime import build_live_specialist_reports


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
