from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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
        self.assertIn("LPFS LIVE | RECENT TRADE SUMMARY", message)
        self.assertIn("Trades: 2 | Wins 1 | Losses 1", message)
        self.assertIn("Net PnL +4.34 | Avg +0.00R", message)
        self.assertIn("Exit mix: TP 1 | SL 1", message)
        self.assertIn("1) EURUSD H4 LONG | TAKE PROFIT | +1.00R | +12.34", message)
        self.assertIn("Entry 1.10000 -> Exit 1.10500 | Size 0.02", message)
        self.assertIn("Hold 8h 15m | Closed 2026-05-02 06:15 SGT", message)

        empty = build_recent_trade_summary_message(events=[], limit=5)
        self.assertIn("No closed trades found", empty)

    def test_summary_loads_jsonl_and_script_prints_without_posting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = Path(tmpdir) / "journal.jsonl"
            config = Path(tmpdir) / "config.local.json"
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
            config.write_text(json.dumps({"live_send": {"journal_path": str(journal)}}), encoding="utf-8")

            loaded = load_live_journal_events(journal)
            self.assertEqual(len(loaded), 2)
            journal.write_text("\n\n".join(json.dumps(row) for row in rows) + "\n\n", encoding="utf-8")
            self.assertEqual(len(load_live_journal_events(journal)), 2)
            with self.assertRaises(FileNotFoundError):
                load_live_journal_events(Path(tmpdir) / "missing.jsonl")

            result = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_ROOT / "scripts" / "summarize_lpfs_live_trades.py"),
                    "--config",
                    str(config),
                    "--limit",
                    "1",
                ],
                cwd=WORKSPACE_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LPFS LIVE | RECENT TRADE SUMMARY", result.stdout)
            self.assertIn("Trades: 1 | Wins 1 | Losses 0", result.stdout)

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
        message = build_recent_trade_summary_message(trades=[profit_only, flat_unknown], limit=2)
        self.assertIn("Trades: 2 | Wins 1 | Losses 0", message)
        self.assertIn("Net PnL +3.00 | Avg n/a", message)
        self.assertIn("n/a | TAKE PROFIT | n/a | +3.00", message)

        self.assertEqual(summary_module._signal_part({"signal_key": "manual"}, 1), "")
        self.assertEqual(summary_module._timestamp_sort_key(None), summary_module._timestamp_sort_key("bad"))
        self.assertEqual(summary_module._first_text(None, ""), None)
        self.assertEqual(summary_module._first_float(None, "bad"), None)
        self.assertEqual(summary_module._first_int(None, "bad"), None)
        self.assertEqual(summary_module._safe_float(""), None)
        self.assertEqual(summary_module._safe_int(""), None)


if __name__ == "__main__":
    unittest.main()
