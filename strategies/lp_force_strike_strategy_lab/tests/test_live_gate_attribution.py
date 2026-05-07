from __future__ import annotations

import sys
import tempfile
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

from lp_force_strike_strategy_lab.live_gate_attribution import (  # noqa: E402
    build_gate_attribution_report,
    load_jsonl_events,
    parse_jsonl_lines,
    render_gate_attribution_markdown,
)
import lp_force_strike_strategy_lab.live_gate_attribution as gate_module  # noqa: E402


class LiveGateAttributionTests(unittest.TestCase):
    def test_counts_retryable_spread_wait_and_later_placement(self) -> None:
        signal_key = "lpfs:AUDCHF:H8:299:long:signal_zone_0p5_pullback__fs_structure__1r:2026-05-05 05:00:00+00:00"
        rows = [
            _notification_row(
                "setup_rejected",
                signal_key,
                status="spread_too_wide",
                occurred_at_utc="2026-05-03T22:00:00+00:00",
            ),
            {
                "event": "order_intent_created",
                "occurred_at_utc": "2026-05-04T02:00:00+00:00",
                "signal_key": signal_key,
                "decision": {"status": "ready", "intent": {"signal_key": signal_key}},
            },
            _notification_row(
                "order_sent",
                signal_key,
                status="pending",
                occurred_at_utc="2026-05-04T02:01:00+00:00",
            ),
            {"event": "signal_already_processed", "occurred_at_utc": "2026-05-04T03:00:00+00:00", "signal_key": signal_key},
        ]

        report = build_gate_attribution_report(rows, source="test", weekly_open_window_hours=12)

        self.assertEqual(report.detected_setups, 1)
        self.assertEqual(report.spread_waits, 1)
        self.assertEqual(report.placed_orders, 1)
        self.assertEqual(report.later_placements_after_spread_wait, 1)
        self.assertEqual(report.weekly_open_waits, 1)
        self.assertEqual(report.by_timeframe, {"H8": 1})

    def test_counts_market_recovery_waits_expiry_and_entry_path_skips(self) -> None:
        price_wait = "lpfs:EURCHF:H4:299:long:signal_zone_0p5_pullback__fs_structure__1r:2026-05-05 21:00:00+00:00"
        expired = "lpfs:NZDCHF:W1:299:short:signal_zone_0p5_pullback__fs_structure__1r:2026-04-25 21:00:00+00:00"
        path_skip = "lpfs:GBPJPY:D1:299:short:signal_zone_0p5_pullback__fs_structure__1r:2026-05-05 21:00:00+00:00"
        rows = [
            _notification_row("setup_rejected", price_wait, status="market_recovery_not_better"),
            _notification_row("setup_rejected", price_wait, status="market_recovery_spread_too_wide"),
            _notification_row("setup_rejected", price_wait, status="market_closed"),
            _notification_row("market_recovery_sent", price_wait, status="open"),
            _notification_row("setup_rejected", expired, status="pending_expired"),
            _notification_row("pending_expired", expired, status="cancelled"),
            _notification_row("setup_rejected", path_skip, status="market_recovery_stop_touched"),
        ]

        report = build_gate_attribution_report(rows, source="test")

        self.assertEqual(report.detected_setups, 3)
        self.assertEqual(report.market_recovery_price_waits, 1)
        self.assertEqual(report.market_recovery_spread_waits, 1)
        self.assertEqual(report.broker_session_waits, 1)
        self.assertEqual(report.market_recoveries, 1)
        self.assertEqual(report.entry_touch_skips, 1)
        self.assertEqual(report.expiries, 2)

    def test_renders_markdown_summary(self) -> None:
        signal_key = "lpfs:AUDCHF:H8:299:long:signal_zone_0p5_pullback__fs_structure__1r:2026-05-05 05:00:00+00:00"
        report = build_gate_attribution_report(
            [_notification_row("order_sent", signal_key, status="pending")],
            source="sample",
        )

        markdown = render_gate_attribution_markdown([report], generated_at_utc="2026-05-06T00:00:00+00:00")

        self.assertIn("# LPFS Live Gate Attribution", markdown)
        self.assertIn("## sample", markdown)
        self.assertIn("Unique decision signal keys: `1`", markdown)
        self.assertIn("AUDCHF H8 LONG", markdown)

    def test_loads_jsonl_and_handles_empty_report_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "journal.jsonl"
            path.write_text('\n{"event": "runner_started", "occurred_at_utc": "2026-05-05T00:00:00+00:00"}\n', encoding="utf-8")

            rows = load_jsonl_events(path)
            report = build_gate_attribution_report(rows, source="empty")
            markdown = render_gate_attribution_markdown([report], generated_at_utc="2026-05-06T00:00:00+00:00")

            self.assertEqual(parse_jsonl_lines(["", '{"event": "x"}\n']), [{"event": "x"}])
            self.assertEqual(report.detected_setups, 0)
            self.assertEqual(report.placed_orders, 0)
            self.assertEqual(report.market_recoveries, 0)
            self.assertEqual(report.adopted_orders, 0)
            self.assertIn("_None._", markdown)
            self.assertIn("_No decision-bearing signal rows._", markdown)

            with self.assertRaises(FileNotFoundError):
                load_jsonl_events(Path(tmpdir) / "missing.jsonl")

    def test_signal_and_status_fallback_paths_are_attributed(self) -> None:
        direct = "lpfs:EURCHF:H8:299:long:signal_zone_0p5_pullback__fs_structure__1r:2026-05-05 21:00:00+00:00"
        decision = "lpfs:GBPCAD:H12:299:long:signal_zone_0p5_pullback__fs_structure__1r:2026-05-05 21:00:00+00:00"
        skipped = "lpfs:NZDCHF:W1:299:short:signal_zone_0p5_pullback__fs_structure__1r:2026-04-25 21:00:00+00:00"
        rows = [
            {"event": "market_snapshot", "occurred_at_utc": "2026-05-05T00:00:00+00:00", "signal_key": direct},
            {"event": "unknown", "occurred_at_utc": "2026-05-05T00:00:00+00:00", "signal_key": direct},
            {
                "event": "setup_rejected",
                "notification_event": {
                    "status": "spread_too_wide_before_send",
                    "signal_key": direct,
                    "occurred_at_utc": "2026-05-04T02:00:00",
                },
            },
            _notification_row("order_sent", direct, status="pending", occurred_at_utc="2026-05-04T02:05:00+00:00"),
            _notification_row("order_adopted", direct, status="adopted", occurred_at_utc="2026-05-04T02:06:00+00:00"),
            _notification_row("market_recovery_sent", direct, status="open", occurred_at_utc="2026-05-04T02:07:00+00:00"),
            {
                "event": "order_intent_created",
                "occurred_at_utc": "2026-05-05T00:00:00+00:00",
                "decision": {"status": "ready", "rejection_reason": "", "intent": {"signal_key": decision}},
            },
            {
                "event": "order_rejected",
                "occurred_at_utc": "2026-05-05T00:01:00+00:00",
                "decision": {"status": "rejected", "rejection_reason": "risk_limit", "intent": {"signal_key": decision}},
            },
            {
                "event": "setup_skipped",
                "occurred_at_utc": "2026-05-05T00:02:00+00:00",
                "skipped": {"signal_key": skipped, "skip_reason": "entry_not_reached"},
            },
            {
                "event": "setup_skipped",
                "occurred_at_utc": "2026-05-05T00:03:00+00:00",
                "skipped": {"signal_key": skipped, "reason": "wrong_side_close"},
            },
            {
                "event": "setup_skipped",
                "occurred_at_utc": "2026-05-05T00:04:00+00:00",
                "skipped": {"signal_key": skipped, "status": "expired"},
            },
        ]

        report = build_gate_attribution_report(rows, source="fallbacks")
        markdown = render_gate_attribution_markdown([report], detail_limit=0)

        self.assertEqual(report.detected_setups, 3)
        self.assertEqual(report.placed_orders, 2)
        self.assertEqual(report.market_recoveries, 1)
        self.assertEqual(report.adopted_orders, 1)
        self.assertEqual(report.spread_waits, 1)
        self.assertEqual(report.later_placements_after_spread_wait, 1)
        self.assertIn("later placement after spread wait", markdown)
        self.assertIn("1 market recovery", markdown)
        self.assertIn("1 adopted", markdown)
        self.assertIn("risk_limit", report.status_counts)
        self.assertIn("entry_not_reached", report.status_counts)

    def test_private_edge_helpers_cover_boundaries(self) -> None:
        signal_key = "lpfs:EURCHF:H8:299:long:signal_zone_0p5_pullback__fs_structure__1r:2026-05-05 21:00:00+00:00"
        build_gate_attribution_report([{}], source="blank-row")
        summary = gate_module._build_signal_summary(
            signal_key,
            [
                {"event": "", "notification_event": {"status": "", "signal_key": signal_key}},
                {"event": "setup_rejected", "notification_event": {"status": "spread_too_wide", "signal_key": signal_key}},
                {
                    "event": "setup_rejected",
                    "occurred_at_utc": "2026-05-03T22:00:00+00:00",
                    "notification_event": {"status": "market_recovery_spread_too_wide", "signal_key": signal_key},
                },
                {"event": "setup_rejected", "notification_event": {"status": "market_closed", "signal_key": signal_key}},
                {"event": "order_sent", "notification_event": {"status": "", "signal_key": signal_key}},
            ],
            weekly_open_window_hours=12,
        )
        self.assertEqual(summary.spread_waits, 1)
        self.assertEqual(summary.market_recovery_spread_waits, 1)
        self.assertEqual(summary.broker_session_waits, 1)
        self.assertEqual(summary.weekly_open_waits, 1)

        self.assertEqual(gate_module._row_signal_key({}), "")
        self.assertEqual(gate_module._row_signal_key({"notification_event": {}, "decision": {"intent": "bad"}}), "")
        self.assertEqual(gate_module._row_signal_key({"decision": {"intent": {}}}), "")
        self.assertEqual(gate_module._row_signal_key({"skipped": {}}), "")
        self.assertEqual(gate_module._row_status({}), "")
        self.assertEqual(gate_module._row_status({"notification_event": {}, "decision": {"status": "ready"}}), "ready")
        self.assertEqual(gate_module._row_status({"skipped": {}}), "")
        self.assertIsNone(gate_module._row_timestamp({}))
        self.assertFalse(gate_module._is_decision_signal_row({}, ""))
        self.assertFalse(gate_module._is_decision_signal_row({"event": "signal_already_processed"}, signal_key))
        self.assertFalse(gate_module._is_decision_signal_row({"event": "market_snapshot"}, signal_key))
        self.assertFalse(gate_module._is_decision_signal_row({"event": "not_a_gate"}, signal_key))
        self.assertEqual(gate_module._signal_part("too:short", 5), "")
        self.assertLess(gate_module._timestamp_or_min(""), pd.Timestamp("1900-01-01", tz="UTC"))
        self.assertFalse(gate_module._is_weekly_open_window(None, hours=12))
        self.assertFalse(gate_module._is_weekly_open_window(pd.Timestamp("2026-05-03T22:00:00Z"), hours=0))
        self.assertTrue(gate_module._is_weekly_open_window(pd.Timestamp("2026-05-03T22:00:00Z"), hours=12))
        self.assertFalse(gate_module._is_weekly_open_window(pd.Timestamp("2026-05-03T20:00:00Z"), hours=12))
        self.assertFalse(gate_module._is_weekly_open_window(pd.Timestamp("2026-05-05T22:00:00Z"), hours=12))


def _notification_row(
    event: str,
    signal_key: str,
    *,
    status: str,
    occurred_at_utc: str = "2026-05-05T00:00:00+00:00",
) -> dict[str, object]:
    parts = signal_key.split(":")
    return {
        "event": event,
        "occurred_at_utc": occurred_at_utc,
        "signal_key": signal_key,
        "notification_event": {
            "kind": event,
            "status": status,
            "signal_key": signal_key,
            "symbol": parts[1],
            "timeframe": parts[2],
            "side": parts[4],
            "fields": {},
        },
    }


if __name__ == "__main__":
    unittest.main()
