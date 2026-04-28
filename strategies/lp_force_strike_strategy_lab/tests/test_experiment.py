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

from lp_force_strike_strategy_lab import (  # noqa: E402
    LPForceStrikeSignal,
    SkippedTrade,
    TradeModelCandidate,
    build_trade_setup,
    make_trade_model_candidates,
    run_lp_force_strike_experiment_on_frame,
    summary_rows,
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(
        [
            {
                "time_utc": times[index],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "spread_points": row.get("spread_points", 0.0),
                "point": row.get("point", 0.01),
            }
            for index, row in enumerate(rows)
        ]
    )


def _signal(side: str = "bullish") -> LPForceStrikeSignal:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=10, freq="h", tz="UTC")
    return LPForceStrikeSignal(
        side=side,  # type: ignore[arg-type]
        scenario="force_bottom" if side == "bullish" else "force_top",
        lp_price=95.0 if side == "bullish" else 105.0,
        lp_break_index=3,
        lp_break_time_utc=times[3],
        lp_pivot_index=1,
        lp_pivot_time_utc=times[1],
        fs_mother_index=4,
        fs_signal_index=6,
        fs_mother_time_utc=times[4],
        fs_signal_time_utc=times[6],
        bars_from_lp_break=4,
        fs_total_bars=3,
    )


class LPForceStrikeExperimentTests(unittest.TestCase):
    def test_make_trade_model_candidates_crosses_entry_stop_and_targets(self) -> None:
        candidates = make_trade_model_candidates(
            entry_models=["next_open", "signal_midpoint_pullback"],
            stop_models=["fs_structure", "fs_structure_max_atr"],
            target_rs=[1.0, 1.5],
            max_risk_atrs=[1.0],
        )

        self.assertEqual(len(candidates), 8)
        self.assertIn("next_open__fs_structure__1r", [candidate.candidate_id for candidate in candidates])
        self.assertIn(
            "signal_midpoint_pullback__fs_structure_max_1atr__1p5r",
            [candidate.candidate_id for candidate in candidates],
        )

    def test_next_open_candidate_builds_setup_from_next_candle_open(self) -> None:
        frame = _frame(
            [
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 104, "low": 96, "close": 101},
                {"open": 101, "high": 103, "low": 97, "close": 100},
                {"open": 100, "high": 106, "low": 94, "close": 104},
                {"open": 103, "high": 108, "low": 102, "close": 106},
            ]
        )
        candidate = TradeModelCandidate("next", "next_open", "fs_structure", 1.5)

        setup = build_trade_setup(frame, _signal("bullish"), candidate, symbol="TEST", timeframe="M30", atr_period=1)

        self.assertNotIsInstance(setup, SkippedTrade)
        assert not isinstance(setup, SkippedTrade)
        self.assertEqual(setup.entry_index, 7)
        self.assertEqual(setup.entry_price, 103)
        self.assertEqual(setup.stop_price, 94)
        self.assertEqual(setup.target_price, 116.5)

    def test_signal_midpoint_pullback_uses_signal_candle_midpoint(self) -> None:
        frame = _frame(
            [
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 104, "low": 96, "close": 101},
                {"open": 101, "high": 103, "low": 97, "close": 100},
                {"open": 100, "high": 106, "low": 94, "close": 104},
                {"open": 105, "high": 107, "low": 99, "close": 104},
            ]
        )
        candidate = TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0)

        setup = build_trade_setup(frame, _signal("bullish"), candidate, symbol="TEST", timeframe="M30", atr_period=1)

        self.assertNotIsInstance(setup, SkippedTrade)
        assert not isinstance(setup, SkippedTrade)
        self.assertEqual(setup.entry_index, 7)
        self.assertEqual(setup.entry_price, 100.0)

    def test_signal_midpoint_pullback_skips_when_entry_not_reached(self) -> None:
        frame = _frame(
            [
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 104, "low": 96, "close": 101},
                {"open": 101, "high": 103, "low": 97, "close": 100},
                {"open": 100, "high": 106, "low": 94, "close": 104},
                {"open": 105, "high": 108, "low": 101, "close": 106},
            ]
        )
        candidate = TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0)

        skipped = build_trade_setup(frame, _signal("bullish"), candidate, symbol="TEST", timeframe="M30", atr_period=1)

        self.assertIsInstance(skipped, SkippedTrade)
        assert isinstance(skipped, SkippedTrade)
        self.assertEqual(skipped.reason, "entry_not_reached")

    def test_structure_max_atr_skips_when_risk_too_wide(self) -> None:
        frame = _frame(
            [
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 104, "low": 80, "close": 101},
                {"open": 101, "high": 103, "low": 97, "close": 100},
                {"open": 100, "high": 106, "low": 94, "close": 104},
                {"open": 103, "high": 108, "low": 102, "close": 106},
            ]
        )
        candidate = TradeModelCandidate("wide", "next_open", "fs_structure_max_atr", 1.0, max_risk_atr=0.5)

        skipped = build_trade_setup(frame, _signal("bullish"), candidate, symbol="TEST", timeframe="M30", atr_period=1)

        self.assertIsInstance(skipped, SkippedTrade)
        assert isinstance(skipped, SkippedTrade)
        self.assertEqual(skipped.reason, "risk_too_wide")

    def test_experiment_runs_detected_signal_and_summarizes_trade(self) -> None:
        rows = [
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
            {"high": 8.8, "low": 3.5, "close": 8.0},
            {"high": 9.5, "low": 7.5, "close": 9.0},
            {"high": 12.0, "low": 8.0, "close": 11.0},
        ]
        frame = _frame(
            [
                {"open": row.get("open", (row["high"] + row["low"]) / 2.0), "high": row["high"], "low": row["low"], "close": row["close"]}
                for row in rows
            ]
        )
        candidates = [TradeModelCandidate("base", "next_open", "fs_structure", 1.0)]

        result = run_lp_force_strike_experiment_on_frame(
            frame,
            symbol="TEST",
            timeframe="M30",
            candidates=candidates,
            pivot_strength=2,
            atr_period=1,
        )
        summaries = summary_rows(result.trades, group_fields=["candidate_id", "timeframe"])

        self.assertEqual(len(result.signals), 1)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(summaries[0]["trades"], 1)


if __name__ == "__main__":
    unittest.main()
