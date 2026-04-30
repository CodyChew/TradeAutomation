from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import (  # noqa: E402
    DatasetConfig,
    DatasetPullItem,
    MT5PullResult,
    MT5SymbolAvailability,
    check_mt5_symbols,
    dataset_coverage_report,
    load_dataset_config,
    load_rates_csv,
    load_rates_parquet,
    mt5_timeframe_value,
    normalize_rates_frame,
    normalize_timeframe,
    pull_mt5_dataset,
    pull_mt5_rates,
    pull_symbol_rates,
    validate_rates_frame,
)
from market_data_lab.datasets import _load_mt5_module as load_dataset_mt5_module  # noqa: E402
from market_data_lab.mt5 import _load_mt5_module as load_mt5_module, ensure_symbol, symbol_metadata  # noqa: E402
from market_data_lab.storage import _iso_or_none  # noqa: E402


def _raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [1767225600, 1767227400, 1767229200],
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "tick_volume": [10, 11, 12],
            "spread": [15, 16, 15],
            "real_volume": [0, 0, 0],
        }
    )


def _canonical_frame() -> pd.DataFrame:
    return normalize_rates_frame(_raw_frame(), symbol="EURUSD", timeframe="M30")


@dataclass
class InvisibleInfo:
    visible: bool = False
    digits: object = None
    point: object = None
    spread: object = None


class InitFailsMT5:
    TIMEFRAME_M30 = 30

    def initialize(self) -> bool:
        return False

    def last_error(self) -> tuple[int, str]:
        return (500, "init failed")

    def shutdown(self) -> None:
        pass


class SelectFailsMT5:
    def symbol_info(self, symbol: str) -> InvisibleInfo:
        del symbol
        return InvisibleInfo()

    def symbol_select(self, symbol: str, selected: bool) -> bool:
        del symbol, selected
        return False

    def last_error(self) -> tuple[int, str]:
        return (501, "select failed")


class CopyFailsMT5:
    TIMEFRAME_M30 = 30

    def copy_rates_range(self, symbol: str, timeframe: int, start: datetime, end: datetime):
        del symbol, timeframe, start, end
        return None

    def last_error(self) -> tuple[int, str]:
        return (502, "copy failed")


class MarketDataEdgeCaseTests(unittest.TestCase):
    def test_dataclasses_and_metadata_defaults_are_serializable(self) -> None:
        pull = MT5PullResult("EURUSD", "M30", 1, "data.parquet", "manifest.json")
        availability = MT5SymbolAvailability("EURUSD", True)

        self.assertEqual(pull.to_dict()["rows"], 1)
        self.assertTrue(availability.to_dict()["available"])
        self.assertEqual(symbol_metadata(object(), "eurusd")["point"], 0.0)

    def test_dataset_config_validation_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dataset.json"

            path.write_text(json.dumps({"symbol_universe": "unknown", "timeframes": ["M30"]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported symbol_universe"):
                load_dataset_config(path)

            path.write_text(json.dumps({"timeframes": ["M30"]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "symbols or symbol_universe"):
                load_dataset_config(path)

            path.write_text(json.dumps({"symbols": ["EURUSD"]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least one timeframe"):
                load_dataset_config(path)

    def test_dataset_window_and_coverage_edges(self) -> None:
        config = DatasetConfig(
            "fx",
            "data/raw",
            ("EURUSD",),
            ("M30",),
            date_start_utc="2026-01-02T00:00:00Z",
            date_end_utc="2026-01-01T00:00:00Z",
        )
        with self.assertRaisesRegex(ValueError, "later than"):
            from market_data_lab import resolve_date_window

            resolve_date_window(config)

        naive_config = DatasetConfig("fx", "data/raw", ("EURUSD",), ("M30",), history_years=1)
        from market_data_lab import resolve_date_window

        start, end = resolve_date_window(naive_config, now=datetime(2026, 1, 1))
        self.assertEqual(end.tzinfo, timezone.utc)
        self.assertEqual((end - start).days, 365)

        with tempfile.TemporaryDirectory() as temp_dir:
            missing_config = DatasetConfig(
                "fx",
                temp_dir,
                ("EURUSD",),
                ("W1",),
                date_start_utc="2026-01-01T00:00:00Z",
                date_end_utc="2026-01-08T00:00:00Z",
            )
            report = dataset_coverage_report(missing_config)

            self.assertEqual(report[0]["boundary_tolerance_hours"], 168.0)
            self.assertFalse(report[0]["coverage_start_ok"])
            self.assertFalse(report[0]["coverage_end_ok"])
            self.assertFalse(report[0]["backtest_ready"])

    def test_mt5_module_loading_and_initialization_edges(self) -> None:
        fake_module = types.SimpleNamespace(marker="fake")
        original = sys.modules.get("MetaTrader5")
        sys.modules["MetaTrader5"] = fake_module
        try:
            self.assertIs(load_mt5_module(None), fake_module)
            self.assertIs(load_dataset_mt5_module(None), fake_module)
        finally:
            if original is None:
                sys.modules.pop("MetaTrader5", None)
            else:
                sys.modules["MetaTrader5"] = original

        with self.assertRaisesRegex(RuntimeError, "initialize failed"):
            check_mt5_symbols(["EURUSD"], mt5_module=InitFailsMT5())

        with self.assertRaisesRegex(RuntimeError, "initialize failed"):
            pull_mt5_rates(
                data_root="data/raw",
                symbol="EURUSD",
                timeframe="M30",
                start="2026-01-01T00:00:00Z",
                end="2026-01-01T01:00:00Z",
                mt5_module=InitFailsMT5(),
            )

    def test_mt5_pull_failure_edges(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "symbol_select failed"):
            ensure_symbol(SelectFailsMT5(), "EURUSD")

        with self.assertRaisesRegex(ValueError, "end must be later"):
            pull_symbol_rates(CopyFailsMT5(), symbol="EURUSD", timeframe="M30", start="2026-01-02", end="2026-01-01")

        with self.assertRaisesRegex(RuntimeError, "copy_rates_range failed"):
            pull_symbol_rates(CopyFailsMT5(), symbol="EURUSD", timeframe="M30", start="2026-01-01", end="2026-01-02")

        with self.assertRaisesRegex(ValueError, "Only source"):
            pull_mt5_dataset(DatasetConfig("fx", "data/raw", ("EURUSD",), ("M30",), source="csv"), mt5_module=InitFailsMT5())

        with self.assertRaisesRegex(RuntimeError, "initialize failed"):
            pull_mt5_dataset(DatasetConfig("fx", "data/raw", ("EURUSD",), ("M30",)), mt5_module=InitFailsMT5())

    def test_schema_validation_edges(self) -> None:
        with self.assertRaisesRegex(ValueError, "either time_utc or time"):
            normalize_rates_frame(pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]}), symbol="EURUSD", timeframe="M30")

        with self.assertRaisesRegex(ValueError, "required OHLC"):
            normalize_rates_frame(pd.DataFrame({"time": [1767225600], "high": [1], "low": [1], "close": [1]}), symbol="EURUSD", timeframe="M30")

        minimal = pd.DataFrame(
            {
                "time_utc": ["2026-01-01T00:00:00Z"],
                "open": [1.0],
                "high": [1.1],
                "low": [0.9],
                "close": [1.0],
            }
        )
        normalized = normalize_rates_frame(minimal, symbol="eurusd", timeframe="M30")
        self.assertTrue(normalized[["tick_volume", "spread_points", "real_volume"]].isna().all().all())
        validate_rates_frame(normalized, symbol="EURUSD", timeframe="M30")

        with self.assertRaisesRegex(ValueError, "missing columns"):
            validate_rates_frame(normalized.drop(columns=["real_volume"]), symbol="EURUSD", timeframe="M30")

        with self.assertRaisesRegex(ValueError, "No rows"):
            validate_rates_frame(normalized.iloc[0:0], symbol="EURUSD", timeframe="M30")

        wrong_symbol = _canonical_frame()
        wrong_symbol.loc[0, "symbol"] = "GBPUSD"
        with self.assertRaisesRegex(ValueError, "symbols other than"):
            validate_rates_frame(wrong_symbol, symbol="EURUSD", timeframe="M30")

        wrong_timeframe = _canonical_frame()
        wrong_timeframe.loc[0, "timeframe"] = "H4"
        with self.assertRaisesRegex(ValueError, "timeframes other than"):
            validate_rates_frame(wrong_timeframe, symbol="EURUSD", timeframe="M30")

        duplicate = _canonical_frame()
        duplicate.loc[1, "time_utc"] = duplicate.loc[0, "time_utc"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_rates_frame(duplicate, symbol="EURUSD", timeframe="M30")

        unsorted = _canonical_frame().iloc[[1, 0, 2]].reset_index(drop=True)
        with self.assertRaisesRegex(ValueError, "increasing"):
            validate_rates_frame(unsorted, symbol="EURUSD", timeframe="M30")

        non_numeric = _canonical_frame()
        non_numeric["close"] = non_numeric["close"].astype(object)
        non_numeric.loc[1, "close"] = "bad"
        with self.assertRaisesRegex(ValueError, "non-numeric close"):
            validate_rates_frame(non_numeric, symbol="EURUSD", timeframe="M30")

        invalid_low = _canonical_frame()
        invalid_low.loc[1, "high"] = 106.0
        invalid_low.loc[1, "low"] = 105.0
        with self.assertRaisesRegex(ValueError, "invalid low"):
            validate_rates_frame(invalid_low, symbol="EURUSD", timeframe="M30")

        negative_volume = _canonical_frame()
        negative_volume.loc[1, "tick_volume"] = -1
        with self.assertRaisesRegex(ValueError, "negative tick_volume"):
            validate_rates_frame(negative_volume, symbol="EURUSD", timeframe="M30")

    def test_storage_and_timeframe_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                load_rates_csv(temp_dir, symbol="EURUSD", timeframe="M30")
            with self.assertRaises(FileNotFoundError):
                load_rates_parquet(temp_dir, symbol="EURUSD", timeframe="M30")

        self.assertIsNone(_iso_or_none(None))
        self.assertIsNone(_iso_or_none(pd.NA))
        self.assertIsNone(_iso_or_none(pd.NaT))
        self.assertEqual(_iso_or_none("2026-01-01T00:00:00"), "2026-01-01T00:00:00+00:00")

        self.assertEqual(normalize_timeframe(30), "M30")
        with self.assertRaisesRegex(ValueError, "non-integer"):
            normalize_timeframe(30.5)
        with self.assertRaisesRegex(ValueError, "Unsupported timeframe"):
            normalize_timeframe("Q1")
        with self.assertRaisesRegex(ValueError, "does not expose"):
            mt5_timeframe_value(types.SimpleNamespace(), "M30")

    def test_dataset_pull_stop_on_error_reraises(self) -> None:
        class MissingSymbolMT5(InitFailsMT5):
            def initialize(self) -> bool:
                return True

            def symbol_info(self, symbol: str):
                del symbol
                return None

            def account_info(self):
                return None

            def terminal_info(self):
                return None

        config = DatasetConfig(
            "fx",
            "data/raw",
            ("MISSING",),
            ("M30",),
            date_start_utc="2026-01-01T00:00:00Z",
            date_end_utc="2026-01-02T00:00:00Z",
        )
        with self.assertRaisesRegex(RuntimeError, "symbol_info unavailable"):
            pull_mt5_dataset(config, mt5_module=MissingSymbolMT5(), stop_on_error=True)

        item = DatasetPullItem("EURUSD", "M30", "failed", error="boom")
        self.assertEqual(item.to_dict()["error"], "boom")


if __name__ == "__main__":
    unittest.main()
