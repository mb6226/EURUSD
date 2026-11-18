import unittest
import pandas as pd

from eurusd_ai_monitor.engines.price_action_engine import summarize_structure


class PriceActionEngineClosedFrameTests(unittest.TestCase):
    def test_closed_candles_only_option_uses_last_input_bar(self):
        times = pd.date_range("2026-11-18T08:00:00Z", periods=44, freq="min")
        frame = pd.DataFrame({
            "time": times,
            "open": [1.0] * 44,
            "high": [1.01] * 44,
            "low": [0.99] * 44,
            "close": [1.0] * 44,
        })
        frame.loc[43, "close"] = 1.005

        default_result = summarize_structure(frame)
        closed_result = summarize_structure(frame, closed_candles_only=True)

        self.assertNotEqual(
            default_result["last_closed_candle_utc"],
            closed_result["last_closed_candle_utc"],
        )
        self.assertEqual(
            closed_result["last_closed_candle_utc"],
            times[-1].to_pydatetime().isoformat(),
        )


if __name__ == "__main__":
    unittest.main()
