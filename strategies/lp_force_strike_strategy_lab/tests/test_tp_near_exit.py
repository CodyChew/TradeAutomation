from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

from backtest_engine_lab import CostConfig, TradeSetup  # noqa: E402
from lp_force_strike_strategy_lab.experiment import SkippedTrade, TradeModelCandidate  # noqa: E402
from lp_force_strike_strategy_lab.tp_near_exit import (  # noqa: E402
    TPNearExitVariant,
    classify_tp_near_outcome,
    run_lp_force_strike_tp_near_exit_on_frame,
    simulate_tp_near_exit_on_normalized_frame,
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(
        [
            {
                "time_utc": times[index],
                "open": row.get("open", 100.0),
                "high": row["high"],
                "low": row["low"],
                "close": row.get("close", row["low"] + (row["high"] - row["low"]) / 2.0),
                "spread_points": row.get("spread_points", 0.0),
                "point": row.get("point", 0.1),
            }
            for index, row in enumerate(rows)
        ]
    )


def _setup(side: str = "long") -> TradeSetup:
    if side == "long":
        return TradeSetup("setup", "long", 0, 100.0, 95.0, 105.0, symbol="TEST", timeframe="H1", signal_index=1)
    return TradeSetup("setup", "short", 0, 100.0, 105.0, 95.0, symbol="TEST", timeframe="H1", signal_index=1)


class TPNearExitTests(unittest.TestCase):
    def test_long_percent_close_exits_at_near_threshold(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 104.8, "low": 100.0}]),
            _setup("long"),
            TPNearExitVariant("close_pct_95", "close", threshold_value=0.95),
        )

        self.assertEqual(trade.exit_reason, "tp_near_close")
        self.assertAlmostEqual(trade.net_r, 0.95)
        self.assertTrue(trade.metadata["tp_near_triggered"])
        self.assertEqual(trade.metadata["tp_near_trigger_index"], 0)

    def test_percent_close_variants_use_effective_reduced_tp_with_full_risk(self) -> None:
        for threshold in [0.9, 0.925, 0.95, 0.98]:
            with self.subTest(threshold=threshold):
                trade = simulate_tp_near_exit_on_normalized_frame(
                    _frame([{"high": 100.0 + 5.0 * threshold + 0.01, "low": 100.0}]),
                    _setup("long"),
                    TPNearExitVariant(f"close_pct_{threshold}", "close", threshold_value=threshold),
                )

                self.assertEqual(trade.exit_reason, "tp_near_close")
                self.assertAlmostEqual(trade.risk_distance, 5.0)
                self.assertAlmostEqual(trade.net_r, threshold)

    def test_short_spread_multiple_close_uses_ask_low(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 101.0, "low": 95.0, "spread_points": 2, "point": 0.1}]),
            _setup("short"),
            TPNearExitVariant("close_spread_1x", "close", threshold_mode="spread_multiple", threshold_value=1.0),
        )

        self.assertEqual(trade.exit_reason, "tp_near_close")
        self.assertAlmostEqual(trade.exit_reference_price, 95.2)
        self.assertAlmostEqual(trade.net_r, 0.96)

    def test_long_spread_multiple_close_uses_bid_high(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 104.8, "low": 100.0, "spread_points": 2, "point": 0.1}]),
            _setup("long"),
            TPNearExitVariant("close_spread_1x", "close", threshold_mode="spread_multiple", threshold_value=1.0),
        )

        self.assertEqual(trade.exit_reason, "tp_near_close")
        self.assertAlmostEqual(trade.exit_reference_price, 104.8)
        self.assertAlmostEqual(trade.net_r, 0.96)

    def test_long_close_haircut_reduces_exit_reference_by_spread_multiple(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 104.8, "low": 100.0, "spread_points": 2, "point": 0.1}]),
            _setup("long"),
            TPNearExitVariant("close_pct_95_haircut", "close", threshold_value=0.95, fill_haircut_spread_mult=0.5),
        )

        self.assertEqual(trade.exit_reason, "tp_near_close")
        self.assertAlmostEqual(trade.exit_reference_price, 104.65)
        self.assertAlmostEqual(trade.net_r, 0.93)

    def test_short_close_haircut_worsens_exit_reference_by_spread_multiple(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 101.0, "low": 95.0, "spread_points": 2, "point": 0.1}]),
            _setup("short"),
            TPNearExitVariant("close_pct_95_haircut", "close", threshold_value=0.95, fill_haircut_spread_mult=0.5),
        )

        self.assertEqual(trade.exit_reason, "tp_near_close")
        self.assertAlmostEqual(trade.exit_reference_price, 95.35)
        self.assertAlmostEqual(trade.net_r, 0.93)

    def test_one_bar_delayed_close_waits_and_uses_conservative_executable_close(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame(
                [
                    {"high": 104.8, "low": 100.0, "close": 104.7},
                    {"high": 104.0, "low": 100.0, "close": 103.0},
                ]
            ),
            _setup("long"),
            TPNearExitVariant("close_pct_95_delay", "close", threshold_value=0.95, activation_delay_bars=1),
        )

        self.assertEqual(trade.exit_reason, "tp_near_close")
        self.assertEqual(trade.exit_index, 1)
        self.assertAlmostEqual(trade.exit_reference_price, 103.0)
        self.assertAlmostEqual(trade.net_r, 0.6)

    def test_short_one_bar_delayed_close_uses_conservative_ask_close(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame(
                [
                    {"high": 101.0, "low": 95.0, "close": 95.4, "spread_points": 2, "point": 0.1},
                    {"high": 97.0, "low": 95.3, "close": 96.0, "spread_points": 2, "point": 0.1},
                ]
            ),
            _setup("short"),
            TPNearExitVariant("close_pct_95_delay", "close", threshold_value=0.95, activation_delay_bars=1),
        )

        self.assertEqual(trade.exit_reason, "tp_near_close")
        self.assertEqual(trade.exit_index, 1)
        self.assertAlmostEqual(trade.exit_reference_price, 96.2)
        self.assertAlmostEqual(trade.net_r, 0.76)

    def test_one_bar_delayed_protect_waits_before_locking_stop(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame(
                [
                    {"high": 104.8, "low": 100.0},
                    {"high": 103.0, "low": 100.0},
                    {"high": 103.0, "low": 102.4},
                ]
            ),
            _setup("long"),
            TPNearExitVariant(
                "lock_0p50r_pct_95_delay",
                "lock_r_protect",
                threshold_value=0.95,
                lock_r=0.5,
                activation_delay_bars=1,
            ),
        )

        self.assertEqual(trade.exit_reason, "tp_near_lock_stop")
        self.assertEqual(trade.exit_index, 2)
        self.assertAlmostEqual(trade.metadata["tp_near_protected_stop"], 102.5)

    def test_delayed_protect_can_still_exit_at_target_after_activation(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame(
                [
                    {"high": 104.8, "low": 100.0},
                    {"high": 105.1, "low": 103.0},
                ]
            ),
            _setup("long"),
            TPNearExitVariant(
                "lock_0p50r_pct_95_delay",
                "lock_r_protect",
                threshold_value=0.95,
                lock_r=0.5,
                activation_delay_bars=1,
                full_target_priority=False,
            ),
        )

        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.exit_index, 1)
        self.assertAlmostEqual(trade.metadata["tp_near_protected_stop"], 102.5)

    def test_real_target_still_beats_near_target_close(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 105.1, "low": 100.0}]),
            _setup("long"),
            TPNearExitVariant("close_pct_90", "close", threshold_value=0.9),
        )

        self.assertEqual(trade.exit_reason, "target")
        self.assertAlmostEqual(trade.net_r, 1.0)

    def test_hard_near_target_close_beats_full_target(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 105.1, "low": 100.0}]),
            _setup("long"),
            TPNearExitVariant("close_pct_90", "close", threshold_value=0.9, full_target_priority=False),
        )

        self.assertEqual(trade.exit_reason, "tp_near_close")
        self.assertAlmostEqual(trade.net_r, 0.9)
        self.assertFalse(trade.metadata["tp_near_full_target_priority"])

    def test_hard_short_near_target_close_beats_full_target(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 101.0, "low": 94.8, "spread_points": 2, "point": 0.1}]),
            _setup("short"),
            TPNearExitVariant("close_pct_90", "close", threshold_value=0.9, full_target_priority=False),
        )

        self.assertEqual(trade.exit_reason, "tp_near_close")
        self.assertAlmostEqual(trade.exit_reference_price, 95.5)
        self.assertAlmostEqual(trade.net_r, 0.9)

    def test_stop_first_same_bar_conservatism_is_preserved(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 105.1, "low": 94.9}]),
            _setup("long"),
            TPNearExitVariant("close_pct_90", "close", threshold_value=0.9),
        )

        self.assertEqual(trade.exit_reason, "same_bar_stop_priority")
        self.assertAlmostEqual(trade.net_r, -1.0)

    def test_gbpcad_shape_near_tp_then_later_full_tp(self) -> None:
        data = _frame(
            [
                {"high": 100.5, "low": 95.05, "spread_points": 2, "point": 0.1},
                {"high": 99.0, "low": 94.7, "spread_points": 2, "point": 0.1},
            ]
        )
        setup = _setup("short")
        control = simulate_tp_near_exit_on_normalized_frame(data, setup, TPNearExitVariant("control_bid_ask", "control"))
        close = simulate_tp_near_exit_on_normalized_frame(data, setup, TPNearExitVariant("close_pct_95", "close", threshold_value=0.95))
        protect = simulate_tp_near_exit_on_normalized_frame(
            data,
            setup,
            TPNearExitVariant("breakeven_pct_95", "breakeven_protect", threshold_value=0.95),
        )

        self.assertEqual(control.exit_reason, "target")
        self.assertEqual(close.exit_reason, "tp_near_close")
        self.assertEqual(protect.exit_reason, "target")
        self.assertEqual(classify_tp_near_outcome(control, close), "sacrificed_full_tp")
        self.assertEqual(classify_tp_near_outcome(control, protect), "unchanged")

    def test_lock_r_protect_exits_after_near_target_trigger(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 104.8, "low": 100.0}, {"high": 103.0, "low": 102.4}]),
            _setup("long"),
            TPNearExitVariant("lock_0p50r_pct_95", "lock_r_protect", threshold_value=0.95, lock_r=0.5),
        )

        self.assertEqual(trade.exit_reason, "tp_near_lock_stop")
        self.assertAlmostEqual(trade.net_r, 0.5)
        self.assertAlmostEqual(trade.metadata["tp_near_protected_stop"], 102.5)

    def test_breakeven_protect_can_save_a_trade_that_later_hits_original_stop(self) -> None:
        data = _frame([{"high": 104.8, "low": 100.0}, {"high": 101.0, "low": 99.8}, {"high": 101.0, "low": 94.9}])
        setup = _setup("long")
        control = simulate_tp_near_exit_on_normalized_frame(data, setup, TPNearExitVariant("control_bid_ask", "control"))
        protect = simulate_tp_near_exit_on_normalized_frame(
            data,
            setup,
            TPNearExitVariant("breakeven_pct_95", "breakeven_protect", threshold_value=0.95),
        )

        self.assertEqual(control.exit_reason, "stop")
        self.assertEqual(protect.exit_reason, "tp_near_breakeven_stop")
        self.assertEqual(classify_tp_near_outcome(control, protect), "saved_from_stop")

    def test_end_of_data_classifications(self) -> None:
        setup = _setup("long")
        control = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 103.0, "low": 100.0, "close": 101.0}]),
            setup,
            TPNearExitVariant("control_bid_ask", "control"),
        )
        better = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 104.8, "low": 100.0, "close": 102.0}]),
            setup,
            TPNearExitVariant("breakeven_pct_95", "breakeven_protect", threshold_value=0.95),
        )
        worse = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 104.8, "low": 100.0, "close": 100.5}]),
            setup,
            TPNearExitVariant("breakeven_pct_95", "breakeven_protect", threshold_value=0.95),
        )

        self.assertEqual(classify_tp_near_outcome(control, better), "improved_end_of_data")
        self.assertEqual(classify_tp_near_outcome(control, worse), "worsened_end_of_data")

    def test_fallback_classification_compares_net_r(self) -> None:
        setup = _setup("long")
        early_close = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 104.8, "low": 100.0}]),
            setup,
            TPNearExitVariant("close_pct_95", "close", threshold_value=0.95),
        )
        later_target = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 105.1, "low": 100.0}]),
            setup,
            TPNearExitVariant("control_bid_ask", "control"),
        )
        later_stop = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 101.0, "low": 94.9}]),
            setup,
            TPNearExitVariant("control_bid_ask", "control"),
        )

        self.assertEqual(classify_tp_near_outcome(early_close, later_target), "saved_from_stop")
        self.assertEqual(classify_tp_near_outcome(early_close, later_stop), "sacrificed_full_tp")

    def test_same_bar_outcome_classification(self) -> None:
        control = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 105.1, "low": 94.9}]),
            _setup("long"),
            TPNearExitVariant("control_bid_ask", "control"),
        )
        unchanged_variant = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 105.1, "low": 94.9}]),
            _setup("long"),
            TPNearExitVariant("close_pct_90", "close", threshold_value=0.9),
        )
        changed_variant = replace(unchanged_variant, exit_reason="target", net_r=1.0)

        self.assertEqual(classify_tp_near_outcome(control, unchanged_variant), "unchanged")
        self.assertEqual(classify_tp_near_outcome(control, changed_variant), "same_bar_conflict")

    def test_short_lock_r_protect_and_spread_threshold(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame(
                [
                    {"high": 100.5, "low": 95.0, "spread_points": 2, "point": 0.1},
                    {"high": 98.8, "low": 96.0, "spread_points": 2, "point": 0.1},
                ]
            ),
            _setup("short"),
            TPNearExitVariant("lock_0p25r_spread_1x", "lock_r_protect", "spread_multiple", 1.0, lock_r=0.25),
        )

        self.assertEqual(trade.exit_reason, "tp_near_lock_stop")
        self.assertAlmostEqual(trade.exit_reference_price, 98.75)
        self.assertAlmostEqual(trade.net_r, 0.25)

    def test_near_target_can_trigger_after_initial_non_near_bar(self) -> None:
        trade = simulate_tp_near_exit_on_normalized_frame(
            _frame([{"high": 103.0, "low": 100.0}, {"high": 104.8, "low": 100.0}, {"high": 105.1, "low": 100.1}]),
            _setup("long"),
            TPNearExitVariant("breakeven_pct_95", "breakeven_protect", threshold_value=0.95),
        )

        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.metadata["tp_near_trigger_index"], 1)

    def test_invalid_variants_are_rejected(self) -> None:
        bad_variants = [
            TPNearExitVariant("", "control"),
            TPNearExitVariant("bad", "bad"),  # type: ignore[arg-type]
            TPNearExitVariant("bad", "close", "bad", 0.9),  # type: ignore[arg-type]
            TPNearExitVariant("bad", "close", threshold_value=0.0),
            TPNearExitVariant("bad", "close", threshold_value=1.1),
            TPNearExitVariant("bad", "lock_r_protect", threshold_value=0.9, lock_r=1.0),
            TPNearExitVariant("bad", "close", threshold_value=0.9, fill_haircut_spread_mult=-0.1),
            TPNearExitVariant("bad", "close", threshold_value=0.9, activation_delay_bars=-1),
        ]
        for variant in bad_variants:
            with self.subTest(variant=variant):
                with self.assertRaises(ValueError):
                    simulate_tp_near_exit_on_normalized_frame(_frame([{"high": 101, "low": 99}]), _setup(), variant)

    def test_run_on_frame_requires_variants_and_expands_skips(self) -> None:
        candidate = TradeModelCandidate("mid", "signal_zone_pullback", "fs_structure", 1.0, entry_zone=0.5)
        with self.assertRaises(ValueError):
            run_lp_force_strike_tp_near_exit_on_frame(
                _frame([{"high": 101, "low": 99}]),
                symbol="TEST",
                timeframe="H1",
                candidate=candidate,
                variants=[],
            )

        skipped = SkippedTrade("mid", "TEST", "H1", "long", 1, None, "entry_not_reached", "existing")
        with (
            patch("lp_force_strike_strategy_lab.tp_near_exit.detect_lp_force_strike_signals", return_value=[SimpleNamespace()]),
            patch("lp_force_strike_strategy_lab.tp_near_exit._build_bid_ask_trade_setup_from_prepared_frame", return_value=skipped),
        ):
            result = run_lp_force_strike_tp_near_exit_on_frame(
                _frame([{"high": 101, "low": 99}]),
                symbol="TEST",
                timeframe="H1",
                candidate=candidate,
                variants=[TPNearExitVariant("control_bid_ask", "control"), TPNearExitVariant("close_pct_95", "close", threshold_value=0.95)],
            )

        self.assertEqual(len(result.skipped), 2)
        self.assertIn("existing; tp_near_variant_id=control_bid_ask", result.skipped[0].detail)

    def test_run_on_frame_simulates_each_variant_for_built_setup(self) -> None:
        candidate = TradeModelCandidate("mid", "signal_zone_pullback", "fs_structure", 1.0, entry_zone=0.5)
        setup = _setup("long")
        with (
            patch("lp_force_strike_strategy_lab.tp_near_exit.detect_lp_force_strike_signals", return_value=[SimpleNamespace()]),
            patch("lp_force_strike_strategy_lab.tp_near_exit._build_bid_ask_trade_setup_from_prepared_frame", return_value=setup),
        ):
            result = run_lp_force_strike_tp_near_exit_on_frame(
                _frame([{"high": 104.8, "low": 100.0}]),
                symbol="TEST",
                timeframe="H1",
                candidate=candidate,
                variants=[TPNearExitVariant("control_bid_ask", "control"), TPNearExitVariant("close_pct_95", "close", threshold_value=0.95)],
            )

        self.assertEqual(len(result.trades), 2)
        self.assertEqual(result.trades[0].metadata["tp_near_variant_id"], "control_bid_ask")
        self.assertEqual(result.trades[1].exit_reason, "tp_near_close")


if __name__ == "__main__":
    unittest.main()
