from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import (
    build_dataset_manifest,
    dataset_status,
    load_rates_csv,
    load_rates_parquet,
    manifest_path,
    normalize_rates_frame,
    rates_parquet_path,
    rates_csv_path,
    read_json,
    validate_rates_frame,
    write_dataset_manifest,
    write_rates_csv,
    write_rates_parquet,
)


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


class SchemaStorageTests(unittest.TestCase):
    def test_normalize_rates_frame_from_mt5_raw_schema(self) -> None:
        frame = normalize_rates_frame(_raw_frame(), symbol="xauusd", timeframe="30m")

        self.assertEqual(list(frame["symbol"].unique()), ["XAUUSD"])
        self.assertEqual(list(frame["timeframe"].unique()), ["M30"])
        self.assertIn("spread_points", frame.columns)
        self.assertEqual(float(frame["spread_points"].iloc[0]), 15.0)
        validate_rates_frame(frame, symbol="XAUUSD", timeframe="M30")

    def test_validation_rejects_invalid_ohlc(self) -> None:
        frame = normalize_rates_frame(_raw_frame(), symbol="XAUUSD", timeframe="M30")
        frame.loc[1, "high"] = 99.0

        with self.assertRaisesRegex(ValueError, "invalid high"):
            validate_rates_frame(frame, symbol="XAUUSD", timeframe="M30")

    def test_validation_rejects_wrong_timeframe_spacing(self) -> None:
        raw = _raw_frame()
        raw.loc[2, "time"] = 1767232800
        frame = normalize_rates_frame(raw, symbol="XAUUSD", timeframe="M30")

        with self.assertRaisesRegex(ValueError, "Median bar spacing"):
            validate_rates_frame(frame, symbol="XAUUSD", timeframe="M30")

    def test_write_load_parquet_and_manifest_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = write_rates_parquet(temp_dir, _raw_frame(), symbol="xauusd", timeframe="30m")
            self.assertEqual(data_path, rates_parquet_path(temp_dir, "XAUUSD", "M30"))

            loaded = load_rates_parquet(temp_dir, symbol="XAUUSD", timeframe="M30")
            self.assertEqual(len(loaded), 3)

            manifest = build_dataset_manifest(
                loaded,
                symbol="XAUUSD",
                timeframe="M30",
                source="unit_test",
                data_path=data_path,
                requested_start_utc="2026-01-01T00:00:00Z",
                requested_end_utc="2026-01-01T01:00:00Z",
                symbol_metadata={"point": 0.01},
            )
            manifest_file = write_dataset_manifest(temp_dir, manifest)

            self.assertEqual(manifest_file, manifest_path(temp_dir, "XAUUSD", "M30"))
            saved = read_json(manifest_file)
            self.assertEqual(saved["rows"], 3)
            self.assertEqual(saved["storage_format"], "parquet")
            self.assertEqual(saved["symbol_metadata"]["point"], 0.01)

            status = dataset_status(temp_dir, symbols=["xauusd"], timeframes=["30m"])
            self.assertEqual(status[0]["rows"], 3)
            self.assertTrue(status[0]["data_exists"])
            self.assertTrue(status[0]["parquet_exists"])
            self.assertTrue(status[0]["manifest_exists"])

    def test_write_load_csv_round_trip_for_debug_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = write_rates_csv(temp_dir, _raw_frame(), symbol="xauusd", timeframe="30m")
            self.assertEqual(csv_path, rates_csv_path(temp_dir, "XAUUSD", "M30"))

            loaded = load_rates_csv(temp_dir, symbol="XAUUSD", timeframe="M30")
            self.assertEqual(len(loaded), 3)


if __name__ == "__main__":
    unittest.main()
