from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from eurusd_ai_monitor.engines import mt5_engine


class MT5ConnectorTests(unittest.TestCase):
    def test_connector_initializes_explicit_terminal_path(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = Path(directory) / "terminal64.exe"
            terminal.write_bytes(b"test")
            with (
                patch.object(mt5_engine.mt5, "initialize", return_value=True) as initialize,
                patch.object(mt5_engine.mt5, "terminal_info", return_value=SimpleNamespace(data_path="data")),
                patch.object(mt5_engine.mt5, "symbol_select", return_value=True),
                patch.object(mt5_engine.mt5, "shutdown") as shutdown,
            ):
                connector = mt5_engine.MT5Connector("EURUSD", terminal_path=terminal)
                connector.connect()
                initialize.assert_called_once_with(str(terminal))
                self.assertTrue(connector.connected)
                connector.close()
                shutdown.assert_called_once()

    def test_connector_rejects_missing_configured_terminal_before_initialize(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.exe"
            with patch.object(mt5_engine.mt5, "initialize") as initialize:
                connector = mt5_engine.MT5Connector("EURUSD", terminal_path=missing)
                with self.assertRaisesRegex(
                    FileNotFoundError, "Configured MT5 terminal executable"
                ):
                    connector.connect()
                initialize.assert_not_called()

    def test_market_data_metadata_identifies_chart_price_basis(self):
        with (
            patch.object(mt5_engine.mt5, "symbol_info", return_value=SimpleNamespace(
                chart_mode=0, digits=5, point=0.00001, trade_tick_size=0.00001
            )),
            patch.object(mt5_engine.mt5, "version", return_value=(500, 1, "build")),
            patch.object(mt5_engine.mt5, "SYMBOL_CHART_MODE_BID", 0, create=True),
            patch.object(mt5_engine.mt5, "SYMBOL_CHART_MODE_LAST", 1, create=True),
        ):
            connector = mt5_engine.MT5Connector("EURUSD")
            connector.connected = True
            metadata = connector.market_data_metadata()
        self.assertEqual(metadata["price_basis"], "BID")
        self.assertEqual(metadata["bar_time_basis"], "UTC")
        self.assertEqual(metadata["digits"], 5)

    def test_connector_preserves_default_terminal_discovery(self):
        with (
            patch.object(mt5_engine.mt5, "initialize", return_value=True) as initialize,
            patch.object(mt5_engine.mt5, "terminal_info", return_value=SimpleNamespace(data_path="data")),
            patch.object(mt5_engine.mt5, "symbol_select", return_value=True),
            patch.object(mt5_engine.mt5, "shutdown"),
        ):
            connector = mt5_engine.MT5Connector("EURUSD")
            connector.connect()
            initialize.assert_called_once_with()
            connector.close()


if __name__ == "__main__":
    unittest.main()
