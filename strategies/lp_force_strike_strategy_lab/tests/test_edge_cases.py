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

from backtest_engine_lab import CostConfig, TradeRecord, TradeSetup  # noqa: E402
from force_strike_pattern_lab import ForceStrikePattern  # noqa: E402
from lp_levels_lab import LPBreakEvent  # noqa: E402
from lp_force_strike_strategy_lab import (  # noqa: E402
    LPForceStrikeSignal,
    PortfolioRule,
    SkippedTrade,
    StabilityFilter,
    TradeModelCandidate,
    add_atr,
    build_trade_setup,
    closed_trade_drawdown_metrics,
    detect_lp_force_strike_signals,
    filter_trade_timeframes,
    make_trade_model_candidates,
    run_lp_force_strike_experiment_on_frame,
    select_portfolio_trades,
    summary_rows,
    summarize_trades,
)
from lp_force_strike_strategy_lab.experiment import (  # noqa: E402
    _candidate_id,
    _resolve_entry,
    _simulate_trade_setup,
)
from lp_force_strike_strategy_lab.signals import _TrapWindow, _window_matches_pattern  # noqa: E402
from lp_force_strike_strategy_lab.stability import (  # noqa: E402
    _filter_pairs,
    normalise_trade_frame,
    run_stability_analysis,
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
                "atr": row.get("atr", 2.0),
            }
            for index, row in enumerate(rows)
        ]
    )


def _setup_frame(*, atr: float = 2.0) -> pd.DataFrame:
    return _frame(
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "atr": atr},
            {"open": 100, "high": 101, "low": 99, "close": 100, "atr": atr},
            {"open": 100, "high": 101, "low": 99, "close": 100, "atr": atr},
            {"open": 100, "high": 101, "low": 99, "close": 100, "atr": atr},
            {"open": 100, "high": 104, "low": 96, "close": 101, "atr": atr},
            {"open": 101, "high": 103, "low": 97, "close": 100, "atr": atr},
            {"open": 100, "high": 106, "low": 94, "close": 104, "atr": atr},
            {"open": 103, "high": 108, "low": 99, "close": 106, "atr": atr},
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


def _portfolio_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "pivot_strength": row.get("pivot_strength", 3),
                "entry_time_utc": row["entry"],
                "exit_time_utc": row["exit"],
                "net_r": row["net_r"],
            }
            for row in rows
        ]
    )


def _trade_record(*, net_r: float = 1.0, candidate_id: str = "c1") -> TradeRecord:
    time = pd.Timestamp("2026-01-01T00:00:00Z")
    return TradeRecord(
        setup_id="T1",
        symbol="EURUSD",
        timeframe="H4",
        side="long",
        signal_index=1,
        entry_index=1,
        exit_index=1,
        entry_time_utc=time,
        exit_time_utc=time,
        entry_reference_price=100.0,
        entry_fill_price=100.0,
        exit_reference_price=101.0,
        exit_fill_price=101.0,
        stop_price=99.0,
        target_price=101.0,
        risk_distance=1.0,
        reference_r=net_r,
        fill_r=net_r,
        commission_r=0.0,
        net_r=net_r,
        bars_held=1,
        exit_reason="target",
        metadata={"candidate_id": candidate_id},
    )


class StrategyEdgeCaseTests(unittest.TestCase):
    def test_signal_detector_validates_empty_and_expired_windows(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            detect_lp_force_strike_signals(pd.DataFrame({"time_utc": [], "open": [], "high": [], "low": []}), "M30")

        empty = pd.DataFrame(columns=["time_utc", "open", "high", "low", "close"])
        self.assertEqual(detect_lp_force_strike_signals(empty, "M30"), [])

        lp_event = LPBreakEvent("support", 95.0, 1, pd.Timestamp("2026-01-01T00:00:00Z"), 2, pd.Timestamp("2026-01-01T01:00:00Z"), 5, pd.Timestamp("2026-01-01T02:00:00Z"))
        pattern = ForceStrikePattern("bullish", 1, 0, 3, pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-01-01T03:00:00Z"), 100.0, 90.0, 101.0, 89.0, 4, "below_mother_low")
        self.assertFalse(_window_matches_pattern(_TrapWindow("bullish", "force_bottom", lp_event), pattern, signal_close=95.0, max_bars_from_lp_break=6))

    def test_candidate_and_setup_validation_edges(self) -> None:
        invalid_candidate_calls = [
            {"partial_fraction": 0.0},
            {"entry_zones": [1.0]},
            {"exit_models": ["bad"]},
            {"entry_models": ["bad"]},
            {"stop_models": ["bad"]},
        ]
        for kwargs in invalid_candidate_calls:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    make_trade_model_candidates(
                        entry_models=kwargs.get("entry_models", ["next_open"]),
                        stop_models=kwargs.get("stop_models", ["fs_structure"]),
                        target_rs=[1.0],
                        max_risk_atrs=[1.0],
                        entry_zones=kwargs.get("entry_zones"),
                        exit_models=kwargs.get("exit_models"),
                        partial_fraction=kwargs.get("partial_fraction", 0.5),
                    )

        with self.assertRaisesRegex(ValueError, "Unsupported stop model"):
            _candidate_id("next_open", "bad", 1.0, exit_model="single_target", partial_target_r=1.0)
        with self.assertRaisesRegex(ValueError, "Unsupported exit model"):
            _candidate_id("next_open", "fs_structure", 1.0, exit_model="bad", partial_target_r=1.0)

        candidate = TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0)
        with self.assertRaisesRegex(ValueError, "ATR period"):
            add_atr(_setup_frame(), period=0)
        with self.assertRaisesRegex(ValueError, "experiment frame is missing columns"):
            add_atr(pd.DataFrame({"time_utc": [], "open": [], "high": [], "low": []}))
        with self.assertRaisesRegex(ValueError, "max_entry_wait_bars"):
            build_trade_setup(_setup_frame(), _signal(), candidate, symbol="T", timeframe="H4", max_entry_wait_bars=0)
        with self.assertRaisesRegex(ValueError, "Unsupported entry_wait_mode"):
            build_trade_setup(_setup_frame(), _signal(), candidate, symbol="T", timeframe="H4", entry_wait_mode="bad")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "Unsupported entry_wait_same_bar_priority"):
            build_trade_setup(_setup_frame(), _signal(), candidate, symbol="T", timeframe="H4", entry_wait_same_bar_priority="bad")  # type: ignore[arg-type]

    def test_setup_builder_skip_reasons_are_explicit(self) -> None:
        next_candidate = TradeModelCandidate("next", "next_open", "fs_structure", 1.0)

        no_next = build_trade_setup(_setup_frame().iloc[:7], _signal(), next_candidate, symbol="T", timeframe="H4")
        self.assertIsInstance(no_next, SkippedTrade)
        assert isinstance(no_next, SkippedTrade)
        self.assertEqual(no_next.reason, "no_next_candle")
        self.assertEqual(no_next.to_dict()["reason"], "no_next_candle")

        invalid_stop_frame = _setup_frame()
        invalid_stop_frame.loc[7, "open"] = 94.0
        invalid_stop = build_trade_setup(invalid_stop_frame, _signal(), next_candidate, symbol="T", timeframe="H4")
        self.assertIsInstance(invalid_stop, SkippedTrade)
        assert isinstance(invalid_stop, SkippedTrade)
        self.assertEqual(invalid_stop.reason, "invalid_stop")

        zero_range = _setup_frame()
        zero_range.loc[6, "high"] = 100.0
        zero_range.loc[6, "low"] = 100.0
        range_skip = build_trade_setup(zero_range, _signal(), TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0), symbol="T", timeframe="H4")
        self.assertIsInstance(range_skip, SkippedTrade)
        assert isinstance(range_skip, SkippedTrade)
        self.assertEqual(range_skip.reason, "invalid_entry_range")

        unsupported = build_trade_setup(_setup_frame(), _signal(), TradeModelCandidate("bad", "bad", "fs_structure", 1.0), symbol="T", timeframe="H4")  # type: ignore[arg-type]
        self.assertIsInstance(unsupported, SkippedTrade)
        assert isinstance(unsupported, SkippedTrade)
        self.assertEqual(unsupported.reason, "unsupported_entry_model")

        missing_atr = build_trade_setup(_setup_frame(atr=0.0), _signal(), TradeModelCandidate("atr", "next_open", "fs_structure_max_atr", 1.0, max_risk_atr=10.0), symbol="T", timeframe="H4")
        self.assertIsInstance(missing_atr, SkippedTrade)
        assert isinstance(missing_atr, SkippedTrade)
        self.assertEqual(missing_atr.reason, "missing_atr")

    def test_bearish_pullback_and_until_1r_invalid_stop_edges(self) -> None:
        setup = build_trade_setup(_setup_frame(), _signal("bearish"), TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0), symbol="T", timeframe="H4")

        self.assertNotIsInstance(setup, SkippedTrade)
        assert not isinstance(setup, SkippedTrade)
        self.assertEqual(setup.side, "short")
        self.assertEqual(setup.entry_price, 100.0)
        self.assertEqual(setup.target_price, 94.0)

        data = add_atr(_setup_frame(), period=1)
        invalid = _resolve_entry(
            data,
            _signal(),
            TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0),
            max_entry_wait_bars=6,
            entry_wait_mode="until_entry_or_1r_target",
            entry_wait_same_bar_priority="entry",
            stop_price=101.0,
        )
        self.assertEqual(invalid, "invalid_stop")

        atr_limited = build_trade_setup(_setup_frame(), _signal(), TradeModelCandidate("atr-ok", "next_open", "fs_structure_max_atr", 1.0, max_risk_atr=10.0), symbol="T", timeframe="H4")
        self.assertNotIsInstance(atr_limited, SkippedTrade)

        entry_only_frame = _setup_frame()
        entry_only_frame.loc[7, "high"] = 105.0
        cancel_priority_entry = build_trade_setup(
            entry_only_frame,
            _signal(),
            TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0),
            symbol="T",
            timeframe="H4",
            entry_wait_mode="until_entry_or_1r_target",
            entry_wait_same_bar_priority="cancel",
        )
        self.assertNotIsInstance(cancel_priority_entry, SkippedTrade)

    def test_partial_runner_and_simulation_error_edges(self) -> None:
        data = _frame(
            [
                {"open": 100, "high": 101, "low": 94, "close": 95},
                {"open": 95, "high": 102, "low": 92, "close": 93},
            ]
        )
        short_setup = TradeSetup("short", "short", 0, 100.0, 105.0, 90.0, symbol="T", timeframe="H4", metadata={"candidate_id": "partial"})
        partial_candidate = TradeModelCandidate("partial", "next_open", "fs_structure", 2.0, exit_model="partial_1r_runner")

        trade = _simulate_trade_setup(data, short_setup, partial_candidate, CostConfig())

        self.assertEqual(trade.exit_reason, "partial_exit")
        self.assertEqual(trade.metadata["partial_exit_reason"], "target")
        self.assertEqual(trade.metadata["runner_exit_reason"], "end_of_data")

        with self.assertRaisesRegex(ValueError, "greater than"):
            _simulate_trade_setup(data, short_setup, TradeModelCandidate("bad", "next_open", "fs_structure", 1.0, exit_model="partial_1r_runner"), CostConfig())
        with self.assertRaisesRegex(ValueError, "Unsupported exit model"):
            _simulate_trade_setup(data, short_setup, TradeModelCandidate("bad", "next_open", "fs_structure", 1.0, exit_model="bad"), CostConfig())  # type: ignore[arg-type]

    def test_experiment_runner_skips_and_validates_wait_modes(self) -> None:
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
        frame = _frame([{"open": (row["high"] + row["low"]) / 2.0, "high": row["high"], "low": row["low"], "close": row["close"]} for row in rows])
        candidate = TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0)

        result = run_lp_force_strike_experiment_on_frame(frame, symbol="T", timeframe="M30", candidates=[candidate], pivot_strength=2, atr_period=1)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0].reason, "entry_not_reached")

        with self.assertRaisesRegex(ValueError, "Unsupported entry_wait_mode"):
            run_lp_force_strike_experiment_on_frame(frame, symbol="T", timeframe="M30", candidates=[candidate], entry_wait_mode="bad")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "Unsupported entry_wait_same_bar_priority"):
            run_lp_force_strike_experiment_on_frame(frame, symbol="T", timeframe="M30", candidates=[candidate], entry_wait_same_bar_priority="bad")  # type: ignore[arg-type]

    def test_summary_rows_empty_and_single_group(self) -> None:
        self.assertEqual(summary_rows([], group_fields=["candidate_id"]), [])

        summary = summary_rows([_trade_record(net_r=1.0)], group_fields=["candidate_id"])
        self.assertEqual(summary[0]["candidate_id"], "c1")
        self.assertEqual(summary[0]["profit_factor"], None)

    def test_portfolio_edge_cases(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            select_portfolio_trades(pd.DataFrame({"symbol": ["EURUSD"]}), PortfolioRule("bad"))
        with self.assertRaisesRegex(ValueError, "At least one timeframe"):
            filter_trade_timeframes(pd.DataFrame({"timeframe": ["H4"]}), [])
        with self.assertRaisesRegex(ValueError, "missing required column"):
            filter_trade_timeframes(pd.DataFrame({"symbol": ["EURUSD"]}), ["H4"])

        self.assertEqual(closed_trade_drawdown_metrics(pd.DataFrame())["max_drawdown_r"], 0.0)

        frame = _portfolio_frame(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-03", "net_r": 1.0},
                {"symbol": "GBPUSD", "timeframe": "H4", "entry": "2026-01-02", "exit": "2026-01-03", "net_r": 1.0},
                {"symbol": "USDJPY", "timeframe": "H4", "entry": "2026-01-02", "exit": "2026-01-03", "net_r": 1.0},
            ]
        )
        selected, rejected = select_portfolio_trades(frame, PortfolioRule("cap", max_open_r=2.0))

        self.assertEqual(len(selected), 2)
        self.assertEqual(rejected["rejected_max_open_r"], 1)

    def test_stability_edge_cases(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing columns"):
            normalise_trade_frame(pd.DataFrame({"candidate_id": ["c1"]}))

        minimal = pd.DataFrame(
            {
                "candidate_id": ["c1", "c1", "c2"],
                "symbol": ["eurusd", "gbpusd", "eurusd"],
                "timeframe": ["h4", "h4", "d1"],
                "entry_time_utc": ["2020-01-01", "2024-01-01", "2024-01-02"],
                "net_r": [0.0, 1.0, -1.0],
            }
        )
        normalized = normalise_trade_frame(minimal)
        self.assertEqual(normalized["bars_held"].tolist(), [0.0, 0.0, 0.0])
        self.assertEqual(normalized["exit_reason"].tolist(), ["", "", ""])

        empty_summary = summarize_trades(normalized.iloc[0:0], ["candidate_id"])
        self.assertEqual(list(empty_summary.columns[:2]), ["candidate_id", "trades"])

        single_group = summarize_trades(normalized, ["candidate_id"])
        self.assertIn("c1", set(single_group["candidate_id"]))

        result = run_stability_analysis(
            normalized,
            split_time_utc=pd.Timestamp("2023-01-01"),
            candidate_ids=[],
            filters=[
                StabilityFilter("none", min_trades=5),
                StabilityFilter("totals", min_trades=1, min_total_net_r=0.5),
            ],
        )
        self.assertTrue((result.filter_results[result.filter_results["filter_id"] == "none"]["trades"] == 0).all())
        self.assertIn("totals", set(result.filter_results["filter_id"]))

        self.assertEqual(_filter_pairs(pd.DataFrame(), StabilityFilter("empty")).empty, True)


if __name__ == "__main__":
    unittest.main()
