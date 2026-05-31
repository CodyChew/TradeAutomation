from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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

from lp_force_strike_strategy_lab.live_trade_summary import (  # noqa: E402
    build_closed_trade_summaries,
    build_recent_trade_summary_message,
    load_live_journal_events,
)
import lp_force_strike_strategy_lab.live_trade_summary as summary_module  # noqa: E402


def _journal_row(kind: str, *, fields: dict, symbol: str = "EURUSD", side: str = "long") -> dict:
    return {
        "event": kind,
        "notification_event": {
            "kind": kind,
            "mode": "LIVE",
            "title": kind,
            "severity": "info",
            "symbol": symbol,
            "timeframe": "H4",
            "side": side,
            "status": "",
            "signal_key": f"lpfs:{symbol}:H4:10:{side}:c:2026-01-01T00:00:00Z",
            "message": "",
            "occurred_at_utc": "",
            "fields": fields,
        },
    }


def _write_snapshot(
    path: Path,
    rows: list[dict],
    *,
    reached_source_start: bool = True,
    first_event_timestamp: str = "2026-01-01T00:00:00+00:00",
) -> None:
    snapshot = ("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8")
    path.write_bytes(snapshot)
    manifest = {
        "schema_version": 1,
        "snapshots": [
            {
                "snapshot_filename": path.name,
                "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
                "snapshot_bytes": len(snapshot),
                "reached_source_start": reached_source_start,
                "first_event_timestamp": first_event_timestamp,
            }
        ],
    }
    (path.parent / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class LiveTradeSummaryTests(unittest.TestCase):
    def test_summary_pairs_lifecycle_events_and_formats_recent_trades(self) -> None:
        events = [
            _journal_row(
                "order_sent",
                fields={"order_ticket": 9001, "entry": 1.1, "volume": 0.02, "price_digits": 5},
            ),
            _journal_row(
                "position_opened",
                fields={
                    "position_id": 7001,
                    "order_ticket": 9001,
                    "fill_price": 1.1,
                    "volume": 0.02,
                    "opened_utc": "2026-05-01T14:00:00+00:00",
                    "price_digits": 5,
                },
            ),
            _journal_row(
                "take_profit_hit",
                fields={
                    "position_id": 7001,
                    "deal_ticket": 3001,
                    "entry": 1.1,
                    "close_price": 1.105,
                    "volume": 0.02,
                    "close_profit": 12.34,
                    "r_result": 1.0,
                    "opened_utc": "2026-05-01T14:00:00+00:00",
                    "closed_utc": "2026-05-01T22:15:00+00:00",
                    "price_digits": 5,
                },
            ),
            _journal_row(
                "position_opened",
                fields={
                    "position_id": 7002,
                    "fill_price": 0.8801,
                    "volume": 0.03,
                    "opened_utc": "2026-05-01T10:00:00+00:00",
                },
                symbol="AUDCAD",
                side="short",
            ),
            _journal_row(
                "stop_loss_hit",
                fields={
                    "position_id": 7002,
                    "deal_ticket": 3002,
                    "entry": 0.8801,
                    "close_price": 0.8841,
                    "volume": 0.03,
                    "close_profit": -8.0,
                    "r_result": -1.0,
                    "opened_utc": "2026-05-01T10:00:00+00:00",
                    "closed_utc": "2026-05-01T11:00:00+00:00",
                },
                symbol="AUDCAD",
                side="short",
            ),
            {"event": "old_sparse_row"},
        ]

        trades = build_closed_trade_summaries(events)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].position_id, 7001)
        self.assertEqual(trades[0].close_kind, "TAKE PROFIT")

        message = build_recent_trade_summary_message(events=events, limit=5)
        self.assertIn("LPFS LIVE | PERFORMANCE SUMMARY", message)
        self.assertIn("Period: Latest 5 closed trades | Closed trades 2", message)
        self.assertIn("Win rate: 50.0% | Wins 1 | Losses 1 | Flat 0", message)
        self.assertIn("Net PnL +4.34 | Total +0.00R | Avg +0.00R", message)
        self.assertIn("Profit factor: 1.00 | Best +1.00R | Worst -1.00R", message)
        self.assertIn("Avg win +1.00R | Avg loss -1.00R | Avg hold 4h 37m", message)
        self.assertIn("Exit mix: TP 1 | SL 1", message)
        self.assertIn("By side: Long 1 | Short 1", message)
        self.assertIn("By TF: H4 2", message)
        self.assertNotIn("1) EURUSD H4 LONG", message)

        detail_message = build_recent_trade_summary_message(events=events, limit=5, include_trades=True)
        self.assertIn("1) EURUSD H4 LONG | TAKE PROFIT | +1.00R | +12.34", detail_message)
        self.assertIn("Entry 1.10000 -> Exit 1.10500 | Size 0.02", detail_message)
        self.assertIn("Hold 8h 15m | Closed 2026-05-02 06:15 SGT", detail_message)

        empty = build_recent_trade_summary_message(events=[], limit=5)
        self.assertIn("No closed trades found", empty)

    def test_summary_pairs_adopted_orders_and_manual_closes(self) -> None:
        events = [
            _journal_row(
                "order_adopted",
                fields={"order_ticket": 9003, "entry": 1.2, "volume": 0.01, "price_digits": 5},
                symbol="GBPUSD",
            ),
            _journal_row(
                "position_opened",
                fields={"position_id": 7003, "order_ticket": 9003, "opened_utc": "2026-05-01T10:00:00+00:00"},
                symbol="GBPUSD",
            ),
            _journal_row(
                "position_closed",
                fields={
                    "position_id": 7003,
                    "deal_ticket": 3003,
                    "close_price": 1.202,
                    "close_profit": 4.0,
                    "r_result": 0.4,
                    "closed_utc": "2026-05-01T11:00:00+00:00",
                },
                symbol="GBPUSD",
            ),
        ]

        trades = build_closed_trade_summaries(events)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].close_kind, "TRADE CLOSED")
        self.assertEqual(trades[0].entry_price, 1.2)
        message = build_recent_trade_summary_message(events=events, limit=5)
        self.assertIn("Exit mix: TP 0 | SL 0 | Other 1", message)

    def test_summary_filters_by_days_and_weeks_without_trade_list(self) -> None:
        recent_trade = summary_module.LPFSLiveClosedTrade(
            symbol="GBPJPY",
            timeframe="H12",
            side="LONG",
            close_kind="TAKE PROFIT",
            position_id=1,
            deal_ticket=10,
            entry_price=1.0,
            close_price=1.1,
            volume=0.01,
            close_profit=10.0,
            r_result=1.0,
            opened_utc="2026-05-04T00:00:00+00:00",
            closed_utc="2026-05-04T12:00:00+00:00",
            signal_key="",
        )
        old_trade = summary_module.LPFSLiveClosedTrade(
            symbol="EURCAD",
            timeframe="H8",
            side="SHORT",
            close_kind="STOP LOSS",
            position_id=2,
            deal_ticket=20,
            entry_price=1.0,
            close_price=0.9,
            volume=0.01,
            close_profit=-7.0,
            r_result=-1.0,
            opened_utc="2026-04-20T00:00:00+00:00",
            closed_utc="2026-04-20T12:00:00+00:00",
            signal_key="",
        )

        days_message = build_recent_trade_summary_message(
            trades=[recent_trade, old_trade],
            days=7,
            now_utc="2026-05-05T00:00:00+00:00",
        )
        self.assertIn("Period: 7 days | Closed trades 1", days_message)
        self.assertIn("Profit factor: no losses", days_message)
        self.assertNotIn("1) GBPJPY", days_message)

        weeks_message = build_recent_trade_summary_message(
            trades=[recent_trade, old_trade],
            weeks=3,
            now_utc="2026-05-05T00:00:00+00:00",
        )
        self.assertIn("Period: 3 weeks | Closed trades 2", weeks_message)
        self.assertIn("By TF: H8 1 | H12 1", weeks_message)

    def test_summary_loads_jsonl_and_script_prints_without_posting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = Path(tmpdir) / "journal.jsonl"
            rows = [
                _journal_row("position_opened", fields={"position_id": 1, "opened_utc": "2026-01-01T00:00:00+00:00"}),
                _journal_row(
                    "take_profit_hit",
                    fields={
                        "position_id": 1,
                        "entry": 1.1,
                        "close_price": 1.2,
                        "volume": 0.01,
                        "close_profit": 1.0,
                        "r_result": 1.0,
                        "opened_utc": "2026-01-01T00:00:00+00:00",
                        "closed_utc": "2026-01-01T01:00:00+00:00",
                    },
                ),
            ]
            journal.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            loaded = load_live_journal_events(journal)
            self.assertEqual(len(loaded), 2)
            journal.write_text("\n\n".join(json.dumps(row) for row in rows) + "\n\n", encoding="utf-8")
            self.assertEqual(len(load_live_journal_events(journal)), 2)
            with self.assertRaises(FileNotFoundError):
                load_live_journal_events(Path(tmpdir) / "missing.jsonl")
            _write_snapshot(journal, rows)

            result = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_ROOT / "scripts" / "summarize_lpfs_live_trades.py"),
                    "--config",
                    str(Path(tmpdir) / "missing-config.json"),
                    "--journal-snapshot",
                    str(journal),
                    "--limit",
                    "1",
                ],
                cwd=WORKSPACE_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LPFS LIVE | PERFORMANCE SUMMARY", result.stdout)
            self.assertIn("Closed trades 1", result.stdout)

            detail_result = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_ROOT / "scripts" / "summarize_lpfs_live_trades.py"),
                    "--journal-snapshot",
                    str(journal),
                    "--include-trades",
                    "--limit",
                    "1",
                ],
                cwd=WORKSPACE_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(detail_result.returncode, 0, detail_result.stderr)
            self.assertIn("LPFS LIVE | PERFORMANCE SUMMARY", detail_result.stdout)
            self.assertIn("1) EURUSD H4 LONG", detail_result.stdout)

            runtime_result = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_ROOT / "scripts" / "summarize_lpfs_live_trades.py"),
                    "--journal-snapshot",
                    str(journal),
                    "--runtime-root",
                    str(Path(tmpdir) / "runtime"),
                ],
                cwd=WORKSPACE_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(runtime_result.returncode, 2)
            self.assertIn("unrecognized arguments: --runtime-root", runtime_result.stderr)

            journal_result = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_ROOT / "scripts" / "summarize_lpfs_live_trades.py"),
                    "--journal-snapshot",
                    str(journal),
                    "--journal",
                    str(journal),
                ],
                cwd=WORKSPACE_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(journal_result.returncode, 2)
            self.assertIn("unrecognized arguments: --journal", journal_result.stderr)

    def test_summary_script_rejects_missing_manifest_tampering_and_unproven_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = Path(tmpdir) / "journal.jsonl"
            rows = [_journal_row("position_opened", fields={"position_id": 1})]
            journal.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            missing_manifest = self._run_summary(journal)
            self.assertEqual(missing_manifest.returncode, 2)
            self.assertIn("Collector manifest not found", missing_manifest.stderr)

            _write_snapshot(journal, rows)
            journal.write_text('{"event":"tampered"}\n', encoding="utf-8")
            tampered = self._run_summary(journal)
            self.assertEqual(tampered.returncode, 2)
            self.assertIn("SHA-256", tampered.stderr)

            _write_snapshot(
                journal,
                rows,
                reached_source_start=False,
                first_event_timestamp="2999-01-01T00:00:00+00:00",
            )
            truncated = self._run_summary(journal, "--days", "7")
            self.assertEqual(truncated.returncode, 2)
            self.assertIn("cannot prove coverage", truncated.stderr)

    def test_summary_posting_passes_the_printed_message_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = Path(tmpdir) / "journal.jsonl"
            rows = [
                _journal_row("position_opened", fields={"position_id": 1}),
                _journal_row(
                    "take_profit_hit",
                    fields={"position_id": 1, "close_profit": 1.0, "r_result": 1.0},
                ),
            ]
            _write_snapshot(journal, rows)
            script_path = WORKSPACE_ROOT / "scripts" / "summarize_lpfs_live_trades.py"
            spec = importlib.util.spec_from_file_location("summary_script", script_path)
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            sent: list[str] = []

            class Notifier:
                def send_message(self, message: str) -> SimpleNamespace:
                    sent.append(message)
                    return SimpleNamespace(sent=True, error="", status="sent")

            with (
                mock.patch.object(module, "load_live_send_settings", return_value=object()),
                mock.patch.object(module, "telegram_notifier_from_settings", return_value=(Notifier(), None)),
                mock.patch.object(
                    sys,
                    "argv",
                    [str(script_path), "--journal-snapshot", str(journal), "--post-telegram"],
                ),
            ):
                self.assertEqual(module.main(), 0)

            self.assertEqual(sent, [build_recent_trade_summary_message(events=rows)])

    def _run_summary(self, journal: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(WORKSPACE_ROOT / "scripts" / "summarize_lpfs_live_trades.py"),
                "--journal-snapshot",
                str(journal),
                *extra_args,
            ],
            cwd=WORKSPACE_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_summary_private_fallback_branches(self) -> None:
        events = [
            _journal_row("order_sent", fields={"order_ticket": None}),
            _journal_row("position_opened", fields={"position_id": None}),
            _journal_row("executor_error", fields={}),
            {
                "notification_event": {
                    "kind": "take_profit_hit",
                    "mode": "LIVE",
                    "title": "TP",
                    "severity": "info",
                    "symbol": "",
                    "timeframe": "",
                    "side": "",
                    "status": "",
                    "signal_key": "lpfs:GBPJPY:H12:20:short:c:2026-01-01T00:00:00Z",
                    "message": "",
                    "occurred_at_utc": "",
                    "fields": {
                        "position_id": 9001,
                        "close_price": 151.1234,
                        "close_profit": 5.0,
                        "closed_utc": "bad",
                    },
                }
            },
        ]

        trades = build_closed_trade_summaries(events)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].symbol, "GBPJPY")
        self.assertEqual(trades[0].timeframe, "H12")
        self.assertEqual(trades[0].side, "SHORT")

        profit_only = summary_module.LPFSLiveClosedTrade(
            symbol="",
            timeframe="",
            side="",
            close_kind="TAKE PROFIT",
            position_id=None,
            deal_ticket=None,
            entry_price=None,
            close_price=None,
            volume=None,
            close_profit=3.0,
            r_result=None,
            opened_utc=None,
            closed_utc=None,
            signal_key="",
        )
        flat_unknown = summary_module.LPFSLiveClosedTrade(
            symbol="",
            timeframe="",
            side="",
            close_kind="STOP LOSS",
            position_id=None,
            deal_ticket=None,
            entry_price=None,
            close_price=None,
            volume=None,
            close_profit=None,
            r_result=None,
            opened_utc=None,
            closed_utc=None,
            signal_key="",
        )
        message = build_recent_trade_summary_message(trades=[profit_only, flat_unknown], limit=2, include_trades=True)
        self.assertIn("Win rate: 50.0% | Wins 1 | Losses 0 | Flat 1", message)
        self.assertIn("Net PnL +3.00 | Total n/a | Avg n/a", message)
        self.assertIn("n/a | TAKE PROFIT | n/a | +3.00", message)

        self.assertEqual(summary_module._signal_part({"signal_key": "manual"}, 1), "")
        self.assertEqual(summary_module._timestamp_sort_key(None), summary_module._timestamp_sort_key("bad"))
        self.assertEqual(summary_module._first_text(None, ""), None)
        self.assertEqual(summary_module._first_float(None, "bad"), None)
        self.assertEqual(summary_module._first_int(None, "bad"), None)
        self.assertEqual(summary_module._safe_float(""), None)
        self.assertEqual(summary_module._safe_int(""), None)
        with self.assertRaisesRegex(ValueError, "either days or weeks"):
            build_recent_trade_summary_message(trades=[profit_only], days=1, weeks=1)
        with self.assertRaisesRegex(ValueError, "days must be positive"):
            build_recent_trade_summary_message(trades=[profit_only], days=0)
        with self.assertRaisesRegex(ValueError, "weeks must be positive"):
            build_recent_trade_summary_message(trades=[profit_only], weeks=0)

        all_message = build_recent_trade_summary_message(trades=[profit_only], limit=0)
        self.assertIn("Period: All closed trades | Closed trades 1", all_message)

        now_default_message = build_recent_trade_summary_message(trades=[profit_only], days=1)
        self.assertIn("Period: 1 day", now_default_message)
        self.assertEqual(summary_module._percent_text(1, 0), "n/a")
        self.assertEqual(summary_module._duration_text(90000), "1d 1h")
        self.assertEqual(summary_module._duration_text(7200), "2h 0m")
        self.assertEqual(summary_module._duration_text(60), "1m")
        self.assertEqual(summary_module._counter_text(Counter({"d1": 2, "h4": 1}), ("h4",)), "H4 1 | D1 2")


if __name__ == "__main__":
    unittest.main()
