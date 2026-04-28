from __future__ import annotations

import argparse
from collections import defaultdict
import html
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_ROOT = REPO_ROOT / "reports" / "strategies" / "lp_force_strike_experiment_v1"
TIMEFRAME_ORDER = ["M30", "H4", "H8", "D1", "W1"]


def _latest_run(report_root: Path) -> Path:
    candidates = [path for path in report_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists()]
    if not candidates:
        raise FileNotFoundError(f"No completed run folders found under {report_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if pd.notna(result) else default


def _fmt_int(value: Any) -> str:
    return f"{int(_to_float(value)):,.0f}"


def _fmt_num(value: Any, digits: int = 3) -> str:
    number = _to_float(value)
    return f"{number:,.{digits}f}"


def _fmt_pct(value: Any) -> str:
    return f"{_to_float(value) * 100.0:,.1f}%"


def _escape(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


def _tf_sort_key(value: Any) -> tuple[int, str]:
    text = str(value)
    try:
        return TIMEFRAME_ORDER.index(text), text
    except ValueError:
        return len(TIMEFRAME_ORDER), text


def _metric_class(value: Any) -> str:
    number = _to_float(value)
    if number > 0:
        return "positive"
    if number < 0:
        return "negative"
    return "neutral"


def _candidate_short(candidate_id: str) -> str:
    text = str(candidate_id)
    text = re.sub(r"signal_zone_(\d+p?\d*)_pullback", lambda match: f"zone {match.group(1).replace('p', '.')} pullback", text)
    text = text.replace("signal_midpoint_pullback", "midpoint")
    text = text.replace("next_open", "next open")
    text = text.replace("fs_structure_max_1atr", "structure <= 1ATR")
    text = re.sub(r"fs_structure_max_(\d+p?\d*)atr", lambda match: f"structure <= {match.group(1).replace('p', '.')}ATR", text)
    text = text.replace("fs_structure", "structure")
    text = re.sub(
        r"partial_(\d+p?\d*)r_to_(\d+p?\d*)r",
        lambda match: f"partial {match.group(1).replace('p', '.')}R -> {match.group(2).replace('p', '.')}R",
        text,
    )
    text = text.replace("__", " / ")
    text = re.sub(r"(?<= / )(\d+p?\d*)r\b", lambda match: f"{match.group(1).replace('p', '.')}R", text)
    return text


def _trade_group_summary(trades_path: Path, group_fields: list[str]) -> pd.DataFrame:
    available = set(pd.read_csv(trades_path, nrows=0).columns)
    missing = [field for field in group_fields + ["net_r", "bars_held", "exit_reason"] if field not in available]
    if missing:
        return pd.DataFrame()
    usecols = list(dict.fromkeys(group_fields + ["net_r", "bars_held", "exit_reason"]))
    accum: dict[tuple[Any, ...], dict[str, float]] = defaultdict(
        lambda: {
            "trades": 0.0,
            "wins": 0.0,
            "losses": 0.0,
            "total_net_r": 0.0,
            "gross_win": 0.0,
            "gross_loss": 0.0,
            "bars_held_sum": 0.0,
            "target_exits": 0.0,
            "stop_exits": 0.0,
            "same_bar_stop_exits": 0.0,
            "end_of_data_exits": 0.0,
        }
    )

    for chunk in pd.read_csv(trades_path, usecols=usecols, chunksize=200_000):
        chunk["net_r"] = pd.to_numeric(chunk["net_r"], errors="coerce").fillna(0.0)
        chunk["bars_held"] = pd.to_numeric(chunk["bars_held"], errors="coerce").fillna(0.0)
        for keys, group in chunk.groupby(group_fields, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            metrics = accum[keys]
            net_r = group["net_r"]
            metrics["trades"] += float(len(group))
            metrics["wins"] += float((net_r > 0).sum())
            metrics["losses"] += float((net_r < 0).sum())
            metrics["total_net_r"] += float(net_r.sum())
            metrics["gross_win"] += float(net_r[net_r > 0].sum())
            metrics["gross_loss"] += float(net_r[net_r < 0].sum())
            metrics["bars_held_sum"] += float(group["bars_held"].sum())
            metrics["target_exits"] += float((group["exit_reason"] == "target").sum())
            metrics["stop_exits"] += float((group["exit_reason"] == "stop").sum())
            metrics["same_bar_stop_exits"] += float((group["exit_reason"] == "same_bar_stop_priority").sum())
            metrics["end_of_data_exits"] += float((group["exit_reason"] == "end_of_data").sum())

    rows: list[dict[str, Any]] = []
    for keys, metrics in accum.items():
        row = {field: value for field, value in zip(group_fields, keys)}
        trades = metrics["trades"]
        gross_loss = metrics["gross_loss"]
        row.update(
            {
                "trades": int(trades),
                "wins": int(metrics["wins"]),
                "losses": int(metrics["losses"]),
                "win_rate": metrics["wins"] / trades if trades else 0.0,
                "total_net_r": metrics["total_net_r"],
                "avg_net_r": metrics["total_net_r"] / trades if trades else 0.0,
                "profit_factor": None if gross_loss == 0 else metrics["gross_win"] / abs(gross_loss),
                "avg_bars_held": metrics["bars_held_sum"] / trades if trades else 0.0,
                "target_exits": int(metrics["target_exits"]),
                "stop_exits": int(metrics["stop_exits"]),
                "same_bar_stop_exits": int(metrics["same_bar_stop_exits"]),
                "end_of_data_exits": int(metrics["end_of_data_exits"]),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _skip_reason_summary(skipped_path: Path) -> pd.DataFrame:
    usecols = ["timeframe", "side", "reason", "candidate_entry_model", "candidate_stop_model"]
    rows: list[pd.DataFrame] = []
    for chunk in pd.read_csv(skipped_path, usecols=usecols, chunksize=200_000):
        grouped = chunk.groupby(usecols, dropna=False).size().reset_index(name="skips")
        rows.append(grouped)
    if not rows:
        return pd.DataFrame(columns=usecols + ["skips"])
    return pd.concat(rows, ignore_index=True).groupby(usecols, dropna=False)["skips"].sum().reset_index()


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


def _kpi(label: str, value: Any, note: str = "") -> str:
    return f"""
    <div class="kpi">
      <div class="kpi-label">{_escape(label)}</div>
      <div class="kpi-value">{_escape(value)}</div>
      <div class="kpi-note">{_escape(note)}</div>
    </div>
    """


def _bar(width: float, label: str = "") -> str:
    value = max(0.0, min(100.0, width))
    return f'<div class="bar-wrap"><div class="bar" style="width:{value:.2f}%"></div><span>{_escape(label)}</span></div>'


def _heat_class(value: float, max_abs: float) -> str:
    if max_abs <= 0:
        return "heat-neutral"
    ratio = abs(value) / max_abs
    bucket = min(4, max(1, int(ratio * 4) + 1))
    if value > 0:
        return f"heat-pos-{bucket}"
    if value < 0:
        return f"heat-neg-{bucket}"
    return "heat-neutral"


def _timeframe_overview(datasets: pd.DataFrame) -> str:
    grouped = datasets.groupby("timeframe", dropna=False)[["signals", "trades", "skipped"]].sum().reset_index()
    total_signals = max(float(grouped["signals"].sum()), 1.0)
    grouped = grouped.sort_values("timeframe", key=lambda series: series.map(_tf_sort_key))
    rows = []
    for _, row in grouped.iterrows():
        share = float(row["signals"]) / total_signals * 100.0
        rows.append(
            [
                _escape(row["timeframe"]),
                _fmt_int(row["signals"]),
                _bar(share, f"{share:.1f}%"),
                _fmt_int(row["trades"]),
                _fmt_int(row["skipped"]),
            ]
        )
    return _table(["Timeframe", "Signals", "Signal Share", "Trades", "Skipped"], rows)


def _leaderboard(summary: pd.DataFrame, *, top_n: int = 10) -> str:
    data = summary.sort_values(["avg_net_r", "total_net_r"], ascending=False).head(top_n)
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(_candidate_short(row["candidate_id"])),
                _fmt_int(row["trades"]),
                _fmt_pct(row["win_rate"]),
                (_fmt_num(row["avg_net_r"]), _metric_class(row["avg_net_r"])),
                (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                _fmt_num(row["profit_factor"], 2),
                _fmt_num(row["avg_bars_held"], 1),
            ]
        )
    return _table(["Candidate", "Trades", "Win Rate", "Avg R", "Total R", "PF", "Bars"], rows)


def _timeframe_leaders(summary_tf: pd.DataFrame) -> str:
    sections = []
    for timeframe in sorted(summary_tf["timeframe"].dropna().unique(), key=_tf_sort_key):
        data = summary_tf[summary_tf["timeframe"] == timeframe].sort_values(["avg_net_r", "total_net_r"], ascending=False).head(5)
        sections.append(f"<h3>{_escape(timeframe)}</h3>{_leaderboard(data, top_n=5)}")
    return "".join(sections)


def _robust_candidates(summary_tf: pd.DataFrame, *, focus_timeframes: list[str] | None = None) -> str:
    preferred_focus = focus_timeframes or ["H4", "H8", "D1", "W1"]
    present = set(summary_tf["timeframe"].dropna().astype(str))
    focus = [timeframe for timeframe in preferred_focus if timeframe in present]
    data = summary_tf[summary_tf["timeframe"].isin(focus)].copy()
    if data.empty:
        return "<p>No focused timeframe rows are available.</p>"

    grouped = data.groupby("candidate_id", dropna=False)
    rows_data = []
    for candidate_id, group in grouped:
        by_tf = group.set_index("timeframe")
        available = [timeframe for timeframe in focus if timeframe in by_tf.index]
        avg_values = [float(by_tf.loc[timeframe, "avg_net_r"]) for timeframe in available]
        pf_values = [float(by_tf.loc[timeframe, "profit_factor"]) for timeframe in available]
        row_data = {
            "candidate_id": candidate_id,
            "timeframes": len(available),
            "positive_timeframes": sum(value > 0 for value in avg_values),
            "pf_above_one": sum(value > 1 for value in pf_values),
            "avg_focus_r": sum(avg_values) / len(avg_values) if avg_values else 0.0,
            "worst_focus_r": min(avg_values) if avg_values else 0.0,
            "total_trades": int(group["trades"].sum()),
        }
        for timeframe in focus:
            row_data[f"{timeframe}_avg_r"] = by_tf.loc[timeframe, "avg_net_r"] if timeframe in by_tf.index else None
        rows_data.append(row_data)

    robust = pd.DataFrame(rows_data)
    robust = robust.sort_values(["positive_timeframes", "pf_above_one", "avg_focus_r"], ascending=False).head(10)
    rows = []
    for _, row in robust.iterrows():
        base_cells = [
            _escape(_candidate_short(row["candidate_id"])),
            _fmt_int(row["total_trades"]),
            f"{_fmt_int(row['positive_timeframes'])}/{_fmt_int(row['timeframes'])}",
            f"{_fmt_int(row['pf_above_one'])}/{_fmt_int(row['timeframes'])}",
            (_fmt_num(row["avg_focus_r"]), _metric_class(row["avg_focus_r"])),
            (_fmt_num(row["worst_focus_r"]), _metric_class(row["worst_focus_r"])),
        ]
        timeframe_cells = [
            (_fmt_num(row.get(f"{timeframe}_avg_r")), _metric_class(row.get(f"{timeframe}_avg_r"))) for timeframe in focus
        ]
        rows.append(base_cells + timeframe_cells)
    return _table(
        ["Candidate", "Trades", "+ Avg R TFs", "PF > 1 TFs", "Avg Focus R", "Worst Focus R"] + focus,
        rows,
    )


def _top_robust_candidate_ids(
    summary_tf: pd.DataFrame,
    *,
    focus_timeframes: list[str] | None = None,
    limit: int = 3,
) -> list[str]:
    preferred_focus = focus_timeframes or ["H4", "H8", "D1", "W1"]
    present = set(summary_tf["timeframe"].dropna().astype(str))
    focus = [timeframe for timeframe in preferred_focus if timeframe in present]
    data = summary_tf[summary_tf["timeframe"].isin(focus)].copy()
    if data.empty:
        return []

    rows_data = []
    for candidate_id, group in data.groupby("candidate_id", dropna=False):
        by_tf = group.set_index("timeframe")
        available = [timeframe for timeframe in focus if timeframe in by_tf.index]
        avg_values = [float(by_tf.loc[timeframe, "avg_net_r"]) for timeframe in available]
        pf_values = [float(by_tf.loc[timeframe, "profit_factor"]) for timeframe in available]
        rows_data.append(
            {
                "candidate_id": candidate_id,
                "positive_timeframes": sum(value > 0 for value in avg_values),
                "pf_above_one": sum(value > 1 for value in pf_values),
                "avg_focus_r": sum(avg_values) / len(avg_values) if avg_values else 0.0,
            }
        )
    robust = pd.DataFrame(rows_data)
    robust = robust.sort_values(["positive_timeframes", "pf_above_one", "avg_focus_r"], ascending=False).head(limit)
    return [str(value) for value in robust["candidate_id"].tolist()]


def _weak_symbol_timeframes(by_candidate_symbol_tf: pd.DataFrame, summary_tf: pd.DataFrame) -> str:
    if by_candidate_symbol_tf.empty:
        return "<p>No symbol/timeframe rows are available for this run.</p>"

    candidate_ids = _top_robust_candidate_ids(summary_tf, limit=3)
    if not candidate_ids:
        return "<p>No robust candidates are available for symbol/timeframe checks.</p>"

    data = by_candidate_symbol_tf[by_candidate_symbol_tf["candidate_id"].isin(candidate_ids)].copy()
    data["profit_factor_check"] = pd.to_numeric(data["profit_factor"], errors="coerce").fillna(float("inf"))
    data["avg_net_r_check"] = pd.to_numeric(data["avg_net_r"], errors="coerce").fillna(0.0)
    weak = data[(data["profit_factor_check"] < 1.0) | (data["avg_net_r_check"] < 0.0)].copy()
    if weak.empty:
        return "<p>No weak symbol/timeframe rows for the top robust candidates.</p>"

    weak["candidate_order"] = weak["candidate_id"].map({candidate_id: idx for idx, candidate_id in enumerate(candidate_ids)})
    weak["tf_order"] = weak["timeframe"].map(_tf_sort_key)
    weak = weak.sort_values(["candidate_order", "tf_order", "avg_net_r_check"]).head(40)
    rows = []
    for _, row in weak.iterrows():
        rows.append(
            [
                _escape(_candidate_short(row["candidate_id"])),
                _escape(row["symbol"]),
                _escape(row["timeframe"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["avg_net_r"]), _metric_class(row["avg_net_r"])),
                (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                _fmt_num(row["profit_factor"], 2),
            ]
        )
    return _table(["Candidate", "Symbol", "TF", "Trades", "Avg R", "Total R", "PF"], rows)


def _load_candidate_trades(trades_path: Path, candidate_id: str) -> pd.DataFrame:
    available = set(pd.read_csv(trades_path, nrows=0).columns)
    required = {"candidate_id", "symbol", "timeframe", "entry_time_utc", "exit_time_utc", "net_r"}
    if required.difference(available):
        return pd.DataFrame()
    usecols = ["candidate_id", "symbol", "timeframe", "entry_time_utc", "exit_time_utc", "net_r"]
    rows: list[pd.DataFrame] = []
    for chunk in pd.read_csv(trades_path, usecols=usecols, chunksize=200_000):
        selected = chunk[chunk["candidate_id"].astype(str) == str(candidate_id)].copy()
        if not selected.empty:
            rows.append(selected)
    if not rows:
        return pd.DataFrame(columns=usecols)
    data = pd.concat(rows, ignore_index=True)
    data["entry_time_utc"] = pd.to_datetime(data["entry_time_utc"], utc=True)
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    return data.sort_values(["exit_time_utc", "entry_time_utc", "symbol", "timeframe"]).reset_index(drop=True)


def _timestamp(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _drawdown_section(trades_path: Path, candidate_id: str) -> str:
    trades = _load_candidate_trades(trades_path, candidate_id)
    if trades.empty:
        return "<p>No trade rows are available for the best overall candidate.</p>"

    trades["equity_r"] = trades["net_r"].cumsum()
    trades["peak_r"] = trades["equity_r"].cummax().clip(lower=0.0)
    trades["drawdown_r"] = trades["peak_r"] - trades["equity_r"]
    max_idx = int(trades["drawdown_r"].idxmax())
    max_row = trades.loc[max_idx]
    peak_value = float(max_row["peak_r"])
    if peak_value > 0:
        peak_idx = int(trades.loc[:max_idx][trades.loc[:max_idx, "equity_r"].eq(peak_value)].index[0])
    else:
        peak_idx = 0
    peak_time = trades.loc[peak_idx, "exit_time_utc"]
    trough_time = max_row["exit_time_utc"]
    recovery = trades[(trades.index > max_idx) & (trades["equity_r"] >= peak_value)]
    recovery_time = None if recovery.empty else recovery.iloc[0]["exit_time_utc"]
    peak_to_recovery_days = None if recovery_time is None else (recovery_time - peak_time).total_seconds() / 86400
    trough_to_recovery_days = None if recovery_time is None else (recovery_time - trough_time).total_seconds() / 86400

    periods = []
    in_drawdown = False
    start_time = None
    trough_drawdown = 0.0
    period_trough_time = None
    for _, row in trades.iterrows():
        drawdown = float(row["drawdown_r"])
        current_time = row["exit_time_utc"]
        if drawdown > 1e-12 and not in_drawdown:
            in_drawdown = True
            start_time = current_time
            trough_drawdown = drawdown
            period_trough_time = current_time
        elif drawdown > 1e-12 and in_drawdown:
            if drawdown > trough_drawdown:
                trough_drawdown = drawdown
                period_trough_time = current_time
        elif drawdown <= 1e-12 and in_drawdown:
            periods.append(
                {
                    "start": start_time,
                    "end": current_time,
                    "days": (current_time - start_time).total_seconds() / 86400,
                    "max_dd_r": trough_drawdown,
                    "trough_time": period_trough_time,
                    "recovered": True,
                }
            )
            in_drawdown = False
    if in_drawdown:
        current_time = trades.iloc[-1]["exit_time_utc"]
        periods.append(
            {
                "start": start_time,
                "end": current_time,
                "days": (current_time - start_time).total_seconds() / 86400,
                "max_dd_r": trough_drawdown,
                "trough_time": period_trough_time,
                "recovered": False,
            }
        )

    periods_frame = pd.DataFrame(periods)
    longest_days = 0.0 if periods_frame.empty else float(periods_frame["days"].max())
    avg_days = 0.0 if periods_frame.empty else float(periods_frame["days"].mean())
    max_drawdown_r = float(max_row["drawdown_r"])
    total_r = float(trades["net_r"].sum())
    rows = []
    if not periods_frame.empty:
        for _, row in periods_frame.sort_values(["days", "max_dd_r"], ascending=False).head(8).iterrows():
            rows.append(
                [
                    _timestamp(row["start"]),
                    _timestamp(row["end"]),
                    _fmt_num(row["days"], 1),
                    (_fmt_num(row["max_dd_r"]), "negative"),
                    _timestamp(row["trough_time"]),
                    "yes" if bool(row["recovered"]) else "no",
                ]
            )

    return f"""
      <div class="kpis">
        {_kpi("Candidate", _candidate_short(candidate_id), "best overall Avg R")}
        {_kpi("Max Drawdown", f"{max_drawdown_r:.2f}R", f"{max_drawdown_r * 0.5:.1f}% at 0.5% risk/trade")}
        {_kpi("Peak To Recovery", "n/a" if peak_to_recovery_days is None else f"{peak_to_recovery_days:.0f} days", f"trough recovery: {'n/a' if trough_to_recovery_days is None else f'{trough_to_recovery_days:.0f} days'}")}
        {_kpi("Longest Underwater", f"{longest_days:.0f} days", f"{len(periods_frame)} periods, avg {avg_days:.1f} days")}
        {_kpi("Closed-Trade Total", f"{total_r:.1f}R", f"{_fmt_int(len(trades))} trades")}
      </div>
      <div class="note">This is a closed-trade R equity curve for one candidate. It is not yet a portfolio simulation with max open trades, position sizing, daily drawdown limits, or overlapping exposure.</div>
      {_table(["Start", "End", "Days", "Max DD", "Trough", "Recovered?"], rows)}
    """


def _candidate_heatmap(summary_tf: pd.DataFrame) -> str:
    pivot = summary_tf.pivot_table(index="candidate_id", columns="timeframe", values="avg_net_r", aggfunc="mean")
    columns = [tf for tf in TIMEFRAME_ORDER if tf in pivot.columns] + [tf for tf in pivot.columns if tf not in TIMEFRAME_ORDER]
    pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index, columns]
    max_abs = max(abs(float(pivot.min().min())), abs(float(pivot.max().max())), 0.001)
    headers = ["Candidate"] + columns
    rows = []
    for candidate_id, row in pivot.iterrows():
        cells: list[Any] = [_escape(_candidate_short(candidate_id))]
        for timeframe in columns:
            value = float(row[timeframe])
            cells.append((_fmt_num(value), f"heat-cell {_heat_class(value, max_abs)}"))
        rows.append(cells)
    return _table(headers, rows, classes="compact")


def _metric_guide() -> str:
    rows = [
        ["Avg R", "Average net result per trade in risk units. This is the first metric to check."],
        ["Total R", "Sum of net R across all trades in the row. Useful, but high-trade-count groups dominate it."],
        ["PF", "Profit factor: gross wins divided by gross losses. Above 1.0 means profitable before deeper checks."],
        ["Win Rate", "Share of positive trades. It must be read together with target size and Avg R."],
        ["Bars", "Average candles held per trade. On H4, 5 bars is about 20 hours; on D1, 5 bars is about 5 days."],
        ["Trades", "Number of simulated trades. More trades give more confidence; tiny samples can mislead."],
        ["Skipped", "Signal/candidate attempts that did not become trades, usually because midpoint entry was not reached or risk was too wide."],
    ]
    return _table(["Metric", "How To Read It"], rows)


def _side_candidate_leaders(by_candidate_side: pd.DataFrame) -> str:
    if by_candidate_side.empty:
        return "<p>No side/candidate rows are available.</p>"
    sections = []
    for timeframe in sorted(by_candidate_side["timeframe"].dropna().unique(), key=_tf_sort_key):
        for side in sorted(by_candidate_side.loc[by_candidate_side["timeframe"] == timeframe, "side"].dropna().unique()):
            data = by_candidate_side[
                (by_candidate_side["timeframe"] == timeframe) & (by_candidate_side["side"] == side)
            ].sort_values(["avg_net_r", "total_net_r"], ascending=False).head(3)
            rows = []
            for _, row in data.iterrows():
                rows.append(
                    [
                        _escape(_candidate_short(row["candidate_id"])),
                        _fmt_int(row["trades"]),
                        _fmt_pct(row["win_rate"]),
                        (_fmt_num(row["avg_net_r"]), _metric_class(row["avg_net_r"])),
                        (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                        _fmt_num(row["profit_factor"], 2),
                    ]
                )
            sections.append(
                f"<h3>{_escape(timeframe)} {_escape(side.title())}</h3>"
                + _table(["Candidate", "Trades", "Win Rate", "Avg R", "Total R", "PF"], rows)
            )
    return "".join(sections)


def _model_table(frame: pd.DataFrame, group_field: str, label: str) -> str:
    if frame.empty:
        return f"<h3>{_escape(label)}</h3><p>No {label.lower()} rows are available for this run.</p>"
    data = frame.sort_values(["timeframe", "avg_net_r"], ascending=[True, False])
    data["tf_order"] = data["timeframe"].map(_tf_sort_key)
    data = data.sort_values(["tf_order", "avg_net_r"], ascending=[True, False])
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row["timeframe"]),
                _escape(row[group_field]),
                _fmt_int(row["trades"]),
                _fmt_pct(row["win_rate"]),
                (_fmt_num(row["avg_net_r"]), _metric_class(row["avg_net_r"])),
                (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                _fmt_num(row["profit_factor"], 2),
            ]
        )
    return f"<h3>{_escape(label)}</h3>" + _table(["TF", label, "Trades", "Win Rate", "Avg R", "Total R", "PF"], rows)


def _symbol_outliers(summary_symbol: pd.DataFrame) -> str:
    data = summary_symbol.copy()
    data["candidate_short"] = data["candidate_id"].map(_candidate_short)
    positive = data.sort_values(["avg_net_r", "trades"], ascending=False).head(15)
    negative = data.sort_values(["avg_net_r", "trades"], ascending=True).head(15)

    def rows_for(frame: pd.DataFrame) -> list[list[Any]]:
        rows = []
        for _, row in frame.iterrows():
            rows.append(
                [
                    _escape(row["symbol"]),
                    _escape(_candidate_short(row["candidate_id"])),
                    _fmt_int(row["trades"]),
                    _fmt_pct(row["win_rate"]),
                    (_fmt_num(row["avg_net_r"]), _metric_class(row["avg_net_r"])),
                    (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                ]
            )
        return rows

    return (
        "<div class=\"split\">"
        "<div><h3>Best Symbol/Candidate Rows</h3>"
        + _table(["Symbol", "Candidate", "Trades", "Win Rate", "Avg R", "Total R"], rows_for(positive))
        + "</div><div><h3>Worst Symbol/Candidate Rows</h3>"
        + _table(["Symbol", "Candidate", "Trades", "Win Rate", "Avg R", "Total R"], rows_for(negative))
        + "</div></div>"
    )


def _skip_table(skips: pd.DataFrame) -> str:
    if skips.empty:
        return "<p>No skipped trades were reported.</p>"
    grouped = skips.groupby(["timeframe", "reason"], dropna=False)["skips"].sum().reset_index()
    grouped["tf_order"] = grouped["timeframe"].map(_tf_sort_key)
    grouped = grouped.sort_values(["tf_order", "skips"], ascending=[True, False])
    rows = []
    for _, row in grouped.iterrows():
        rows.append([_escape(row["timeframe"]), _escape(row["reason"]), _fmt_int(row["skips"])])
    return _table(["Timeframe", "Reason", "Skipped"], rows)


def _page_links(current_page: str) -> str:
    pages = [
        ("index.html", "Home"),
        ("v1.html", "V1"),
        ("v2.html", "V2"),
        ("v3.html", "V3"),
        ("v4.html", "V4"),
        ("v5.html", "V5"),
    ]
    links = []
    for href, label in pages:
        active = " active" if current_page == href else ""
        links.append(f'<a class="page-link{active}" href="{href}">{label}</a>')
    return "\n      ".join(links)


def _html_document(
    *,
    run_dir: Path,
    current_page: str,
    summary: dict[str, Any],
    datasets: pd.DataFrame,
    candidates: pd.DataFrame,
    summary_candidate: pd.DataFrame,
    summary_tf: pd.DataFrame,
    summary_symbol: pd.DataFrame,
    by_side: pd.DataFrame,
    by_candidate_side: pd.DataFrame,
    by_entry: pd.DataFrame,
    by_entry_zone: pd.DataFrame,
    by_stop: pd.DataFrame,
    by_exit: pd.DataFrame,
    by_target: pd.DataFrame,
    by_candidate_symbol_tf: pd.DataFrame,
    drawdown_html: str,
    skips: pd.DataFrame,
) -> str:
    del candidates
    top_overall = summary_candidate.sort_values(["avg_net_r", "total_net_r"], ascending=False).head(1)
    best_label = _candidate_short(top_overall.iloc[0]["candidate_id"]) if not top_overall.empty else "n/a"
    timeframes = sorted(datasets["timeframe"].dropna().astype(str).unique(), key=_tf_sort_key)
    timeframe_note = (
        "M30 contributes most signals and can dominate the aggregate; H4, H8, D1, and W1 should be judged on their own."
        if "M30" in timeframes
        else "Overall metrics are weighted by trade count. Read each timeframe separately before making strategy decisions."
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike Dashboard - by Cody</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #627181;
      --line: #d8e0e8;
      --accent: #22577a;
      --accent-2: #3a7d44;
      --warn: #9b5f00;
      --bad: #a23b3b;
      --good: #2e7d50;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 Inter, Segoe UI, Roboto, Arial, sans-serif;
    }}
    header {{
      background: #17202a;
      color: white;
      padding: 28px max(24px, 5vw);
      border-bottom: 4px solid #57a773;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 28px; font-weight: 700; }}
    header p {{ margin: 0; color: #d8e0e8; max-width: 980px; }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }}
    nav a {{
      color: white;
      text-decoration: none;
      border: 1px solid rgba(255,255,255,.25);
      padding: 7px 10px;
      border-radius: 6px;
      background: rgba(255,255,255,.08);
    }}
    nav.page-nav a.active {{
      background: #57a773;
      border-color: #57a773;
      color: #17202a;
      font-weight: 700;
    }}
    nav.report-nav {{
      margin-top: 10px;
    }}
    main {{ padding: 24px max(24px, 5vw) 48px; }}
    section {{
      margin: 0 0 22px;
      padding: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(23,32,42,.05);
    }}
    h2 {{ margin: 0 0 14px; font-size: 20px; }}
    h3 {{ margin: 18px 0 8px; font-size: 15px; color: #34495e; }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .kpi {{
      background: #f9fbfc;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .kpi-label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .kpi-value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
    .kpi-note {{ color: var(--muted); font-size: 12px; min-height: 18px; }}
    .note {{
      background: #f6f8f2;
      border-left: 4px solid #8aa936;
      padding: 12px 14px;
      color: #34412d;
      margin-bottom: 14px;
    }}
    .split {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 18px;
      align-items: start;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 8px 9px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      vertical-align: top;
      white-space: nowrap;
    }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{
      color: #455464;
      background: #f7f9fb;
      font-weight: 700;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    .compact td, .compact th {{ font-size: 12px; padding: 6px 7px; }}
    .positive {{ color: var(--good); font-weight: 700; }}
    .negative {{ color: var(--bad); font-weight: 700; }}
    .neutral {{ color: var(--muted); }}
    .bar-wrap {{
      position: relative;
      min-width: 130px;
      height: 22px;
      border-radius: 5px;
      background: #edf1f4;
      overflow: hidden;
    }}
    .bar {{
      position: absolute;
      inset: 0 auto 0 0;
      background: #7aa6c2;
    }}
    .bar-wrap span {{
      position: relative;
      z-index: 1;
      display: block;
      text-align: right;
      padding: 2px 6px;
      color: #17202a;
      font-size: 12px;
      font-weight: 700;
    }}
    .heat-cell {{ font-weight: 700; text-align: center; border-left: 1px solid white; }}
    .heat-pos-1 {{ background: #e9f5ee; color: #1f5e3a; }}
    .heat-pos-2 {{ background: #cfe9da; color: #1f5e3a; }}
    .heat-pos-3 {{ background: #9bd0b2; color: #173f2a; }}
    .heat-pos-4 {{ background: #5eae7d; color: white; }}
    .heat-neg-1 {{ background: #faeeee; color: #8a2d2d; }}
    .heat-neg-2 {{ background: #f2d1d1; color: #8a2d2d; }}
    .heat-neg-3 {{ background: #df9b9b; color: #612020; }}
    .heat-neg-4 {{ background: #bd5b5b; color: white; }}
    .heat-neutral {{ background: #f1f4f6; color: #5a6875; }}
    .scroll {{ overflow-x: auto; }}
    footer {{ color: var(--muted); padding: 0 max(24px, 5vw) 28px; }}
  </style>
</head>
<body>
  <header>
    <h1>LP + Force Strike Dashboard - by Cody</h1>
    <p>Static analysis report generated from <code>{_escape(run_dir)}</code>. Use this page to choose the next research slice; do not treat the aggregate result as a final strategy verdict.</p>
    <nav class="page-nav" aria-label="Dashboard pages">
      {_page_links(current_page)}
    </nav>
    <nav class="report-nav" aria-label="Report sections">
      <a href="#overview">Overview</a>
      <a href="#guide">Metric Guide</a>
      <a href="#timeframes">Timeframes</a>
      <a href="#robustness">Robustness</a>
      <a href="#drawdown">Drawdown</a>
      <a href="#stability">Stability</a>
      <a href="#candidates">Candidates</a>
      <a href="#models">Model Families</a>
      <a href="#side">Side</a>
      <a href="#symbols">Symbols</a>
      <a href="#skips">Skipped</a>
    </nav>
  </header>
  <main>
    <section id="overview">
      <h2>Overview</h2>
      <div class="kpis">
        {_kpi("Datasets", _fmt_int(summary.get("datasets")), f"{_fmt_int(summary.get('failed_datasets'))} failed")}
        {_kpi("Signals", _fmt_int(summary.get("signals")), "LP break + raw FS")}
        {_kpi("Trades", _fmt_int(summary.get("trades")), "simulated candidates")}
        {_kpi("Skipped", _fmt_int(summary.get("skipped")), "filtered attempts")}
        {_kpi("Best Overall Avg R", best_label, "overall is trade-count weighted")}
      </div>
      <div class="note">Read by timeframe first. {_escape(timeframe_note)}</div>
      {_timeframe_overview(datasets)}
    </section>

    <section id="guide">
      <h2>Metric Guide</h2>
      <div class="note">Start with Avg R and PF, then confirm the sample size with Trades. Bars is duration, not profit.</div>
      {_metric_guide()}
    </section>

    <section id="timeframes">
      <h2>Best Candidates By Timeframe</h2>
      {_timeframe_leaders(summary_tf)}
    </section>

    <section id="robustness">
      <h2>Robust Candidates Across Focus Timeframes</h2>
      <div class="note">This section ignores M30 because it dominates the sample count and currently behaves differently. Favor rows with positive Avg R and PF above 1 across all focused timeframes.</div>
      {_robust_candidates(summary_tf)}
    </section>

    <section id="drawdown">
      <h2>Best Overall Candidate Drawdown</h2>
      {drawdown_html}
    </section>

    <section id="stability">
      <h2>Symbol-Timeframe Stability</h2>
      <div class="note">Profit factor cannot be negative. PF below 1.0 or negative Avg R is the warning condition. This table checks weak symbol/timeframe rows for the top robust candidates.</div>
      {_weak_symbol_timeframes(by_candidate_symbol_tf, summary_tf)}
    </section>

    <section id="candidates">
      <h2>Candidate Heatmap</h2>
      <div class="scroll">{_candidate_heatmap(summary_tf)}</div>
      <h3>Overall Leaderboard</h3>
      {_leaderboard(summary_candidate, top_n=12)}
    </section>

    <section id="models">
      <h2>Model Family Slices</h2>
      <div class="split">
        <div>{_model_table(by_entry, "meta_entry_model", "Entry Model")}</div>
        <div>{_model_table(by_entry_zone, "meta_entry_zone", "Entry Zone")}</div>
      </div>
      <div class="split">
        <div>{_model_table(by_stop, "meta_stop_model", "Stop Model")}</div>
        <div>{_model_table(by_exit, "meta_exit_model", "Exit Model")}</div>
      </div>
      <div class="split">
        <div>{_model_table(by_target, "meta_target_r", "Target R")}</div>
        <div>{_model_table(by_side, "side", "Side")}</div>
      </div>
    </section>

    <section id="side">
      <h2>Best Candidates By Timeframe And Side</h2>
      <div class="note">Use this to see whether bullish force bottoms or bearish force tops are carrying the result. If one side is weak, it should become a filter candidate before execution work.</div>
      {_side_candidate_leaders(by_candidate_side)}
    </section>

    <section id="symbols">
      <h2>Symbol Outliers</h2>
      {_symbol_outliers(summary_symbol)}
    </section>

    <section id="skips">
      <h2>Skipped Trade Attempts</h2>
      <div class="note">Skipped attempts are not failed backtests. They usually mean midpoint entry was not reached, risk was wider than the ATR filter, or no next candle existed.</div>
      {_skip_table(skips)}
    </section>
  </main>
  <footer>Generated from LP Force Strike experiment reports. Source CSVs remain the audit trail.</footer>
</body>
</html>
"""


def build_dashboard(run_dir: Path, output: Path) -> Path:
    summary = _read_json(run_dir / "run_summary.json")
    datasets = _read_csv(run_dir / "datasets.csv")
    candidates = _read_csv(run_dir / "candidates.csv")
    summary_candidate = _read_csv(run_dir / "summary_by_candidate.csv")
    summary_tf = _read_csv(run_dir / "summary_by_candidate_timeframe.csv")
    summary_symbol = _read_csv(run_dir / "summary_by_candidate_symbol.csv")
    trades_path = run_dir / "trades.csv"
    skipped_path = run_dir / "skipped.csv"

    by_side = _trade_group_summary(trades_path, ["timeframe", "side"])
    by_candidate_side = _trade_group_summary(trades_path, ["candidate_id", "timeframe", "side"])
    by_entry = _trade_group_summary(trades_path, ["timeframe", "meta_entry_model"])
    by_entry_zone = _trade_group_summary(trades_path, ["timeframe", "meta_entry_zone"])
    by_stop = _trade_group_summary(trades_path, ["timeframe", "meta_stop_model"])
    by_exit = _trade_group_summary(trades_path, ["timeframe", "meta_exit_model"])
    by_target = _trade_group_summary(trades_path, ["timeframe", "meta_target_r"])
    by_candidate_symbol_tf = _trade_group_summary(trades_path, ["candidate_id", "symbol", "timeframe"])
    top_overall = summary_candidate.sort_values(["avg_net_r", "total_net_r"], ascending=False).head(1)
    top_candidate_id = "" if top_overall.empty else str(top_overall.iloc[0]["candidate_id"])
    drawdown_html = _drawdown_section(trades_path, top_candidate_id) if top_candidate_id else "<p>No top candidate is available.</p>"
    skips = _skip_reason_summary(skipped_path)

    html_text = _html_document(
        run_dir=run_dir,
        current_page=output.name,
        summary=summary,
        datasets=datasets,
        candidates=candidates,
        summary_candidate=summary_candidate,
        summary_tf=summary_tf,
        summary_symbol=summary_symbol,
        by_side=by_side,
        by_candidate_side=by_candidate_side,
        by_entry=by_entry,
        by_entry_zone=by_entry_zone,
        by_stop=by_stop,
        by_exit=by_exit,
        by_target=by_target,
        by_candidate_symbol_tf=by_candidate_symbol_tf,
        drawdown_html=drawdown_html,
        skips=skips,
    )
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a static LP + Force Strike experiment dashboard.")
    parser.add_argument("--run-dir", help="Experiment run directory. Defaults to latest run under the V1 report root.")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT), help="Report root used when --run-dir is omitted.")
    parser.add_argument("--output", help="Output HTML path. Defaults to <run-dir>/dashboard.html.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else _latest_run(Path(args.report_root))
    output = Path(args.output) if args.output else run_dir / "dashboard.html"
    result = build_dashboard(run_dir, output)
    print(f"dashboard={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
