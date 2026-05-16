"""Build the LPFS live weekly performance dashboard.

This script is read-only with respect to live operations. It reads FTMO/IC live
journals and state snapshots, compares closed-trade performance against the
historical V22 commission-adjusted weekly distributions, and writes local report
artifacts plus the stable docs page.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from lp_force_strike_dashboard_metadata import dashboard_base_css, dashboard_header_html, metric_glossary_html


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [
    REPO_ROOT / "concepts" / "lp_levels_lab" / "src",
    REPO_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    REPO_ROOT / "shared" / "backtest_engine_lab" / "src",
    REPO_ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab.live_trade_summary import (  # noqa: E402
    LPFSLiveClosedTrade,
    build_closed_trade_summaries,
)


DEFAULT_REPORT_ROOT = REPO_ROOT / "reports" / "live_ops" / "lpfs_weekly_performance"
DEFAULT_DOCS_OUTPUT = REPO_ROOT / "docs" / "live_weekly_performance.html"
DEFAULT_FTMO_TRADES = (
    REPO_ROOT
    / "reports"
    / "strategies"
    / "lp_force_strike_account_commission_sensitivity"
    / "20260505_165121"
    / "ftmo_baseline_commission_adjusted_trades.csv"
)
DEFAULT_IC_TRADES = (
    REPO_ROOT
    / "reports"
    / "strategies"
    / "lp_force_strike_account_commission_sensitivity"
    / "20260505_165121"
    / "ic_markets_raw_spread_commission_adjusted_trades.csv"
)


def _display_path(path_value: str | Path) -> str:
    path = Path(path_value)
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


SGT = "Asia/Singapore"
TRADING_WEEK_START_UTC_WEEKDAY = 6  # Sunday, matching pandas Monday=0 indexing.
TRADING_WEEK_START_UTC_HOUR = 21
TRADING_WEEK_DURATION_DAYS = 5
JOURNAL_EVENT_KEYWORDS = (
    "runner_started",
    "order_sent",
    "order_adopted",
    "position_opened",
    "take_profit_hit",
    "stop_loss_hit",
    "position_closed",
    "setup_rejected",
)
RETRYABLE_STATUSES = {
    "spread_too_wide",
    "market_recovery_not_better",
    "market_closed",
    "autotrading_disabled",
}
RUNTIME_PATHS = [
    "scripts/run_lp_force_strike_live_executor.py",
    "strategies/lp_force_strike_strategy_lab/src",
    "strategies/lp_force_strike_strategy_lab/tradingview",
    "concepts/lp_levels_lab/src",
    "concepts/force_strike_pattern_lab/src",
    "shared/backtest_engine_lab/src",
]
LANE_DISPLAY_ORDER = ("FTMO", "IC")


@dataclass(frozen=True)
class LaneConfig:
    name: str
    ssh_alias: str
    journal_path: str
    state_path: str
    benchmark_path: Path
    benchmark_label: str
    repo_root: str = "C:\\TradeAutomation"


@dataclass(frozen=True)
class LaneInput:
    config: LaneConfig
    first_journal_row: dict[str, Any] | None
    lifecycle_rows: list[dict[str, Any]]
    state_payload: dict[str, Any]
    vps_head: str
    fetch_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TableCell:
    value: Any
    class_name: str = ""


DEFAULT_LANES = [
    LaneConfig(
        name="FTMO",
        ssh_alias="lpfs-vps",
        journal_path=r"C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl",
        state_path=r"C:\TradeAutomationRuntime\data\live\lpfs_live_state.json",
        benchmark_path=DEFAULT_FTMO_TRADES,
        benchmark_label="FTMO V22 separated commission-adjusted",
    ),
    LaneConfig(
        name="IC",
        ssh_alias="lpfs-ic-vps",
        journal_path=r"C:\TradeAutomationRuntimeIC\data\live\lpfs_ic_live_journal.jsonl",
        state_path=r"C:\TradeAutomationRuntimeIC\data\live\lpfs_ic_live_state.json",
        benchmark_path=DEFAULT_IC_TRADES,
        benchmark_label="IC raw-spread V22 separated commission-adjusted",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", action="store_true", help="Build or confirm the latest weekly dashboard.")
    parser.add_argument("--force", action="store_true", help="Rewrite outputs even if inputs match the latest run.")
    parser.add_argument("--as-of-utc", default=None, help="Override report timestamp, e.g. 2026-05-08T15:00:00Z.")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--docs-output", default=str(DEFAULT_DOCS_OUTPUT))
    parser.add_argument("--skip-git-fetch", action="store_true", help="Do not refresh origin/main before version checks.")
    args = parser.parse_args()

    as_of_utc = parse_timestamp(args.as_of_utc) if args.as_of_utc else pd.Timestamp.now(tz="UTC")
    report_root = Path(args.report_root)
    docs_output = Path(args.docs_output)

    if not args.skip_git_fetch:
        run_command(["git", "fetch", "--quiet", "origin"], check=False)

    git_info = collect_git_info(as_of_utc=as_of_utc)
    lane_inputs = [safe_fetch_lane_input(config) for config in DEFAULT_LANES]
    result = build_weekly_report(
        lane_inputs=lane_inputs,
        git_info=git_info,
        as_of_utc=as_of_utc,
        report_root=report_root,
        docs_output=docs_output,
    )

    latest_summary = latest_run_summary(report_root)
    if latest_summary and not args.force and latest_summary.get("input_fingerprint") == result["run_summary"]["input_fingerprint"]:
        print(f"already up to date: {latest_summary.get('output_dir')}")
        print(f"docs_output={latest_summary.get('docs_output')}")
        return 0

    write_outputs(
        output_dir=Path(result["run_summary"]["output_dir"]),
        docs_output=docs_output,
        weekly_summary=result["weekly_summary"],
        lane_breakdown=result["lane_breakdown"],
        historical_benchmark=result["historical_benchmark"],
        weekly_flags=result["weekly_flags"],
        live_week_history=result["live_week_history"],
        live_week_trade_details=result["live_week_trade_details"],
        consistency_flags=result["consistency_flags"],
        run_summary=result["run_summary"],
    )
    print(f"weekly_performance_report={result['run_summary']['output_dir']}")
    print(f"docs_output={docs_output}")
    return 0


def fetch_lane_input(config: LaneConfig) -> LaneInput:
    first_line, lifecycle_lines, state_text, vps_head, fetch_metadata = fetch_remote_lane_text(config)
    first_row = parse_json_line(first_line)
    lifecycle_rows: list[dict[str, Any]] = []
    lifecycle_parse_errors = 0
    for line in lifecycle_lines:
        row = parse_json_line(line)
        if row is None:
            lifecycle_parse_errors += 1
            continue
        lifecycle_rows.append(row)
    state_payload = parse_json_line(state_text)
    state_parse_error = bool(state_text.strip()) and state_payload is None
    metadata = {
        **fetch_metadata,
        "matched_lifecycle_rows": len(lifecycle_lines),
        "parsed_lifecycle_rows": len(lifecycle_rows),
        "lifecycle_parse_errors": lifecycle_parse_errors,
        "state_parse_error": state_parse_error,
    }
    return LaneInput(
        config=config,
        first_journal_row=first_row,
        lifecycle_rows=lifecycle_rows,
        state_payload=state_payload or {},
        vps_head=vps_head.strip(),
        fetch_metadata=metadata,
    )


def safe_fetch_lane_input(config: LaneConfig) -> LaneInput:
    try:
        return fetch_lane_input(config)
    except Exception as exc:  # pragma: no cover - exercised only when VPS access is unavailable.
        return LaneInput(
            config=config,
            first_journal_row=None,
            lifecycle_rows=[],
            state_payload={"fetch_error": str(exc)},
            vps_head="fetch_error",
            fetch_metadata={"fetch_error": str(exc)},
        )


def fetch_remote_lane_text(config: LaneConfig) -> tuple[str, list[str], str, str, dict[str, Any]]:
    patterns = "@(" + ",".join(f"'{keyword}'" for keyword in JOURNAL_EVENT_KEYWORDS) + ")"
    script = f"""
$ErrorActionPreference = 'Stop'
$journal = '{config.journal_path}'
$state = '{config.state_path}'
$repo = '{config.repo_root}'
$patterns = {patterns}
Write-Output '---META---'
$journalItem = Get-Item -LiteralPath $journal
[ordered]@{{
  journal_path = $journal
  journal_size_bytes = $journalItem.Length
  journal_last_write_utc = $journalItem.LastWriteTimeUtc.ToString('o')
  event_keywords = $patterns
}} | ConvertTo-Json -Compress
Write-Output '---FIRST---'
Get-Content -LiteralPath $journal -First 1
Write-Output '---LIFECYCLE---'
Select-String -LiteralPath $journal -SimpleMatch -Pattern $patterns | ForEach-Object {{ $_.Line }}
Write-Output '---STATE---'
Get-Content -LiteralPath $state -Raw
Write-Output '---HEAD---'
git -C $repo rev-parse HEAD
"""
    raw = ssh_powershell(config.ssh_alias, script, timeout=240)
    sections: dict[str, list[str]] = defaultdict(list)
    current: str | None = None
    for line in raw.splitlines():
        marker = line.strip()
        if marker in {"---META---", "---FIRST---", "---LIFECYCLE---", "---STATE---", "---HEAD---"}:
            current = marker.strip("-")
            continue
        if current in {"META", "STATE"}:
            sections[current].append(line)
            continue
        if current in {"FIRST", "LIFECYCLE"} and line.strip().startswith("{"):
            sections[current].append(line)
            continue
        if current == "HEAD" and line.strip():
            sections[current].append(line)
    first = first_json_line(sections.get("FIRST", []))
    lifecycle = [line for line in sections.get("LIFECYCLE", []) if line.strip().startswith("{")]
    state = "\n".join(sections.get("STATE", [])).strip()
    head = next((line.strip() for line in sections.get("HEAD", []) if line.strip() and not line.startswith("#<")), "")
    metadata = parse_json_line("\n".join(sections.get("META", [])).strip()) or {}
    return first, lifecycle, state, head, metadata


def first_json_line(lines: Sequence[str]) -> str:
    return next((line for line in lines if line.strip().startswith("{")), "")


def ssh_powershell(alias: str, script: str, *, timeout: int) -> str:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return run_command(
        ["ssh", alias, f"powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"],
        timeout=timeout,
    )


def build_weekly_report(
    *,
    lane_inputs: Sequence[LaneInput],
    git_info: dict[str, Any],
    as_of_utc: pd.Timestamp,
    report_root: Path,
    docs_output: Path,
) -> dict[str, Any]:
    week_start_sgt, week_end_sgt = latest_sgt_week_window(as_of_utc)
    generated = as_of_utc.strftime("%Y%m%d_%H%M%S")
    output_dir = report_root / generated

    weekly_rows: list[dict[str, Any]] = []
    breakdown_rows: list[dict[str, Any]] = []
    benchmark_rows: list[dict[str, Any]] = []
    flag_rows: list[dict[str, Any]] = []
    live_history_rows: list[dict[str, Any]] = []
    live_trade_detail_rows: list[dict[str, Any]] = []
    consistency_rows: list[dict[str, Any]] = []
    fingerprint_payload: dict[str, Any] = {
        "week_start_sgt": week_start_sgt.isoformat(),
        "week_end_sgt": week_end_sgt.isoformat(),
        "git": git_info,
        "lanes": [],
    }

    for lane_input in lane_inputs:
        benchmark = historical_weekly_benchmark(lane_input.config.benchmark_path)
        history, trade_details = live_week_history_rows(lane_input, benchmark, as_of_utc)
        consistency = consistency_flag_row(lane_input.config.name, history)
        lane_summary = summarize_lane_week(lane_input, week_start_sgt, week_end_sgt, as_of_utc, git_info)
        lane_summary["completed_full_live_weeks"] = consistency["completed_full_weeks"]
        lane_summary["latest_week_complete"] = not bool(lane_summary["partial_week"])
        flag = classify_week(lane_summary, benchmark)
        weekly_rows.append(lane_summary)
        live_history_rows.extend(history)
        live_trade_detail_rows.extend(trade_details)
        consistency_rows.append(consistency)
        benchmark_rows.append(
            {
                "lane": lane_input.config.name,
                "benchmark_label": lane_input.config.benchmark_label,
                **{key: value for key, value in benchmark.items() if key != "weekly_r_values"},
            }
        )
        flag_rows.append({"lane": lane_input.config.name, **flag})
        breakdown_rows.extend(lane_breakdown_rows(lane_input.config.name, lane_summary["trades"]))
        fingerprint_payload["lanes"].append(
            {
                "lane": lane_input.config.name,
                "vps_head": lane_input.vps_head,
                "state_hash": stable_hash(lane_input.state_payload),
                "lifecycle_hash": stable_hash(lane_input.lifecycle_rows),
                "fetch_metadata": lane_input.fetch_metadata,
                "benchmark_path": str(lane_input.config.benchmark_path),
                "benchmark_mtime": lane_input.config.benchmark_path.stat().st_mtime if lane_input.config.benchmark_path.exists() else None,
            }
        )

    combined = combined_summary_row(weekly_rows, week_start_sgt, week_end_sgt)
    if combined:
        weekly_rows.append(combined)

    safe_weekly_rows = [{k: v for k, v in row.items() if k != "trades"} for row in weekly_rows]
    run_summary = {
        "generated_at_utc": as_of_utc.isoformat(),
        "output_dir": str(output_dir),
        "docs_output": str(docs_output),
        "week_start_sgt": week_start_sgt.isoformat(),
        "week_end_sgt": week_end_sgt.isoformat(),
        "week_window_label": week_window_label(week_start_sgt, week_end_sgt),
        "week_is_complete": as_of_utc.tz_convert(SGT) >= week_end_sgt,
        "input_fingerprint": stable_hash(fingerprint_payload),
        "git": git_info,
        "lanes": [
            {
                "lane": row["lane"],
                "status": row["concern_status"],
                "closed_trades": row["closed_trades"],
                "net_r": row["net_r"],
                "partial_week": row["partial_week"],
                "completed_full_live_weeks": row.get("completed_full_live_weeks", 0),
                "fetch_metadata": next(
                    (lane.fetch_metadata for lane in lane_inputs if lane.config.name == row["lane"]),
                    {},
                ),
                "state_hash": next(
                    (stable_hash(lane.state_payload) for lane in lane_inputs if lane.config.name == row["lane"]),
                    "",
                ),
                "vps_head": row.get("vps_head"),
            }
            for row in safe_weekly_rows
            if row["lane"] != "COMBINED"
        ],
    }

    return {
        "weekly_summary": safe_weekly_rows,
        "lane_breakdown": breakdown_rows,
        "historical_benchmark": benchmark_rows,
        "weekly_flags": flag_rows,
        "live_week_history": live_history_rows,
        "live_week_trade_details": live_trade_detail_rows,
        "consistency_flags": consistency_rows,
        "run_summary": run_summary,
    }


def summarize_lane_week(
    lane_input: LaneInput,
    week_start_sgt: pd.Timestamp,
    week_end_sgt: pd.Timestamp,
    as_of_utc: pd.Timestamp,
    git_info: dict[str, Any],
) -> dict[str, Any]:
    events = lane_input.lifecycle_rows
    trades = build_closed_trade_summaries(events)
    week_trades = select_trades_for_sgt_week(trades, week_start_sgt, week_end_sgt)
    start_info = lane_start_info(lane_input.first_journal_row, events, trades)
    wait_counts = setup_wait_counts(events, week_start_sgt, week_end_sgt)
    state_counts = live_state_counts(lane_input.state_payload)
    net_r_values = [float(trade.r_result or 0.0) for trade in week_trades]
    pnl_values = [float(trade.close_profit or 0.0) for trade in week_trades if trade.close_profit is not None]
    wins = sum(1 for value in net_r_values if value > 0)
    losses = sum(1 for value in net_r_values if value < 0)
    gross_win = sum(value for value in net_r_values if value > 0)
    gross_loss = abs(sum(value for value in net_r_values if value < 0))
    net_r = sum(net_r_values)
    now_sgt = as_of_utc.tz_convert(SGT)
    first_order_sgt = parse_timestamp(start_info.get("first_order_utc")).tz_convert(SGT) if start_info.get("first_order_utc") else None
    first_journal_sgt = parse_timestamp(start_info.get("first_journal_utc")).tz_convert(SGT) if start_info.get("first_journal_utc") else None
    partial_reasons: list[str] = []
    if now_sgt < week_end_sgt:
        partial_reasons.append("week_in_progress")
    if first_order_sgt is not None and first_order_sgt > week_start_sgt:
        partial_reasons.append("portfolio_started_after_week_start")
    if first_journal_sgt is not None and first_journal_sgt > week_start_sgt:
        partial_reasons.append("journal_started_after_week_start")
    runtime_synced = git_info.get("latest_runtime_commit_full") and is_commit_ancestor(
        str(git_info.get("latest_runtime_commit_full")), lane_input.vps_head
    )
    runtime_changed = bool(git_info.get("runtime_commits_in_window"))
    fetch_error = str(lane_input.state_payload.get("fetch_error") or "")

    row = {
        "lane": lane_input.config.name,
        "week_start_sgt": week_start_sgt.isoformat(),
        "week_end_sgt": week_end_sgt.isoformat(),
        "report_as_of_utc": as_of_utc.isoformat(),
        "first_journal_utc": start_info.get("first_journal_utc"),
        "first_runner_utc": start_info.get("first_runner_utc"),
        "first_order_utc": start_info.get("first_order_utc"),
        "first_closed_trade_utc": start_info.get("first_closed_trade_utc"),
        "partial_week": bool(partial_reasons),
        "partial_reasons": ";".join(partial_reasons),
        "vps_head": lane_input.vps_head,
        "fetch_error": fetch_error,
        "local_head": git_info.get("local_head"),
        "origin_head": git_info.get("origin_head"),
        "latest_runtime_commit": git_info.get("latest_runtime_commit"),
        "runtime_synced": runtime_synced,
        "runtime_changed_in_week": runtime_changed,
        "closed_trades": len(week_trades),
        "wins": wins,
        "losses": losses,
        "win_rate": safe_ratio(wins, len(week_trades)),
        "net_r": net_r,
        "net_pnl": sum(pnl_values) if pnl_values else 0.0,
        "profit_factor": None if gross_loss == 0 else gross_win / gross_loss,
        "worst_symbol": worst_group(week_trades, "symbol"),
        "worst_timeframe": worst_group(week_trades, "timeframe"),
        "worst_side": worst_group(week_trades, "side"),
        "retryable_waits": wait_counts["retryable_waits"],
        "spread_waits": wait_counts["spread_too_wide"],
        "market_recovery_waits": wait_counts["market_recovery_not_better"],
        "market_closed_waits": wait_counts["market_closed"],
        "true_rejections": wait_counts["true_rejections"],
        "pending_orders": state_counts["pending_orders"],
        "active_positions": state_counts["active_positions"],
        "processed_signal_keys": state_counts["processed_signal_keys"],
        "trades": week_trades,
    }
    return row


def lane_start_info(
    first_journal_row: dict[str, Any] | None,
    lifecycle_rows: Sequence[dict[str, Any]],
    trades: Sequence[LPFSLiveClosedTrade],
) -> dict[str, str | None]:
    first_journal_utc = event_time(first_journal_row) if first_journal_row else None
    first_runner_utc = first_event_time(lifecycle_rows, "runner_started")
    first_order_utc = first_event_time(lifecycle_rows, "order_sent")
    first_closed_trade_utc = None
    if trades:
        closed = sorted(parse_timestamp(trade.closed_utc) for trade in trades if trade.closed_utc)
        first_closed_trade_utc = None if not closed else closed[0].isoformat()
    return {
        "first_journal_utc": first_journal_utc,
        "first_runner_utc": first_runner_utc,
        "first_order_utc": first_order_utc,
        "first_closed_trade_utc": first_closed_trade_utc,
    }


def first_event_time(rows: Sequence[dict[str, Any]], kind: str) -> str | None:
    for row in rows:
        event = row.get("notification_event") or {}
        if event.get("kind") == kind:
            return event_time(row)
    return None


def event_time(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    event = row.get("notification_event") or {}
    fields = event.get("fields") or {}
    for value in (
        row.get("occurred_at_utc"),
        event.get("occurred_at_utc"),
        fields.get("closed_utc"),
        fields.get("placed_time_utc"),
    ):
        if value:
            return parse_timestamp(value).isoformat()
    return None


def select_trades_for_sgt_week(
    trades: Sequence[LPFSLiveClosedTrade],
    week_start_sgt: pd.Timestamp,
    week_end_sgt: pd.Timestamp,
) -> list[LPFSLiveClosedTrade]:
    selected = []
    for trade in trades:
        if not trade.closed_utc:
            continue
        closed_sgt = parse_timestamp(trade.closed_utc).tz_convert(SGT)
        if week_start_sgt <= closed_sgt < week_end_sgt:
            selected.append(trade)
    return sorted(selected, key=lambda trade: parse_timestamp(trade.closed_utc or "1970-01-01T00:00:00Z"))


def setup_wait_counts(
    rows: Sequence[dict[str, Any]],
    week_start_sgt: pd.Timestamp,
    week_end_sgt: pd.Timestamp,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        event = row.get("notification_event") or {}
        if event.get("kind") != "setup_rejected":
            continue
        occurred = event_time(row)
        if not occurred:
            continue
        occurred_sgt = parse_timestamp(occurred).tz_convert(SGT)
        if not (week_start_sgt <= occurred_sgt < week_end_sgt):
            continue
        status = str(event.get("status") or "")
        event_key = str(row.get("event_key") or "")
        if event_key.startswith("setup_blocked") or status in RETRYABLE_STATUSES:
            counts["retryable_waits"] += 1
            counts[status or "retryable_unknown"] += 1
        else:
            counts["true_rejections"] += 1
            counts[status or "rejected_unknown"] += 1
    return counts


def live_state_counts(payload: dict[str, Any]) -> dict[str, int]:
    return {
        "pending_orders": len(payload.get("pending_orders") or []),
        "active_positions": len(payload.get("active_positions") or []),
        "processed_signal_keys": len(payload.get("processed_signal_keys") or []),
    }


def worst_group(trades: Sequence[LPFSLiveClosedTrade], field: str) -> str:
    totals: dict[str, float] = defaultdict(float)
    for trade in trades:
        key = str(getattr(trade, field) or "n/a").upper()
        totals[key] += float(trade.r_result or 0.0)
    if not totals:
        return "n/a"
    key, value = min(totals.items(), key=lambda item: (item[1], item[0]))
    return f"{key} {value:+.2f}R"


def lane_breakdown_rows(lane: str, trades: Sequence[LPFSLiveClosedTrade]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_name in ("symbol", "timeframe", "side"):
        bucket: dict[str, list[LPFSLiveClosedTrade]] = defaultdict(list)
        for trade in trades:
            bucket[str(getattr(trade, group_name) or "n/a").upper()].append(trade)
        for key, group_trades in sorted(bucket.items()):
            values = [float(trade.r_result or 0.0) for trade in group_trades]
            rows.append(
                {
                    "lane": lane,
                    "group_type": group_name,
                    "group_value": key,
                    "closed_trades": len(group_trades),
                    "wins": sum(1 for value in values if value > 0),
                    "losses": sum(1 for value in values if value < 0),
                    "net_r": sum(values),
                    "net_pnl": sum(float(trade.close_profit or 0.0) for trade in group_trades),
                }
            )
    return rows


def live_week_history_rows(
    lane_input: LaneInput,
    benchmark: dict[str, Any],
    as_of_utc: pd.Timestamp,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = lane_input.lifecycle_rows
    trades = build_closed_trade_summaries(events)
    start_info = lane_start_info(lane_input.first_journal_row, events, trades)
    first_live_utc = first_live_timestamp(start_info)
    if first_live_utc is None:
        return [], []

    first_week_start_sgt, _ = trading_week_window_for_timestamp(first_live_utc)
    latest_week_start_sgt, _ = latest_sgt_week_window(as_of_utc)
    first_order_sgt = parse_timestamp(start_info["first_order_utc"]).tz_convert(SGT) if start_info.get("first_order_utc") else None
    first_journal_sgt = parse_timestamp(start_info["first_journal_utc"]).tz_convert(SGT) if start_info.get("first_journal_utc") else None
    now_sgt = as_of_utc.tz_convert(SGT)
    fetch_error = str(lane_input.state_payload.get("fetch_error") or "")

    history_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    completed_full_count = 0
    week_start_sgt = first_week_start_sgt
    while week_start_sgt <= latest_week_start_sgt:
        week_end_sgt = week_start_sgt + pd.Timedelta(days=TRADING_WEEK_DURATION_DAYS)
        week_trades = select_trades_for_sgt_week(trades, week_start_sgt, week_end_sgt)
        partial_reasons: list[str] = []
        if now_sgt < week_end_sgt:
            partial_reasons.append("week_in_progress")
        if first_order_sgt is not None and first_order_sgt > week_start_sgt:
            partial_reasons.append("portfolio_started_after_week_start")
        if first_journal_sgt is not None and first_journal_sgt > week_start_sgt:
            partial_reasons.append("journal_started_after_week_start")
        if fetch_error:
            partial_reasons.append("lane_fetch_incomplete")

        values = [float(trade.r_result or 0.0) for trade in week_trades]
        pnl_values = [float(trade.close_profit or 0.0) for trade in week_trades if trade.close_profit is not None]
        wins = sum(1 for value in values if value > 0)
        losses = sum(1 for value in values if value < 0)
        gross_win = sum(value for value in values if value > 0)
        gross_loss = abs(sum(value for value in values if value < 0))
        net_r = sum(values)
        percentile = historical_percentile(net_r, benchmark.get("weekly_r_values") or [])
        performance_status, performance_reasons, percentile_band_value = classify_performance(net_r, benchmark)
        partial_week = bool(partial_reasons)
        completed_full_week = not partial_week and week_end_sgt <= now_sgt
        included_in_consistency = completed_full_week and not fetch_error
        if included_in_consistency:
            completed_full_count += 1

        row = {
            "lane": lane_input.config.name,
            "week_start_sgt": week_start_sgt.isoformat(),
            "week_end_sgt": week_end_sgt.isoformat(),
            "week_label": week_window_label(week_start_sgt, week_end_sgt),
            "partial_week": partial_week,
            "partial_reasons": ";".join(partial_reasons),
            "completed_full_week": completed_full_week,
            "completed_full_week_number": completed_full_count if included_in_consistency else "",
            "included_in_consistency": included_in_consistency,
            "closed_trades": len(week_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": safe_ratio(wins, len(week_trades)),
            "net_r": net_r,
            "net_pnl": sum(pnl_values) if pnl_values else 0.0,
            "profit_factor": None if gross_loss == 0 else gross_win / gross_loss,
            "historical_percentile": "" if percentile is None else percentile,
            "historical_percentile_band": percentile_band_value,
            "performance_status": performance_status,
            "performance_reasons": ";".join(performance_reasons),
        }
        history_rows.append(row)

        for trade in week_trades:
            trade_rows.append(
                {
                    "lane": lane_input.config.name,
                    "week_start_sgt": week_start_sgt.isoformat(),
                    "week_end_sgt": week_end_sgt.isoformat(),
                    "week_label": row["week_label"],
                    "symbol": trade.symbol,
                    "timeframe": trade.timeframe,
                    "side": trade.side,
                    "close_kind": trade.close_kind,
                    "position_id": trade.position_id,
                    "deal_ticket": trade.deal_ticket,
                    "entry_price": trade.entry_price,
                    "close_price": trade.close_price,
                    "volume": trade.volume,
                    "close_profit": trade.close_profit,
                    "r_result": trade.r_result,
                    "opened_utc": trade.opened_utc,
                    "closed_utc": trade.closed_utc,
                    "signal_key": trade.signal_key,
                }
            )

        week_start_sgt = week_start_sgt + pd.Timedelta(days=7)

    return history_rows, trade_rows


def first_live_timestamp(start_info: dict[str, str | None]) -> pd.Timestamp | None:
    timestamps = [
        parse_timestamp(value)
        for value in (
            start_info.get("first_journal_utc"),
            start_info.get("first_order_utc"),
            start_info.get("first_closed_trade_utc"),
        )
        if value
    ]
    if not timestamps:
        return None
    return min(timestamps)


def classify_performance(net_r: float, benchmark: dict[str, Any]) -> tuple[str, list[str], str]:
    p10 = float(benchmark.get("p10_week_r") or 0.0)
    p05 = float(benchmark.get("p05_week_r") or 0.0)
    percentile = historical_percentile(net_r, benchmark.get("weekly_r_values") or [])
    if net_r <= p05:
        return "review", ["below_historical_5th_percentile"], "<=p5"
    if net_r <= p10:
        return "watch", ["below_historical_10th_percentile"], "<=p10"
    return "normal", ["inside_expected_weekly_range"], "" if percentile is None else percentile_band(percentile)


def consistency_flag_row(lane: str, history_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        row
        for row in sorted(history_rows, key=lambda item: str(item["week_start_sgt"]))
        if bool(row.get("included_in_consistency"))
    ]
    latest = eligible[-1] if eligible else {}
    last4 = eligible[-4:]
    p10_streak = trailing_count(eligible, lambda row: str(row.get("historical_percentile_band")) in {"<=p10", "<=p5"})
    p05_streak = trailing_count(eligible, lambda row: str(row.get("historical_percentile_band")) == "<=p5")
    last4_below_p10 = sum(1 for row in last4 if str(row.get("historical_percentile_band")) in {"<=p10", "<=p5"})
    last4_below_p05 = sum(1 for row in last4 if str(row.get("historical_percentile_band")) == "<=p5")

    status = "normal"
    reasons: list[str] = []
    if p05_streak >= 2:
        status = "review"
        reasons.append("two_consecutive_weeks_below_historical_5th_percentile")
    if last4_below_p10 >= 3:
        status = "review"
        reasons.append("three_of_last_four_weeks_below_historical_10th_percentile")
    if status != "review" and p10_streak >= 2:
        status = "watch"
        reasons.append("two_consecutive_weeks_below_historical_10th_percentile")
    if status != "review" and last4_below_p10 >= 2:
        status = "watch"
        reasons.append("two_of_last_four_weeks_below_historical_10th_percentile")
    if not reasons:
        reasons.append("no_consistent_underperformance" if eligible else "no_completed_full_live_weeks")

    return {
        "lane": lane,
        "consistency_status": status,
        "consistency_reasons": ";".join(reasons),
        "completed_full_weeks": len(eligible),
        "latest_completed_week": latest.get("week_label", ""),
        "latest_completed_net_r": latest.get("net_r", ""),
        "latest_completed_percentile": latest.get("historical_percentile", ""),
        "p10_streak": p10_streak,
        "p05_streak": p05_streak,
        "last4_completed_weeks": len(last4),
        "last4_below_p10": last4_below_p10,
        "last4_below_p05": last4_below_p05,
    }


def pivot_live_week_history(history_rows: Sequence[dict[str, Any]]) -> list[list[Any]]:
    by_week: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in history_rows:
        by_week[str(row["week_start_sgt"])][str(row["lane"])] = dict(row)

    table_rows: list[list[Any]] = []
    for week_start in sorted(by_week.keys(), reverse=True):
        lane_rows = by_week[week_start]
        first_row = next(iter(lane_rows.values()))
        notes = week_notes(lane_rows)
        row: list[Any] = [
            first_row["week_label"],
            week_type_label(lane_rows),
            consistency_input_label(lane_rows),
        ]
        for lane in LANE_DISPLAY_ORDER:
            row.extend(compact_lane_week_cells(lane_rows.get(lane)))
        row.append(notes)
        table_rows.append(row)
    return table_rows


def compact_lane_week_cells(row: dict[str, Any] | None) -> list[Any]:
    if row is None:
        return [muted_cell("n/a"), "n/a", "n/a", "n/a", "n/a"]
    return [
        status_cell(row.get("performance_status")),
        fmt_r(row.get("net_r")),
        percentile_text(row.get("historical_percentile")),
        fmt_int(row.get("closed_trades")),
        win_loss_text(row),
    ]


def week_type_label(lane_rows: dict[str, dict[str, Any]]) -> str:
    if all(lane in lane_rows and bool(lane_rows[lane].get("completed_full_week")) for lane in LANE_DISPLAY_ORDER):
        return "COMPLETED"
    return "PARTIAL"


def consistency_input_label(lane_rows: dict[str, dict[str, Any]]) -> str:
    included = [lane for lane in LANE_DISPLAY_ORDER if bool(lane_rows.get(lane, {}).get("included_in_consistency"))]
    if len(included) == len(LANE_DISPLAY_ORDER):
        return "Both"
    if included:
        return " / ".join(included)
    return "No"


def week_notes(lane_rows: dict[str, dict[str, Any]]) -> str:
    notes: list[str] = []
    for lane in LANE_DISPLAY_ORDER:
        row = lane_rows.get(lane)
        if row is None:
            notes.append(f"{lane} n/a")
            continue
        reasons = str(row.get("partial_reasons") or "")
        if reasons:
            notes.append(f"{lane}: {humanize_reasons(reasons)}")
    return "; ".join(notes) if notes else "none"


def humanize_reasons(raw: str) -> str:
    return ", ".join(part.replace("_", " ") for part in raw.split(";") if part)


def trailing_count(rows: Sequence[dict[str, Any]], predicate: Any) -> int:
    count = 0
    for row in reversed(rows):
        if not predicate(row):
            break
        count += 1
    return count


def combined_summary_row(
    weekly_rows: Sequence[dict[str, Any]],
    week_start_sgt: pd.Timestamp,
    week_end_sgt: pd.Timestamp,
) -> dict[str, Any] | None:
    rows = [row for row in weekly_rows if row["lane"] != "COMBINED"]
    if not rows:
        return None
    closed = sum(int(row["closed_trades"]) for row in rows)
    wins = sum(int(row["wins"]) for row in rows)
    losses = sum(int(row["losses"]) for row in rows)
    gross_win = 0.0
    gross_loss = 0.0
    for row in rows:
        for trade in row.get("trades", []):
            value = float(trade.r_result or 0.0)
            if value > 0:
                gross_win += value
            elif value < 0:
                gross_loss += abs(value)
    return {
        "lane": "COMBINED",
        "week_start_sgt": week_start_sgt.isoformat(),
        "week_end_sgt": week_end_sgt.isoformat(),
        "report_as_of_utc": rows[0].get("report_as_of_utc"),
        "first_journal_utc": "",
        "first_runner_utc": "",
        "first_order_utc": "",
        "first_closed_trade_utc": "",
        "partial_week": any(bool(row["partial_week"]) for row in rows),
        "partial_reasons": "combined_from_lane_statuses",
        "completed_full_live_weeks": min(int(row.get("completed_full_live_weeks") or 0) for row in rows),
        "latest_week_complete": all(bool(row.get("latest_week_complete")) for row in rows),
        "vps_head": "",
        "fetch_error": ";".join(str(row.get("fetch_error") or "") for row in rows if row.get("fetch_error")),
        "local_head": rows[0].get("local_head"),
        "origin_head": rows[0].get("origin_head"),
        "latest_runtime_commit": rows[0].get("latest_runtime_commit"),
        "runtime_synced": all(bool(row["runtime_synced"]) for row in rows),
        "runtime_changed_in_week": any(bool(row["runtime_changed_in_week"]) for row in rows),
        "closed_trades": closed,
        "wins": wins,
        "losses": losses,
        "win_rate": safe_ratio(wins, closed),
        "net_r": sum(float(row["net_r"]) for row in rows),
        "net_pnl": sum(float(row["net_pnl"]) for row in rows),
        "profit_factor": None if gross_loss == 0 else gross_win / gross_loss,
        "worst_symbol": "see lane rows",
        "worst_timeframe": "see lane rows",
        "worst_side": "see lane rows",
        "retryable_waits": sum(int(row["retryable_waits"]) for row in rows),
        "spread_waits": sum(int(row["spread_waits"]) for row in rows),
        "market_recovery_waits": sum(int(row["market_recovery_waits"]) for row in rows),
        "market_closed_waits": sum(int(row["market_closed_waits"]) for row in rows),
        "true_rejections": sum(int(row["true_rejections"]) for row in rows),
        "pending_orders": sum(int(row["pending_orders"]) for row in rows),
        "active_positions": sum(int(row["active_positions"]) for row in rows),
        "processed_signal_keys": sum(int(row["processed_signal_keys"]) for row in rows),
    }


def historical_weekly_benchmark(path: Path) -> dict[str, Any]:
    data = pd.read_csv(path)
    if "separation_variant_id" in data.columns:
        data = data[data["separation_variant_id"] == "exclude_lp_pivot_inside_fs"].copy()
    value_col = "commission_adjusted_net_r" if "commission_adjusted_net_r" in data.columns else "net_r"
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    data["week_start_sgt"] = data["exit_time_utc"].map(lambda value: trading_week_window_for_timestamp(value)[0])
    weekly = data.groupby("week_start_sgt")[value_col].sum().sort_values()
    if weekly.empty:
        return {
            "historical_weeks": 0,
            "avg_week_r": 0.0,
            "median_week_r": 0.0,
            "p10_week_r": 0.0,
            "p05_week_r": 0.0,
            "worst_week_r": 0.0,
            "worst_week": "",
            "weekly_r_values": [],
        }
    return {
        "historical_weeks": int(len(weekly)),
        "avg_week_r": float(weekly.mean()),
        "median_week_r": float(weekly.median()),
        "p10_week_r": float(weekly.quantile(0.10)),
        "p05_week_r": float(weekly.quantile(0.05)),
        "worst_week_r": float(weekly.iloc[0]),
        "worst_week": str(weekly.index[0].date()),
        "weekly_r_values": [float(value) for value in weekly.tolist()],
    }


def classify_week(row: dict[str, Any], benchmark: dict[str, Any]) -> dict[str, Any]:
    if row["lane"] == "COMBINED":
        return {"concern_status": "watch", "concern_reasons": "combined_view"}
    net_r = float(row.get("net_r") or 0.0)
    performance_status, performance_reasons, band = classify_performance(net_r, benchmark)
    status = performance_status
    reasons: list[str] = list(performance_reasons)
    evidence_caveats: list[str] = []
    if row.get("partial_week"):
        status = "watch" if status == "normal" else status
        evidence_caveats.append("partial_week")
    if row.get("runtime_changed_in_week"):
        evidence_caveats.append("runtime_changed_in_week")
    if not row.get("runtime_synced"):
        evidence_caveats.append("vps_not_confirmed_runtime_synced")
    if row.get("fetch_error"):
        status = "review"
        evidence_caveats.append("lane_fetch_incomplete")
    if concentration_risk(row):
        evidence_caveats.append("loss_concentration")
    percentile = historical_percentile(net_r, benchmark.get("weekly_r_values") or [])
    row["concern_status"] = status
    row["concern_reasons"] = ";".join(reasons)
    row["evidence_caveats"] = ";".join(evidence_caveats) if evidence_caveats else "none"
    row["historical_percentile"] = "" if percentile is None else percentile
    row["historical_percentile_band"] = band
    return {
        "concern_status": status,
        "concern_reasons": row["concern_reasons"],
        "evidence_caveats": row["evidence_caveats"],
        "net_r": net_r,
        "p10_week_r": benchmark.get("p10_week_r"),
        "p05_week_r": benchmark.get("p05_week_r"),
        "historical_percentile": row["historical_percentile"],
        "historical_percentile_band": row["historical_percentile_band"],
    }


def historical_percentile(net_r: float, historical_values: Sequence[float]) -> float | None:
    if not historical_values:
        return None
    below_or_equal = sum(1 for value in historical_values if value <= net_r)
    return (below_or_equal / len(historical_values)) * 100.0


def percentile_band(percentile: float) -> str:
    if percentile <= 5.0:
        return "<=p5"
    if percentile <= 10.0:
        return "<=p10"
    return f"p{percentile:.1f}"


def concentration_risk(row: dict[str, Any]) -> bool:
    if float(row.get("net_r") or 0.0) >= 0:
        return False
    for field in ("worst_symbol", "worst_timeframe", "worst_side"):
        text = str(row.get(field) or "")
        if "R" not in text:
            continue
        try:
            value = float(text.split()[-1].replace("R", ""))
        except ValueError:
            continue
        if value <= float(row["net_r"]) * 0.5:
            return True
    return False


def write_outputs(
    *,
    output_dir: Path,
    docs_output: Path,
    weekly_summary: Sequence[dict[str, Any]],
    lane_breakdown: Sequence[dict[str, Any]],
    historical_benchmark: Sequence[dict[str, Any]],
    weekly_flags: Sequence[dict[str, Any]],
    live_week_history: Sequence[dict[str, Any]],
    live_week_trade_details: Sequence[dict[str, Any]],
    consistency_flags: Sequence[dict[str, Any]],
    run_summary: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "weekly_summary.csv", weekly_summary)
    write_csv(output_dir / "lane_weekly_breakdown.csv", lane_breakdown)
    write_csv(output_dir / "historical_benchmark.csv", historical_benchmark)
    write_csv(output_dir / "weekly_flags.csv", weekly_flags)
    write_csv(output_dir / "live_week_history.csv", live_week_history)
    write_csv(output_dir / "live_week_trade_details.csv", live_week_trade_details)
    write_csv(output_dir / "consistency_flags.csv", consistency_flags)
    (output_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, sort_keys=True), encoding="utf-8")
    dashboard = build_dashboard_html(
        weekly_summary,
        lane_breakdown,
        historical_benchmark,
        weekly_flags,
        live_week_history,
        consistency_flags,
        run_summary,
    )
    (output_dir / "dashboard.html").write_text(dashboard, encoding="utf-8")
    docs_output.parent.mkdir(parents=True, exist_ok=True)
    docs_output.write_text(dashboard, encoding="utf-8")


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})


def build_dashboard_html(
    weekly_summary: Sequence[dict[str, Any]],
    lane_breakdown: Sequence[dict[str, Any]],
    historical_benchmark: Sequence[dict[str, Any]],
    weekly_flags: Sequence[dict[str, Any]],
    live_week_history: Sequence[dict[str, Any]],
    consistency_flags: Sequence[dict[str, Any]],
    run_summary: dict[str, Any],
) -> str:
    lane_rows = [row for row in weekly_summary if row["lane"] != "COMBINED"]
    combined = next((row for row in weekly_summary if row["lane"] == "COMBINED"), None)
    flags = {row["lane"]: row for row in weekly_flags}
    benchmarks = {row["lane"]: row for row in historical_benchmark}
    kpis = []
    for row in lane_rows:
        flag = flags.get(row["lane"], {})
        benchmark = benchmarks.get(row["lane"], {})
        kpis.append(
            [
                row["lane"],
                str(flag.get("concern_status", row.get("concern_status", "watch"))).upper(),
                f"{fmt_r(row['net_r'])} | {fmt_int(row['closed_trades'])} closed | {full_week_text(row.get('completed_full_live_weeks'))}",
            ]
        )
    summary_table = [
        [
            row["lane"],
            str(row["partial_week"]),
            row["partial_reasons"],
            fmt_int(row.get("completed_full_live_weeks")),
            str(row.get("latest_week_complete")),
            row["first_journal_utc"],
            row["first_runner_utc"],
            row["first_order_utc"],
            row["first_closed_trade_utc"],
            short_text(row.get("local_head")),
            short_text(row.get("origin_head")),
            short_text(row.get("vps_head")),
            row["fetch_error"],
            (str(row.get("latest_runtime_commit") or "").split() or [""])[0],
            str(row["runtime_synced"]),
            str(row["runtime_changed_in_week"]),
            fmt_int(row["closed_trades"]),
            fmt_r(row["net_r"]),
            fmt_money(row["net_pnl"]),
            pct(row["win_rate"]),
            pf(row["profit_factor"]),
            row["worst_symbol"],
            row["worst_timeframe"],
            row["worst_side"],
            fmt_int(row["retryable_waits"]),
            fmt_int(row["true_rejections"]),
            fmt_int(row["pending_orders"]),
            fmt_int(row["active_positions"]),
        ]
        for row in weekly_summary
    ]
    benchmark_table = [
        [
            row["lane"],
            row["benchmark_label"],
            fmt_int(row["historical_weeks"]),
            fmt_r(row["avg_week_r"]),
            fmt_r(row["median_week_r"]),
            fmt_r(row["p10_week_r"]),
            fmt_r(row["p05_week_r"]),
            fmt_r(row["worst_week_r"]),
            row["worst_week"],
        ]
        for row in historical_benchmark
    ]
    flag_table = [
        [
            row["lane"],
            status_cell(row["concern_status"]),
            row["concern_reasons"],
            row.get("evidence_caveats", "none"),
            fmt_r(row["net_r"]),
            percentile_text(row.get("historical_percentile")),
            row["historical_percentile_band"],
            fmt_r(row["p10_week_r"]),
            fmt_r(row["p05_week_r"]),
        ]
        for row in weekly_flags
    ]
    consistency_table = [
        [
            row["lane"],
            status_cell(row["consistency_status"]),
            row["consistency_reasons"],
            fmt_int(row["completed_full_weeks"]),
            row["latest_completed_week"],
            fmt_r(row["latest_completed_net_r"]),
            percentile_text(row.get("latest_completed_percentile")),
            fmt_int(row["p10_streak"]),
            fmt_int(row["p05_streak"]),
            fmt_int(row["last4_below_p10"]),
            fmt_int(row["last4_below_p05"]),
        ]
        for row in consistency_flags
    ]
    comparison_table = pivot_live_week_history(live_week_history)
    breakdown_table = [
        [
            row["lane"],
            row["group_type"],
            row["group_value"],
            fmt_int(row["closed_trades"]),
            fmt_int(row["wins"]),
            fmt_int(row["losses"]),
            fmt_r(row["net_r"]),
            fmt_money(row["net_pnl"]),
        ]
        for row in lane_breakdown
    ]
    combined_note = ""
    if combined:
        combined_note = (
            f"<p class=\"callout\">Combined live view: {fmt_int(combined['closed_trades'])} closed trades, "
            f"{fmt_r(combined['net_r'])}, {fmt_money(combined['net_pnl'])}. This is not benchmarked because FTMO and IC use different broker feeds and account sizing.</p>"
        )
    rows_html = "".join(
        f'<div class="kpi"><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></div>'
        for label, value, note in kpis
    )
    title = "LPFS Live Weekly Performance"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    {dashboard_base_css(table_min_width="1100px", extra_css=weekly_css())}
  </style>
</head>
<body>
  {dashboard_header_html(
      title=title,
      subtitle_html="Read-only FTMO and IC weekly live-performance monitor. It compares live closed-trade R to the current V22 historical distributions and labels whether the week is normal, watch, or review-worthy.",
      current_page="live_weekly_performance.html",
      section_links=[
          ("#status", "Status"),
          ("#summary", "Weekly Summary"),
          ("#consistency", "Consistency"),
          ("#comparison", "Week Comparison"),
          ("#benchmark", "Backtest Benchmark"),
          ("#breakdown", "Breakdown"),
          ("#workflow", "Refresh Workflow"),
      ],
  )}
  <main>
    <section id="status">
      <h2>Cause For Concern</h2>
      <p class="note">Latest dashboard window: <strong>{escape(run_summary.get('week_window_label'))}</strong>. It is marked complete after the Friday 21:00 UTC market close. Runtime changes and partial starts are evidence-quality caveats, while percentile status is measured against each lane's V22 weekly distribution.</p>
      <div class="kpis">{rows_html}</div>
      {combined_note}
      {table_html(["Lane", "Status", "Performance reasons", "Evidence caveats", "Net R", "Historical percentile", "Band", "p10", "p5"], flag_table)}
    </section>
    <section id="summary">
      <h2>Live Weekly Summary</h2>
      <p>Portfolio starts are detected from the first journal row and first live order. Runtime synced means the VPS contains the latest local strategy/runtime commit even if local docs/reporting commits are ahead.</p>
      {table_html(["Lane", "Partial", "Partial reasons", "Completed full weeks", "Latest complete", "First journal UTC", "First runner UTC", "First order UTC", "First closed UTC", "Local HEAD", "Origin HEAD", "VPS commit", "Fetch error", "Latest runtime", "Runtime synced", "Runtime changed", "Closed", "Net R", "Net PnL", "Win rate", "PF", "Worst symbol", "Worst TF", "Worst side", "Retry waits", "True rejects", "Pending", "Active"], summary_table)}
    </section>
    <section id="consistency">
      <h2>Consistency Check</h2>
      <p>Consistency flags ignore partial first weeks and use only completed full live weeks. Watch means repeated p10 underperformance; Review means repeated p5 or broad p10 underperformance.</p>
      {table_html(["Lane", "Status", "Reasons", "Completed full weeks", "Latest completed week", "Latest net R", "Latest percentile", "p10 streak", "p5 streak", "Last 4 <=p10", "Last 4 <=p5"], consistency_table)}
    </section>
    <section id="comparison">
      <h2>Live Week Comparison</h2>
      <p>Each row is one live trading week, shown latest first. FTMO and IC columns compare the same week window; partial startup weeks stay visible but do not count toward consistency unless marked as an input.</p>
      {table_html(["Week", "Week type", "Consistency input", "FTMO status", "FTMO net R", "FTMO percentile", "FTMO closed", "FTMO W/L", "IC status", "IC net R", "IC percentile", "IC closed", "IC W/L", "Notes"], comparison_table)}
    </section>
    <section id="benchmark">
      <h2>Historical Weekly Benchmark</h2>
      <p>Benchmarks use the current V22 LP-before-FS separated trade population with commission-adjusted R. FTMO and IC are compared to their own broker-data lineage.</p>
      {table_html(["Lane", "Benchmark", "Weeks", "Avg R", "Median R", "p10", "p5", "Worst R", "Worst week"], benchmark_table)}
    </section>
    <section id="breakdown">
      <h2>Loss Concentration Breakdown</h2>
      <p>Use this to see whether a weak week is broad strategy variance or concentrated in one symbol, timeframe, or side.</p>
      {table_html(["Lane", "Group", "Value", "Closed", "Wins", "Losses", "Net R", "Net PnL"], breakdown_table)}
    </section>
    <section id="workflow">
      <h2>Manual Refresh Workflow</h2>
      <p class="callout">Default command: <code>.\\venv\\Scripts\\python.exe scripts\\build_lpfs_live_weekly_performance.py --latest</code></p>
      <p>The script reads over SSH, fingerprints the inputs, and prints <code>already up to date</code> without rewriting files when the latest report already matches current journals, state, benchmarks, and git heads. Use <code>--force</code> only when intentionally regenerating the same evidence.</p>
      <p>Generated at <code>{escape(run_summary['generated_at_utc'])}</code>. Report packet: <code>{escape(_display_path(run_summary['output_dir']))}</code>.</p>
    </section>
    {metric_glossary_html()}
  </main>
  <footer>Read-only monitor. No live configs, VPS runtime state, journals, orders, positions, or scheduled tasks are changed.</footer>
</body>
</html>
"""


def weekly_css() -> str:
    return """
    .callout {
      background: #eef6f2;
      border-left: 4px solid #57a773;
      padding: 12px 14px;
      color: #253c30;
      margin: 0 0 14px;
    }
    .kpi small {
      display: block;
      margin-top: 4px;
      color: var(--muted);
    }
    .status-cell {
      font-weight: 800;
      letter-spacing: 0;
    }
    .status-normal {
      color: var(--good);
    }
    .status-watch {
      color: var(--warn);
    }
    .status-review {
      color: var(--bad);
    }
    .muted-cell {
      color: var(--muted);
    }
    """


def table_html(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    head = "".join(f"<th>{escape(value)}</th>" for value in headers)
    body = "".join("<tr>" + "".join(table_cell_html(value) for value in row) + "</tr>" for row in rows)
    return f'<div class="table-scroll"><table class="data-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def table_cell_html(value: Any) -> str:
    if isinstance(value, TableCell):
        class_attr = f' class="{escape(value.class_name)}"' if value.class_name else ""
        return f"<td{class_attr}>{escape(value.value)}</td>"
    return f"<td>{escape(value)}</td>"


def collect_git_info(*, as_of_utc: pd.Timestamp) -> dict[str, Any]:
    local_head = git_output(["rev-parse", "HEAD"])
    origin_head = git_output(["rev-parse", "origin/main"], check=False)
    latest_runtime_full = git_output(["log", "-1", "--format=%H", "--", *RUNTIME_PATHS], check=False)
    latest_runtime = git_output(["log", "-1", "--format=%h %aI %s", "--", *RUNTIME_PATHS], check=False)
    week_start_sgt, week_end_sgt = latest_sgt_week_window(as_of_utc)
    since = week_start_sgt.tz_convert("UTC").isoformat()
    until = min(as_of_utc, week_end_sgt.tz_convert("UTC")).isoformat()
    runtime_window = git_output(
        ["log", f"--since={since}", f"--until={until}", "--format=%h %aI %s", "--", *RUNTIME_PATHS],
        check=False,
    )
    return {
        "local_head": local_head,
        "origin_head": origin_head,
        "latest_runtime_commit_full": latest_runtime_full,
        "latest_runtime_commit": latest_runtime,
        "runtime_commits_in_window": [line for line in runtime_window.splitlines() if line.strip()],
    }


def is_commit_ancestor(ancestor: str, descendant: str) -> bool:
    if not ancestor or not descendant:
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def latest_sgt_week_window(as_of_utc: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    return trading_week_window_for_timestamp(as_of_utc)


def trading_week_window_for_timestamp(timestamp: Any) -> tuple[pd.Timestamp, pd.Timestamp]:
    value_utc = parse_timestamp(timestamp)
    start_utc = latest_trading_week_start_utc(value_utc)
    end_utc = start_utc + pd.Timedelta(days=TRADING_WEEK_DURATION_DAYS)
    return start_utc.tz_convert(SGT), end_utc.tz_convert(SGT)


def latest_trading_week_start_utc(as_of_utc: pd.Timestamp) -> pd.Timestamp:
    value_utc = as_of_utc.tz_convert("UTC")
    midnight = value_utc.normalize()
    days_since_start = (value_utc.weekday() - TRADING_WEEK_START_UTC_WEEKDAY) % 7
    start = midnight - pd.Timedelta(days=days_since_start) + pd.Timedelta(hours=TRADING_WEEK_START_UTC_HOUR)
    if start > value_utc:
        start -= pd.Timedelta(days=7)
    return start


def week_window_label(week_start_sgt: pd.Timestamp, week_end_sgt: pd.Timestamp) -> str:
    return f"{week_start_sgt:%Y-%m-%d %H:%M SGT} to {week_end_sgt:%Y-%m-%d %H:%M SGT}"


def latest_run_summary(report_root: Path) -> dict[str, Any] | None:
    if not report_root.exists():
        return None
    summaries = sorted(report_root.glob("*/run_summary.json"))
    if not summaries:
        return None
    return json.loads(summaries[-1].read_text(encoding="utf-8"))


def parse_json_line(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text.startswith("{"):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_timestamp(value: Any) -> pd.Timestamp:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    timestamp = pd.Timestamp(text)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def run_command(command: Sequence[str], *, timeout: int = 120, check: bool = True) -> str:
    result = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, timeout=timeout, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(command)}\n{result.stderr}")
    return result.stdout.strip()


def git_output(args: Sequence[str], *, check: bool = True) -> str:
    return run_command(["git", *args], check=check)


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safe_ratio(part: int, whole: int) -> float | None:
    if whole <= 0:
        return None
    return part / whole


def csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return f"{value:.10f}"
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return ""
    return value


def escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def status_cell(value: Any) -> TableCell:
    label = status_label(value)
    if label == "N/A":
        return muted_cell("n/a")
    return TableCell(label, f"status-cell status-{label.lower()}")


def muted_cell(value: Any) -> TableCell:
    return TableCell(value, "muted-cell")


def status_label(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text.upper() if text else "N/A"


def fmt_r(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{float(value):+.2f}R"


def fmt_money(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{float(value):+.2f}"


def pct(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def percentile_text(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{float(value):.1f}%"


def pf(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{float(value):.2f}"


def fmt_int(value: Any) -> str:
    if value is None or value == "":
        return "0"
    return str(int(value))


def full_week_text(value: Any) -> str:
    count = int(value or 0)
    noun = "week" if count == 1 else "weeks"
    return f"{count} full {noun}"


def win_loss_text(row: dict[str, Any] | None) -> str:
    if row is None:
        return "n/a"
    return f"{fmt_int(row.get('wins'))}/{fmt_int(row.get('losses'))}"


def short_text(value: Any, length: int = 7) -> str:
    text = "" if value is None else str(value)
    return text[:length]


if __name__ == "__main__":
    raise SystemExit(main())
