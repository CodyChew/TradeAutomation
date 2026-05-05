from __future__ import annotations

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

from backtest_engine_lab import TradeSetup  # noqa: E402
from lp_force_strike_strategy_lab.experiment import SkippedTrade, TradeModelCandidate  # noqa: E402
from lp_force_strike_strategy_lab.signals import LPForceStrikeSignal  # noqa: E402
from lp_force_strike_strategy_lab.protection_realism import (  # noqa: E402
    ProtectionRealismVariant,
    _as_utc,
    run_lp_force_strike_m30_protection_realism_on_frame,
    simulate_protection_realism_on_m30_frame,
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=len(rows), freq="30min", tz="UTC")
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
    metadata = {"candidate_id": "mid", "fs_signal_time_utc": "2025-12-31 20:00:00+00:00"}
    if side == "long":
        return TradeSetup("setup", "long", 0, 100.0, 95.0, 105.0, symbol="TEST", timeframe="H4", signal_index=1, metadata=metadata)
    return TradeSetup("setup", "short", 0, 100.0, 105.0, 95.0, symbol="TEST", timeframe="H4", signal_index=1, metadata=metadata)


def _signal(side: str = "bullish", time: str = "2026-01-01 00:00:00+00:00") -> LPForceStrikeSignal:
    return LPForceStrikeSignal(
        side=side,  # type: ignore[arg-type]
        scenario="force_bottom" if side == "bullish" else "force_top",
        lp_price=99.0,
        lp_break_index=1,
        lp_break_time_utc=pd.Timestamp(time),
        lp_pivot_index=0,
        lp_pivot_time_utc=pd.Timestamp(time),
        fs_mother_index=1,
        fs_signal_index=1,
        fs_mother_time_utc=pd.Timestamp(time),
        fs_signal_time_utc=pd.Timestamp(time),
        bars_from_lp_break=1,
        fs_total_bars=3,
    )


class ProtectionRealismTests(unittest.TestCase):
    def test_control_variant_delegates_to_bid_ask_bracket(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame([{"open": 100.0, "high": 105.1, "low": 100.0, "close": 105.0}]),
            _setup("long"),
            ProtectionRealismVariant("control_bid_ask", "control"),
        )

        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.metadata["tp_near_mode"], "control")
        self.assertEqual(trade.metadata["protection_activation_status"], "not_triggered")

    def test_long_lock_stop_activates_on_next_m30_bar_then_exits_at_half_r(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 104.6, "low": 100.0, "close": 104.2},
                    {"open": 103.0, "high": 103.2, "low": 102.4, "close": 102.6},
                ]
            ),
            _setup("long"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_next", "lock_r_protect"),
        )

        self.assertEqual(trade.exit_reason, "tp_near_lock_stop")
        self.assertEqual(trade.exit_index, 1)
        self.assertAlmostEqual(trade.net_r, 0.5)
        self.assertTrue(trade.metadata["tp_near_triggered"])
        self.assertTrue(trade.metadata["protection_activated"])
        self.assertEqual(trade.metadata["protection_activation_status"], "activated")

    def test_long_fast_snapback_does_not_credit_instant_stop_modification(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 104.6, "low": 100.0, "close": 104.2},
                    {"open": 101.0, "high": 101.5, "low": 99.0, "close": 99.5},
                    {"open": 99.0, "high": 100.0, "low": 94.8, "close": 95.0},
                ]
            ),
            _setup("long"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_next", "lock_r_protect"),
        )

        self.assertEqual(trade.exit_reason, "stop")
        self.assertAlmostEqual(trade.net_r, -1.0)
        self.assertTrue(trade.metadata["tp_near_triggered"])
        self.assertFalse(trade.metadata["protection_activated"])
        self.assertEqual(trade.metadata["protection_activation_status"], "rejected_too_late")

    def test_pending_protection_can_end_without_exit(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame([{"open": 100.0, "high": 104.6, "low": 100.0, "close": 104.2}]),
            _setup("long"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_next", "lock_r_protect"),
        )

        self.assertEqual(trade.exit_reason, "end_of_data")
        self.assertTrue(trade.metadata["tp_near_triggered"])
        self.assertEqual(trade.metadata["protection_activation_status"], "pending")

    def test_retry_rejected_min_distance_can_activate_later(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 104.6, "low": 100.0, "close": 104.2, "spread_points": 2, "point": 0.1},
                    {"open": 102.55, "high": 103.0, "low": 102.6, "close": 102.8, "spread_points": 2, "point": 0.1},
                    {"open": 103.0, "high": 103.2, "low": 102.4, "close": 102.6, "spread_points": 2, "point": 0.1},
                ]
            ),
            _setup("long"),
            ProtectionRealismVariant(
                "lock_0p50r_pct_90_m30_retry_minstop_1x",
                "lock_r_protect",
                min_stop_distance_spread_mult=1.0,
                retry_rejected_modification=True,
            ),
        )

        self.assertEqual(trade.exit_reason, "tp_near_lock_stop")
        self.assertEqual(trade.metadata["protection_activation_index"], 2)
        self.assertEqual(trade.metadata["protection_rejected_attempts"], 1)

    def test_same_m30_assumed_variant_brackets_live_loop_timing(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 104.6, "low": 100.0, "close": 104.2},
                    {"open": 101.0, "high": 101.5, "low": 99.0, "close": 99.5},
                ]
            ),
            _setup("long"),
            ProtectionRealismVariant(
                "lock_0p50r_pct_90_m30_same_assumed",
                "lock_r_protect",
                activation_model="same_m30_assumed",
            ),
        )

        self.assertEqual(trade.exit_reason, "tp_near_lock_stop")
        self.assertAlmostEqual(trade.net_r, 0.5)
        self.assertTrue(trade.metadata["protection_activated"])
        self.assertEqual(trade.metadata["protection_activation_status"], "activated_same_m30_assumed")

    def test_short_lock_stop_activates_on_next_m30_bar_then_exits_at_half_r(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 100.0, "low": 95.4, "close": 95.8, "spread_points": 1, "point": 0.1},
                    {"open": 97.0, "high": 97.6, "low": 96.8, "close": 97.2, "spread_points": 1, "point": 0.1},
                ]
            ),
            _setup("short"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_next", "lock_r_protect"),
        )

        self.assertEqual(trade.exit_reason, "tp_near_lock_stop")
        self.assertEqual(trade.exit_index, 1)
        self.assertAlmostEqual(trade.net_r, 0.5)
        self.assertTrue(trade.metadata["protection_activated"])

    def test_short_fast_snapback_rejects_too_late_stop_update(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 100.0, "low": 95.4, "close": 95.8, "spread_points": 1, "point": 0.1},
                    {"open": 98.0, "high": 99.0, "low": 97.8, "close": 98.6, "spread_points": 1, "point": 0.1},
                    {"open": 100.0, "high": 105.1, "low": 99.0, "close": 105.0, "spread_points": 1, "point": 0.1},
                ]
            ),
            _setup("short"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_next", "lock_r_protect"),
        )

        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.metadata["protection_activation_status"], "rejected_too_late")

    def test_short_min_stop_distance_can_block_update(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 100.0, "low": 95.2, "close": 95.8, "spread_points": 2, "point": 0.1},
                    {"open": 97.2, "high": 97.4, "low": 96.8, "close": 97.0, "spread_points": 2, "point": 0.1},
                    {"open": 96.0, "high": 96.5, "low": 94.7, "close": 95.5, "spread_points": 2, "point": 0.1},
                ]
            ),
            _setup("short"),
            ProtectionRealismVariant(
                "lock_0p50r_pct_90_m30_minstop_1x",
                "lock_r_protect",
                min_stop_distance_spread_mult=1.0,
            ),
        )

        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.metadata["protection_activation_status"], "rejected_min_stop_distance")

    def test_one_bar_delay_waits_an_extra_m30_bar_before_locking(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 104.6, "low": 100.0, "close": 104.2},
                    {"open": 103.0, "high": 103.2, "low": 102.4, "close": 102.6},
                    {"open": 103.0, "high": 103.2, "low": 102.4, "close": 102.6},
                ]
            ),
            _setup("long"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_delay1", "lock_r_protect", activation_delay_m30_bars=1),
        )

        self.assertEqual(trade.exit_reason, "tp_near_lock_stop")
        self.assertEqual(trade.exit_index, 2)
        self.assertEqual(trade.metadata["protection_activation_index"], 2)

    def test_target_still_wins_before_delayed_protection_can_activate(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 105.1, "low": 100.0, "close": 105.0},
                ]
            ),
            _setup("long"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_next", "lock_r_protect"),
        )

        self.assertEqual(trade.exit_reason, "target")
        self.assertAlmostEqual(trade.net_r, 1.0)
        self.assertFalse(trade.metadata["protection_activated"])

    def test_min_stop_distance_can_block_a_too_close_stop_update(self) -> None:
        trade = simulate_protection_realism_on_m30_frame(
            _frame(
                [
                    {"open": 100.0, "high": 104.6, "low": 100.0, "close": 104.2, "spread_points": 2, "point": 0.1},
                    {"open": 102.55, "high": 103.0, "low": 102.4, "close": 102.8, "spread_points": 2, "point": 0.1},
                    {"open": 103.0, "high": 105.1, "low": 102.7, "close": 105.0, "spread_points": 2, "point": 0.1},
                ]
            ),
            _setup("long"),
            ProtectionRealismVariant(
                "lock_0p50r_pct_90_m30_min1x",
                "lock_r_protect",
                min_stop_distance_spread_mult=1.0,
            ),
        )

        self.assertEqual(trade.exit_reason, "target")
        self.assertFalse(trade.metadata["protection_activated"])
        self.assertEqual(trade.metadata["protection_activation_status"], "rejected_min_stop_distance")
        self.assertEqual(trade.metadata["protection_rejected_attempts"], 1)

    def test_invalid_variants_are_rejected(self) -> None:
        bad_variants = [
            ProtectionRealismVariant("", "control"),
            ProtectionRealismVariant("bad", "bad"),  # type: ignore[arg-type]
            ProtectionRealismVariant("bad", "lock_r_protect", threshold_r=0.0),
            ProtectionRealismVariant("bad", "lock_r_protect", threshold_r=1.1),
            ProtectionRealismVariant("bad", "lock_r_protect", lock_r=-0.1),
            ProtectionRealismVariant("bad", "lock_r_protect", threshold_r=0.5, lock_r=0.5),
            ProtectionRealismVariant("bad", "lock_r_protect", activation_delay_m30_bars=-1),
            ProtectionRealismVariant("bad", "lock_r_protect", activation_model="bad"),  # type: ignore[arg-type]
            ProtectionRealismVariant("bad", "lock_r_protect", min_stop_distance_spread_mult=-1.0),
            ProtectionRealismVariant("bad", "lock_r_protect", activation_model="same_m30_assumed", min_stop_distance_spread_mult=1.0),
        ]
        for variant in bad_variants:
            with self.subTest(variant=variant):
                with self.assertRaises(ValueError):
                    simulate_protection_realism_on_m30_frame(_frame([{"high": 101.0, "low": 99.0}]), _setup(), variant)

    def test_missing_replay_columns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            simulate_protection_realism_on_m30_frame(
                pd.DataFrame({"time_utc": [pd.Timestamp("2026-01-01", tz="UTC")], "open": [1.0]}),
                _setup(),
                ProtectionRealismVariant("control_bid_ask", "control"),
            )

    def test_naive_timestamp_is_localized_to_utc(self) -> None:
        self.assertEqual(str(_as_utc(pd.Timestamp("2026-01-01 00:00:00"))), "2026-01-01 00:00:00+00:00")

    def test_run_on_frame_requires_variants(self) -> None:
        with self.assertRaises(ValueError):
            run_lp_force_strike_m30_protection_realism_on_frame(
                _frame([{"high": 101.0, "low": 99.0}]),
                _frame([{"high": 101.0, "low": 99.0}]),
                symbol="TEST",
                timeframe="H4",
                candidate=TradeModelCandidate("mid", "signal_zone_pullback", "fs_structure", 1.0, entry_zone=0.5),
                variants=[],
            )

    def test_run_on_frame_expands_high_timeframe_skips_for_each_variant(self) -> None:
        candidate = TradeModelCandidate("mid", "signal_zone_pullback", "fs_structure", 1.0, entry_zone=0.5)
        skipped = SkippedTrade("mid", "TEST", "H4", "long", 1, pd.Timestamp("2026-01-01", tz="UTC"), "entry_not_reached", "existing")
        variants = [
            ProtectionRealismVariant("control_bid_ask", "control"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_next", "lock_r_protect"),
        ]
        with (
            patch("lp_force_strike_strategy_lab.protection_realism.detect_lp_force_strike_signals", return_value=[_signal()]),
            patch("lp_force_strike_strategy_lab.protection_realism._build_bid_ask_trade_setup_from_prepared_frame", return_value=skipped),
        ):
            result = run_lp_force_strike_m30_protection_realism_on_frame(
                _frame([{"high": 101.0, "low": 99.0}]),
                _frame([{"high": 101.0, "low": 99.0}]),
                symbol="TEST",
                timeframe="H4",
                candidate=candidate,
                variants=variants,
            )

        self.assertEqual(len(result.skipped), 2)
        self.assertIn("existing; tp_near_variant_id=control_bid_ask", result.skipped[0].detail)

    def test_run_on_frame_expands_empty_replay_window_skips_for_each_variant(self) -> None:
        candidate = TradeModelCandidate("mid", "signal_zone_pullback", "fs_structure", 1.0, entry_zone=0.5)
        variants = [
            ProtectionRealismVariant("control_bid_ask", "control"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_next", "lock_r_protect"),
        ]
        with (
            patch("lp_force_strike_strategy_lab.protection_realism.detect_lp_force_strike_signals", return_value=[_signal()]),
            patch("lp_force_strike_strategy_lab.protection_realism._build_bid_ask_trade_setup_from_prepared_frame", return_value=_setup("long")),
        ):
            result = run_lp_force_strike_m30_protection_realism_on_frame(
                _frame([{"high": 101.0, "low": 99.0}]),
                _frame([{"high": 101.0, "low": 99.0}]),
                symbol="TEST",
                timeframe="H4",
                candidate=candidate,
                variants=variants,
            )

        self.assertEqual(len(result.skipped), 2)
        self.assertEqual(result.skipped[0].reason, "m30_entry_window_empty")

    def test_run_on_frame_expands_m30_entry_not_reached_skips_for_each_variant(self) -> None:
        candidate = TradeModelCandidate("mid", "signal_zone_pullback", "fs_structure", 1.0, entry_zone=0.5)
        variants = [ProtectionRealismVariant("control_bid_ask", "control")]
        replay = _frame([{"open": 101.5, "high": 102.0, "low": 101.0, "close": 101.5}])
        replay["time_utc"] = [pd.Timestamp("2026-01-01 04:00:00+00:00")]
        with (
            patch("lp_force_strike_strategy_lab.protection_realism.detect_lp_force_strike_signals", return_value=[_signal()]),
            patch("lp_force_strike_strategy_lab.protection_realism._build_bid_ask_trade_setup_from_prepared_frame", return_value=_setup("long")),
        ):
            result = run_lp_force_strike_m30_protection_realism_on_frame(
                _frame([{"high": 101.0, "low": 99.0}]),
                replay,
                symbol="TEST",
                timeframe="H4",
                candidate=candidate,
                variants=variants,
            )

        self.assertEqual(result.skipped[0].reason, "m30_entry_not_reached")

    def test_run_on_frame_builds_m30_replay_setup_and_simulates_variants(self) -> None:
        candidate = TradeModelCandidate("mid", "signal_zone_pullback", "fs_structure", 1.0, entry_zone=0.5)
        variants = [
            ProtectionRealismVariant("control_bid_ask", "control"),
            ProtectionRealismVariant("lock_0p50r_pct_90_m30_next", "lock_r_protect"),
        ]
        replay = _frame(
            [
                {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
                {"open": 100.0, "high": 104.6, "low": 100.0, "close": 104.2},
                {"open": 103.0, "high": 103.2, "low": 102.4, "close": 102.6},
            ]
        )
        replay["time_utc"] = [
            pd.Timestamp("2026-01-01 04:00:00+00:00"),
            pd.Timestamp("2026-01-01 04:30:00+00:00"),
            pd.Timestamp("2026-01-01 05:00:00+00:00"),
        ]
        with (
            patch("lp_force_strike_strategy_lab.protection_realism.detect_lp_force_strike_signals", return_value=[_signal()]),
            patch("lp_force_strike_strategy_lab.protection_realism._build_bid_ask_trade_setup_from_prepared_frame", return_value=_setup("long")),
        ):
            result = run_lp_force_strike_m30_protection_realism_on_frame(
                _frame([{"high": 101.0, "low": 99.0}]),
                replay,
                symbol="TEST",
                timeframe="H4",
                candidate=candidate,
                variants=variants,
            )

        self.assertEqual(len(result.trades), 2)
        self.assertEqual(result.trades[0].metadata["replay_entry_model"], "first_m30_bid_ask_touch")
        self.assertEqual(result.trades[1].exit_reason, "tp_near_lock_stop")


if __name__ == "__main__":
    unittest.main()
