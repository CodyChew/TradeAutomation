from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPT = WORKSPACE_ROOT / "scripts" / "build_lpfs_skipped_opportunity_diagnostics.py"


class SkippedOpportunityDiagnosticsTests(unittest.TestCase):
    def test_cli_builds_volume_below_min_diagnostics_without_counting_closed_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            journal = tmp / "journal.jsonl"
            _write_jsonl(
                journal,
                [
                    _notification_row(
                        "lpfs:GBPNZD:D1:299:long:candidate:2026-07-01T00:00:00Z",
                        "volume_below_min",
                    ),
                    _decision_row(
                        "lpfs:GBPNZD:D1:299:long:candidate:2026-07-01T00:00:00Z",
                        "volume_below_min",
                        detail="raw_volume=0.006 rounded_volume=0 min=0.01",
                    ),
                    _notification_row(
                        "lpfs:EURUSD:H4:299:short:candidate:2026-07-01T04:00:00Z",
                        "spread_too_wide",
                    ),
                    _placement_row("lpfs:AUDUSD:H4:299:long:candidate:2026-07-01T08:00:00Z"),
                ],
            )

            result = _run_builder(journal, tmp / "reports")

            self.assertEqual(result.returncode, 0, result.stderr)
            output_dir = tmp / "reports" / "20260705_000000"
            volume_rows = _read_csv(output_dir / "volume_below_min_opportunities.csv")
            summary_rows = _read_csv(output_dir / "skipped_opportunity_summary.csv")
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            summary = (output_dir / "summary.md").read_text(encoding="utf-8")

            self.assertEqual(len(volume_rows), 1)
            volume = volume_rows[0]
            self.assertEqual(volume["rejection_reason"], "volume_below_min")
            self.assertEqual(volume["opportunity_class"], "strategy_relevant_untradeable_volume")
            self.assertEqual(volume["strategy_relevant"], "true")
            self.assertEqual(volume["counts_as_closed_trade"], "false")
            self.assertEqual(volume["include_in_closed_trade_performance"], "false")
            self.assertEqual(volume["raw_volume"], "0.006")
            self.assertEqual(volume["rounded_volume"], "0")
            self.assertEqual(volume["min_volume"], "0.01")
            self.assertEqual(volume["symbol"], "GBPNZD")
            self.assertEqual(volume["timeframe"], "D1")
            self.assertEqual(volume["side"], "LONG")
            self.assertEqual(volume["risk_atr"], "0.42")
            self.assertEqual(volume["fs_total_bars"], "3")

            summary_volume = next(row for row in summary_rows if row["rejection_reason"] == "volume_below_min")
            self.assertEqual(summary_volume["skipped_setups"], "1")
            self.assertEqual(summary_volume["strategy_relevant_skips"], "1")
            self.assertEqual(summary_volume["closed_trade_count_impact"], "0")
            self.assertEqual(summary_volume["live_change_authorized"], "false")

            self.assertEqual(manifest["scope"], "offline_read_only_skipped_opportunity_diagnostics")
            self.assertEqual(manifest["row_counts"]["volume_below_min_opportunities"], 1)
            self.assertEqual(manifest["classification"]["closed_trade_count_impact"], 0)
            self.assertIn("no_broker_mutation", manifest["non_actions"])
            self.assertIn("Skipped opportunities are not closed trades", summary)

    def test_retryable_broker_and_order_reject_rows_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            journal = tmp / "journal.jsonl"
            _write_jsonl(
                journal,
                [
                    _notification_row(
                        "lpfs:EURUSD:H4:299:short:candidate:2026-07-01T04:00:00Z",
                        "spread_too_wide",
                        event_key_prefix="setup_blocked",
                    ),
                    _event_row(
                        "order_check_failed",
                        "lpfs:EURJPY:H8:299:long:candidate:2026-07-01T00:00:00Z",
                        "risk_limit",
                    ),
                    _event_row(
                        "order_rejected",
                        "lpfs:CADJPY:H12:299:short:candidate:2026-07-01T04:00:00Z",
                        "broker_rejected",
                    ),
                ],
            )

            result = _run_builder(journal, tmp / "reports")

            self.assertEqual(result.returncode, 0, result.stderr)
            rows = _read_csv(tmp / "reports" / "20260705_000000" / "skipped_opportunity_events.csv")

            self.assertEqual(rows, [])

    def test_malformed_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            journal = tmp / "journal.jsonl"
            journal.write_text('{"event": "setup_rejected"}\n{bad json}\n', encoding="utf-8")

            result = _run_builder(journal, tmp / "reports")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("malformed JSONL row", result.stderr)

    def test_missing_journal_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            result = _run_builder(tmp / "missing.jsonl", tmp / "reports")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("journal not found", result.stderr)


def _run_builder(journal: Path, output_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--journal",
            f"IC={journal}",
            "--output-root",
            str(output_root),
            "--as-of-utc",
            "2026-07-05T00:00:00Z",
        ],
        cwd=WORKSPACE_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _decision_row(signal_key: str, reason: str, *, detail: str = "") -> dict[str, object]:
    parts = signal_key.split(":")
    return {
        "event": "setup_rejected",
        "occurred_at_utc": "2026-07-01T00:00:00+00:00",
        "signal_key": signal_key,
        "decision": {
            "status": "rejected",
            "rejection_reason": reason,
            "detail": detail,
        },
        "diagnostics": _diagnostics(parts),
    }


def _notification_row(signal_key: str, reason: str, *, event_key_prefix: str = "setup_rejected") -> dict[str, object]:
    parts = signal_key.split(":")
    return {
        "event": "setup_rejected",
        "event_key": f"{event_key_prefix}:{signal_key}:{reason}",
        "occurred_at_utc": "2026-07-01T00:01:00+00:00",
        "notification_event": {
            "kind": "setup_rejected",
            "mode": "LIVE",
            "status": reason,
            "signal_key": signal_key,
            "symbol": parts[1],
            "timeframe": parts[2],
            "side": parts[4],
            "fields": {"diagnostics": _diagnostics(parts)},
        },
    }


def _event_row(event: str, signal_key: str, reason: str) -> dict[str, object]:
    parts = signal_key.split(":")
    return {
        "event": event,
        "occurred_at_utc": "2026-07-01T00:03:00+00:00",
        "notification_event": {
            "kind": event,
            "mode": "LIVE",
            "status": reason,
            "signal_key": signal_key,
            "symbol": parts[1],
            "timeframe": parts[2],
            "side": parts[4],
            "fields": {"diagnostics": _diagnostics(parts)},
        },
    }


def _placement_row(signal_key: str) -> dict[str, object]:
    parts = signal_key.split(":")
    return {
        "event": "order_sent",
        "occurred_at_utc": "2026-07-01T00:02:00+00:00",
        "notification_event": {
            "kind": "order_sent",
            "mode": "LIVE",
            "signal_key": signal_key,
            "symbol": parts[1],
            "timeframe": parts[2],
            "side": parts[4],
        },
    }


def _diagnostics(parts: list[str]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "setup": {
            "setup_id": "synthetic_setup",
            "symbol": parts[1],
            "timeframe": parts[2],
            "side": parts[4],
            "entry_price": 1.2345,
            "stop_price": 1.22,
            "take_profit": 1.27,
            "risk_distance": 0.0145,
            "target_r": 2.5,
            "risk_atr": 0.42,
            "atr": 0.034,
            "fs_total_bars": 3,
            "bars_from_lp_break": 4,
        },
        "market": {"spread_points": 3},
        "spread_gate": {"spread_risk_fraction": 0.04},
        "strategy": {"risk_bucket_scale": 1.0},
        "execution": {"stage": "order_intent_created"},
        "backtest_join": {
            "signal_key": ":".join(parts),
            "setup_id": "synthetic_setup",
            "candidate_id": "candidate",
            "trade_key": "|".join(parts[1:5]),
        },
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
