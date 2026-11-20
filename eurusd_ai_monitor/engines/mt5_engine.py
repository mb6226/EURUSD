from __future__ import annotations
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
}

class MT5Connector:
    def __init__(self, symbol: str, terminal_path: str | Path | None = None):
        self.symbol = symbol
        self.terminal_path = Path(terminal_path).expanduser() if terminal_path else None
        self.connected = False

    def connect(self) -> None:
        if self.terminal_path is not None:
            if not self.terminal_path.is_file():
                raise FileNotFoundError(
                    f"Configured MT5 terminal executable does not exist: {self.terminal_path}"
                )
            initialized = mt5.initialize(str(self.terminal_path))
        else:
            initialized = mt5.initialize()
        if not initialized:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        info = mt5.terminal_info()
        if info is None:
            raise RuntimeError(f"Cannot read MT5 terminal info: {mt5.last_error()}")
        if not mt5.symbol_select(self.symbol, True):
            raise RuntimeError(f"Cannot select {self.symbol}: {mt5.last_error()}")
        self.connected = True
        print(f"[MT5] Connected. Data path: {info.data_path}")

    def close(self) -> None:
        if self.connected:
            mt5.shutdown()
            self.connected = False

    def broker_server(self) -> str:
        if not self.connected:
            raise RuntimeError("MT5 connector is not connected")
        account = mt5.account_info()
        if account is None:
            raise RuntimeError(
                f"Cannot read MT5 account info: {mt5.last_error()}"
            )
        server = getattr(account, "server", None)
        if not isinstance(server, str) or not server.strip():
            raise RuntimeError("MT5 account did not provide a broker server")
        return server.strip()

    def terminal_data_path(self) -> Path:
        info = mt5.terminal_info()
        if info is None:
            raise RuntimeError("MT5 terminal info unavailable")
        return Path(info.data_path)

    def market_data_metadata(self) -> dict:
        """Return read-only terminal/symbol metadata used to qualify bar provenance."""
        if not self.connected:
            raise RuntimeError("MT5 connector is not connected")
        info = mt5.symbol_info(self.symbol)
        chart_mode = getattr(info, "chart_mode", None) if info is not None else None
        bid_mode = getattr(mt5, "SYMBOL_CHART_MODE_BID", 0)
        last_mode = getattr(mt5, "SYMBOL_CHART_MODE_LAST", 1)
        if chart_mode == bid_mode:
            price_basis = "BID"
        elif chart_mode == last_mode:
            price_basis = "LAST"
        else:
            price_basis = "UNKNOWN"
        version = mt5.version()
        return {
            "price_basis": price_basis,
            "chart_mode_code": chart_mode,
            "digits": getattr(info, "digits", None) if info is not None else None,
            "point": getattr(info, "point", None) if info is not None else None,
            "trade_tick_size": getattr(info, "trade_tick_size", None) if info is not None else None,
            "terminal_version": list(version) if version else None,
            "python_package_version": getattr(mt5, "__version__", None),
            "bar_time_basis": "UTC",
        }

    def tick(self) -> dict:
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {self.symbol}: {mt5.last_error()}")
        return {
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "last": float(tick.last),
            "spread_pips": round((tick.ask - tick.bid) / 0.0001, 2),
        }

    def bars(self, timeframe: str, count: int = 300) -> pd.DataFrame:
        if timeframe not in TIMEFRAME_MAP:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        rates = mt5.copy_rates_from_pos(self.symbol, TIMEFRAME_MAP[timeframe], 0, count)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No {timeframe} bars: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    def bars_range(
        self,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> pd.DataFrame:
        if not self.connected:
            raise RuntimeError("MT5 connector is not connected")
        if timeframe not in TIMEFRAME_MAP:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        if not isinstance(start_utc, datetime) or not isinstance(
            end_utc, datetime
        ):
            raise TypeError("MT5 range boundaries must be datetimes")
        if (
            start_utc.tzinfo is None
            or start_utc.utcoffset() is None
            or end_utc.tzinfo is None
            or end_utc.utcoffset() is None
        ):
            raise ValueError("MT5 range boundaries must be timezone-aware")

        start = start_utc.astimezone(timezone.utc)
        end = end_utc.astimezone(timezone.utc)
        if start >= end:
            raise ValueError("start_utc must be earlier than end_utc")

        rates = mt5.copy_rates_range(
            self.symbol,
            TIMEFRAME_MAP[timeframe],
            start,
            end,
        )
        if rates is None:
            raise RuntimeError(
                f"No {timeframe} bars in requested range: {mt5.last_error()}"
            )
        df = pd.DataFrame(rates)
        if "time" in df.columns and not df.empty:
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    def screenshot_path(self, timeframe: str) -> Path:
        return self.terminal_data_path() / "MQL5" / "Files" / f"{self.symbol}_{timeframe}.png"
