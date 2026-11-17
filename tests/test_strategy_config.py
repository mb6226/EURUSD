import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from eurusd_ai_monitor.strategy_config import (
    StrategyConfig,
    load_strategy_config,
)


class StrategyConfigTests(unittest.TestCase):
    def test_loads_experimental_baseline_v1_exactly(self):
        config = load_strategy_config()

        self.assertEqual(config.strategy_version, "experimental_baseline_v1")
        self.assertEqual(config.algorithm_version, "price_action_contract_v1")
        self.assertEqual(config.pivot_left_bars, 2)
        self.assertEqual(config.pivot_right_bars, 2)
        self.assertEqual(config.min_correction_pips, Decimal("5"))
        self.assertEqual(config.max_correction_ratio, Decimal("0.80"))
        self.assertEqual(config.min_wick_body_ratio, Decimal("1.5"))
        self.assertEqual(config.bullish_close_location_min, Decimal("0.70"))
        self.assertEqual(config.bearish_close_location_max, Decimal("0.30"))
        self.assertEqual(config.pullback_tolerance_pips, Decimal("2"))
        self.assertEqual(config.setup_expiry_bars, 30)
        self.assertEqual(config.stop_loss_pips, Decimal("5"))
        self.assertEqual(config.take_profit_pips, Decimal("50"))
        self.assertFalse(config.trailing_stop_enabled)
        self.assertFalse(config.parameters_validated)
        self.assertFalse(config.live_signals_enabled)
        self.assertIsNone(config.entry_gap_policy)
        self.assertEqual(len(config.parameter_digest), 64)

    def test_decimal_config_values_must_be_strings_not_floats(self):
        payload = load_strategy_config().to_dict()
        payload["min_wick_body_ratio"] = 1.5

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "strategy_config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(TypeError, "decimal string"):
                load_strategy_config(path)

    def test_rejects_invalid_parameters_and_version(self):
        config = load_strategy_config()
        with self.assertRaisesRegex(ValueError, "positive integer"):
            replace(config, pivot_left_bars=0)
        with self.assertRaisesRegex(ValueError, "at most 1"):
            replace(config, bullish_close_location_min=Decimal("1.1"))
        with self.assertRaisesRegex(ValueError, "config_schema_version"):
            replace(config, config_schema_version=2)

    def test_unvalidated_parameters_cannot_enable_live_signals(self):
        config = load_strategy_config()
        with self.assertRaisesRegex(ValueError, "unvalidated parameters"):
            replace(config, live_signals_enabled=True)

    def test_parameter_digest_changes_when_experimental_parameter_changes(self):
        config = load_strategy_config()
        changed = replace(
            config,
            pullback_tolerance_pips=Decimal("2.5"),
        )
        self.assertNotEqual(config.parameter_digest, changed.parameter_digest)

    def test_rejects_missing_or_unknown_configuration_fields(self):
        config = load_strategy_config()
        payload = config.to_dict()
        payload.pop("pivot_left_bars")
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            StrategyConfig.from_mapping(payload)

        payload = config.to_dict()
        payload["unreviewed_setting"] = "value"
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            StrategyConfig.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()
