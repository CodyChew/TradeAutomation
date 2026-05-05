from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
for src_root in [
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from force_strike_pattern_lab import ForceStrikePattern
from lp_force_strike_strategy_lab import detect_lp_force_strike_signals
from lp_force_strike_strategy_lab.signals import _TrapWindow, _select_matching_window, _window_matches_pattern
from lp_levels_lab import LPBreakEvent


def _frame(rows: list[dict]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(
        [
            {
                "time_utc": times[index],
                "open": row.get("open", (row["high"] + row["low"]) / 2.0),
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
            for index, row in enumerate(rows)
        ]
    )


def _bullish_multiple_support_rows(signal_close: float = 8.0) -> list[dict]:
    return [
        {"high": 10.0, "low": 8.0, "close": 9.0},
        {"high": 9.0, "low": 7.0, "close": 8.0},
        {"high": 8.0, "low": 5.0, "close": 6.0},
        {"high": 9.0, "low": 7.0, "close": 8.0},
        {"high": 10.0, "low": 8.0, "close": 9.0},
        {"high": 8.0, "low": 4.0, "close": 5.0},
        {"high": 9.0, "low": 7.0, "close": 8.0},
        {"high": 10.0, "low": 8.0, "close": 9.0},
        {"high": 9.0, "low": 3.8, "close": 7.0},
        {"high": 8.5, "low": 4.5, "close": 7.0},
        {"high": 8.8, "low": 3.5, "close": signal_close},
    ]


def _bearish_multiple_resistance_rows(signal_close: float = 11.0) -> list[dict]:
    return [
        {"high": 12.0, "low": 8.0, "close": 10.0},
        {"high": 13.0, "low": 9.0, "close": 11.0},
        {"high": 15.0, "low": 10.0, "close": 12.0},
        {"high": 13.0, "low": 9.0, "close": 11.0},
        {"high": 12.0, "low": 8.0, "close": 10.0},
        {"high": 16.0, "low": 10.0, "close": 12.0},
        {"high": 13.0, "low": 9.0, "close": 11.0},
        {"high": 12.0, "low": 8.0, "close": 10.0},
        {"high": 17.0, "low": 10.0, "close": 12.0},
        {"high": 16.5, "low": 10.5, "close": 12.0},
        {"high": 17.2, "low": 10.5, "close": signal_close},
    ]


def _bearish_lp_mother_overlap_rows() -> list[dict]:
    return [
        {"high": 8.0, "low": 5.0, "close": 6.0},
        {"high": 8.5, "low": 5.5, "close": 6.5},
        {"high": 9.2, "low": 6.0, "close": 7.0},
        {"high": 9.4, "low": 6.5, "close": 7.5},
        {"high": 10.0, "low": 8.0, "close": 9.8},
        {"high": 9.8, "low": 8.4, "close": 9.0},
        {"high": 9.7, "low": 8.5, "close": 9.2},
        {"high": 9.8, "low": 8.6, "close": 9.4},
        {"high": 10.2, "low": 8.5, "close": 8.9},
    ]


def _lp_break(side: str, price: float, break_index: int) -> LPBreakEvent:
    break_time = pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(hours=break_index)
    return LPBreakEvent(
        side=side,  # type: ignore[arg-type]
        price=price,
        pivot_index=max(0, break_index - 3),
        pivot_time_utc=break_time - pd.Timedelta(hours=3),
        confirmed_index=max(0, break_index - 1),
        confirmed_time_utc=break_time - pd.Timedelta(hours=1),
        break_index=break_index,
        break_time_utc=break_time,
    )


def _pattern(*, mother_index: int, signal_index: int) -> ForceStrikePattern:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=20, freq="h", tz="UTC")
    return ForceStrikePattern(
        side="bearish",
        direction=-1,
        mother_index=mother_index,
        signal_index=signal_index,
        mother_time_utc=times[mother_index],
        signal_time_utc=times[signal_index],
        mother_high=10.0,
        mother_low=8.0,
        structure_high=10.2,
        structure_low=8.0,
        total_bars=signal_index - mother_index + 1,
        breakout_side="above_mother_high",
    )


class LPForceStrikeSignalTests(unittest.TestCase):
    def test_bullish_force_bottom_uses_lowest_broken_support(self) -> None:
        signals = detect_lp_force_strike_signals(_frame(_bullish_multiple_support_rows()), "M30", pivot_strength=2)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].side, "bullish")
        self.assertEqual(signals[0].scenario, "force_bottom")
        self.assertEqual(signals[0].lp_price, 4.0)
        self.assertEqual(signals[0].lp_break_index, 8)
        self.assertEqual(signals[0].fs_signal_index, 10)
        self.assertEqual(signals[0].bars_from_lp_break, 3)

    def test_bearish_force_top_uses_highest_broken_resistance(self) -> None:
        signals = detect_lp_force_strike_signals(_frame(_bearish_multiple_resistance_rows()), "M30", pivot_strength=2)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].side, "bearish")
        self.assertEqual(signals[0].scenario, "force_top")
        self.assertEqual(signals[0].lp_price, 16.0)
        self.assertEqual(signals[0].lp_break_index, 8)
        self.assertEqual(signals[0].fs_signal_index, 10)
        self.assertEqual(signals[0].bars_from_lp_break, 3)

    def test_bullish_active_window_uses_lowest_support_not_latest_break(self) -> None:
        older_extreme = _TrapWindow("bullish", "force_bottom", _lp_break("support", 1.08, 5))
        newer_non_extreme = _TrapWindow("bullish", "force_bottom", _lp_break("support", 1.10, 8))

        selected = _select_matching_window([older_extreme, newer_non_extreme])

        self.assertIs(selected, older_extreme)

    def test_bearish_active_window_uses_highest_resistance_not_latest_break(self) -> None:
        older_extreme = _TrapWindow("bearish", "force_top", _lp_break("resistance", 1.12, 5))
        newer_non_extreme = _TrapWindow("bearish", "force_top", _lp_break("resistance", 1.10, 8))

        selected = _select_matching_window([older_extreme, newer_non_extreme])

        self.assertIs(selected, older_extreme)

    def test_active_window_extreme_tie_uses_latest_break(self) -> None:
        earlier = _TrapWindow("bearish", "force_top", _lp_break("resistance", 1.12, 5))
        later = _TrapWindow("bearish", "force_top", _lp_break("resistance", 1.12, 8))

        selected = _select_matching_window([earlier, later])

        self.assertIs(selected, later)

    def test_active_window_selector_validates_non_empty_matches(self) -> None:
        with self.assertRaisesRegex(ValueError, "matches"):
            _select_matching_window([])

    def test_force_strike_signal_must_be_inside_six_bar_window(self) -> None:
        signals = detect_lp_force_strike_signals(
            _frame(_bullish_multiple_support_rows()),
            "M30",
            pivot_strength=2,
            max_bars_from_lp_break=2,
        )

        self.assertEqual(signals, [])

    def test_bullish_exe_candle_must_close_at_or_above_selected_support(self) -> None:
        rows = [
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 8.0, "low": 6.0, "close": 7.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 8.0, "close": 8.5},
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 8.0, "close": 8.5},
            {"high": 8.0, "low": 5.0, "close": 7.0},
            {"high": 7.5, "low": 5.5, "close": 7.0},
            {"high": 6.1, "low": 4.8, "close": 5.8},
        ]

        signals = detect_lp_force_strike_signals(_frame(rows), "M30", pivot_strength=2)

        self.assertEqual(signals, [])

    def test_bearish_exe_candle_must_close_at_or_below_selected_resistance(self) -> None:
        signals = detect_lp_force_strike_signals(
            _frame(_bearish_multiple_resistance_rows(signal_close=16.2)),
            "M30",
            pivot_strength=2,
        )

        self.assertEqual(signals, [])

    def test_detector_requires_no_sma_atr_or_context_columns(self) -> None:
        frame = _frame(_bullish_multiple_support_rows())

        signals = detect_lp_force_strike_signals(frame, "M30", pivot_strength=2)

        self.assertEqual(len(signals), 1)

    def test_validates_max_bars_from_lp_break(self) -> None:
        with self.assertRaises(ValueError):
            detect_lp_force_strike_signals(_frame([]), "M30", max_bars_from_lp_break=0)

    def test_default_detector_rejects_lp_pivot_as_force_strike_mother(self) -> None:
        signals = detect_lp_force_strike_signals(
            _frame(_bearish_lp_mother_overlap_rows()),
            "M30",
            pivot_strength=2,
        )

        self.assertEqual(signals, [])

    def test_explicit_legacy_policy_allows_lp_pivot_as_force_strike_mother(self) -> None:
        signals = detect_lp_force_strike_signals(
            _frame(_bearish_lp_mother_overlap_rows()),
            "M30",
            pivot_strength=2,
            require_lp_pivot_before_fs_mother=False,
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].lp_pivot_index, signals[0].fs_mother_index)

    def test_usdchf_like_lp_mother_overlap_rejected_by_default_but_available_to_legacy_control(self) -> None:
        default = detect_lp_force_strike_signals(
            _frame(_bearish_lp_mother_overlap_rows()),
            "M30",
            pivot_strength=2,
        )
        legacy = detect_lp_force_strike_signals(
            _frame(_bearish_lp_mother_overlap_rows()),
            "M30",
            pivot_strength=2,
            require_lp_pivot_before_fs_mother=False,
        )

        self.assertEqual(default, [])
        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy[0].lp_pivot_index, legacy[0].fs_mother_index)

    def test_separation_policy_rejects_lp_pivot_inside_force_strike_formation(self) -> None:
        window = _TrapWindow("bearish", "force_top", _lp_break("resistance", 10.0, 8))
        inside_pivot = _TrapWindow(
            window.side,
            window.scenario,
            LPBreakEvent(
                side=window.lp_event.side,
                price=window.lp_event.price,
                pivot_index=6,
                pivot_time_utc=window.lp_event.pivot_time_utc,
                confirmed_index=7,
                confirmed_time_utc=window.lp_event.confirmed_time_utc,
                break_index=window.lp_event.break_index,
                break_time_utc=window.lp_event.break_time_utc,
            ),
        )

        self.assertFalse(
            _window_matches_pattern(
                inside_pivot,
                _pattern(mother_index=4, signal_index=8),
                signal_close=9.0,
                max_bars_from_lp_break=6,
                require_lp_pivot_before_fs_mother=True,
            )
        )

    def test_separation_policy_accepts_lp_pivot_before_force_strike_mother(self) -> None:
        event = _lp_break("resistance", 10.0, 8)
        window = _TrapWindow(
            "bearish",
            "force_top",
            LPBreakEvent(
                side=event.side,
                price=event.price,
                pivot_index=3,
                pivot_time_utc=event.pivot_time_utc,
                confirmed_index=event.confirmed_index,
                confirmed_time_utc=event.confirmed_time_utc,
                break_index=event.break_index,
                break_time_utc=event.break_time_utc,
            ),
        )

        self.assertTrue(
            _window_matches_pattern(
                window,
                _pattern(mother_index=4, signal_index=8),
                signal_close=9.0,
                max_bars_from_lp_break=6,
                require_lp_pivot_before_fs_mother=True,
            )
        )

    def test_window_match_rejects_force_strike_outside_break_window(self) -> None:
        window = _TrapWindow("bearish", "force_top", _lp_break("resistance", 10.0, 8))

        self.assertFalse(
            _window_matches_pattern(
                window,
                _pattern(mother_index=4, signal_index=19),
                signal_close=9.0,
                max_bars_from_lp_break=6,
                require_lp_pivot_before_fs_mother=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
