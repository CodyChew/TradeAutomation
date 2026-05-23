"""Build LPFS closed-trade diagnostic reports from journal rows.

The script is local/reporting-only. It does not read active VPS files directly;
copy or safely fetch journal rows first, then pass local paths with --journal.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
import sys
from typing import Any, Sequence

import pandas as pd


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
    closed_trade_diagnostic_rows,
    load_live_journal_events,
)


DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "live_ops" / "lpfs_trade_diagnostics"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--journal",
        action="append",
        default=[],
        help="Local journal path, or LANE=path. Repeat for multiple lanes.",
    )
    parser.add_argument(
        "--benchmark-trades",
        action="append",
        default=[],
        help="Optional backtest trades CSV, or LANE=path. Repeat for multiple lanes.",
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--as-of-utc", default=None)
    args = parser.parse_args()

    if not args.journal:
        parser.error("provide at least one --journal")

    as_of = pd.Timestamp(args.as_of_utc) if args.as_of_utc else pd.Timestamp.now(tz="UTC")
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    else:
        as_of = as_of.tz_convert("UTC")
    output_dir = Path(args.output_root) / as_of.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    live_rows: list[dict[str, Any]] = []
    for raw in args.journal:
        lane, path = _split_label(raw)
        events = load_live_journal_events(path)
        live_rows.extend(closed_trade_diagnostic_rows(events, lane=lane or Path(path).stem))

    benchmark_specs = args.benchmark_trades or [
        f"FTMO={DEFAULT_FTMO_TRADES}",
        f"IC={DEFAULT_IC_TRADES}",
    ]
    benchmark_rows: list[dict[str, Any]] = []
    for raw in benchmark_specs:
        lane, path = _split_label(raw)
        path_obj = Path(path)
        if path_obj.exists():
            benchmark_rows.extend(_load_backtest_rows(path_obj, lane=lane or path_obj.stem))

    diagnostic_csv = output_dir / "closed_trade_diagnostics.csv"
    comparison_csv = output_dir / "backtest_comparison.csv"
    summary_md = output_dir / "summary.md"
    _write_csv(diagnostic_csv, live_rows)
    comparison_rows = _comparison_rows(live_rows, benchmark_rows)
    _write_csv(comparison_csv, comparison_rows)
    summary_md.write_text(_render_summary(live_rows, comparison_rows, as_of), encoding="utf-8")

    print(f"trade_diagnostics_report={output_dir}")
    print(f"closed_trade_diagnostics={diagnostic_csv}")
    print(f"backtest_comparison={comparison_csv}")
    print(f"summary={summary_md}")
    return 0


def _split_label(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        return "", raw
    label, value = raw.split("=", 1)
    return label.strip(), value.strip()


def _load_backtest_rows(path: Path, *, lane: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows.append(
                {
                    "lane": lane,
                    "symbol": str(raw.get("symbol") or "").upper(),
                    "timeframe": str(raw.get("timeframe") or "").upper(),
                    "side": str(raw.get("side") or "").upper(),
                    "r_result": _first_float(raw.get("net_r"), raw.get("fill_r"), raw.get("reference_r")),
                    "entry_time_utc": raw.get("entry_time_utc"),
                    "exit_time_utc": raw.get("exit_time_utc"),
                    "risk_atr": _first_float(raw.get("meta_risk_atr"), raw.get("risk_atr")),
                    "bars_from_lp_break": _first_float(raw.get("meta_bars_from_lp_break"), raw.get("bars_from_lp_break")),
                }
            )
    return rows


def _comparison_rows(live_rows: Sequence[dict[str, Any]], benchmark_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    group_sets = [
        ("lane", "timeframe"),
        ("lane", "symbol"),
        ("lane", "side"),
        ("lane", "symbol", "timeframe"),
        ("lane", "timeframe", "side"),
    ]
    for group_by in group_sets:
        live_groups = _group_result_stats(live_rows, group_by)
        benchmark_groups = _group_result_stats(benchmark_rows, group_by)
        keys = sorted(set(live_groups) | set(benchmark_groups))
        for key in keys:
            live = live_groups.get(key, {})
            benchmark = benchmark_groups.get(key, {})
            row = {"group_by": "|".join(group_by)}
            row.update({column: value for column, value in zip(group_by, key)})
            row.update(_prefix("live", live))
            row.update(_prefix("backtest", benchmark))
            row["avg_r_delta_live_minus_backtest"] = _delta(live.get("avg_r"), benchmark.get("avg_r"))
            rows.append(row)
    return rows


def _group_result_stats(rows: Sequence[dict[str, Any]], group_by: Sequence[str]) -> dict[tuple[Any, ...], dict[str, Any]]:
    values_by_key: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        value = _first_float(row.get("r_result"))
        if value is None:
            continue
        key = tuple(str(row.get(column) or "").upper() for column in group_by)
        values_by_key[key].append(value)
    stats: dict[tuple[Any, ...], dict[str, Any]] = {}
    for key, values in values_by_key.items():
        wins = sum(1 for value in values if value > 0)
        losses = sum(1 for value in values if value < 0)
        gross_win = sum(value for value in values if value > 0)
        gross_loss = abs(sum(value for value in values if value < 0))
        stats[key] = {
            "trades": len(values),
            "net_r": sum(values),
            "avg_r": sum(values) / len(values),
            "win_rate": wins / len(values) if values else None,
            "losses": losses,
            "profit_factor": None if gross_loss <= 0 else gross_win / gross_loss,
        }
    return stats


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    columns = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _render_summary(live_rows: Sequence[dict[str, Any]], comparison_rows: Sequence[dict[str, Any]], as_of_utc: pd.Timestamp) -> str:
    enriched = sum(1 for row in live_rows if row.get("diagnostic_schema_version"))
    lines = [
        "# LPFS Trade Diagnostics",
        "",
        f"Generated UTC: `{as_of_utc.isoformat()}`",
        f"Closed trades: `{len(live_rows)}`",
        f"Rows with diagnostic payloads: `{enriched}`",
        "",
        "This report is additive and does not change live trading behavior.",
    ]
    notable = [
        row
        for row in comparison_rows
        if row.get("group_by") == "lane|timeframe" and _first_float(row.get("live_trades")) not in (None, 0)
    ]
    if notable:
        lines.extend(["", "## Timeframe Comparison", ""])
        for row in notable:
            lines.append(
                "- "
                + f"{row.get('lane')} {row.get('timeframe')}: "
                + f"live {row.get('live_trades')} trades, avg {float(row.get('live_avg_r') or 0):+.3f}R; "
                + f"backtest avg {float(row.get('backtest_avg_r') or 0):+.3f}R"
            )
    return "\n".join(lines) + "\n"


def _prefix(prefix: str, values: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in values.items()}


def _delta(left: Any, right: Any) -> float | None:
    left_value = _first_float(left)
    right_value = _first_float(right)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def _first_float(*values: Any) -> float | None:
    for value in values:
        try:
            if value in (None, ""):
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


if __name__ == "__main__":
    raise SystemExit(main())
