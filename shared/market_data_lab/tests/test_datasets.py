from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import (
    DatasetConfig,
    dataset_coverage_report,
    load_dataset_config,
    load_rates_parquet,
    pull_mt5_dataset,
    resolve_date_window,
)


@dataclass
class FakeInfo:
    visible: bool = True
    digits: int = 5
    point: float = 0.00001
    spread: int = 10
    spread_float: bool = True
    trade_tick_value: float = 1.0
    trade_tick_size: float = 0.00001
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    trade_contract_size: float = 100000.0


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

    def account_info(self):
        return None

    def terminal_info(self):
        return None

    def copy_rates_range(self, symbol: str, timeframe: int, start: datetime, end: datetime):
        del symbol, timeframe, start, end
        return [
            {
                "time": 1767225600,
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "tick_volume": 10,
                "spread": 10,
                "real_volume": 0,
            },
            {
                "time": 1767227400,
                "open": 1.1005,
                "high": 1.1020,
                "low": 1.1000,
                "close": 1.1010,
                "tick_volume": 11,
                "spread": 11,
                "real_volume": 0,
            },
        ]


class DatasetTests(unittest.TestCase):
    def test_load_dataset_config_resolves_forex_universe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dataset.json"
            path.write_text(
                json.dumps(
                    {
                        "dataset_name": "fx",
                        "data_root": "data/raw/ftmo/forex",
                        "symbol_universe": "forex_major_cross_pairs",
                        "timeframes": ["30m", "4h"],
                        "history_years": 10,
                    }
                ),
                encoding="utf-8",
            )

            config = load_dataset_config(path)

            self.assertEqual(config.dataset_name, "fx")
            self.assertEqual(len(config.symbols), 28)
            self.assertIn("EURUSD", config.symbols)
            self.assertEqual(config.timeframes, ("M30", "H4"))

    def test_resolve_date_window_uses_history_years(self) -> None:
        config = DatasetConfig(
            dataset_name="fx",
            data_root="data/raw",
            symbols=("EURUSD",),
            timeframes=("M30",),
            history_years=10,
        )

        start, end = resolve_date_window(config, now=datetime(2026, 4, 28, tzinfo=timezone.utc))

        self.assertEqual(end.isoformat(), "2026-04-28T00:00:00+00:00")
        self.assertEqual(start.isoformat(), "2016-04-30T00:00:00+00:00")

    def test_pull_mt5_dataset_writes_parquet_and_reports_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = DatasetConfig(
                dataset_name="fx",
                data_root=temp_dir,
                symbols=("EURUSD", "MISSING"),
                timeframes=("M30",),
                date_start_utc="2026-01-01T00:00:00Z",
                date_end_utc="2026-01-02T00:00:00Z",
            )
            fake = FakeMT5()

            results = pull_mt5_dataset(config, mt5_module=fake)

            self.assertTrue(fake.initialized)
            self.assertTrue(fake.shutdown_called)
            self.assertEqual(results[0].status, "ok")
            self.assertEqual(results[0].rows, 2)
            self.assertTrue(str(results[0].data_path).endswith(".parquet"))
            self.assertEqual(results[1].status, "failed")

            frame = load_rates_parquet(temp_dir, symbol="EURUSD", timeframe="M30")
            self.assertEqual(len(frame), 2)

    def test_dataset_coverage_report_marks_ready_when_manifest_covers_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = DatasetConfig(
                dataset_name="fx",
                data_root=temp_dir,
                symbols=("EURUSD",),
                timeframes=("M30",),
                date_start_utc="2026-01-01T00:00:00Z",
                date_end_utc="2026-01-01T00:30:00Z",
            )
            pull_mt5_dataset(config, mt5_module=FakeMT5())

            report = dataset_coverage_report(config)

            self.assertEqual(len(report), 1)
            self.assertTrue(report[0]["data_exists"])
            self.assertTrue(report[0]["coverage_start_ok"])
            self.assertTrue(report[0]["coverage_end_ok"])
            self.assertTrue(report[0]["backtest_ready"])

    def test_dataset_coverage_allows_market_closure_start_boundary_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = DatasetConfig(
                dataset_name="fx",
                data_root=temp_dir,
                symbols=("EURUSD",),
                timeframes=("M30",),
                date_start_utc="2025-12-30T00:00:00Z",
                date_end_utc="2026-01-01T00:30:00Z",
            )
            pull_mt5_dataset(config, mt5_module=FakeMT5())

            wider_request = DatasetConfig(
                dataset_name="fx",
                data_root=temp_dir,
                symbols=("EURUSD",),
                timeframes=("M30",),
                date_start_utc="2025-12-29T00:00:00Z",
                date_end_utc="2026-01-01T00:30:00Z",
            )
            report = dataset_coverage_report(wider_request)

            self.assertEqual(report[0]["boundary_tolerance_hours"], 72.0)
            self.assertTrue(report[0]["coverage_start_ok"])
            self.assertTrue(report[0]["backtest_ready"])


if __name__ == "__main__":
    unittest.main()
