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
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from majority_flush_strategy_lab import (  # noqa: E402
    SkippedTrade,
    TradeModelCandidate,
    baseline_candidate,
    build_trade_setup,
    run_majority_flush_experiment_on_frame,
    summary_rows,
    trade_report_row,
)
from majority_flush_strategy_lab.experiment import _max_closed_trade_drawdown  # noqa: E402
from majority_flush_strategy_lab.signals import MajorityFlushSignal  # noqa: E402


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=len(rows), freq="h", tz="UTC")
    data = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    data.insert(0, "time_utc", [str(item) for item in times])
    data["spread_points"] = 0.0
    data["point"] = 0.01
    return data


def _signal(side: str = "long", *, execution_index: int = 3, structure_low: float = 9.0, structure_high: float = 15.0) -> MajorityFlushSignal:
    times = pd.date_range("2026-01-01", periods=12, freq="h", tz="UTC")
    return MajorityFlushSignal(
        side=side,  # type: ignore[arg-type]
        flush_side="downside" if side == "long" else "upside",
        lp_side="support" if side == "long" else "resistance",
        lp_price=10.0 if side == "long" else 14.0,
        lp_pivot_index=1,
        lp_pivot_time_utc=times[1],
        lp_force_index=2,
        lp_force_time_utc=times[2],
        origin_index=0,
        origin_time_utc=times[0],
        origin_price=16.0 if side == "long" else 8.0,
        flush_start_index=1,
        flush_start_time_utc=times[1],
        flush_start_price=15.0 if side == "long" else 9.0,
        execution_index=execution_index,
        execution_time_utc=times[execution_index],
        bars_from_lp_break=execution_index - 1,
        execution_open=10.0,
        execution_high=12.0,
        execution_low=9.0,
        execution_close=11.5,
        leg_high=16.0,
        leg_low=9.0,
        structure_high=structure_high,
        structure_low=structure_low,
        forced_lp_count=1,
    )


def _upside_rows() -> list[tuple[float, float, float, float]]:
    return [
        (13.0, 16.0, 12.0, 13.5),
        (15.0, 18.0, 13.0, 14.0),
        (14.0, 16.0, 12.0, 13.0),
        (11.0, 15.0, 10.0, 14.0),
        (13.0, 16.0, 11.0, 12.0),
        (12.0, 15.0, 10.0, 11.0),
        (10.0, 12.0, 8.0, 9.0),
        (11.0, 14.0, 9.0, 13.0),
        (13.0, 19.0, 12.0, 18.0),
        (18.0, 18.5, 15.0, 15.5),
        (15.2, 16.0, 13.0, 14.0),
        (14.0, 14.5, 10.0, 12.0),
    ]


class MajorityFlushExperimentTests(unittest.TestCase):
    def test_baseline_candidate_matches_v1_contract(self) -> None:
        candidate = baseline_candidate()

        self.assertEqual(candidate.candidate_id, "next_open__flush_structure__1r")
        self.assertEqual(candidate.entry_model, "next_open")
        self.assertEqual(candidate.stop_model, "flush_structure")
        self.assertEqual(candidate.target_r, 1.0)

    def test_build_trade_setup_uses_next_open_flush_structure_stop_and_1r_target(self) -> None:
        frame = _frame(
            [
                (10.0, 12.0, 9.0, 11.0),
                (11.0, 13.0, 9.5, 12.0),
                (12.0, 14.0, 9.2, 13.0),
                (13.0, 15.0, 9.1, 14.0),
                (11.0, 14.0, 10.0, 13.0),
            ]
        )

        setup = build_trade_setup(frame, _signal("long", execution_index=3, structure_low=9.0), baseline_candidate(), symbol="TEST", timeframe="H4")

        self.assertNotIsInstance(setup, SkippedTrade)
        assert not isinstance(setup, SkippedTrade)
        self.assertEqual(setup.side, "long")
        self.assertEqual(setup.entry_index, 4)
        self.assertEqual(setup.entry_price, 11.0)
        self.assertEqual(setup.stop_price, 9.0)
        self.assertEqual(setup.target_price, 13.0)
        self.assertEqual(setup.metadata["candidate_id"], "next_open__flush_structure__1r")

    def test_short_trade_setup_uses_structure_high_stop(self) -> None:
        frame = _frame(
            [
                (14.0, 15.0, 10.0, 11.0),
                (13.0, 16.0, 11.0, 12.0),
                (12.0, 17.0, 11.0, 13.0),
                (13.0, 18.0, 12.0, 13.0),
                (16.0, 17.0, 14.0, 15.0),
            ]
        )

        setup = build_trade_setup(frame, _signal("short", execution_index=3, structure_high=18.0), baseline_candidate(), symbol="TEST", timeframe="H4")

        self.assertNotIsInstance(setup, SkippedTrade)
        assert not isinstance(setup, SkippedTrade)
        self.assertEqual(setup.side, "short")
        self.assertEqual(setup.entry_price, 16.0)
        self.assertEqual(setup.stop_price, 18.0)
        self.assertEqual(setup.target_price, 14.0)

    def test_no_next_candle_after_execution_is_skipped(self) -> None:
        skipped = build_trade_setup(_frame([(10.0, 12.0, 9.0, 11.0)] * 4), _signal(execution_index=3), baseline_candidate(), symbol="TEST", timeframe="H4")

        self.assertIsInstance(skipped, SkippedTrade)
        assert isinstance(skipped, SkippedTrade)
        self.assertEqual(skipped.reason, "no_next_candle")
        self.assertEqual(skipped.to_dict()["reason"], "no_next_candle")

    def test_invalid_stop_distance_is_skipped(self) -> None:
        frame = _frame(
            [
                (10.0, 12.0, 9.0, 11.0),
                (10.0, 12.0, 9.0, 11.0),
                (10.0, 12.0, 9.0, 11.0),
                (10.0, 12.0, 9.0, 11.0),
                (8.0, 12.0, 7.0, 11.0),
            ]
        )

        skipped = build_trade_setup(frame, _signal("long", execution_index=3, structure_low=9.0), baseline_candidate(), symbol="TEST", timeframe="H4")

        self.assertIsInstance(skipped, SkippedTrade)
        assert isinstance(skipped, SkippedTrade)
        self.assertEqual(skipped.reason, "invalid_stop")
        self.assertIn("risk=-1", skipped.detail)

    def test_unsupported_candidate_settings_are_skipped(self) -> None:
        frame = _frame([(10.0, 12.0, 9.0, 11.0)] * 5)

        unsupported_entry = build_trade_setup(
            frame,
            _signal(),
            TradeModelCandidate("bad_entry", "bad", "flush_structure", 1.0),  # type: ignore[arg-type]
            symbol="TEST",
            timeframe="H4",
        )
        unsupported_stop = build_trade_setup(
            frame,
            _signal(),
            TradeModelCandidate("bad_stop", "next_open", "bad", 1.0),  # type: ignore[arg-type]
            symbol="TEST",
            timeframe="H4",
        )
        invalid_target = build_trade_setup(
            frame,
            _signal(),
            TradeModelCandidate("bad_target", "next_open", "flush_structure", 0.0),
            symbol="TEST",
            timeframe="H4",
        )

        self.assertIsInstance(unsupported_entry, SkippedTrade)
        self.assertIsInstance(unsupported_stop, SkippedTrade)
        self.assertIsInstance(invalid_target, SkippedTrade)
        assert isinstance(unsupported_entry, SkippedTrade)
        assert isinstance(unsupported_stop, SkippedTrade)
        assert isinstance(invalid_target, SkippedTrade)
        self.assertEqual(unsupported_entry.reason, "unsupported_entry_model")
        self.assertEqual(unsupported_stop.reason, "unsupported_stop_model")
        self.assertEqual(invalid_target.reason, "invalid_target_r")

    def test_run_experiment_simulates_detected_majority_flush_trade(self) -> None:
        result = run_majority_flush_experiment_on_frame(
            _frame(_upside_rows()),
            symbol="TEST",
            timeframe="D1",
            pivot_strength=1,
        )

        self.assertEqual(len(result.signals), 1)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.skipped, [])
        trade = result.trades[0]
        self.assertEqual(trade.side, "short")
        self.assertEqual(trade.entry_index, 10)
        self.assertEqual(trade.entry_reference_price, 15.2)
        self.assertEqual(trade.stop_price, 19.0)
        self.assertAlmostEqual(trade.target_price, 11.4)
        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.metadata["lp_price"], 18.0)

    def test_run_experiment_accepts_explicit_candidates(self) -> None:
        candidate = TradeModelCandidate("explicit", "next_open", "flush_structure", 1.0)

        result = run_majority_flush_experiment_on_frame(
            _frame(_upside_rows()),
            symbol="TEST",
            timeframe="D1",
            candidates=[candidate],
            pivot_strength=1,
        )

        self.assertEqual(result.candidates, [candidate])
        self.assertEqual(result.trades[0].metadata["candidate_id"], "explicit")

    def test_run_experiment_records_skipped_candidates(self) -> None:
        candidate = TradeModelCandidate("invalid", "next_open", "flush_structure", 0.0)

        result = run_majority_flush_experiment_on_frame(
            _frame(_upside_rows()),
            symbol="TEST",
            timeframe="D1",
            candidates=[candidate],
            pivot_strength=1,
        )

        self.assertEqual(result.trades, [])
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0].reason, "invalid_target_r")

    def test_trade_report_row_and_summary_rows_flatten_metadata(self) -> None:
        result = run_majority_flush_experiment_on_frame(
            _frame(_upside_rows()),
            symbol="TEST",
            timeframe="D1",
            pivot_strength=1,
        )

        row = trade_report_row(result.trades[0])
        summaries = summary_rows(result.trades, group_fields=["candidate_id"])
        multi = summary_rows(result.trades, group_fields=["candidate_id", "timeframe"])

        self.assertEqual(row["candidate_id"], "next_open__flush_structure__1r")
        self.assertEqual(row["meta_lp_price"], 18.0)
        self.assertEqual(summaries[0]["trades"], 1)
        self.assertEqual(summaries[0]["target_exits"], 1)
        self.assertEqual(summaries[0]["stop_exits"], 0)
        self.assertEqual(multi[0]["timeframe"], "D1")
        self.assertEqual(summary_rows([], group_fields=["candidate_id"]), [])

    def test_drawdown_helper_handles_empty_and_non_empty_series(self) -> None:
        self.assertEqual(_max_closed_trade_drawdown(pd.Series(dtype=float)), 0.0)
        self.assertEqual(_max_closed_trade_drawdown(pd.Series([1.0, -2.0, 1.0])), 2.0)


if __name__ == "__main__":
    unittest.main()
