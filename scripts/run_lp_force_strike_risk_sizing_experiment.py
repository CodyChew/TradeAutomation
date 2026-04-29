from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

from lp_force_strike_dashboard_metadata import (
    dashboard_page,
    dashboard_page_links,
    experiment_summary_css,
    experiment_summary_html,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [
    REPO_ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _write_csv(path: str | Path, frame: pd.DataFrame | list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    payload.to_csv(target, index=False)


def _escape(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


def _fmt_int(value: Any) -> str:
    return f"{int(float(value)):,.0f}"


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.{digits}f}"


def _fmt_pct_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.2f}%"


def _metric_class(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if number > 0:
        return "positive"
    if number < 0:
        return "negative"
    return "neutral"


def _table(headers: list[str], rows: list[list[Any]], *, classes: str = "") -> str:
    thead = "".join(f"<th>{_escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        cells = []
        for value in row:
            if isinstance(value, tuple):
                display, cell_class = value
                cells.append(f'<td class="{cell_class}">{display}</td>')
            else:
                cells.append(f"<td>{value}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="{classes}"><thead><tr>{thead}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _risk_label(schedule: dict[str, Any]) -> str:
    return str(schedule.get("label") or schedule["schedule_id"])


def risk_pct_for_timeframe(schedule: dict[str, Any], timeframe: str) -> float:
    """Return percent of account risked for a trade in the given timeframe."""

    kind = str(schedule["kind"])
    if kind == "fixed":
        return float(schedule["risk_pct"])
    if kind == "timeframe":
        risk_by_timeframe = schedule["risk_by_timeframe"]
        if timeframe not in risk_by_timeframe:
            raise ValueError(f"Risk schedule {schedule['schedule_id']} has no risk for timeframe {timeframe!r}")
        return float(risk_by_timeframe[timeframe])
    raise ValueError(f"Unsupported risk schedule kind: {kind!r}")


def filter_baseline_trades(trades: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    required = {
        "symbol",
        "timeframe",
        "entry_time_utc",
        "exit_time_utc",
        "net_r",
        "pivot_strength",
        "base_candidate_id",
    }
    missing = sorted(required.difference(trades.columns))
    if missing:
        raise ValueError(f"Trade frame missing required columns: {missing}")

    data = trades.copy()
    data["pivot_strength"] = data["pivot_strength"].astype(int)
    data["timeframe"] = data["timeframe"].astype(str)
    data["base_candidate_id"] = data["base_candidate_id"].astype(str)
    selected_timeframes = {str(value) for value in config["timeframes"]}
    data = data[
        (data["pivot_strength"] == int(config["pivot_strength"]))
        & (data["timeframe"].isin(selected_timeframes))
        & (data["base_candidate_id"] == str(config["base_candidate_id"]))
    ].copy()
    data["entry_time_utc"] = pd.to_datetime(data["entry_time_utc"], utc=True)
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    data["symbol"] = data["symbol"].astype(str)
    return data.sort_values(["entry_time_utc", "exit_time_utc", "symbol", "timeframe"]).reset_index(drop=True)


def apply_risk_schedule(trades: pd.DataFrame, schedule: dict[str, Any]) -> pd.DataFrame:
    data = trades.copy()
    data["schedule_id"] = str(schedule["schedule_id"])
    data["schedule_label"] = _risk_label(schedule)
    data["risk_pct"] = data["timeframe"].map(lambda timeframe: risk_pct_for_timeframe(schedule, str(timeframe)))
    data["pnl_pct"] = data["net_r"] * data["risk_pct"]
    return data


def _max_drawdown_from_curve(curve: pd.DataFrame, value_col: str) -> dict[str, Any]:
    if curve.empty:
        return {
            "max_drawdown_pct": 0.0,
            "longest_underwater_days": 0.0,
            "max_drawdown_start_utc": None,
            "max_drawdown_trough_utc": None,
            "max_drawdown_recovery_utc": None,
        }

    data = curve.copy().reset_index(drop=True)
    data["peak_pct"] = data[value_col].cummax().clip(lower=0.0)
    data["drawdown_pct"] = data["peak_pct"] - data[value_col]
    max_idx = int(data["drawdown_pct"].idxmax())
    max_row = data.loc[max_idx]
    peak_value = float(max_row["peak_pct"])
    peak_idx = 0
    if peak_value > 0:
        peak_matches = data.loc[:max_idx][data.loc[:max_idx, value_col].eq(peak_value)]
        if not peak_matches.empty:
            peak_idx = int(peak_matches.index[0])
    recovery = data[(data.index > max_idx) & (data[value_col] >= peak_value)]

    in_drawdown = False
    period_start = None
    longest_days = 0.0
    for row in data.itertuples():
        drawdown = float(row.drawdown_pct)
        current_time = row.time_utc
        if drawdown > 1e-12 and not in_drawdown:
            in_drawdown = True
            period_start = current_time
        elif drawdown <= 1e-12 and in_drawdown:
            days = (current_time - period_start).total_seconds() / 86400
            longest_days = max(longest_days, days)
            in_drawdown = False
            period_start = None
    if in_drawdown and period_start is not None:
        days = (data.iloc[-1]["time_utc"] - period_start).total_seconds() / 86400
        longest_days = max(longest_days, days)

    return {
        "max_drawdown_pct": float(max_row["drawdown_pct"]),
        "longest_underwater_days": longest_days,
        "max_drawdown_start_utc": data.loc[peak_idx, "time_utc"].isoformat(),
        "max_drawdown_trough_utc": max_row["time_utc"].isoformat(),
        "max_drawdown_recovery_utc": None if recovery.empty else recovery.iloc[0]["time_utc"].isoformat(),
    }


def realized_equity_curve(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["time_utc", "equity_pct"])
    data = trades.sort_values(["exit_time_utc", "entry_time_utc", "symbol", "timeframe"]).copy()
    data["equity_pct"] = data["pnl_pct"].cumsum()
    return data[["exit_time_utc", "equity_pct"]].rename(columns={"exit_time_utc": "time_utc"}).reset_index(drop=True)


def risk_reserved_equity_curve(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["time_utc", "equity_reserved_pct", "realized_pct", "open_risk_pct"])

    events = []
    for row in trades.itertuples():
        events.append(
            {
                "time_utc": row.entry_time_utc,
                "sort_order": 0,
                "pnl_delta_pct": 0.0,
                "risk_delta_pct": float(row.risk_pct),
            }
        )
        events.append(
            {
                "time_utc": row.exit_time_utc,
                "sort_order": 1,
                "pnl_delta_pct": float(row.pnl_pct),
                "risk_delta_pct": -float(row.risk_pct),
            }
        )

    data = pd.DataFrame(events).sort_values(["time_utc", "sort_order"]).reset_index(drop=True)
    realized = 0.0
    open_risk = 0.0
    rows = []
    for row in data.itertuples():
        realized += float(row.pnl_delta_pct)
        open_risk += float(row.risk_delta_pct)
        if abs(open_risk) < 1e-12:
            open_risk = 0.0
        rows.append(
            {
                "time_utc": row.time_utc,
                "realized_pct": realized,
                "open_risk_pct": open_risk,
                "equity_reserved_pct": realized - open_risk,
            }
        )
    return pd.DataFrame(rows)


def worst_periods(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "negative_days": 0,
            "worst_day": None,
            "worst_day_pct": 0.0,
            "negative_weeks": 0,
            "worst_week": None,
            "worst_week_pct": 0.0,
            "negative_months": 0,
            "worst_month": None,
            "worst_month_pct": 0.0,
        }

    data = trades.copy()
    exit_naive = data["exit_time_utc"].dt.tz_convert(None)
    daily = data.groupby(exit_naive.dt.strftime("%Y-%m-%d"))["pnl_pct"].sum()
    weekly = data.groupby(exit_naive.dt.to_period("W").astype(str))["pnl_pct"].sum()
    monthly = data.groupby(exit_naive.dt.strftime("%Y-%m"))["pnl_pct"].sum()
    return {
        "negative_days": int((daily < 0).sum()),
        "worst_day": None if daily.empty else str(daily.idxmin()),
        "worst_day_pct": 0.0 if daily.empty else float(daily.min()),
        "negative_weeks": int((weekly < 0).sum()),
        "worst_week": None if weekly.empty else str(weekly.idxmin()),
        "worst_week_pct": 0.0 if weekly.empty else float(weekly.min()),
        "negative_months": int((monthly < 0).sum()),
        "worst_month": None if monthly.empty else str(monthly.idxmin()),
        "worst_month_pct": 0.0 if monthly.empty else float(monthly.min()),
    }


def exposure_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "max_concurrent_trades": 0,
            "max_same_symbol_stack": 0,
            "max_reserved_open_risk_pct": 0.0,
            "max_reserved_open_risk_time_utc": None,
            "max_new_trades_same_time": 0,
        }

    events = []
    for row in trades.itertuples():
        events.append((row.entry_time_utc, 0, str(row.symbol), 1, float(row.risk_pct)))
        events.append((row.exit_time_utc, 1, str(row.symbol), -1, -float(row.risk_pct)))
    events.sort(key=lambda item: (item[0], item[1], item[2]))

    open_count = 0
    open_risk = 0.0
    max_count = 0
    max_risk = 0.0
    max_risk_time = None
    symbol_counts: dict[str, int] = {}
    max_symbol_stack = 0
    for event_time, _order, symbol, count_delta, risk_delta in events:
        open_count += count_delta
        open_risk += risk_delta
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + count_delta
        max_count = max(max_count, open_count)
        max_symbol_stack = max(max_symbol_stack, symbol_counts[symbol])
        if open_risk > max_risk:
            max_risk = open_risk
            max_risk_time = event_time

    return {
        "max_concurrent_trades": int(max_count),
        "max_same_symbol_stack": int(max_symbol_stack),
        "max_reserved_open_risk_pct": float(max_risk),
        "max_reserved_open_risk_time_utc": None if max_risk_time is None else max_risk_time.isoformat(),
        "max_new_trades_same_time": int(trades.groupby("entry_time_utc").size().max()),
    }


def contribution_rows(trades: pd.DataFrame, group_field: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=[group_field, "trades", "total_return_pct", "avg_return_pct", "win_rate"])

    grouped = trades.groupby(group_field, dropna=False)
    rows = []
    total = float(trades["pnl_pct"].sum())
    for key, group in grouped:
        returns = group["pnl_pct"]
        gross_loss = float(returns[returns < 0].sum())
        rows.append(
            {
                group_field: key,
                "trades": int(len(group)),
                "total_return_pct": float(returns.sum()),
                "avg_return_pct": float(returns.mean()),
                "win_rate": float((returns > 0).mean()),
                "profit_factor": None if gross_loss == 0 else float(returns[returns > 0].sum()) / abs(gross_loss),
                "share_of_total_return": 0.0 if total <= 0 else float(returns.sum()) / total,
            }
        )
    return pd.DataFrame(rows).sort_values("total_return_pct", ascending=False).reset_index(drop=True)


def analyze_schedule(trades: pd.DataFrame, schedule: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    data = apply_risk_schedule(trades, schedule)
    realized_curve = realized_equity_curve(data)
    reserved_curve = risk_reserved_equity_curve(data)
    realized_dd = _max_drawdown_from_curve(realized_curve, "equity_pct")
    reserved_dd = _max_drawdown_from_curve(reserved_curve, "equity_reserved_pct")
    period = worst_periods(data)
    exposure = exposure_metrics(data)
    total_return = float(data["pnl_pct"].sum())
    max_reserved_dd = float(reserved_dd["max_drawdown_pct"])
    row = {
        "schedule_id": str(schedule["schedule_id"]),
        "schedule_label": _risk_label(schedule),
        "schedule_kind": str(schedule["kind"]),
        "trades": int(len(data)),
        "total_return_pct": total_return,
        "avg_return_pct": float(data["pnl_pct"].mean()) if len(data) else 0.0,
        "win_rate": float((data["pnl_pct"] > 0).mean()) if len(data) else 0.0,
        "realized_max_drawdown_pct": float(realized_dd["max_drawdown_pct"]),
        "realized_longest_underwater_days": float(realized_dd["longest_underwater_days"]),
        "realized_drawdown_start_utc": realized_dd["max_drawdown_start_utc"],
        "realized_drawdown_trough_utc": realized_dd["max_drawdown_trough_utc"],
        "realized_drawdown_recovery_utc": realized_dd["max_drawdown_recovery_utc"],
        "reserved_max_drawdown_pct": max_reserved_dd,
        "reserved_longest_underwater_days": float(reserved_dd["longest_underwater_days"]),
        "reserved_drawdown_start_utc": reserved_dd["max_drawdown_start_utc"],
        "reserved_drawdown_trough_utc": reserved_dd["max_drawdown_trough_utc"],
        "reserved_drawdown_recovery_utc": reserved_dd["max_drawdown_recovery_utc"],
        "return_to_reserved_drawdown": None if max_reserved_dd <= 0 else total_return / max_reserved_dd,
    }
    row.update(period)
    row.update(exposure)
    timeframe = contribution_rows(data, "timeframe")
    ticker = contribution_rows(data, "symbol")
    timeframe["schedule_id"] = row["schedule_id"]
    ticker["schedule_id"] = row["schedule_id"]
    return row, timeframe, ticker


def run_risk_sizing_analysis(
    trades: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline = filter_baseline_trades(trades, config)
    if baseline.empty:
        raise ValueError("No trades matched the configured V13 baseline filters.")

    summary_rows = []
    timeframe_frames = []
    ticker_frames = []
    for schedule in config["risk_schedules"]:
        row, timeframe, ticker = analyze_schedule(baseline, schedule)
        summary_rows.append(row)
        timeframe_frames.append(timeframe)
        ticker_frames.append(ticker)

    summary = pd.DataFrame(summary_rows)
    summary = summary.sort_values(["return_to_reserved_drawdown", "total_return_pct"], ascending=False).reset_index(drop=True)
    timeframe_rows = pd.concat(timeframe_frames, ignore_index=True) if timeframe_frames else pd.DataFrame()
    ticker_rows = pd.concat(ticker_frames, ignore_index=True) if ticker_frames else pd.DataFrame()
    return summary, timeframe_rows, ticker_rows


def _recommendation(summary: pd.DataFrame) -> pd.Series:
    preferred = summary[summary["schedule_id"] == "ladder_balanced_equal_ltf"]
    if not preferred.empty:
        return preferred.iloc[0]
    return summary.sort_values(["return_to_reserved_drawdown", "total_return_pct"], ascending=False).iloc[0]


def _summary_table(frame: pd.DataFrame, schedule_ids: set[str] | None = None) -> str:
    data = frame.copy()
    if schedule_ids is not None:
        data = data[data["schedule_id"].isin(schedule_ids)].copy()
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row["schedule_label"]),
                _fmt_int(row["trades"]),
                (_fmt_pct_value(row["total_return_pct"]), _metric_class(row["total_return_pct"])),
                _fmt_pct_value(row["realized_max_drawdown_pct"]),
                _fmt_num(row["realized_longest_underwater_days"], 0),
                _fmt_pct_value(row["reserved_max_drawdown_pct"]),
                _fmt_num(row["reserved_longest_underwater_days"], 0),
                _fmt_num(row["return_to_reserved_drawdown"], 2),
                (_fmt_pct_value(row["worst_day_pct"]), _metric_class(row["worst_day_pct"])),
                (_fmt_pct_value(row["worst_week_pct"]), _metric_class(row["worst_week_pct"])),
                (_fmt_pct_value(row["worst_month_pct"]), _metric_class(row["worst_month_pct"])),
                _fmt_pct_value(row["max_reserved_open_risk_pct"]),
                _fmt_int(row["max_concurrent_trades"]),
                _fmt_int(row["max_same_symbol_stack"]),
            ]
        )
    return _table(
        [
            "Schedule",
            "Trades",
            "Total Return",
            "Realized DD",
            "Realized UW Days",
            "Risk-Reserved DD",
            "Reserved UW Days",
            "Return/DD",
            "Worst Day",
            "Worst Week",
            "Worst Month",
            "Max Reserved Risk",
            "Max Concurrent",
            "Max Symbol Stack",
        ],
        rows,
    )


def _period_table(frame: pd.DataFrame) -> str:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _escape(row["schedule_label"]),
                _escape(row["worst_day"]),
                (_fmt_pct_value(row["worst_day_pct"]), _metric_class(row["worst_day_pct"])),
                _fmt_int(row["negative_days"]),
                _escape(row["worst_week"]),
                (_fmt_pct_value(row["worst_week_pct"]), _metric_class(row["worst_week_pct"])),
                _fmt_int(row["negative_weeks"]),
                _escape(row["worst_month"]),
                (_fmt_pct_value(row["worst_month_pct"]), _metric_class(row["worst_month_pct"])),
                _fmt_int(row["negative_months"]),
            ]
        )
    return _table(
        [
            "Schedule",
            "Worst Day",
            "Day Return",
            "Negative Days",
            "Worst Week",
            "Week Return",
            "Negative Weeks",
            "Worst Month",
            "Month Return",
            "Negative Months",
        ],
        rows,
    )


def _exposure_table(frame: pd.DataFrame) -> str:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _escape(row["schedule_label"]),
                _fmt_int(row["max_concurrent_trades"]),
                _fmt_int(row["max_same_symbol_stack"]),
                _fmt_int(row["max_new_trades_same_time"]),
                _fmt_pct_value(row["max_reserved_open_risk_pct"]),
                _escape(row["max_reserved_open_risk_time_utc"]),
            ]
        )
    return _table(
        [
            "Schedule",
            "Max Concurrent Trades",
            "Max Same-Symbol Stack",
            "Max New Trades Same Time",
            "Max Reserved Open Risk",
            "Max Risk Time",
        ],
        rows,
    )


def _contribution_table(frame: pd.DataFrame, field: str, schedule_id: str) -> str:
    data = frame[frame["schedule_id"] == schedule_id].copy()
    if data.empty:
        return "<p>No contribution rows are available.</p>"
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row[field]),
                _fmt_int(row["trades"]),
                (_fmt_pct_value(row["total_return_pct"]), _metric_class(row["total_return_pct"])),
                _fmt_pct_value(row["avg_return_pct"]),
                f"{float(row['win_rate']) * 100.0:.1f}%",
                _fmt_num(row["profit_factor"], 2),
                f"{float(row['share_of_total_return']) * 100.0:.1f}%",
            ]
        )
    return _table([field.title(), "Trades", "Total Return", "Avg Return", "Win Rate", "PF", "Return Share"], rows)


def _kpi(label: str, value: str, note: str = "") -> str:
    return f"""
    <div class="kpi">
      <div class="kpi-label">{_escape(label)}</div>
      <div class="kpi-value">{_escape(value)}</div>
      <div class="kpi-note">{_escape(note)}</div>
    </div>
    """


def _html_report(
    run_dir: Path,
    summary: pd.DataFrame,
    timeframe_rows: pd.DataFrame,
    ticker_rows: pd.DataFrame,
    *,
    current_page: str,
) -> str:
    try:
        page_metadata = dashboard_page(current_page)
    except KeyError:
        page_metadata = {
            "page": current_page,
            "nav_label": "Run",
            "title": "LP + Force Strike Risk Sizing Dashboard",
            "status_label": "Run report",
            "status_kind": "neutral",
            "question": "Which risk schedule gives practical drawdowns?",
            "setup": "Run-local V14 risk sizing dashboard.",
            "how_to_read": "Compare fixed risk and timeframe ladders before choosing account risk.",
            "conclusion": "No version-level conclusion is attached to this run-local page.",
            "action": "Use versioned docs pages for research conclusions.",
        }

    recommended = _recommendation(summary)
    fixed_ids = {"fixed_0p10", "fixed_0p25", "fixed_0p50"}
    ladder_ids = set(summary["schedule_id"]) - fixed_ids
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V14 Risk Sizing - by Cody</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #627181;
      --line: #d8e0e8;
      --accent: #22577a;
      --good: #2e7d50;
      --bad: #a23b3b;
      --warn: #9b5f00;
    }}
    * {{ box-sizing: border-box; }}
    html {{ -webkit-text-size-adjust: 100%; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 Inter, Segoe UI, Roboto, Arial, sans-serif; min-width: 0; overflow-x: hidden; }}
    header {{ background: #17202a; color: white; padding: 28px max(18px, 5vw); border-bottom: 4px solid #57a773; }}
    header h1 {{ margin: 0 0 8px; font-size: clamp(22px, 4vw, 28px); }}
    header p {{ margin: 0; color: #d8e0e8; max-width: 980px; overflow-wrap: anywhere; }}
    code {{ overflow-wrap: anywhere; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }}
    nav a {{ color: white; text-decoration: none; border: 1px solid rgba(255,255,255,.25); padding: 7px 10px; border-radius: 6px; background: rgba(255,255,255,.08); min-height: 34px; }}
    nav a.active {{ background: #57a773; border-color: #57a773; color: #17202a; font-weight: 700; }}
    main {{ padding: 24px max(18px, 5vw) 48px; }}
    section {{ margin: 0 0 22px; padding: 20px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 1px 2px rgba(23,32,42,.05); max-width: 100%; overflow-x: auto; }}
    h2 {{ margin: 0 0 14px; font-size: 20px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(170px, 100%), 1fr)); gap: 12px; margin-bottom: 18px; }}
    .kpi {{ background: #f9fbfc; border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .kpi-value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
    .kpi-note {{ color: var(--muted); font-size: 12px; min-height: 18px; }}
    .note {{ background: #f6f8f2; border-left: 4px solid #8aa936; padding: 12px 14px; color: #34412d; margin-bottom: 14px; }}
    .warning {{ background: #fff8e8; border-left-color: var(--warn); color: #4d3b13; }}
    {experiment_summary_css()}
    table {{ width: 100%; min-width: 1080px; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; vertical-align: top; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: #455464; background: #f7f9fb; font-weight: 700; position: sticky; top: 0; z-index: 1; }}
    .positive {{ color: var(--good); font-weight: 700; }}
    .negative {{ color: var(--bad); font-weight: 700; }}
    .neutral {{ color: var(--muted); }}
    footer {{ color: var(--muted); padding: 0 max(18px, 5vw) 28px; }}
    @media (max-width: 760px) {{
      header {{ padding: 22px 16px; }}
      nav a {{ flex: 1 1 auto; text-align: center; }}
      main {{ padding: 16px 12px 34px; }}
      section {{ padding: 14px; margin-bottom: 16px; }}
      .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
      .kpi {{ padding: 10px; }}
      .kpi-value {{ font-size: 20px; }}
      th, td {{ padding: 6px 7px; font-size: 12px; }}
    }}
    @media (max-width: 480px) {{
      .kpis {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>LP + Force Strike V14 Risk Sizing - by Cody</h1>
    <p>Static V14 report generated from <code>{_escape(run_dir)}</code>. This page converts the V13 take-all baseline into account-risk drawdowns.</p>
    <nav aria-label="Dashboard pages">
      {dashboard_page_links(current_page)}
    </nav>
  </header>
  <main>
    {experiment_summary_html(page_metadata)}
    <section id="recommendation">
      <h2>Recommendation Card</h2>
      <div class="kpis">
        {_kpi("Practical Starting Point", str(recommended["schedule_label"]), "default recommendation")}
        {_kpi("Total Return", _fmt_pct_value(recommended["total_return_pct"]), "account percent")}
        {_kpi("Realized DD", _fmt_pct_value(recommended["realized_max_drawdown_pct"]), "closed trade exits")}
        {_kpi("Risk-Reserved DD", _fmt_pct_value(recommended["reserved_max_drawdown_pct"]), "full open risk reserved")}
        {_kpi("Max Reserved Risk", _fmt_pct_value(recommended["max_reserved_open_risk_pct"]), "overlap exposure")}
      </div>
      <div class="note">Risk-reserved drawdown subtracts full risk for every open trade while it is active. It is intentionally more conservative than closed-trade drawdown.</div>
    </section>
    <section id="leaderboard">
      <h2>Risk Schedule Leaderboard</h2>
      {_summary_table(summary)}
    </section>
    <section id="fixed-risk">
      <h2>Fixed Risk Drawdown</h2>
      <div class="note">These rows scale the same trade sequence at one fixed percent risk per trade.</div>
      {_summary_table(summary, fixed_ids)}
    </section>
    <section id="ladders">
      <h2>Timeframe Ladder Drawdown</h2>
      <div class="note">Primary ladders keep H4 and H8 equal because their win rate and PF are close. The quality-weighted row is only a diagnostic H8 upsize.</div>
      {_summary_table(summary, ladder_ids)}
    </section>
    <section id="reserved">
      <h2>Realized vs Risk-Reserved Drawdown</h2>
      <div class="note warning">Use risk-reserved drawdown when judging how overlapping take-all trades may feel in a live account. It is a stress view, not a prop-firm rule simulation.</div>
      {_summary_table(summary)}
    </section>
    <section id="periods">
      <h2>Worst Day / Week / Month</h2>
      <div class="note">These rows aggregate closed-trade returns by exit date. They show the calendar pain points for each risk schedule.</div>
      {_period_table(summary)}
    </section>
    <section id="exposure">
      <h2>Max Concurrent Exposure</h2>
      <div class="note">The conservative exposure view processes entries before exits at the same timestamp, matching the risk-reserved drawdown stress assumption.</div>
      {_exposure_table(summary)}
    </section>
    <section id="timeframes">
      <h2>Timeframe Contribution</h2>
      <div class="note">Shown for the recommended schedule.</div>
      {_contribution_table(timeframe_rows, "timeframe", str(recommended["schedule_id"]))}
    </section>
    <section id="tickers">
      <h2>Ticker Contribution</h2>
      <div class="note">Shown for the recommended schedule. Use this to spot concentration after risk sizing.</div>
      {_contribution_table(ticker_rows, "symbol", str(recommended["schedule_id"]))}
    </section>
  </main>
  <footer>Generated from existing LP3 trade rows. No MT5 data pull or signal rerun was performed.</footer>
</body>
</html>
"""


def _run(config_path: Path, *, docs_output: Path | None = None) -> int:
    config = _read_json(config_path)
    input_path = REPO_ROOT / str(config["input_trades_path"])
    trades = _read_csv(input_path)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = REPO_ROOT / str(config["report_root"]) / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    summary, timeframe_rows, ticker_rows = run_risk_sizing_analysis(trades, config)
    for row in summary.itertuples():
        print(
            f"{row.schedule_id}: total={row.total_return_pct:.2f}% "
            f"realized_dd={row.realized_max_drawdown_pct:.2f}% "
            f"reserved_dd={row.reserved_max_drawdown_pct:.2f}% "
            f"max_open={row.max_reserved_open_risk_pct:.2f}%"
        )

    _write_json(run_dir / "run_config.json", {"config_path": str(config_path), "config": config})
    _write_csv(run_dir / "risk_sizing_summary.csv", summary)
    _write_csv(run_dir / "timeframe_contribution.csv", timeframe_rows)
    _write_csv(run_dir / "ticker_contribution.csv", ticker_rows)
    recommended = _recommendation(summary)
    run_summary = {
        "run_dir": str(run_dir),
        "input_trades_path": str(input_path),
        "summary_rows": int(len(summary)),
        "recommended_schedule_id": str(recommended["schedule_id"]),
        "recommended_total_return_pct": float(recommended["total_return_pct"]),
        "recommended_reserved_max_drawdown_pct": float(recommended["reserved_max_drawdown_pct"]),
    }
    _write_json(run_dir / "run_summary.json", run_summary)

    html_text = _html_report(
        run_dir,
        summary,
        timeframe_rows,
        ticker_rows,
        current_page="v14.html" if docs_output else "dashboard.html",
    )
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    (run_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    if docs_output is not None:
        target = REPO_ROOT / docs_output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True))
    return 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    summary = _read_csv(run_dir / "risk_sizing_summary.csv")
    timeframe_rows = _read_csv(run_dir / "timeframe_contribution.csv")
    ticker_rows = _read_csv(run_dir / "ticker_contribution.csv")
    html_text = _html_report(
        run_dir,
        summary,
        timeframe_rows,
        ticker_rows,
        current_page=docs_output.name,
    )
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V14 risk sizing and drawdown study.")
    parser.add_argument("--config", help="Path to risk sizing experiment config JSON.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v14.html.")
    parser.add_argument("--render-run-dir", help="Existing V14 run directory to render without rerunning.")
    args = parser.parse_args()

    if args.render_run_dir:
        if args.docs_output is None:
            raise SystemExit("--docs-output is required with --render-run-dir")
        return _render_existing(Path(args.render_run_dir), Path(args.docs_output))
    if args.config is None:
        raise SystemExit("--config is required unless --render-run-dir is used")
    return _run(Path(args.config), docs_output=None if args.docs_output is None else Path(args.docs_output))


if __name__ == "__main__":
    raise SystemExit(main())
