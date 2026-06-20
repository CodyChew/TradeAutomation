from __future__ import annotations

import contextlib
import csv
import base64
import io
import json
import shutil
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
    def test_default_max_source_bytes_documents_weekly_and_snapshot_conventions(self) -> None:
        self.assertEqual(weekly.SNAPSHOT_DEFAULT_MAX_SOURCE_BYTES, 64 * 1024 * 1024)
        self.assertEqual(weekly.DEFAULT_WEEKLY_MAX_SOURCE_BYTES, 128 * 1024 * 1024)
        self.assertEqual(weekly.DEFAULT_FETCH_TIMEOUT_SECONDS, 900)
        self.assertEqual(
            weekly.resolve_max_source_bytes(weekly.DEFAULT_WEEKLY_MAX_SOURCE_BYTES, allow_full_scan=False),
            128 * 1024 * 1024,
        )

    def test_full_scan_requires_explicit_allow_full_scan(self) -> None:
        with self.assertRaisesRegex(ValueError, "--max-source-bytes"):
            weekly.resolve_max_source_bytes(0, allow_full_scan=False)

        self.assertIsNone(weekly.resolve_max_source_bytes(0, allow_full_scan=True))

    def test_benchmark_paths_can_be_overridden_for_clean_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ftmo_path = tmp / "reviewed_ftmo_trades.csv"
            ic_path = tmp / "reviewed_ic_trades.csv"
            lanes = [
                weekly.LaneConfig(
                    name="FTMO",
                    ssh_alias="ftmo-vps",
                    journal_path="journal",
                    state_path="state",
                    benchmark_path=Path("missing-default-ftmo.csv"),
                    benchmark_label="ftmo",
                ),
                weekly.LaneConfig(
                    name="IC",
                    ssh_alias="ic-vps",
                    journal_path="journal",
                    state_path="state",
                    benchmark_path=Path("missing-default-ic.csv"),
                    benchmark_label="ic",
                ),
            ]

            configs = weekly.lane_configs_with_benchmark_paths(
                ftmo_benchmark_path=ftmo_path,
                ic_benchmark_path=ic_path,
                lanes=lanes,
            )

        self.assertEqual(configs[0].benchmark_path, ftmo_path)
        self.assertEqual(configs[1].benchmark_path, ic_path)
        self.assertEqual(configs[0].journal_path, "journal")
        self.assertEqual(configs[1].ssh_alias, "ic-vps")

    def test_missing_benchmark_error_mentions_explicit_path_options(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            missing = Path(raw_tmp) / "missing.csv"
            with self.assertRaisesRegex(FileNotFoundError, "--ftmo-benchmark-path.*--ic-benchmark-path"):
                weekly.historical_weekly_benchmark(missing)

    def test_main_uses_explicit_benchmark_path_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ftmo_benchmark = tmp / "ftmo.csv"
            ic_benchmark = tmp / "ic.csv"
            _benchmark_csv(ftmo_benchmark)
            _benchmark_csv(ic_benchmark)
            default_lanes = [
                weekly.LaneConfig(
                    name="FTMO",
                    ssh_alias="ftmo-vps",
                    journal_path="journal",
                    state_path="state",
                    benchmark_path=Path("missing-default-ftmo.csv"),
                    benchmark_label="ftmo",
                ),
                weekly.LaneConfig(
                    name="IC",
                    ssh_alias="ic-vps",
                    journal_path="journal",
                    state_path="state",
                    benchmark_path=Path("missing-default-ic.csv"),
                    benchmark_label="ic",
                ),
            ]
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
                "--ftmo-benchmark-path",
                str(ftmo_benchmark),
                "--ic-benchmark-path",
                str(ic_benchmark),
            ]
            captured_configs: list[weekly.LaneConfig] = []
            captured_max_source_bytes: list[int | None] = []
            captured_fetch_timeouts: list[int] = []

            def fake_fetch(
                config: weekly.LaneConfig,
                *,
                max_source_bytes: int | None,
                fetch_timeout_seconds: int,
                week_start_sgt: pd.Timestamp,
                week_end_sgt: pd.Timestamp,
            ) -> weekly.LaneInput:
                captured_configs.append(config)
                captured_max_source_bytes.append(max_source_bytes)
                captured_fetch_timeouts.append(fetch_timeout_seconds)
                return weekly.LaneInput(
                    config=config,
                    first_journal_row={"occurred_at_utc": "2026-04-30T19:48:13Z"},
                    lifecycle_rows=[],
                    state_payload={"pending_orders": [], "active_positions": [], "processed_signal_keys": []},
                    vps_head=_repo_head(),
                    fetch_metadata={"fetch_incomplete": True, "fetch_incomplete_reason": "fixture"},
                )

            with mock.patch.object(weekly, "DEFAULT_LANES", default_lanes), mock.patch.object(
                weekly, "safe_fetch_lane_input", side_effect=fake_fetch
            ), mock.patch.object(weekly, "collect_git_info", return_value=_git_info(runtime_changed=False)), mock.patch.object(
                sys, "argv", args
            ), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(weekly.main(), 0)

        self.assertEqual([config.benchmark_path for config in captured_configs], [ftmo_benchmark, ic_benchmark])
        self.assertEqual(captured_max_source_bytes, [weekly.DEFAULT_WEEKLY_MAX_SOURCE_BYTES, weekly.DEFAULT_WEEKLY_MAX_SOURCE_BYTES])
        self.assertEqual(captured_fetch_timeouts, [weekly.DEFAULT_FETCH_TIMEOUT_SECONDS, weekly.DEFAULT_FETCH_TIMEOUT_SECONDS])

    def test_fetch_classifies_transport_matches_by_parsed_event_kind(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            benchmark = tmp / "benchmark.csv"
            _benchmark_csv(benchmark)
            config = weekly.LaneConfig(
                name="FTMO",
                ssh_alias="ftmo-vps",
                journal_path="remote-journal",
                state_path="remote-state",
                benchmark_path=benchmark,
                benchmark_label="fixture",
            )
            week_start, week_end = weekly.latest_sgt_week_window(weekly.parse_timestamp("2026-05-16T02:00:00Z"))
            transport_rows = [
                json.dumps({"event": "runner_started", "occurred_at_utc": "2026-05-03T21:00:00Z"}),
                json.dumps(
                    {
                        "event": "operator_note",
                        "occurred_at_utc": "2026-05-10T21:00:00Z",
                        "message": "take_profit_hit appears in free text only",
                    }
                ),
                json.dumps(
                    _row(
                        "take_profit_hit",
                        "2026-05-11T22:00:00Z",
                        signal_key="FTMO-TRADE-1",
                        r_result=1.0,
                        close_profit=100.0,
                        closed_utc="2026-05-11T22:00:00Z",
                    )
                ),
            ]

            with mock.patch.object(
                weekly,
                "fetch_remote_lane_text",
                return_value=(
                    transport_rows[0],
                    transport_rows,
                    json.dumps({"pending_orders": [{"ticket": 1}], "active_positions": []}),
                    _repo_head(),
                    {
                        "reached_source_start": True,
                        "window_first_row_utc": "2026-05-03T21:00:00Z",
                        "window_last_row_utc": "2026-05-11T22:00:00Z",
                        "source_size_bytes": 123,
                        "source_start_offset": 0,
                        "source_end_offset": 123,
                    },
                ),
            ):
                lane = weekly.fetch_lane_input(
                    config,
                    max_source_bytes=weekly.DEFAULT_WEEKLY_MAX_SOURCE_BYTES,
                    week_start_sgt=week_start,
                    week_end_sgt=week_end,
                )

        self.assertEqual([weekly.weekly_row_kind(row) for row in lane.lifecycle_rows], ["runner_started", "take_profit_hit"])
        self.assertEqual(lane.fetch_metadata["transport_matched_lifecycle_rows"], 3)
        self.assertEqual(lane.fetch_metadata["parsed_lifecycle_rows"], 2)
        self.assertEqual(lane.fetch_metadata["lifecycle_rows_filtered_out"], 1)
        self.assertFalse(lane.fetch_metadata["fetch_incomplete"])
        self.assertEqual(weekly.live_state_counts(lane.state_payload)["pending_orders"], 1)
        self.assertEqual(lane.vps_head, _repo_head())

    def test_bounded_window_before_week_start_proves_week_coverage(self) -> None:
        config = weekly.LaneConfig(
            name="FTMO",
            ssh_alias="ftmo-vps",
            journal_path="remote-journal",
            state_path="remote-state",
            benchmark_path=Path("unused.csv"),
            benchmark_label="fixture",
        )
        week_start, week_end = weekly.latest_sgt_week_window(weekly.parse_timestamp("2026-06-13T02:00:00Z"))
        with mock.patch.object(
            weekly,
            "fetch_remote_lane_text",
            return_value=(
                "",
                [json.dumps({"event": "take_profit_hit", "occurred_at_utc": "2026-06-10T12:00:00Z"})],
                '{"pending_orders":[],"active_positions":[]}',
                _repo_head(),
                {
                    "reached_source_start": False,
                    "window_first_row_utc": "2026-06-01T00:00:00Z",
                    "window_last_row_utc": "2026-06-13T01:00:00Z",
                    "source_size_bytes": 900,
                    "source_start_offset": 100,
                    "source_end_offset": 900,
                },
            ),
        ):
            lane = weekly.fetch_lane_input(
                config,
                max_source_bytes=weekly.DEFAULT_WEEKLY_MAX_SOURCE_BYTES,
                week_start_sgt=week_start,
                week_end_sgt=week_end,
            )

        self.assertFalse(lane.fetch_metadata["reached_source_start"])
        self.assertTrue(lane.fetch_metadata["week_coverage_proven"])
        self.assertFalse(lane.fetch_metadata["fetch_incomplete"])

    def test_remote_fetch_script_uses_bounded_substring_transport_filter(self) -> None:
        captured: dict[str, object] = {}

        def fake_ssh(alias: str, python_exe: str, script: str, payload_b64: str, *, timeout: int) -> str:
            captured["alias"] = alias
            captured["python_exe"] = python_exe
            captured["script"] = script
            captured["payload"] = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
            captured["timeout"] = timeout
            return "\n".join(
                [
                    "---META---",
                    json.dumps(
                        {
                            "reached_source_start": True,
                            "source_size_bytes": 20,
                            "source_start_offset": 0,
                            "source_end_offset": 20,
                            "window_first_row_utc": "2026-05-03T21:00:00Z",
                            "window_last_row_utc": "2026-05-11T22:00:00Z",
                        }
                    ),
                    "---FIRST---",
                    '{"event":"runner_started","occurred_at_utc":"2026-05-03T21:00:00Z"}',
                    "---WINDOW_FIRST---",
                    '{"event":"runner_started","occurred_at_utc":"2026-05-03T21:00:00Z"}',
                    "---WINDOW_LAST---",
                    '{"event":"take_profit_hit","occurred_at_utc":"2026-05-11T22:00:00Z"}',
                    "---LIFECYCLE---",
                    '{"event":"take_profit_hit","occurred_at_utc":"2026-05-11T22:00:00Z"}',
                    "---STATE---",
                    '{"pending_orders":[],"active_positions":[]}',
                    "---HEAD---",
                    "abcdef",
                ]
            )

        config = weekly.LaneConfig(
            name="FTMO",
            ssh_alias="ftmo-vps",
            journal_path=r"C:\journal.jsonl",
            state_path=r"C:\state.json",
            benchmark_path=Path("unused.csv"),
            benchmark_label="fixture",
        )
        with mock.patch.object(weekly, "ssh_remote_python", side_effect=fake_ssh):
            _, lifecycle, state_text, head, metadata = weekly.fetch_remote_lane_text(
                config,
                max_source_bytes=weekly.DEFAULT_WEEKLY_MAX_SOURCE_BYTES,
            )

        script = str(captured["script"])
        self.assertEqual(captured["alias"], "ftmo-vps")
        self.assertEqual(captured["python_exe"], r"C:\TradeAutomation\venv\Scripts\python.exe")
        self.assertEqual(captured["timeout"], weekly.DEFAULT_FETCH_TIMEOUT_SECONDS)
        self.assertIn("base64.b64decode", script)
        self.assertIn("CreateFileW", script)
        self.assertIn("file_share_write", script)
        self.assertEqual(captured["payload"]["scan_mode"], "bounded_suffix")
        self.assertEqual(captured["payload"]["max_source_bytes"], weekly.DEFAULT_WEEKLY_MAX_SOURCE_BYTES)
        self.assertIn("with open_shared_read_binary(journal) as handle:", script)
        self.assertIn("if pattern in line:", script)
        self.assertNotIn("New-Object byte[] ([Int32]$bytesToRead)", script)
        self.assertEqual(lifecycle, ['{"event":"take_profit_hit","occurred_at_utc":"2026-05-11T22:00:00Z"}'])
        self.assertEqual(state_text, '{"pending_orders":[],"active_positions":[]}')
        self.assertEqual(head, "abcdef")
        self.assertTrue(metadata["reached_source_start"])

    def test_remote_fetch_stops_at_captured_source_end_when_journal_grows(self) -> None:
        if shutil.which("powershell") is None:
            self.skipTest("PowerShell is required for the local remote-fetch script regression")
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            journal = tmp / "journal.jsonl"
            state = tmp / "state.json"
            journal.write_text(
                "\n".join(
                    [
                        '{"event":"runner_started","occurred_at_utc":"2026-05-03T21:00:00Z"}',
                        '{"event":"take_profit_hit","occurred_at_utc":"2026-05-11T22:00:00Z","event_key":"ORIGINAL"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            state.write_text('{"pending_orders":[],"active_positions":[]}', encoding="utf-8")
            appended = '{"event":"take_profit_hit","occurred_at_utc":"2030-01-01T00:00:00Z","event_key":"APPENDED"}'

            def run_script_locally(alias: str, python_exe: str, script: str, payload_b64: str, *, timeout: int) -> str:
                self.assertEqual(alias, "local")
                growth_script = script.replace(
                    "before = os.stat(journal)",
                    f"before = os.stat(journal)\nwith open({str(journal)!r}, 'ab') as _growth: _growth.write(({appended!r} + '\\n').encode('utf-8'))",
                    1,
                )
                completed = subprocess.run(
                    [sys.executable, "-", payload_b64],
                    input=growth_script,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
                if completed.returncode != 0:
                    raise AssertionError(completed.stderr)
                return completed.stdout

            config = weekly.LaneConfig(
                name="FTMO",
                ssh_alias="local",
                journal_path=str(journal),
                state_path=str(state),
                benchmark_path=Path("unused.csv"),
                benchmark_label="fixture",
                repo_root=str(WORKSPACE_ROOT),
            )
            with mock.patch.object(weekly, "ssh_remote_python", side_effect=run_script_locally):
                _, lifecycle, state_text, head, metadata = weekly.fetch_remote_lane_text(
                    config,
                    max_source_bytes=weekly.DEFAULT_WEEKLY_MAX_SOURCE_BYTES,
                )

        payload = "\n".join(lifecycle)
        self.assertIn("ORIGINAL", payload)
        self.assertNotIn("APPENDED", payload)
        self.assertNotIn("2030-01-01", payload)
        self.assertEqual(json.loads(state_text)["pending_orders"], [])
        self.assertEqual(head, _repo_head())
        self.assertTrue(metadata["source_changed_during_collection"])
        self.assertGreater(metadata["source_size_bytes_after"], metadata["source_size_bytes"])

    def test_ssh_powershell_sends_full_script_over_stdin_with_short_bootstrap(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["ssh"],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with mock.patch.object(subprocess, "run", return_value=completed) as run:
            output = weekly.ssh_powershell("ftmo-vps", "Write-Output 'ok'", timeout=12)

        self.assertEqual(output, "ok")
        args, kwargs = run.call_args
        self.assertEqual(args[0][0:2], ["ssh", "ftmo-vps"])
        self.assertIn("powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand", args[0][2])
        self.assertEqual(kwargs["input"], "Write-Output 'ok'")
        self.assertNotIn("Write-Output 'ok'", " ".join(args[0]))
        self.assertLess(len(args[0][2]), 260)

    def test_weekend_uses_latest_completed_trading_week(self) -> None:
        start, end = weekly.latest_sgt_week_window(weekly.parse_timestamp("2026-05-16T02:00:00Z"))

        self.assertEqual(start.isoformat(), "2026-05-11T05:00:00+08:00")
        self.assertEqual(end.isoformat(), "2026-05-16T05:00:00+08:00")

    def test_weekday_open_market_week_is_still_partial(self) -> None:
        start, end = weekly.latest_sgt_week_window(weekly.parse_timestamp("2026-05-13T02:00:00Z"))

        self.assertEqual(start.isoformat(), "2026-05-11T05:00:00+08:00")
        self.assertEqual(end.isoformat(), "2026-05-16T05:00:00+08:00")
        self.assertLess(weekly.parse_timestamp("2026-05-13T02:00:00Z").tz_convert(weekly.SGT), end)

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

    def test_bounded_window_after_week_start_marks_lane_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            as_of = weekly.parse_timestamp("2026-05-16T02:00:00Z")
            lane = _lane_input(tmp, "FTMO", first_journal="2026-05-03T21:00:00Z", first_order="2026-05-04T21:00:00Z")
            lane = weekly.LaneInput(
                config=lane.config,
                first_journal_row=None,
                lifecycle_rows=[],
                state_payload=lane.state_payload,
                vps_head=lane.vps_head,
                fetch_metadata={
                    "fetch_incomplete": True,
                    "week_coverage_proven": False,
                    "reached_source_start": False,
                    "window_first_row_utc": "2026-05-12T00:00:00Z",
                    "first_live_metadata_unavailable": True,
                },
            )
            result = weekly.build_weekly_report(
                lane_inputs=[lane],
                git_info=_git_info(runtime_changed=False),
                as_of_utc=as_of,
                report_root=tmp / "reports",
                docs_output=tmp / "docs" / "live_weekly_performance.html",
            )

        row = result["weekly_summary"][0]
        self.assertTrue(row["fetch_incomplete"])
        self.assertIn("lane_fetch_incomplete", row["partial_reasons"])
        self.assertFalse(row["analysis_eligible"])
        self.assertEqual(row["performance_confidence"], "incomplete")
        self.assertEqual(row["coverage_status"], "incomplete")
        self.assertEqual(row["coverage_failure_reason"], "bounded_window_after_week_start")
        self.assertEqual(row["closed_trades_display"], "incomplete")
        self.assertIsNone(row["closed_trades"])
        self.assertEqual(row["known_fetched_closed_trades"], 0)
        self.assertEqual(row["completed_full_live_weeks"], "")
        self.assertEqual(row["consistency_history_status"], "unavailable")
        self.assertEqual(row["consistency_history_reason"], "lane_fetch_incomplete")
        flag = result["weekly_flags"][0]
        self.assertEqual(flag["concern_status"], "review")
        self.assertFalse(flag["analysis_eligible"])
        self.assertEqual(flag["performance_confidence"], "incomplete")
        self.assertIn("lane_fetch_incomplete", flag["evidence_caveats"])
        html = weekly.build_dashboard_html(
            result["weekly_summary"],
            result["lane_breakdown"],
            result["historical_benchmark"],
            result["weekly_flags"],
            result["live_week_history"],
            result["consistency_flags"],
            result["run_summary"],
        )
        self.assertIn(">incomplete<", html)

    def test_complete_bounded_week_with_missing_first_live_metadata_marks_consistency_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            lane = _lane_input(tmp, "FTMO", first_journal="2026-05-03T21:00:00Z", first_order="2026-05-04T21:00:00Z")
            lane = weekly.LaneInput(
                config=lane.config,
                first_journal_row=None,
                lifecycle_rows=lane.lifecycle_rows,
                state_payload=lane.state_payload,
                vps_head=lane.vps_head,
                fetch_metadata={
                    "fetch_incomplete": False,
                    "week_coverage_proven": True,
                    "reached_source_start": False,
                    "first_live_metadata_unavailable": True,
                    "window_first_row_utc": "2026-05-03T21:00:00Z",
                },
            )
            result = weekly.build_weekly_report(
                lane_inputs=[lane],
                git_info=_git_info(runtime_changed=False),
                as_of_utc=weekly.parse_timestamp("2026-05-09T00:00:00Z"),
                report_root=tmp / "reports",
                docs_output=tmp / "docs" / "live_weekly_performance.html",
            )

        row = result["weekly_summary"][0]
        self.assertTrue(row["analysis_eligible"])
        self.assertEqual(row["coverage_status"], "complete")
        self.assertEqual(row["closed_trades"], 1)
        self.assertEqual(row["consistency_history_status"], "unavailable")
        self.assertEqual(
            row["consistency_history_reason"],
            weekly.CONSISTENCY_HISTORY_UNAVAILABLE_REASON,
        )
        self.assertEqual(row["completed_full_live_weeks"], "")

        flag = result["consistency_flags"][0]
        self.assertEqual(flag["consistency_status"], "unavailable")
        self.assertEqual(flag["completed_full_weeks"], "")
        self.assertEqual(flag["consistency_reasons"], weekly.CONSISTENCY_HISTORY_UNAVAILABLE_REASON)
        self.assertEqual(result["run_summary"]["lanes"][0]["consistency_history_status"], "unavailable")

        html = weekly.build_dashboard_html(
            result["weekly_summary"],
            result["lane_breakdown"],
            result["historical_benchmark"],
            result["weekly_flags"],
            result["live_week_history"],
            result["consistency_flags"],
            result["run_summary"],
        )
        self.assertIn("history unavailable", html)
        self.assertIn("first_live_metadata_unavailable_bounded_fetch", html)
        self.assertNotIn("no_completed_full_live_weeks", html)

    def test_incomplete_lane_with_fetched_closes_is_not_analysis_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ftmo = _lane_input(
                tmp,
                "FTMO",
                first_journal="2026-04-30T19:48:13Z",
                first_order="2026-04-30T19:48:18Z",
                close_r=1.25,
            )
            ftmo = weekly.LaneInput(
                config=ftmo.config,
                first_journal_row=ftmo.first_journal_row,
                lifecycle_rows=ftmo.lifecycle_rows,
                state_payload=ftmo.state_payload,
                vps_head=ftmo.vps_head,
                fetch_metadata={
                    "fetch_incomplete": True,
                    "week_coverage_proven": False,
                    "reached_source_start": False,
                    "window_first_row_utc": "2026-05-05T00:00:00Z",
                },
            )
            ic = _lane_input(
                tmp,
                "IC",
                first_journal="2026-04-30T19:48:13Z",
                first_order="2026-04-30T19:48:18Z",
                close_r=-0.50,
            )
            result = weekly.build_weekly_report(
                lane_inputs=[ftmo, ic],
                git_info=_git_info(runtime_changed=False),
                as_of_utc=weekly.parse_timestamp("2026-05-08T08:00:00Z"),
                report_root=tmp / "reports",
                docs_output=tmp / "docs" / "live_weekly_performance.html",
            )

        rows = {row["lane"]: row for row in result["weekly_summary"]}
        ftmo_row = rows["FTMO"]
        combined = rows["COMBINED"]
        self.assertFalse(ftmo_row["analysis_eligible"])
        self.assertEqual(ftmo_row["performance_confidence"], "incomplete")
        self.assertEqual(ftmo_row["coverage_status"], "incomplete")
        self.assertEqual(ftmo_row["coverage_failure_reason"], "bounded_window_after_week_start")
        self.assertEqual(ftmo_row["closed_trades_display"], "incomplete")
        self.assertIsNone(ftmo_row["closed_trades"])
        self.assertIsNone(ftmo_row["wins"])
        self.assertIsNone(ftmo_row["losses"])
        self.assertIsNone(ftmo_row["win_rate"])
        self.assertIsNone(ftmo_row["net_r"])
        self.assertIsNone(ftmo_row["net_pnl"])
        self.assertIsNone(ftmo_row["profit_factor"])
        self.assertEqual(ftmo_row["known_fetched_closed_trades"], 1)
        self.assertAlmostEqual(ftmo_row["known_fetched_net_r"], 1.25)
        self.assertAlmostEqual(ftmo_row["known_fetched_net_pnl"], 125.0)
        self.assertFalse(combined["analysis_eligible"])
        self.assertEqual(combined["closed_trades_display"], "incomplete")
        self.assertIsNone(combined["closed_trades"])
        self.assertIsNone(combined["net_r"])
        self.assertIsNone(combined["win_rate"])
        self.assertIsNone(combined["profit_factor"])
        self.assertEqual(combined["coverage_failure_reason"], "combined_from_incomplete_lane")
        self.assertEqual(combined["known_fetched_closed_trades"], 2)
        self.assertAlmostEqual(combined["known_fetched_net_r"], 0.75)
        self.assertNotIn("FTMO", {row["lane"] for row in result["lane_breakdown"]})
        html = weekly.build_dashboard_html(
            result["weekly_summary"],
            result["lane_breakdown"],
            result["historical_benchmark"],
            result["weekly_flags"],
            result["live_week_history"],
            result["consistency_flags"],
            result["run_summary"],
        )
        self.assertIn(">incomplete<", html)
        self.assertIn("partial evidence", html)
        self.assertIn("1 known fetched", html)
        weekly.write_outputs(
            output_dir=tmp / "out",
            docs_output=tmp / "docs" / "weekly.html",
            weekly_summary=result["weekly_summary"],
            lane_breakdown=result["lane_breakdown"],
            historical_benchmark=result["historical_benchmark"],
            weekly_flags=result["weekly_flags"],
            live_week_history=result["live_week_history"],
            live_week_trade_details=result["live_week_trade_details"],
            consistency_flags=result["consistency_flags"],
            run_summary=result["run_summary"],
        )
        with (tmp / "out" / "weekly_summary.csv").open(newline="", encoding="utf-8") as handle:
            csv_rows = {row["lane"]: row for row in csv.DictReader(handle)}
        self.assertEqual(csv_rows["FTMO"]["analysis_eligible"], "false")
        self.assertEqual(csv_rows["FTMO"]["closed_trades"], "")
        self.assertEqual(csv_rows["FTMO"]["net_r"], "")
        self.assertEqual(csv_rows["FTMO"]["known_fetched_closed_trades"], "1")
        self.assertEqual(csv_rows["COMBINED"]["closed_trades"], "")

    def test_positive_r_negative_broker_pnl_is_account_outcome_watch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ftmo_base = _lane_input(
                tmp,
                "FTMO",
                first_journal="2026-05-04T00:00:00Z",
                first_order="2026-05-04T00:05:00Z",
            )
            ftmo = weekly.LaneInput(
                config=ftmo_base.config,
                first_journal_row={"occurred_at_utc": "2026-05-04T00:00:00Z"},
                lifecycle_rows=[
                    _row("runner_started", "2026-05-04T00:00:00Z", signal_key=""),
                    *_closed_trade_rows(
                        signal_key="FTMO-R-PNL-DIVERGENCE",
                        symbol="CADCHF",
                        timeframe="W1",
                        side="LONG",
                        order_time="2026-05-04T00:05:00Z",
                        close_time="2026-05-06T21:00:00Z",
                        r_result=1.25,
                        profit=-25.0,
                        ticket=101,
                        position_id=1001,
                    ),
                ],
                state_payload={"pending_orders": [], "active_positions": [], "processed_signal_keys": ["a"]},
                vps_head=_repo_head(),
                fetch_metadata={"reached_source_start": True, "fetch_incomplete": False},
            )
            ic = _lane_input(
                tmp,
                "IC",
                first_journal="2026-05-04T00:00:00Z",
                first_order="2026-05-04T00:05:00Z",
                close_r=0.75,
            )
            result = weekly.build_weekly_report(
                lane_inputs=[ftmo, ic],
                git_info=_git_info(runtime_changed=False),
                as_of_utc=weekly.parse_timestamp("2026-05-08T08:00:00Z"),
                report_root=tmp / "reports",
                docs_output=tmp / "docs" / "live_weekly_performance.html",
            )

        rows = {row["lane"]: row for row in result["weekly_summary"]}
        ftmo_row = rows["FTMO"]
        self.assertTrue(ftmo_row["analysis_eligible"])
        self.assertAlmostEqual(ftmo_row["net_r"], 1.25)
        self.assertAlmostEqual(ftmo_row["net_pnl"], -25.0)
        self.assertEqual(ftmo_row["account_outcome_status"], "pnl_negative")
        self.assertEqual(ftmo_row["r_pnl_alignment"], "r_positive_pnl_negative")
        self.assertEqual(ftmo_row["account_outcome_caveat"], "strategy_r_positive_broker_pnl_negative")

        ftmo_flag = next(row for row in result["weekly_flags"] if row["lane"] == "FTMO")
        self.assertEqual(ftmo_flag["concern_status"], "watch")
        self.assertIn("strategy_r_positive_broker_pnl_negative", ftmo_flag["concern_reasons"])
        self.assertIn("strategy_r_positive_broker_pnl_negative", ftmo_flag["evidence_caveats"])

        combined = rows["COMBINED"]
        self.assertTrue(combined["analysis_eligible"])
        self.assertEqual(combined["account_outcome_status"], "pnl_positive")
        self.assertEqual(combined["r_pnl_alignment"], "r_positive_pnl_positive")

        html = weekly.build_dashboard_html(
            result["weekly_summary"],
            result["lane_breakdown"],
            result["historical_benchmark"],
            result["weekly_flags"],
            result["live_week_history"],
            result["consistency_flags"],
            result["run_summary"],
        )
        self.assertIn("positive R but negative broker PnL", html)
        self.assertIn("R/PnL alignment", html)

    def test_combined_row_inherits_incomplete_lane_caveat(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ftmo = _lane_input(tmp, "FTMO", first_journal="2026-05-03T21:00:00Z", first_order="2026-05-04T21:00:00Z")
            ic = _lane_input(tmp, "IC", first_journal="2026-05-03T21:00:00Z", first_order="2026-05-04T21:00:00Z")
            ic = weekly.LaneInput(
                config=ic.config,
                first_journal_row=None,
                lifecycle_rows=[],
                state_payload=ic.state_payload,
                vps_head=ic.vps_head,
                fetch_metadata={"fetch_incomplete": True, "first_live_metadata_unavailable": True},
            )
            result = weekly.build_weekly_report(
                lane_inputs=[ftmo, ic],
                git_info=_git_info(runtime_changed=False),
                as_of_utc=weekly.parse_timestamp("2026-05-16T02:00:00Z"),
                report_root=tmp / "reports",
                docs_output=tmp / "docs" / "live_weekly_performance.html",
            )

        combined = next(row for row in result["weekly_summary"] if row["lane"] == "COMBINED")
        self.assertTrue(combined["fetch_incomplete"])
        self.assertIn("combined_from_incomplete_lane", combined["partial_reasons"])
        self.assertFalse(combined["analysis_eligible"])
        self.assertEqual(combined["coverage_failure_reason"], "combined_from_incomplete_lane")
        self.assertIsNone(combined["closed_trades"])
        self.assertIsNone(combined["net_r"])

    def test_partial_and_unresolved_rows_are_caveats_not_closed_trades(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            lane = _lane_input(tmp, "FTMO", first_journal="2026-05-03T21:00:00Z", first_order="2026-05-04T21:00:00Z")
            lane = weekly.LaneInput(
                config=lane.config,
                first_journal_row=lane.first_journal_row,
                lifecycle_rows=[
                    _row("runner_started", "2026-05-03T21:00:00Z", signal_key=""),
                    {"event": "position_partially_closed", "occurred_at_utc": "2026-05-11T22:00:00Z"},
                    {"event": "active_position_final_close_unresolved", "occurred_at_utc": "2026-05-12T22:00:00Z"},
                ],
                state_payload=lane.state_payload,
                vps_head=lane.vps_head,
                fetch_metadata={"reached_source_start": True, "fetch_incomplete": False},
            )
            result = weekly.build_weekly_report(
                lane_inputs=[lane],
                git_info=_git_info(runtime_changed=False),
                as_of_utc=weekly.parse_timestamp("2026-05-16T02:00:00Z"),
                report_root=tmp / "reports",
                docs_output=tmp / "docs" / "live_weekly_performance.html",
            )

        row = result["weekly_summary"][0]
        self.assertEqual(row["closed_trades"], 0)
        self.assertIn("position_partially_closed:1", row["lifecycle_evidence_caveats"])
        self.assertIn("active_position_final_close_unresolved:1", row["lifecycle_evidence_caveats"])
        self.assertIn("position_partially_closed:1", result["weekly_flags"][0]["evidence_caveats"])

    def test_long_fetch_errors_are_preserved_in_packet_and_shortened_on_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            lane = _lane_input(tmp, "FTMO", first_journal="2026-05-03T21:00:00Z", first_order="2026-05-04T21:00:00Z")
            full_error = "ssh timeout " + ("EncodedCommand ABCDEF " * 80)
            lane = weekly.LaneInput(
                config=lane.config,
                first_journal_row=None,
                lifecycle_rows=[],
                state_payload={"fetch_error": full_error},
                vps_head="fetch_error",
                fetch_metadata={"fetch_error": full_error, "fetch_incomplete": True, "first_live_metadata_unavailable": True},
            )
            result = weekly.build_weekly_report(
                lane_inputs=[lane],
                git_info=_git_info(runtime_changed=False),
                as_of_utc=weekly.parse_timestamp("2026-05-16T02:00:00Z"),
                report_root=tmp / "reports",
                docs_output=tmp / "docs" / "live_weekly_performance.html",
            )
            html = weekly.build_dashboard_html(
                result["weekly_summary"],
                result["lane_breakdown"],
                result["historical_benchmark"],
                result["weekly_flags"],
                result["live_week_history"],
                result["consistency_flags"],
                result["run_summary"],
            )

        self.assertEqual(result["weekly_summary"][0]["fetch_error"], full_error)
        self.assertEqual(result["run_summary"]["lanes"][0]["fetch_metadata"]["fetch_error"], full_error)
        self.assertIn("ssh timeout", html)
        self.assertNotIn("EncodedCommand ABCDEF " * 20, html)

        timeout_error = "Command '['ssh', 'lane', 'powershell -EncodedCommand ABC']' timed out after 420 seconds"
        self.assertEqual(weekly.short_error(timeout_error), "SSH/PowerShell fetch timed out after 420 seconds")
        negative_timeout = "Command '['ssh', 'lane', 'powershell -EncodedCommand ABC']' timed out after -105 seconds"
        self.assertEqual(weekly.short_error(negative_timeout), "SSH/PowerShell fetch timed out")


    def test_live_week_history_excludes_partial_first_week_from_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            lane = _lane_input(tmp, "IC", first_journal="2026-05-05T19:49:36Z", first_order="2026-05-05T19:49:45Z")
            benchmark = weekly.historical_weekly_benchmark(lane.config.benchmark_path)
            history, _ = weekly.live_week_history_rows(lane, benchmark, weekly.parse_timestamp("2026-05-16T02:00:00Z"))

        self.assertEqual(len(history), 2)
        self.assertTrue(history[0]["partial_week"])
        self.assertFalse(history[0]["included_in_consistency"])
        self.assertFalse(history[1]["partial_week"])
        self.assertTrue(history[1]["included_in_consistency"])
        self.assertEqual(history[1]["completed_full_week_number"], 1)

    def test_runtime_change_in_week_is_reported_as_evidence_caveat(self) -> None:
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

        self.assertEqual(flag["concern_status"], "normal")
        self.assertIn("runtime_changed_in_week", flag["evidence_caveats"])

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

    def test_consistency_flags_use_percentile_streaks(self) -> None:
        history = [
            {
                "lane": "FTMO",
                "week_start_sgt": "2026-05-04T05:00:00+08:00",
                "week_label": "2026-05-04 05:00 SGT to 2026-05-09 05:00 SGT",
                "included_in_consistency": True,
                "net_r": -3.0,
                "historical_percentile": 9.0,
                "historical_percentile_band": "<=p10",
            },
            {
                "lane": "FTMO",
                "week_start_sgt": "2026-05-11T05:00:00+08:00",
                "week_label": "2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT",
                "included_in_consistency": True,
                "net_r": -3.5,
                "historical_percentile": 8.0,
                "historical_percentile_band": "<=p10",
            },
        ]

        flag = weekly.consistency_flag_row("FTMO", history)

        self.assertEqual(flag["consistency_status"], "watch")
        self.assertIn("two_consecutive_weeks_below_historical_10th_percentile", flag["consistency_reasons"])
        self.assertEqual(flag["completed_full_weeks"], 2)

    def test_consistency_flags_review_on_repeated_p5(self) -> None:
        history = [
            {
                "lane": "FTMO",
                "week_start_sgt": "2026-05-04T05:00:00+08:00",
                "week_label": "2026-05-04 05:00 SGT to 2026-05-09 05:00 SGT",
                "included_in_consistency": True,
                "net_r": -5.0,
                "historical_percentile": 4.0,
                "historical_percentile_band": "<=p5",
            },
            {
                "lane": "FTMO",
                "week_start_sgt": "2026-05-11T05:00:00+08:00",
                "week_label": "2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT",
                "included_in_consistency": True,
                "net_r": -6.0,
                "historical_percentile": 3.0,
                "historical_percentile_band": "<=p5",
            },
        ]

        flag = weekly.consistency_flag_row("FTMO", history)

        self.assertEqual(flag["consistency_status"], "review")
        self.assertIn("two_consecutive_weeks_below_historical_5th_percentile", flag["consistency_reasons"])

    def test_pivot_live_week_history_latest_first_and_side_by_side(self) -> None:
        history = [
            {
                "lane": "FTMO",
                "week_label": "2026-05-04 05:00 SGT to 2026-05-09 05:00 SGT",
                "week_start_sgt": "2026-05-04T05:00:00+08:00",
                "completed_full_week": True,
                "completed_full_week_number": 1,
                "included_in_consistency": True,
                "performance_status": "normal",
                "closed_trades": 25,
                "wins": 10,
                "losses": 15,
                "net_r": -5.33,
                "historical_percentile": 10.5,
                "partial_reasons": "",
            },
            {
                "lane": "FTMO",
                "week_label": "2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT",
                "week_start_sgt": "2026-05-11T05:00:00+08:00",
                "completed_full_week": True,
                "completed_full_week_number": 2,
                "included_in_consistency": True,
                "performance_status": "watch",
                "closed_trades": 15,
                "wins": 4,
                "losses": 11,
                "net_r": -7.08,
                "historical_percentile": 5.94,
                "partial_reasons": "",
            },
            {
                "lane": "IC",
                "week_label": "2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT",
                "week_start_sgt": "2026-05-11T05:00:00+08:00",
                "completed_full_week": True,
                "completed_full_week_number": 1,
                "included_in_consistency": True,
                "performance_status": "normal",
                "closed_trades": 15,
                "wins": 7,
                "losses": 8,
                "net_r": -1.29,
                "historical_percentile": 23.9,
                "partial_reasons": "",
            },
        ]

        rows = weekly.pivot_live_week_history(history)

        self.assertEqual(rows[0][0], "2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT")
        self.assertEqual(rows[0][1], "FTMO W2 / IC W1")
        self.assertEqual(rows[0][2], "COMPLETED")
        self.assertEqual(rows[0][3], "Both")
        self.assertEqual(rows[0][4].value, "WATCH")
        self.assertEqual(rows[0][8], "4/11")
        self.assertEqual(rows[0][9].value, "NORMAL")
        self.assertEqual(rows[0][13], "7/8")
        self.assertEqual(rows[1][-1], "IC n/a")

    def test_generated_dashboard_contains_live_start_version_and_concern_context(self) -> None:
        run_summary = {
            "generated_at_utc": "2026-05-08T08:00:00+00:00",
            "output_dir": "reports/live_ops/lpfs_weekly_performance/test",
            "week_window_label": "2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT",
        }
        weekly_summary = [
            {
                "lane": "FTMO",
                "partial_week": True,
                "partial_reasons": "week_in_progress",
                "completed_full_live_weeks": 2,
                "latest_week_complete": False,
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
                "completed_full_live_weeks": 1,
                "latest_week_complete": False,
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
                "evidence_caveats": "runtime_changed_in_week",
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
                "evidence_caveats": "partial_week",
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
            [
                {
                    "lane": "FTMO",
                    "week_label": "2026-05-04 05:00 SGT to 2026-05-09 05:00 SGT",
                    "week_start_sgt": "2026-05-04T05:00:00+08:00",
                    "completed_full_week": False,
                    "included_in_consistency": False,
                    "completed_full_week_number": "",
                    "performance_status": "normal",
                    "closed_trades": 2,
                    "wins": 1,
                    "losses": 1,
                    "net_r": -0.02,
                    "net_pnl": 2.37,
                    "win_rate": 0.5,
                    "historical_percentile": 35.1,
                    "historical_percentile_band": "p35.1",
                    "partial_reasons": "portfolio_started_after_week_start;journal_started_after_week_start",
                },
                {
                    "lane": "FTMO",
                    "week_label": "2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT",
                    "week_start_sgt": "2026-05-11T05:00:00+08:00",
                    "completed_full_week": True,
                    "included_in_consistency": True,
                    "completed_full_week_number": 2,
                    "performance_status": "watch",
                    "closed_trades": 15,
                    "wins": 4,
                    "losses": 11,
                    "net_r": -7.08,
                    "net_pnl": -61.77,
                    "win_rate": 4 / 15,
                    "historical_percentile": 5.94,
                    "historical_percentile_band": "<=p10",
                    "partial_reasons": "",
                },
                {
                    "lane": "IC",
                    "week_label": "2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT",
                    "week_start_sgt": "2026-05-11T05:00:00+08:00",
                    "completed_full_week": True,
                    "included_in_consistency": True,
                    "completed_full_week_number": 1,
                    "performance_status": "normal",
                    "closed_trades": 15,
                    "wins": 7,
                    "losses": 8,
                    "net_r": -1.29,
                    "net_pnl": -6.05,
                    "win_rate": 7 / 15,
                    "historical_percentile": 23.9,
                    "historical_percentile_band": "p23.9",
                    "partial_reasons": "",
                },
            ],
            [
                {
                    "lane": "FTMO",
                    "consistency_status": "normal",
                    "consistency_reasons": "no_consistent_underperformance",
                    "completed_full_weeks": 2,
                    "latest_completed_week": "2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT",
                    "latest_completed_net_r": -7.08,
                    "latest_completed_percentile": 5.94,
                    "p10_streak": 1,
                    "p05_streak": 0,
                    "last4_completed_weeks": 2,
                    "last4_below_p10": 1,
                    "last4_below_p05": 0,
                }
            ],
            run_summary,
        )

        self.assertIn("LPFS Live Weekly Performance", html)
        self.assertIn("FTMO", html)
        self.assertIn("IC", html)
        self.assertIn("First journal (SGT)", html)
        self.assertIn("01 May 2026 03:48 SGT", html)
        self.assertIn("06 May 2026 03:49 SGT", html)
        self.assertNotIn("2026-04-30T19:48:13+00:00", html)
        self.assertIn("Runtime synced", html)
        self.assertIn("Cause For Concern", html)
        self.assertIn("Evidence caveats", html)
        self.assertIn("Consistency Check", html)
        self.assertIn("Live Week Comparison", html)
        self.assertIn("Live week", html)
        self.assertIn("FTMO W2 / IC W1", html)
        self.assertIn("FTMO W/L", html)
        self.assertIn("IC W/L", html)
        self.assertIn("4/11", html)
        self.assertIn("7/8", html)
        self.assertIn("IC n/a", html)
        self.assertLess(
            html.index("2026-05-11 05:00 SGT to 2026-05-16 05:00 SGT"),
            html.index("2026-05-04 05:00 SGT to 2026-05-09 05:00 SGT"),
        )
        self.assertNotIn("Live Week History", html)
        self.assertIn("Completed full weeks", html)
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
