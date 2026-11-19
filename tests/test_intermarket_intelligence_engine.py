import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.engines.intermarket_intelligence_engine import (
    IntermarketIntelligenceEngine,
)


UTC = timezone.utc
AS_OF = datetime(2026, 11, 19, 23, tzinfo=UTC)
CHANGES = [Decimal(value) for value in (
    "1","-1","2","-2","3","-3","2","-1","1","-2",
    "3","-1","2","-3","1","-2","2","-1","3","-2",
    "1","-3","2","-1","3","-2","1","-1","2",
)]
UNITS = {
    "US_10Y_TREASURY_YIELD": ("FRED_INTERMARKET","percent_per_annum","YIELD"),
    "DE_10Y_GOVERNMENT_YIELD": ("ECB_INTERMARKET","percent_per_annum","YIELD"),
    "USD_BROAD_TRADE_WEIGHTED_INDEX": ("FRED_INTERMARKET","index_points","PRICE"),
    "GOLD_USD_TROY_OUNCE": ("LBMA_INTERMARKET","usd_per_troy_ounce","PRICE"),
    "SP500_INDEX": ("FRED_INTERMARKET","index_points","PRICE"),
}


def make_rows(source, product, unit, values, *, offset_minutes=0, start=None):
    start = start or datetime(2026,10,20,16,tzinfo=UTC)
    rows = []
    for index, value in enumerate(values):
        observed = start + timedelta(days=index, minutes=offset_minutes)
        rows.append({
            "source_id": source, "product_id": product, "unit": unit,
            "effective_at_utc": observed.isoformat(),
            "published_at_utc": (observed + timedelta(minutes=1)).isoformat(),
            "retrieved_at_utc": (observed + timedelta(minutes=2)).isoformat(),
            "value": str(value), "source_record_id": f"{product}-{index}",
            "version": 1, "payload_sha256": format(index % 16, "x") * 64,
        })
    return rows


def price_values(initial, changes):
    value = Decimal(initial)
    values = [value]
    for change in changes:
        value *= (Decimal(100) + change) / Decimal(100)
        values.append(value)
    return values


def yield_values(initial, changes):
    value = Decimal(initial)
    values = [value]
    for change in changes:
        value += change / Decimal(100)
        values.append(value)
    return values


class IntermarketIntelligenceEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = IntermarketIntelligenceEngine(
            lookback_observations=60, minimum_observations=20
        )
        self.eurusd = make_rows(
            "BROKER_SPOT_REFERENCE", "EURUSD_SPOT_REFERENCE", "usd_per_eur",
            price_values("1.10", CHANGES),
        )

    def drivers(self):
        result = {}
        for product, (source, unit, kind) in UNITS.items():
            values = (
                yield_values("4.0", CHANGES) if kind == "YIELD"
                else price_values("100", CHANGES)
            )
            result[product] = make_rows(source, product, unit, values)
        return result

    def test_reports_cross_market_correlations_and_provenance(self):
        report = self.engine.assess(
            as_of_utc=AS_OF, eurusd_observations=self.eurusd,
            driver_observations=self.drivers(),
        )
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(report["report_type"], "INTERMARKET_INTELLIGENCE")
        self.assertEqual(
            report["drivers"]["GOLD_USD_TROY_OUNCE"]["contemporaneous_correlation"],
            "1.000000",
        )
        self.assertEqual(
            report["drivers"]["US_10Y_TREASURY_YIELD"]["change_method"],
            "YIELD_CHANGE_BP",
        )
        self.assertEqual(report["decision_authority"], "ASSESSMENT_ONLY")
        self.assertEqual(report["trade_authority"], "NONE")
        self.assertTrue(report["provenance"]["eurusd_payload_sha256"])

    def test_missing_driver_is_partial_not_zero_filled(self):
        report = self.engine.assess(
            as_of_utc=AS_OF, eurusd_observations=self.eurusd,
            driver_observations={"GOLD_USD_TROY_OUNCE": self.drivers()["GOLD_USD_TROY_OUNCE"]},
        )
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["drivers"]["SP500_INDEX"]["status"], "INSUFFICIENT_DATA")
        self.assertNotIn("contemporaneous_correlation", report["drivers"]["SP500_INDEX"])

    def test_exact_timestamp_alignment_does_not_forward_fill(self):
        drivers = self.drivers()
        rows = drivers["GOLD_USD_TROY_OUNCE"]
        shifted = []
        for row in rows:
            copy = dict(row)
            for field in ("effective_at_utc","published_at_utc","retrieved_at_utc"):
                stamp = datetime.fromisoformat(copy[field].replace("Z","+00:00")) + timedelta(minutes=1)
                copy[field] = stamp.isoformat()
            shifted.append(copy)
        drivers["GOLD_USD_TROY_OUNCE"] = shifted
        report = self.engine.assess(
            as_of_utc=AS_OF, eurusd_observations=self.eurusd,
            driver_observations=drivers,
        )
        self.assertEqual(
            report["drivers"]["GOLD_USD_TROY_OUNCE"]["reason_codes"],
            ["COMMON_TIMESTAMP_HISTORY_INSUFFICIENT"],
        )

    def test_future_effective_published_and_retrieved_rows_are_excluded(self):
        future = dict(self.eurusd[-1])
        for field in ("effective_at_utc","published_at_utc","retrieved_at_utc"):
            future[field] = (AS_OF + timedelta(days=1)).isoformat()
        future["source_record_id"] = "future"
        self.eurusd.append(future)
        report = self.engine.assess(
            as_of_utc=AS_OF, eurusd_observations=self.eurusd,
            driver_observations=self.drivers(),
        )
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertNotIn("future", report["provenance"]["eurusd_observation_ids"])

    def test_future_publication_is_excluded_even_if_retrieved_before_cutoff(self):
        row = dict(self.eurusd[-1])
        row["published_at_utc"] = (AS_OF + timedelta(hours=1)).isoformat()
        row["retrieved_at_utc"] = (AS_OF - timedelta(hours=1)).isoformat()
        self.eurusd[-1] = row
        report = self.engine.assess(
            as_of_utc=AS_OF, eurusd_observations=self.eurusd,
            driver_observations=self.drivers(),
        )
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertIn("EURUSD_REFERENCE_HISTORY_INSUFFICIENT", report["reason_codes"])

    def test_stale_eurusd_reference_blocks_all_comparisons(self):
        old = datetime(2026,10,1,16,tzinfo=UTC)
        rows = make_rows(
            "BROKER_SPOT_REFERENCE","EURUSD_SPOT_REFERENCE","usd_per_eur",
            price_values("1.10",CHANGES),start=old,
        )
        report = self.engine.assess(
            as_of_utc=AS_OF, eurusd_observations=rows,
            driver_observations=self.drivers(),
        )
        self.assertEqual(report["status"], "STALE")
        self.assertEqual(report["reason_codes"], ["EURUSD_REFERENCE_STALE"])

    def test_stale_driver_is_reported_separately(self):
        drivers = self.drivers()
        old = datetime(2026,10,1,16,tzinfo=UTC)
        drivers["GOLD_USD_TROY_OUNCE"] = make_rows(
            "LBMA_INTERMARKET","GOLD_USD_TROY_OUNCE","usd_per_troy_ounce",
            price_values("2000",CHANGES),start=old,
        )
        report = self.engine.assess(
            as_of_utc=AS_OF, eurusd_observations=self.eurusd,
            driver_observations=drivers,
        )
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["drivers"]["GOLD_USD_TROY_OUNCE"]["status"], "STALE")

    def test_identity_and_unit_mismatch_fail_closed(self):
        bad = [dict(row) for row in self.eurusd]
        bad[0]["unit"] = "wrong"
        with self.assertRaises(ValueError):
            self.engine.assess(
                as_of_utc=AS_OF, eurusd_observations=bad,
                driver_observations=self.drivers(),
            )

    def test_naive_as_of_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.assess(
                as_of_utc=datetime(2026,11,19,23),
                eurusd_observations=self.eurusd,
                driver_observations=self.drivers(),
            )

    def test_invalid_thresholds_are_rejected(self):
        with self.assertRaises(ValueError):
            IntermarketIntelligenceEngine(minimum_observations=2)
        with self.assertRaises(ValueError):
            IntermarketIntelligenceEngine(lookback_observations=10,minimum_observations=11)


if __name__ == "__main__":
    unittest.main()
