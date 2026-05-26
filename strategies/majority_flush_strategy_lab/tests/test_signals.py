from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
for src_root in [
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "concepts" / "majority_flush_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from majority_flush_strategy_lab import MajorityFlushSignal, detect_majority_flush_strategy_signals  # noqa: E402


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=len(rows), freq="h", tz="UTC")
    data = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    data.insert(0, "time_utc", [str(item) for item in times])
    return data


def _upside_rows(*, execution_close: float = 15.5, execution_index: int = 9) -> list[tuple[float, float, float, float]]:
    base = [
        (13.0, 16.0, 12.0, 13.5),
        (15.0, 18.0, 13.0, 14.0),
        (14.0, 16.0, 12.0, 13.0),
        (11.0, 15.0, 10.0, 14.0),
        (13.0, 16.0, 11.0, 12.0),
        (12.0, 15.0, 10.0, 11.0),
        (10.0, 12.0, 8.0, 9.0),
        (11.0, 14.0, 9.0, 13.0),
        (13.0, 19.0, 12.0, 18.0),
    ]
    if execution_index == 8:
        base[8] = (13.0, 19.0, 12.0, execution_close)
        return base
    while len(base) < execution_index:
        base.append((18.0, 18.5, 17.2, 18.0))
    base.append((18.0, 18.5, 15.0, execution_close))
    return base


def _downside_rows(*, execution_close: float = 12.5, execution_index: int = 9) -> list[tuple[float, float, float, float]]:
    base = [
        (15.0, 16.0, 14.0, 15.5),
        (13.0, 15.0, 10.0, 14.0),
        (14.0, 15.0, 13.0, 14.5),
        (16.0, 17.0, 14.0, 15.0),
        (13.0, 16.0, 12.0, 15.0),
        (15.0, 17.0, 14.0, 16.0),
        (18.0, 20.0, 16.0, 17.0),
        (19.0, 18.0, 13.0, 14.0),
        (14.0, 15.0, 9.5, 10.5),
    ]
    if execution_index == 8:
        base[8] = (14.0, 15.0, 9.5, execution_close)
        return base
    while len(base) < execution_index:
        base.append((10.0, 10.4, 9.8, 10.0))
    base.append((10.0, 13.0, 9.8, execution_close))
    return base


class MajorityFlushSignalTests(unittest.TestCase):
    def test_public_export_is_available(self) -> None:
        self.assertEqual(MajorityFlushSignal.__name__, "MajorityFlushSignal")

    def test_upside_flush_final_resistance_creates_short_signal(self) -> None:
        signals = detect_majority_flush_strategy_signals(_frame(_upside_rows()), "D1", pivot_strength=1)

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.side, "short")
        self.assertEqual(signal.flush_side, "upside")
        self.assertEqual(signal.lp_side, "resistance")
        self.assertEqual(signal.lp_price, 18.0)
        self.assertEqual(signal.lp_force_index, 8)
        self.assertEqual(signal.execution_index, 9)
        self.assertEqual(signal.bars_from_lp_break, 2)
        self.assertEqual(signal.structure_high, 19.0)
        self.assertEqual(signal.structure_low, 8.0)
        self.assertEqual(signal.forced_lp_count, 2)
        self.assertEqual(signal.to_dict()["lp_price"], 18.0)

    def test_downside_flush_final_support_creates_long_signal(self) -> None:
        signals = detect_majority_flush_strategy_signals(_frame(_downside_rows()), "D1", pivot_strength=1)

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.side, "long")
        self.assertEqual(signal.flush_side, "downside")
        self.assertEqual(signal.lp_side, "support")
        self.assertEqual(signal.lp_price, 10.0)
        self.assertEqual(signal.lp_force_index, 8)
        self.assertEqual(signal.execution_index, 9)
        self.assertEqual(signal.bars_from_lp_break, 2)
        self.assertEqual(signal.structure_high, 20.0)
        self.assertEqual(signal.structure_low, 9.5)
        self.assertEqual(signal.forced_lp_count, 2)

    def test_lp_breaking_candle_counts_as_bar_one(self) -> None:
        signals = detect_majority_flush_strategy_signals(_frame(_upside_rows(execution_close=14.0, execution_index=8)), "D1", pivot_strength=1)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].execution_index, 8)
        self.assertEqual(signals[0].bars_from_lp_break, 1)

    def test_execution_on_bar_seven_is_rejected(self) -> None:
        signals = detect_majority_flush_strategy_signals(_frame(_upside_rows(execution_index=14)), "D1", pivot_strength=1)

        self.assertEqual(signals, [])

    def test_close_equal_to_lp_is_rejected(self) -> None:
        upside = detect_majority_flush_strategy_signals(_frame(_upside_rows(execution_close=18.0)), "D1", pivot_strength=1)
        downside = detect_majority_flush_strategy_signals(_frame(_downside_rows(execution_close=10.0)), "D1", pivot_strength=1)

        self.assertEqual(upside, [])
        self.assertEqual(downside, [])

    def test_wrong_third_close_is_rejected(self) -> None:
        upside = detect_majority_flush_strategy_signals(_frame(_upside_rows(execution_close=17.5)), "D1", pivot_strength=1)
        downside = detect_majority_flush_strategy_signals(_frame(_downside_rows(execution_close=10.4)), "D1", pivot_strength=1)

        self.assertEqual(upside, [])
        self.assertEqual(downside, [])

    def test_empty_frame_returns_no_signals(self) -> None:
        frame = pd.DataFrame(columns=["time_utc", "open", "high", "low", "close"])

        self.assertEqual(detect_majority_flush_strategy_signals(frame, "D1"), [])

    def test_missing_columns_raise_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing columns: close, open"):
            detect_majority_flush_strategy_signals(pd.DataFrame({"time_utc": [], "high": [], "low": []}), "D1")

    def test_invalid_window_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_bars_from_lp_break"):
            detect_majority_flush_strategy_signals(_frame([]), "D1", max_bars_from_lp_break=0)


if __name__ == "__main__":
    unittest.main()
