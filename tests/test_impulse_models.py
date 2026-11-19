import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from eurusd_ai_monitor.models.impulse import Impulse
from eurusd_ai_monitor.models.price_action import EvidenceRef, EvidenceRole, MovementDirection
from eurusd_ai_monitor.storage.market_data_store import Candle


BASE = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
BROKER = "TestBroker"
SYMBOL = "EURUSD"
ALGORITHM = "market_structure_v1"
PARAMETERS = "test-parameters"


def candle(index, high, low):
    return Candle(
        broker_server=BROKER,
        symbol=SYMBOL,
        timeframe="M5",
        candle_open_time_utc=BASE + timedelta(minutes=5 * index),
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(low),
        tick_volume=10,
        spread=2,
        real_volume=0,
    )


def evidence(index, high, low, confirmed_after_minutes=10):
    item = candle(index, high, low)
    return EvidenceRef(
        candle=item,
        role=EvidenceRole.TREND_PIVOT,
        confirmed_at_utc=item.candle_open_time_utc + timedelta(minutes=confirmed_after_minutes),
        algorithm_version=ALGORITHM,
        parameter_version=PARAMETERS,
    )


class ImpulseModelTests(unittest.TestCase):
    def make_up_impulse(self):
        start = evidence(0, "1.1010", "1.1000")
        end = evidence(4, "1.1100", "1.1080")
        return Impulse(
            direction=MovementDirection.UP,
            start_pivot=start,
            end_pivot=end,
            start_price=Decimal("1.1000"),
            end_price=Decimal("1.1100"),
            pip_size=Decimal("0.0001"),
            size_pips=Decimal("100"),
            started_at_utc=start.candle.candle_open_time_utc,
            ended_at_utc=end.candle.candle_open_time_utc,
            confirmed_at_utc=end.confirmed_at_utc,
            algorithm_version=ALGORITHM,
            parameter_version=PARAMETERS,
        )

    def test_up_impulse_uses_low_to_high_and_exact_pip_distance(self):
        impulse = self.make_up_impulse()
        self.assertEqual(impulse.size_pips, Decimal("100"))
        self.assertIn("EURUSD", impulse.impulse_id)

    def test_down_impulse_uses_high_to_low(self):
        start = evidence(0, "1.1100", "1.1080")
        end = evidence(4, "1.1020", "1.1000")
        impulse = Impulse(
            direction=MovementDirection.DOWN,
            start_pivot=start,
            end_pivot=end,
            start_price=Decimal("1.1100"),
            end_price=Decimal("1.1000"),
            pip_size=Decimal("0.0001"),
            size_pips=Decimal("100"),
            started_at_utc=start.candle.candle_open_time_utc,
            ended_at_utc=end.candle.candle_open_time_utc,
            confirmed_at_utc=end.confirmed_at_utc,
            algorithm_version=ALGORITHM,
            parameter_version=PARAMETERS,
        )
        self.assertEqual(impulse.direction, MovementDirection.DOWN)

    def test_rejects_mismatched_size(self):
        impulse = self.make_up_impulse()
        with self.assertRaisesRegex(ValueError, "size_pips"):
            Impulse(
                **{
                    **impulse.__dict__,
                    "size_pips": Decimal("99"),
                }
            )

    def test_rejects_unconfirmed_or_wrong_time_terminal_pivot(self):
        impulse = self.make_up_impulse()
        with self.assertRaisesRegex(ValueError, "confirmed_at_utc"):
            Impulse(
                **{
                    **impulse.__dict__,
                    "confirmed_at_utc": impulse.ended_at_utc,
                }
            )

    def test_serialization_round_trip_preserves_decimal_and_evidence(self):
        impulse = self.make_up_impulse()
        restored = Impulse.from_dict(impulse.to_dict())
        self.assertEqual(restored, impulse)
        self.assertIsInstance(restored.size_pips, Decimal)


if __name__ == "__main__":
    unittest.main()
