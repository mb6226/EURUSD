import unittest
from datetime import datetime, timedelta, timezone

from eurusd_ai_monitor.engines.evidence_lineage_engine import (
    EvidenceLineageEngine, build_candle_inventory, candle_evidence_id,
)
from eurusd_ai_monitor.engines.evidence_lineage_runtime import (
    build_evidence_lineage_payload,
)
from eurusd_ai_monitor.storage.market_data_store import Candle

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def candle(tf="M1", minute=0, broker="Broker-Demo", symbol="EURUSD"):
    opened = NOW - timedelta(minutes=minute + (1 if tf == "M1" else 5))
    seconds = 60 if tf == "M1" else 300
    opened = opened.replace(second=0, microsecond=0)
    if tf == "M5":
        opened = opened.replace(minute=(opened.minute // 5) * 5)
    return Candle(
        broker_server=broker, symbol=symbol, timeframe=tf,
        candle_open_time_utc=opened,
        open="1.1000", high="1.1010", low="1.0990", close="1.1005",
        tick_volume=10, spread=1, real_volume=0,
    )


class EvidenceLineageEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = EvidenceLineageEngine()
        self.m1 = candle("M1", 0)
        self.m5 = candle("M5", 0)
        self.inventory = build_candle_inventory(
            (self.m1, self.m5), evaluated_at_utc=NOW
        )
        self.m1_id = self.inventory[0]["candle_id"]
        self.m5_id = self.inventory[1]["candle_id"]

    def audit(self, sources=None, inventory=None):
        return self.engine.audit(
            evaluated_at_utc=NOW, broker_server="Broker-Demo", symbol="EURUSD",
            candle_inventory=self.inventory if inventory is None else inventory,
            sources={} if sources is None else sources,
        )

    def test_missing_sources_are_partial_and_authority_is_restricted(self):
        result = self.audit({name: {} for name in (
            "technical_analysis", "fusion_assessment", "market_regime_intelligence",
            "price_action_lifecycle", "setup_assessment",
        )})
        self.assertEqual(result["status"], "TRACEABLE")
        self.assertEqual(result["inventory"]["total_candles"], 2)
        self.assertEqual(result["trade_authority"], "NONE")
        self.assertEqual(result["order_execution"], "DISABLED")

    def test_setup_m1_references_resolve(self):
        result = self.audit({"setup_assessment": {
            "rejection": {"candle_id": self.m1_id},
            "pullback": {
                "breakout_candle_id": self.m1_id,
                "retest_candle_id": self.m1_id,
            },
        }})
        item = next(x for x in result["source_manifest"] if x["source"] == "setup_assessment")
        self.assertEqual(item["status"], "TRACEABLE")
        self.assertEqual(item["reference_count"], 1)

    def test_technical_m5_reference_resolves_and_metadata_is_checked(self):
        opened = self.m5.candle_open_time_utc
        closed = opened + timedelta(minutes=5)
        result = self.audit({"technical_analysis": {
            "trend": {"swing_highs": [{
                "candle_id": self.m5_id,
                "confirmed_at_utc": closed.isoformat(),
                "candle": {"timeframe": "M5", "open_time_utc": opened.isoformat()},
            }]}
        }})
        self.assertEqual(result["status"], "TRACEABLE")

    def test_unknown_candle_reference_degrades(self):
        result = self.audit({"setup_assessment": {"rejection": {"candle_id": "missing"}}})
        self.assertEqual(result["status"], "DEGRADED")
        self.assertIn("REFERENCED_CANDLE_NOT_IN_SNAPSHOT", result["reason_codes"])

    def test_wrong_timeframe_reference_degrades(self):
        result = self.audit({"setup_assessment": {"rejection": {"candle_id": self.m5_id}}})
        self.assertEqual(result["status"], "DEGRADED")
        item = next(x for x in result["source_manifest"] if x["source"] == "setup_assessment")
        self.assertIn("REFERENCE_TIMEFRAME_CONTRACT_VIOLATION", item["reason_codes"])

    def test_evidence_confirmation_before_candle_close_degrades(self):
        opened = self.m1.candle_open_time_utc
        result = self.audit({"setup_assessment": {"evidence": {
            "candle_id": self.m1_id,
            "confirmed_at_utc": (opened + timedelta(seconds=30)).isoformat(),
            "candle": {"timeframe": "M1", "open_time_utc": opened.isoformat()},
        }}})
        self.assertEqual(result["status"], "DEGRADED")
        self.assertIn("SOURCE_LINEAGE_CONTRACT_VIOLATION", result["reason_codes"])

    def test_evidence_confirmation_after_cycle_degrades(self):
        opened = self.m1.candle_open_time_utc
        result = self.audit({"setup_assessment": {"evidence": {
            "candle_id": self.m1_id,
            "confirmed_at_utc": (NOW + timedelta(seconds=1)).isoformat(),
            "candle": {"timeframe": "M1", "open_time_utc": opened.isoformat()},
        }}})
        self.assertEqual(result["status"], "DEGRADED")

    def test_evidence_metadata_mismatch_degrades(self):
        opened = self.m1.candle_open_time_utc
        result = self.audit({"setup_assessment": {"evidence": {
            "candle_id": self.m1_id,
            "confirmed_at_utc": (opened + timedelta(minutes=1)).isoformat(),
            "candle": {"timeframe": "M5", "open_time_utc": opened.isoformat()},
        }}})
        self.assertEqual(result["status"], "DEGRADED")

    def test_market_regime_can_reference_both_timeframes(self):
        result = self.audit({"market_regime_intelligence": {
            "provenance": {"m5_candle_ids": [self.m5_id],
                           "m1_confirmation_candle_ids": [self.m1_id]}
        }})
        self.assertEqual(result["status"], "TRACEABLE")

    def test_lifecycle_can_reference_mixed_timeframes(self):
        result = self.audit({"price_action_lifecycle": {
            "lifecycle_snapshot": {"evidence_candle_ids": [self.m5_id, self.m1_id]}
        }})
        self.assertEqual(result["status"], "TRACEABLE")

    def test_duplicate_inventory_id_degrades(self):
        result = self.audit(inventory=self.inventory + [self.inventory[0]])
        self.assertEqual(result["status"], "DEGRADED")
        self.assertIn("DUPLICATE_CANDLE_ID", result["reason_codes"])

    def test_inventory_identity_mismatch_degrades(self):
        altered = [dict(item) for item in self.inventory]
        altered[0]["symbol"] = "GBPUSD"
        result = self.audit(inventory=altered)
        self.assertEqual(result["status"], "DEGRADED")

    def test_open_candle_inventory_is_rejected(self):
        altered = [dict(item) for item in self.inventory]
        altered[0]["close_time_utc"] = (NOW + timedelta(minutes=1)).isoformat()
        result = self.audit(inventory=altered)
        self.assertEqual(result["status"], "DEGRADED")

    def test_inventory_digest_is_deterministic(self):
        first = self.audit()
        second = self.audit()
        self.assertEqual(first["inventory"]["inventory_sha256"],
                         second["inventory"]["inventory_sha256"])

    def test_orphaned_candles_are_reported_not_failed(self):
        result = self.audit({name: {} for name in (
            "technical_analysis", "fusion_assessment", "market_regime_intelligence",
            "price_action_lifecycle", "setup_assessment",
        )})
        self.assertEqual(result["status"], "TRACEABLE")
        self.assertEqual(result["reference_coverage"]["orphaned_inventory_count"], 2)

    def test_builder_uses_stable_evidence_id_format(self):
        expected = (
            f"Broker-Demo|EURUSD|M1|"
            f"{self.m1.candle_open_time_utc.isoformat().replace('+00:00', 'Z')}"
        )
        self.assertEqual(self.m1_id, expected)
        self.assertEqual(candle_evidence_id(
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            open_time_utc=self.m1.candle_open_time_utc,
        ), expected)


class EvidenceLineageRuntimeTests(unittest.TestCase):
    def test_runtime_success_returns_engine_report(self):
        engine = EvidenceLineageEngine()
        inventory = build_candle_inventory((candle(),), evaluated_at_utc=NOW)
        result = build_evidence_lineage_payload(
            engine, evaluated_at_utc=NOW, broker_server="Broker-Demo",
            symbol="EURUSD", candle_inventory=inventory,
            sources={name: {} for name in (
                "technical_analysis", "fusion_assessment", "market_regime_intelligence",
                "price_action_lifecycle", "setup_assessment",
            )},
        )
        self.assertEqual(result["status"], "TRACEABLE")

    def test_runtime_failure_fails_closed(self):
        result = build_evidence_lineage_payload(
            object(), evaluated_at_utc=NOW, broker_server="Broker-Demo",
            symbol="EURUSD", candle_inventory=[], sources={},
        )
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["trade_authority"], "NONE")
        self.assertIn("EVIDENCE_LINEAGE_ERROR:TypeError", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
