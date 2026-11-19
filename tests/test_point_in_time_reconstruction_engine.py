from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import tempfile
import unittest
from pathlib import Path

from eurusd_ai_monitor.engines.point_in_time_reconstruction_engine import (
    PointInTimeReconstructionEngine,
)
from eurusd_ai_monitor.models.macro_event import MacroEvent, MacroEventStatus, MacroImpact
from eurusd_ai_monitor.models.news_item import NewsItem
from eurusd_ai_monitor.storage.macro_calendar_store import MacroCalendarStore
from eurusd_ai_monitor.storage.market_data_store import Candle, MarketDataStore
from eurusd_ai_monitor.storage.news_store import NewsStore
from source_registry.adapters.models import FetchResult, Observation
from source_registry.observation_store import PointInTimeObservationStore


UTC = timezone.utc
BASE = datetime(2026, 11, 1, tzinfo=UTC)


def candle(minute=0, close="1.1000"):
    value = Decimal(close)
    return Candle(
        broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
        candle_open_time_utc=BASE + timedelta(minutes=minute),
        open=value, high=value + Decimal("0.0002"),
        low=value - Decimal("0.0002"), close=value,
        tick_volume=10, spread=2, real_volume=0,
    )


def news_item(title, retrieved):
    return NewsItem(
        item_id="ECB-1", source_id="ECB", source_name="ECB",
        publisher_role="REGULATOR", authority_tier="A",
        title=title, url="https://www.ecb.europa.eu/press/example",
        published_at_utc=BASE + timedelta(minutes=1),
        retrieved_at_utc=retrieved, summary=title,
        categories=("CENTRAL_BANK",), currencies=("EUR",), topics=("POLICY",),
    )


def macro_event(title, retrieved):
    return MacroEvent(
        event_id="BLS:1", source_id="BLS", source_name="BLS",
        source_url="https://www.bls.gov/schedule/news_release/bls.ics",
        source_event_id="1", title=title, description="",
        currency_codes=("USD",), category="ECONOMIC_RELEASE",
        impact=MacroImpact.HIGH, impact_reason="test",
        scheduled_date=date(2026, 11, 2),
        scheduled_at_utc=BASE + timedelta(days=1),
        source_timezone="UTC", status=MacroEventStatus.SCHEDULED,
        retrieved_at_utc=retrieved,
    )


class PointInTimeReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.market = MarketDataStore(root / "market.sqlite")
        observation_path = root / "observations.sqlite"
        self.observation_writer = PointInTimeObservationStore(observation_path)
        self.observations = PointInTimeObservationStore.open_read_only(observation_path)
        self.news = NewsStore(root / "news.sqlite")
        self.calendar = MacroCalendarStore(root / "calendar.sqlite")
        self.engine = PointInTimeReconstructionEngine(
            self.market, observation_store=self.observations,
            news_store=self.news, macro_calendar_store=self.calendar,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_writable_observation_store_is_rejected(self):
        with self.assertRaises(ValueError):
            PointInTimeReconstructionEngine(
                self.market, observation_store=self.observation_writer
            )

    def test_candle_revision_is_rolled_back_to_as_of_value(self):
        self.market.upsert_candles(
            [candle()], as_of_utc=BASE + timedelta(minutes=10),
            observed_at_utc=BASE + timedelta(minutes=10),
        )
        self.market.upsert_candles(
            [candle(close="1.1010")], as_of_utc=BASE + timedelta(minutes=20),
            observed_at_utc=BASE + timedelta(minutes=20),
        )
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=15),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
        )
        self.assertEqual(result["market_candles"]["status"], "AVAILABLE")
        self.assertEqual(result["market_candles"]["candles"][0]["close"], "1.1000")
        self.assertEqual(result["market_candles"]["candles"][0]["revisions_rolled_back"], 1)

    def test_candle_not_observed_closed_by_as_of_is_excluded(self):
        self.market.upsert_candles(
            [candle()], as_of_utc=BASE + timedelta(minutes=10),
            observed_at_utc=BASE + timedelta(minutes=10),
        )
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(seconds=30),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(seconds=20),
        )
        self.assertEqual(result["market_candles"]["reconstructed_count"], 0)
        self.assertIn("CANDLE_NOT_CLOSED_AT_AS_OF", result["market_candles"]["excluded_counts"])

    def test_candle_revision_scan_limit_fails_closed(self):
        for minute, close in [(0, "1.1000"), (0, "1.1010"), (0, "1.1020")]:
            observed = 10 + self.market.get_candle_revision_watermark(
                "Broker-Demo", "EURUSD", "M1"
            ) * 10
            self.market.upsert_candles(
                [candle(minute, close)], as_of_utc=BASE + timedelta(minutes=observed),
                observed_at_utc=BASE + timedelta(minutes=observed),
            )
        engine = PointInTimeReconstructionEngine(self.market, max_revision_scan=1)
        result = engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=5),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
        )
        self.assertEqual(result["market_candles"]["status"], "UNAVAILABLE")
        self.assertFalse(result["market_candles"]["revision_history_complete"])

    def test_observations_require_published_retrieved_and_effective_before_as_of(self):
        observation = Observation(
            source_id="TEST", product_id="RATE", value=Decimal("4.5"),
            unit="percent", effective_at_utc=BASE + timedelta(minutes=1),
            published_at_utc=BASE + timedelta(minutes=2), source_record_id="R1",
        )
        self.observation_writer.persist_fetch_result(FetchResult(
            source_id="TEST", product_id="RATE", observations=(observation,),
            source_url="https://example.com/rate", record_count=1,
            retrieved_at_utc=BASE + timedelta(minutes=3),
        ))
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=2, seconds=30),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
            observation_requests={"policy": [("TEST", "RATE")]},
        )
        product = result["source_observations"]["domains"]["policy"]["products"][0]
        self.assertEqual(product["observations"], [])
        later = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=4),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
            observation_requests={"policy": [("TEST", "RATE")]},
        )
        self.assertEqual(
            later["source_observations"]["domains"]["policy"]["products"][0]["observations"][0]["value"],
            "4.5",
        )

    def test_news_revision_rolls_back_to_original_published_article(self):
        self.news.upsert_items([news_item("Original title", BASE + timedelta(minutes=2))])
        self.news.upsert_items([news_item("Corrected title", BASE + timedelta(minutes=5))])
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=3),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
        )
        self.assertEqual(result["news"]["items"][0]["title"], "Original title")

    def test_macro_calendar_revision_rolls_back_and_uses_first_seen(self):
        self.calendar.upsert_events(
            [macro_event("Original event", BASE + timedelta(minutes=2))],
            BASE + timedelta(minutes=2),
        )
        self.calendar.upsert_events(
            [macro_event("Revised event", BASE + timedelta(minutes=5))],
            BASE + timedelta(minutes=5),
        )
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=3),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
            calendar_start_utc=BASE, calendar_end_utc=BASE + timedelta(days=2),
        )
        self.assertEqual(result["macro_calendar"]["events"][0]["title"], "Original event")


    def test_news_uses_last_semantic_version_before_as_of_after_later_unchanged_refresh(self):
        self.news.upsert_items([news_item("Original title", BASE + timedelta(minutes=2))])
        self.news.upsert_items([news_item("Corrected title", BASE + timedelta(minutes=3))])
        self.news.upsert_items([news_item("Corrected title", BASE + timedelta(minutes=5))])
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=4),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
        )
        self.assertEqual(result["news"]["items"][0]["title"], "Corrected title")
        self.assertEqual(
            result["news"]["items"][0]["retrieved_at_utc"],
            (BASE + timedelta(minutes=3)).isoformat(),
        )

    def test_news_without_version_history_is_excluded_after_unchanged_refresh(self):
        self.news.upsert_items([news_item("Stable title", BASE + timedelta(minutes=2))])
        self.news.upsert_items([news_item("Stable title", BASE + timedelta(minutes=5))])
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=4),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
        )
        self.assertEqual(result["news"]["items"], [])
        self.assertEqual(result["news"]["excluded_counts"]["NEWS_NOT_AVAILABLE_AS_OF"], 1)

    def test_non_monotonic_candle_revision_timeline_fails_closed_for_bar(self):
        self.market.upsert_candles(
            [candle()], as_of_utc=BASE + timedelta(minutes=10),
            observed_at_utc=BASE + timedelta(minutes=10),
        )
        self.market.upsert_candles(
            [candle(close="1.1010")], as_of_utc=BASE + timedelta(minutes=20),
            observed_at_utc=BASE + timedelta(minutes=20),
        )
        self.market.upsert_candles(
            [candle(close="1.1020")], as_of_utc=BASE + timedelta(minutes=18),
            observed_at_utc=BASE + timedelta(minutes=18),
        )
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=19),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
        )
        self.assertEqual(result["market_candles"]["reconstructed_count"], 0)
        self.assertIn(
            "NON_MONOTONIC_CANDLE_REVISION_TIMELINE",
            result["market_candles"]["excluded_counts"],
        )

    def test_non_monotonic_news_revision_timeline_is_unavailable(self):
        self.news.upsert_items([news_item("Original", BASE + timedelta(minutes=10))])
        self.news.upsert_items([news_item("Later", BASE + timedelta(minutes=20))])
        self.news.upsert_items([news_item("Backdated", BASE + timedelta(minutes=18))])
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=19),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
        )
        self.assertEqual(result["news"]["status"], "UNAVAILABLE")
        self.assertIn("NEWS_REVISION_TIMELINE_NON_MONOTONIC", result["news"]["reason_codes"])

    def test_non_monotonic_calendar_revision_timeline_is_unavailable(self):
        self.calendar.upsert_events(
            [macro_event("Original", BASE + timedelta(minutes=10))],
            BASE + timedelta(minutes=10),
        )
        self.calendar.upsert_events(
            [macro_event("Later", BASE + timedelta(minutes=20))],
            BASE + timedelta(minutes=20),
        )
        self.calendar.upsert_events(
            [macro_event("Backdated", BASE + timedelta(minutes=18))],
            BASE + timedelta(minutes=18),
        )
        result = self.engine.reconstruct(
            as_of_utc=BASE + timedelta(minutes=19),
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=2),
            calendar_start_utc=BASE, calendar_end_utc=BASE + timedelta(days=2),
        )
        self.assertEqual(result["macro_calendar"]["status"], "UNAVAILABLE")
        self.assertIn(
            "CALENDAR_REVISION_TIMELINE_NON_MONOTONIC",
            result["macro_calendar"]["reason_codes"],
        )

    def test_replay_rejects_future_specialist_reports(self):
        point = {
            "evaluated_at_utc": (BASE + timedelta(minutes=10)).isoformat(),
            "specialist_reports": {
                "technical_analysis": {
                    "evaluated_at_utc": (BASE + timedelta(minutes=11)).isoformat(),
                    "broker_server": "Broker-Demo", "symbol": "EURUSD",
                    "status": "AVAILABLE",
                }
            },
        }
        result = self.engine.replay(
            [point], broker_server="Broker-Demo", symbol="EURUSD",
            timeframe="M1", start_utc=BASE,
            end_utc=BASE + timedelta(minutes=20),
        )
        self.assertEqual(result["replay_points_processed"], 1)
        self.assertEqual(
            result["points"][0]["rejected_specialist_reports"]["technical_analysis"],
            "FUTURE_REPORT",
        )
        self.assertFalse(result["points"][0]["historical_specialists_recomputed"])

    def test_replay_point_outside_window_is_rejected(self):
        result = self.engine.replay(
            [{"evaluated_at_utc": (BASE - timedelta(seconds=1)).isoformat()}],
            broker_server="Broker-Demo", symbol="EURUSD", timeframe="M1",
            start_utc=BASE, end_utc=BASE + timedelta(minutes=10),
        )
        self.assertEqual(result["rejected_counts"]["REPLAY_POINT_OUTSIDE_REQUESTED_WINDOW"], 1)

    def test_invalid_or_future_reconstruction_window_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.reconstruct(
                as_of_utc=BASE, broker_server="Broker-Demo", symbol="EURUSD",
                timeframe="M1", start_utc=BASE, end_utc=BASE + timedelta(seconds=1),
            )


if __name__ == "__main__":
    unittest.main()
