from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import write_rates_parquet


SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_dataset_fingerprint.py"
SPEC = importlib.util.spec_from_file_location("verify_dataset_fingerprint", SCRIPT_PATH)
fingerprint_script = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(fingerprint_script)


def _m30_frame() -> pd.DataFrame:
    rows = []
    for idx, timestamp in enumerate(pd.date_range("2026-01-01T00:00:00Z", periods=17, freq="30min")):
        open_price = 100.0 + (idx * 0.1)
        rows.append(
            {
                "time_utc": timestamp,
                "open": open_price,
                "high": open_price + 0.07,
                "low": open_price - 0.05,
                "close": open_price + 0.03,
                "tick_volume": 100 + idx,
                "spread_points": 10,
                "real_volume": 0,
            }
        )
    return pd.DataFrame(rows)


def _h4_row(m30: pd.DataFrame, start: str, end: str) -> dict[str, object]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    window = m30[(m30["time_utc"] >= start_ts) & (m30["time_utc"] < end_ts)]
    return {
        "time_utc": start_ts,
        "open": float(window["open"].iloc[0]),
        "high": float(window["high"].max()),
        "low": float(window["low"].min()),
        "close": float(window["close"].iloc[-1]),
        "tick_volume": int(window["tick_volume"].sum()),
        "spread_points": 10,
        "real_volume": 0,
    }


def _write_config(temp_dir: str, data_root: Path) -> Path:
    config_path = Path(temp_dir) / "dataset.json"
    config_path.write_text(
        json.dumps(
            {
                "dataset_name": "unit",
                "data_root": str(data_root),
                "symbols": ["EURUSD"],
                "timeframes": ["M30", "H4"],
            }
        ),
        encoding="utf-8",
    )
    return config_path


class DatasetFingerprintTests(unittest.TestCase):
    def test_verify_succeeds_for_matching_fingerprint_and_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            config_path = _write_config(temp_dir, data_root)
            m30 = _m30_frame()
            h4 = pd.DataFrame(
                [
                    _h4_row(m30, "2026-01-01T00:00:00Z", "2026-01-01T04:00:00Z"),
                    _h4_row(m30, "2026-01-01T04:00:00Z", "2026-01-01T08:00:00Z"),
                ]
            )
            write_rates_parquet(data_root, m30, symbol="EURUSD", timeframe="M30")
            write_rates_parquet(data_root, h4, symbol="EURUSD", timeframe="H4")

            baseline = Path(temp_dir) / "fingerprint.json"
            fingerprint_script._write_json(baseline, fingerprint_script.build_fingerprint([config_path]))
            result = fingerprint_script.verify(
                [config_path],
                baseline,
                aggregation_tolerance=1e-9,
                aggregation_settlement_days=0.0,
            )

            self.assertEqual(result["status"], "OK")
            self.assertEqual(result["fingerprint_dataset_count"], 2)
            self.assertEqual(result["aggregation_checks"][0]["mismatch_count"], 0)

    def test_verify_fails_when_dataset_hash_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            config_path = _write_config(temp_dir, data_root)
            m30 = _m30_frame()
            h4 = pd.DataFrame(
                [
                    _h4_row(m30, "2026-01-01T00:00:00Z", "2026-01-01T04:00:00Z"),
                    _h4_row(m30, "2026-01-01T04:00:00Z", "2026-01-01T08:00:00Z"),
                ]
            )
            write_rates_parquet(data_root, m30, symbol="EURUSD", timeframe="M30")
            write_rates_parquet(data_root, h4, symbol="EURUSD", timeframe="H4")
            baseline = Path(temp_dir) / "fingerprint.json"
            fingerprint_script._write_json(baseline, fingerprint_script.build_fingerprint([config_path]))

            tampered = m30.copy()
            tampered.loc[tampered.index[-1], "close"] += 0.02
            write_rates_parquet(data_root, tampered, symbol="EURUSD", timeframe="M30")

            result = fingerprint_script.verify(
                [config_path],
                baseline,
                aggregation_tolerance=1e-9,
                aggregation_settlement_days=0.0,
            )

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("data_hash_sha256 changed" in failure for failure in result["failures"]))

    def test_aggregation_settlement_window_skips_unsettled_live_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            config_path = _write_config(temp_dir, data_root)
            m30 = _m30_frame()
            h4_rows = [
                _h4_row(m30, "2026-01-01T00:00:00Z", "2026-01-01T04:00:00Z"),
                _h4_row(m30, "2026-01-01T04:00:00Z", "2026-01-01T08:00:00Z"),
            ]
            h4_rows[1]["high"] = float(h4_rows[1]["high"]) + 0.5
            h4 = pd.DataFrame(h4_rows)
            write_rates_parquet(data_root, m30, symbol="EURUSD", timeframe="M30")
            write_rates_parquet(data_root, h4, symbol="EURUSD", timeframe="H4")
            baseline = Path(temp_dir) / "fingerprint.json"
            fingerprint_script._write_json(baseline, fingerprint_script.build_fingerprint([config_path]))

            live_edge_result = fingerprint_script.verify(
                [config_path],
                baseline,
                aggregation_tolerance=1e-9,
                aggregation_settlement_days=0.0,
            )
            settled_result = fingerprint_script.verify(
                [config_path],
                baseline,
                aggregation_tolerance=1e-9,
                aggregation_settlement_days=0.125,
            )

            self.assertEqual(live_edge_result["status"], "FAIL")
            self.assertTrue(any("M30 aggregation mismatches" in failure for failure in live_edge_result["failures"]))
            self.assertEqual(settled_result["status"], "OK")


if __name__ == "__main__":
    unittest.main()
