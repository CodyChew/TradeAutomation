from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import check_mt5_symbols, load_rates_parquet, pull_mt5_rates, query_mt5_symbol, read_json


@dataclass
class FakeInfo:
    visible: bool = True
    digits: int = 2
    point: float = 0.01
    spread: int = 15
    spread_float: bool = True
    trade_tick_value: float = 1.0
    trade_tick_size: float = 0.01
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    trade_contract_size: float = 100.0


@dataclass
class FakeAccount:
    login: int = 123456
    server: str = "Demo"
    currency: str = "USD"
    leverage: int = 100
    company: str = "Test Broker"


@dataclass
class FakeTerminal:
    name: str = "MetaTrader 5"
    company: str = "MetaQuotes"
    path: str = "C:/MT5"
    data_path: str = "C:/MT5/Data"
    build: int = 9999


class FakeMT5:
    TIMEFRAME_M30 = 30

    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False

    def initialize(self) -> bool:
        self.initialized = True
        return True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self) -> tuple[int, str]:
        return (0, "ok")

    def symbol_info(self, symbol: str) -> FakeInfo | None:
        if symbol == "MISSING":
            return None
        return FakeInfo()

    def symbol_select(self, symbol: str, selected: bool) -> bool:
        del symbol, selected
        return True

    def account_info(self) -> FakeAccount:
        return FakeAccount()

    def terminal_info(self) -> FakeTerminal:
        return FakeTerminal()

    def copy_rates_range(self, symbol: str, timeframe: int, start: datetime, end: datetime):
        del symbol, timeframe, start, end
        return [
            {
                "time": 1767225600,
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "tick_volume": 10,
                "spread": 15,
                "real_volume": 0,
            },
            {
                "time": 1767227400,
                "open": 101.0,
                "high": 103.0,
                "low": 100.0,
                "close": 102.0,
                "tick_volume": 11,
                "spread": 16,
                "real_volume": 0,
            },
        ]


class MT5Tests(unittest.TestCase):
    def test_query_mt5_symbol_returns_metadata(self) -> None:
        result = query_mt5_symbol(FakeMT5(), "xauusd")

        self.assertTrue(result["available"])
        self.assertEqual(result["symbol_metadata"]["symbol"], "XAUUSD")
        self.assertEqual(result["symbol_metadata"]["point"], 0.01)

    def test_check_mt5_symbols_reports_available_and_missing_symbols(self) -> None:
        fake = FakeMT5()

        results = check_mt5_symbols(["xauusd", "missing"], mt5_module=fake)

        self.assertTrue(fake.initialized)
        self.assertTrue(fake.shutdown_called)
        self.assertTrue(results[0].available)
        self.assertEqual(results[0].symbol, "XAUUSD")
        self.assertFalse(results[1].available)
        self.assertEqual(results[1].symbol, "MISSING")

    def test_pull_mt5_rates_writes_candles_and_manifest(self) -> None:
        fake = FakeMT5()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = pull_mt5_rates(
                data_root=temp_dir,
                symbol="xauusd",
                timeframe="30m",
                start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                end=datetime(2026, 1, 2, tzinfo=timezone.utc),
                mt5_module=fake,
            )

            self.assertTrue(fake.initialized)
            self.assertTrue(fake.shutdown_called)
            self.assertEqual(result.symbol, "XAUUSD")
            self.assertEqual(result.timeframe, "M30")
            self.assertEqual(result.rows, 2)
            self.assertTrue(result.data_path.endswith(".parquet"))

            frame = load_rates_parquet(temp_dir, symbol="XAUUSD", timeframe="M30")
            self.assertEqual(len(frame), 2)

            manifest = read_json(result.manifest_path)
            self.assertEqual(manifest["source"], "mt5")
            self.assertEqual(manifest["rows"], 2)
            self.assertEqual(manifest["storage_format"], "parquet")
            self.assertEqual(manifest["account_metadata"]["server"], "Demo")
            self.assertEqual(manifest["symbol_metadata"]["spread_points"], 15)


if __name__ == "__main__":
    unittest.main()
