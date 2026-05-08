from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import build_lpfs_live_weekly_performance as weekly  # noqa: E402
from lp_force_strike_dashboard_metadata import dashboard_page_links  # noqa: E402


def _repo_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE_ROOT, text=True).strip()


def _row(kind: str, occurred: str, **fields: object) -> dict[str, object]:
    return {
        "occurred_at_utc": occurred,
        "event_key": fields.pop("event_key", kind),
        "notification_event": {
            "kind": kind,
            "symbol": fields.pop("symbol", "EURNZD"),
            "timeframe": fields.pop("timeframe", "H8"),
            "side": fields.pop("side", "SHORT"),
            "signal_key": fields.pop("signal_key", "EURNZD-H8-1-short"),
            "status": fields.pop("status", ""),
            "fields": dict(fields),
        },
    }


def _closed_trade_rows(
    *,
    signal_key: str,
    symbol: str,
    timeframe: str,
    side: str,
    order_time: str,
    close_time: str,
    r_result: float,
    profit: float,
    ticket: int,
    position_id: int,
) -> list[dict[str, object]]:
    return [
        _row(
            "order_sent",
            order_time,
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            signal_key=signal_key,
            order_ticket=ticket,
            entry=1.1000,
        ),
        _row(
            "position_opened",
            order_time,
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            signal_key=signal_key,
            order_ticket=ticket,
            position_id=position_id,
            fill_price=1.1000,
            volume=0.10,
            opened_utc=order_time,
        ),
        _row(
            "take_profit_hit" if r_result > 0 else "stop_loss_hit",
            close_time,
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            signal_key=signal_key,
            position_id=position_id,
            deal_ticket=position_id + 1000,
            close_price=1.1010,
            close_profit=profit,
            r_result=r_result,
            closed_utc=close_time,
        ),
    ]


def _benchmark_csv(path: Path) -> None:
    rows = [
        ("2026-01-06T00:00:00Z", "exclude_lp_pivot_inside_fs", -5.0),
        ("2026-01-13T00:00:00Z", "exclude_lp_pivot_inside_fs", -2.0),
        ("2026-01-20T00:00:00Z", "exclude_lp_pivot_inside_fs", 1.0),
        ("2026-01-27T00:00:00Z", "exclude_lp_pivot_inside_fs", 3.0),
        ("2026-02-03T00:00:00Z", "control_current", -99.0),
    ]
    path.write_text(
        "exit_time_utc,separation_variant_id,commission_adjusted_net_r\n"
        + "\n".join(f"{time},{variant},{value}" for time, variant, value in rows)
        + "\n",
        encoding="utf-8",
    )


def _lane_input(tmp: Path, name: str, *, first_journal: str, first_order: str, close_r: float = -1.0) -> weekly.LaneInput:
    benchmark = tmp / f"{name.lower()}_benchmark.csv"
    _benchmark_csv(benchmark)
    head = _repo_head()
    events = [
        _row("runner_started", first_journal, signal_key=""),
        *_closed_trade_rows(
            signal_key=f"{name}-TRADE-1",
            symbol="EURNZD" if name == "FTMO" else "AUDCHF",
            timeframe="H8",
            side="SHORT" if name == "FTMO" else "LONG",
            order_time=first_order,
            close_time="2026-05-06T21:00:00Z",
            r_result=close_r,
            profit=close_r * 100.0,
            ticket=100 if name == "FTMO" else 200,
            position_id=1000 if name == "FTMO" else 2000,
        ),
        _row(
            "setup_rejected",
            "2026-05-06T22:00:00Z",
            signal_key=f"{name}-WAIT-1",
            status="spread_too_wide",
            event_key=f"setup_blocked:{name}-WAIT-1:spread_too_wide",
        ),
    ]
    return weekly.LaneInput(
        config=weekly.LaneConfig(
            name=name,
            ssh_alias=f"{name.lower()}-vps",
            journal_path="unused",
            state_path="unused",
            benchmark_path=benchmark,
            benchmark_label=f"{name} fixture benchmark",
        ),
        first_journal_row={"occurred_at_utc": first_journal},
        lifecycle_rows=events,
        state_payload={"pending_orders": [{"ticket": 1}], "active_positions": [], "processed_signal_keys": ["a", "b"]},
        vps_head=head,
    )


def _git_info(*, runtime_changed: bool = True) -> dict[str, object]:
    head = _repo_head()
    return {
        "local_head": head,
        "origin_head": head,
        "latest_runtime_commit_full": head,
        "latest_runtime_commit": f"{head[:7]} 2026-05-08T00:00:00+00:00 test runtime",
        "runtime_commits_in_window": ["94ffea1 2026-05-08T00:00:00+00:00 test patch"] if runtime_changed else [],
    }


class LiveWeeklyPerformanceTests(unittest.TestCase):
    def test_lane_start_detection_from_journal_rows(self) -> None:
        rows = [
            _row("runner_started", "2026-04-30T19:48:13Z", signal_key=""),
            _row("order_sent", "2026-04-30T19:48:18Z", order_ticket=1),
        ]
        start = weekly.lane_start_info({"occurred_at_utc": "2026-04-30T19:48:13Z"}, rows, [])

        self.assertEqual(start["first_journal_utc"], "2026-04-30T19:48:13+00:00")
        self.assertEqual(start["first_runner_utc"], "2026-04-30T19:48:13+00:00")
        self.assertEqual(start["first_order_utc"], "2026-04-30T19:48:18+00:00")

    def test_current_first_week_is_partial_for_ftmo_and_ic(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            as_of = weekly.parse_timestamp("2026-05-08T08:00:00Z")
            result = weekly.build_weekly_report(
                lane_inputs=[
                    _lane_input(tmp, "FTMO", first_journal="2026-04-30T19:48:13Z", first_order="2026-04-30T19:48:18Z"),
                    _lane_input(tmp, "IC", first_journal="2026-05-05T19:49:36Z", first_order="2026-05-05T19:49:45Z"),
                ],
                git_info=_git_info(runtime_changed=True),
                as_of_utc=as_of,
                report_root=tmp / "reports",
                docs_output=tmp / "docs" / "live_weekly_performance.html",
            )

        rows = {row["lane"]: row for row in result["weekly_summary"]}
        self.assertTrue(rows["FTMO"]["partial_week"])
        self.assertIn("week_in_progress", rows["FTMO"]["partial_reasons"])
        self.assertTrue(rows["IC"]["partial_week"])
        self.assertIn("portfolio_started_after_week_start", rows["IC"]["partial_reasons"])
        self.assertIn("journal_started_after_week_start", rows["IC"]["partial_reasons"])

    def test_runtime_change_in_week_downgrades_to_watch(self) -> None:
        row = {
            "lane": "FTMO",
            "partial_week": False,
            "runtime_changed_in_week": True,
            "runtime_synced": True,
            "net_r": 1.0,
            "worst_symbol": "EURNZD +1.00R",
            "worst_timeframe": "H8 +1.00R",
            "worst_side": "SHORT +1.00R",
        }
        flag = weekly.classify_week(row, {"p10_week_r": -2.0, "p05_week_r": -4.0, "weekly_r_values": [-4, -2, 0, 2]})

        self.assertEqual(flag["concern_status"], "watch")
        self.assertIn("runtime_changed_in_week", flag["concern_reasons"])

    def test_unchanged_inputs_keep_same_fingerprint_and_main_skips_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            lane = _lane_input(tmp, "FTMO", first_journal="2026-04-30T19:48:13Z", first_order="2026-04-30T19:48:18Z")
            args = [
                "build_lpfs_live_weekly_performance.py",
                "--latest",
                "--skip-git-fetch",
                "--as-of-utc",
                "2026-05-08T08:00:00Z",
                "--report-root",
                str(tmp / "reports"),
                "--docs-output",
                str(tmp / "docs" / "live_weekly_performance.html"),
            ]
            with mock.patch.object(weekly, "DEFAULT_LANES", [lane.config]), mock.patch.object(
                weekly, "safe_fetch_lane_input", return_value=lane
            ), mock.patch.object(weekly, "collect_git_info", return_value=_git_info(runtime_changed=True)), mock.patch.object(
                sys, "argv", args
            ):
                self.assertEqual(weekly.main(), 0)

            second = list(args)
            second[second.index("2026-05-08T08:00:00Z")] = "2026-05-08T09:00:00Z"
            with mock.patch.object(weekly, "DEFAULT_LANES", [lane.config]), mock.patch.object(
                weekly, "safe_fetch_lane_input", return_value=lane
            ), mock.patch.object(weekly, "collect_git_info", return_value=_git_info(runtime_changed=True)), mock.patch.object(
                sys, "argv", second
            ), mock.patch.object(weekly, "write_outputs") as write_outputs, contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(weekly.main(), 0)

            self.assertIn("already up to date", stdout.getvalue())
            write_outputs.assert_not_called()

    def test_historical_percentile_and_status_rules(self) -> None:
        benchmark = {"p10_week_r": -3.0, "p05_week_r": -4.0, "weekly_r_values": [-5.0, -3.0, 0.0, 2.0]}
        normal_row = {
            "lane": "FTMO",
            "partial_week": False,
            "runtime_changed_in_week": False,
            "runtime_synced": True,
            "net_r": 1.0,
            "worst_symbol": "EURNZD +1.00R",
            "worst_timeframe": "H8 +1.00R",
            "worst_side": "SHORT +1.00R",
        }
        watch = dict(normal_row, net_r=-3.0)
        review = dict(normal_row, net_r=-5.0)

        self.assertEqual(weekly.classify_week(normal_row, benchmark)["concern_status"], "normal")
        self.assertEqual(weekly.classify_week(watch, benchmark)["concern_status"], "watch")
        review_flag = weekly.classify_week(review, benchmark)
        self.assertEqual(review_flag["concern_status"], "review")
        self.assertEqual(review_flag["historical_percentile_band"], "<=p5")

    def test_generated_dashboard_contains_live_start_version_and_concern_context(self) -> None:
        run_summary = {
            "generated_at_utc": "2026-05-08T08:00:00+00:00",
            "output_dir": "reports/live_ops/lpfs_weekly_performance/test",
        }
        weekly_summary = [
            {
                "lane": "FTMO",
                "partial_week": True,
                "partial_reasons": "week_in_progress",
                "first_journal_utc": "2026-04-30T19:48:13+00:00",
                "first_runner_utc": "2026-04-30T19:48:13+00:00",
                "first_order_utc": "2026-04-30T19:48:18+00:00",
                "first_closed_trade_utc": "2026-05-06T21:00:00+00:00",
                "local_head": "abcdef0",
                "origin_head": "abcdef0",
                "vps_head": "abcdef0",
                "fetch_error": "",
                "latest_runtime_commit": "94ffea1 2026-05-08T00:00:00+00:00 test",
                "runtime_synced": True,
                "runtime_changed_in_week": True,
                "closed_trades": 1,
                "net_r": -1.0,
                "net_pnl": -100.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "worst_symbol": "EURNZD -1.00R",
                "worst_timeframe": "H8 -1.00R",
                "worst_side": "SHORT -1.00R",
                "retryable_waits": 1,
                "true_rejections": 0,
                "pending_orders": 1,
                "active_positions": 0,
            },
            {
                "lane": "IC",
                "partial_week": True,
                "partial_reasons": "portfolio_started_after_week_start",
                "first_journal_utc": "2026-05-05T19:49:36+00:00",
                "first_runner_utc": "2026-05-05T19:49:36+00:00",
                "first_order_utc": "2026-05-05T19:49:45+00:00",
                "first_closed_trade_utc": "",
                "local_head": "abcdef0",
                "origin_head": "abcdef0",
                "vps_head": "abcdef0",
                "fetch_error": "",
                "latest_runtime_commit": "94ffea1 2026-05-08T00:00:00+00:00 test",
                "runtime_synced": True,
                "runtime_changed_in_week": True,
                "closed_trades": 0,
                "net_r": 0.0,
                "net_pnl": 0.0,
                "win_rate": None,
                "profit_factor": None,
                "worst_symbol": "n/a",
                "worst_timeframe": "n/a",
                "worst_side": "n/a",
                "retryable_waits": 0,
                "true_rejections": 0,
                "pending_orders": 2,
                "active_positions": 1,
            },
        ]
        flags = [
            {
                "lane": "FTMO",
                "concern_status": "watch",
                "concern_reasons": "partial_week;runtime_changed_in_week",
                "net_r": -1.0,
                "historical_percentile": 25.0,
                "historical_percentile_band": "p25.0",
                "p10_week_r": -2.0,
                "p05_week_r": -4.0,
            },
            {
                "lane": "IC",
                "concern_status": "watch",
                "concern_reasons": "partial_week",
                "net_r": 0.0,
                "historical_percentile": 60.0,
                "historical_percentile_band": "p60.0",
                "p10_week_r": -1.0,
                "p05_week_r": -3.0,
            },
        ]
        html = weekly.build_dashboard_html(
            weekly_summary,
            [],
            [
                {
                    "lane": "FTMO",
                    "benchmark_label": "FTMO V22 separated commission-adjusted",
                    "historical_weeks": 4,
                    "avg_week_r": 0.0,
                    "median_week_r": 0.0,
                    "p10_week_r": -2.0,
                    "p05_week_r": -4.0,
                    "worst_week_r": -5.0,
                    "worst_week": "2026-01-05",
                },
                {
                    "lane": "IC",
                    "benchmark_label": "IC raw-spread V22 separated commission-adjusted",
                    "historical_weeks": 4,
                    "avg_week_r": 0.0,
                    "median_week_r": 0.0,
                    "p10_week_r": -1.0,
                    "p05_week_r": -3.0,
                    "worst_week_r": -4.0,
                    "worst_week": "2026-01-05",
                },
            ],
            flags,
            run_summary,
        )

        self.assertIn("LPFS Live Weekly Performance", html)
        self.assertIn("FTMO", html)
        self.assertIn("IC", html)
        self.assertIn("2026-04-30T19:48:13+00:00", html)
        self.assertIn("2026-05-05T19:49:45+00:00", html)
        self.assertIn("Runtime synced", html)
        self.assertIn("Cause For Concern", html)
        self.assertIn("WATCH", html)
        self.assertIn("normal, watch, or review-worthy", html)
        self.assertNotIn("<script", html.lower())

    def test_shared_navigation_includes_weekly_performance(self) -> None:
        nav = dashboard_page_links("live_weekly_performance.html")

        self.assertIn('href="live_weekly_performance.html"', nav)
        self.assertIn("Weekly Performance", nav)
        self.assertIn('class="page-link active"', nav)


if __name__ == "__main__":
    unittest.main()
