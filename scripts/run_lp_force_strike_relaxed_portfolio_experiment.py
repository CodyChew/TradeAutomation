from __future__ import annotations

import argparse
from dataclasses import asdict
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
    REPO_ROOT / "shared" / "backtest_engine_lab" / "src",
    REPO_ROOT / "concepts" / "lp_levels_lab" / "src",
    REPO_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    REPO_ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab import (  # noqa: E402
    PortfolioRule,
    closed_trade_drawdown_metrics,
    filter_trade_timeframes,
    run_portfolio_rule,
)


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


def _fmt_r(value: Any) -> str:
    return f"{_fmt_num(value, 1)}R"


def _fmt_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) * 100.0:,.1f}%"


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


def _rules(config: dict[str, Any]) -> list[PortfolioRule]:
    return [
        PortfolioRule(
            portfolio_id=str(row["portfolio_id"]),
            max_open_r=None if row.get("max_open_r") is None else float(row["max_open_r"]),
            enforce_one_per_symbol=bool(row.get("enforce_one_per_symbol", False)),
            risk_r_per_trade=float(row.get("risk_r_per_trade", 1.0)),
        )
        for row in config["portfolio_rules"]
    ]


def _profile_label(portfolio_id: str) -> str:
    labels = {
        "take_all": "Take all",
        "one_symbol_no_cap": "One symbol / no cap",
    }
    if portfolio_id in labels:
        return labels[portfolio_id]
    return portfolio_id.replace("cap_", "Cap ").replace("r", "R")


def _portfolio_order(portfolio_id: str) -> int:
    order = {
        "take_all": 0,
        "one_symbol_no_cap": 1,
        "cap_4r": 2,
        "cap_6r": 3,
        "cap_8r": 4,
        "cap_10r": 5,
        "cap_12r": 6,
        "cap_16r": 7,
    }
    return order.get(str(portfolio_id), 99)


def exposure_metrics(frame: pd.DataFrame, risk_r_per_trade: float = 1.0) -> dict[str, float | str | None]:
    """Return concurrent-trade and same-symbol stacking metrics."""

    if frame.empty:
        return {
            "max_concurrent_trades": 0,
            "max_open_r": 0.0,
            "max_concurrent_time_utc": None,
            "max_same_symbol_stack": 0,
            "max_new_trades_same_time": 0,
            "max_same_symbol_same_time": 0,
        }

    data = frame.copy()
    data["entry_time_utc"] = pd.to_datetime(data["entry_time_utc"], utc=True)
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    events = []
    for row in data.itertuples():
        events.append((row.entry_time_utc, 1))
        events.append((row.exit_time_utc, -1))
    events.sort(key=lambda item: (item[0], item[1]))

    current = 0
    max_concurrent = 0
    max_time = None
    for event_time, delta in events:
        current += delta
        if current > max_concurrent:
            max_concurrent = current
            max_time = event_time

    max_same_symbol_stack = 0
    for symbol, symbol_frame in data.groupby("symbol", dropna=False):
        del symbol
        symbol_events = []
        for row in symbol_frame.itertuples():
            symbol_events.append((row.entry_time_utc, 1))
            symbol_events.append((row.exit_time_utc, -1))
        symbol_events.sort(key=lambda item: (item[0], item[1]))
        current_symbol = 0
        for _event_time, delta in symbol_events:
            current_symbol += delta
            max_same_symbol_stack = max(max_same_symbol_stack, current_symbol)

    new_trades_same_time = int(data.groupby("entry_time_utc").size().max())
    same_symbol_same_time = int(data.groupby(["entry_time_utc", "symbol"], dropna=False).size().max())
    return {
        "max_concurrent_trades": int(max_concurrent),
        "max_open_r": float(max_concurrent * risk_r_per_trade),
        "max_concurrent_time_utc": None if max_time is None else max_time.isoformat(),
        "max_same_symbol_stack": int(max_same_symbol_stack),
        "max_new_trades_same_time": new_trades_same_time,
        "max_same_symbol_same_time": same_symbol_same_time,
    }


def top_underwater_periods(frame: pd.DataFrame, limit: int = 5) -> pd.DataFrame:
    """Return the longest closed-trade underwater periods."""

    if frame.empty:
        return pd.DataFrame(
            columns=["start_utc", "end_utc", "days", "trough_utc", "trough_drawdown_r"]
        )

    data = frame.copy()
    data["entry_time_utc"] = pd.to_datetime(data["entry_time_utc"], utc=True)
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    data = data.sort_values(["exit_time_utc", "entry_time_utc", "symbol", "timeframe"]).reset_index(drop=True)
    data["equity_r"] = data["net_r"].cumsum()
    data["peak_r"] = data["equity_r"].cummax().clip(lower=0.0)
    data["drawdown_r"] = data["peak_r"] - data["equity_r"]

    periods: list[dict[str, Any]] = []
    in_drawdown = False
    start_time = None
    trough_time = None
    trough_drawdown = 0.0
    for row in data.itertuples():
        drawdown = float(row.drawdown_r)
        current_time = row.exit_time_utc
        if drawdown > 1e-12 and not in_drawdown:
            in_drawdown = True
            start_time = current_time
            trough_time = current_time
            trough_drawdown = drawdown
        elif drawdown > 1e-12 and in_drawdown:
            if drawdown > trough_drawdown:
                trough_drawdown = drawdown
                trough_time = current_time
        elif drawdown <= 1e-12 and in_drawdown:
            periods.append(
                {
                    "start_utc": start_time.isoformat(),
                    "end_utc": current_time.isoformat(),
                    "days": (current_time - start_time).total_seconds() / 86400,
                    "trough_utc": trough_time.isoformat(),
                    "trough_drawdown_r": trough_drawdown,
                }
            )
            in_drawdown = False

    if in_drawdown and start_time is not None:
        current_time = data.iloc[-1]["exit_time_utc"]
        periods.append(
            {
                "start_utc": start_time.isoformat(),
                "end_utc": current_time.isoformat(),
                "days": (current_time - start_time).total_seconds() / 86400,
                "trough_utc": trough_time.isoformat(),
                "trough_drawdown_r": trough_drawdown,
            }
        )
    columns = ["start_utc", "end_utc", "days", "trough_utc", "trough_drawdown_r"]
    if not periods:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(periods, columns=columns).sort_values("days", ascending=False).head(limit).reset_index(drop=True)


def period_robustness(frame: pd.DataFrame) -> dict[str, Any]:
    """Return year/month/quarter robustness metrics."""

    if frame.empty:
        return {
            "negative_years": 0,
            "worst_year": None,
            "worst_year_r": 0.0,
            "best_year": None,
            "best_year_r": 0.0,
            "negative_months": 0,
            "worst_month": None,
            "worst_month_r": 0.0,
            "negative_quarters": 0,
            "worst_quarter": None,
            "worst_quarter_r": 0.0,
            "top_year_share": 0.0,
        }

    data = frame.copy()
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    total_r = float(data["net_r"].sum())
    year = data.groupby(data["exit_time_utc"].dt.year)["net_r"].sum()
    month = data.groupby(data["exit_time_utc"].dt.strftime("%Y-%m"))["net_r"].sum()
    exit_time_naive = data["exit_time_utc"].dt.tz_convert(None)
    quarter = data.groupby(exit_time_naive.dt.to_period("Q").astype(str))["net_r"].sum()
    top_year_r = float(year.max()) if not year.empty else 0.0
    return {
        "negative_years": int((year < 0).sum()),
        "worst_year": None if year.empty else str(year.idxmin()),
        "worst_year_r": 0.0 if year.empty else float(year.min()),
        "best_year": None if year.empty else str(year.idxmax()),
        "best_year_r": 0.0 if year.empty else float(year.max()),
        "negative_months": int((month < 0).sum()),
        "worst_month": None if month.empty else str(month.idxmin()),
        "worst_month_r": 0.0 if month.empty else float(month.min()),
        "negative_quarters": int((quarter < 0).sum()),
        "worst_quarter": None if quarter.empty else str(quarter.idxmin()),
        "worst_quarter_r": 0.0 if quarter.empty else float(quarter.min()),
        "top_year_share": 0.0 if total_r <= 0 else top_year_r / total_r,
    }


def ticker_robustness(frame: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    """Return symbol robustness metrics plus per-symbol rows."""

    if frame.empty:
        return {
            "negative_symbols": 0,
            "worst_symbol": None,
            "worst_symbol_r": 0.0,
            "best_symbol": None,
            "best_symbol_r": 0.0,
            "top_symbol_share": 0.0,
            "top_three_symbol_share": 0.0,
        }, pd.DataFrame(columns=["symbol", "trades", "total_net_r", "avg_net_r"])

    data = frame.copy()
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    by_symbol = (
        data.groupby("symbol", dropna=False)["net_r"]
        .agg(trades="count", total_net_r="sum", avg_net_r="mean")
        .reset_index()
        .sort_values("total_net_r")
    )
    total_r = float(data["net_r"].sum())
    top_symbol = by_symbol.iloc[-1]
    worst_symbol = by_symbol.iloc[0]
    top_three = by_symbol.sort_values("total_net_r", ascending=False).head(3)
    metrics = {
        "negative_symbols": int((by_symbol["total_net_r"] < 0).sum()),
        "worst_symbol": str(worst_symbol["symbol"]),
        "worst_symbol_r": float(worst_symbol["total_net_r"]),
        "best_symbol": str(top_symbol["symbol"]),
        "best_symbol_r": float(top_symbol["total_net_r"]),
        "top_symbol_share": 0.0 if total_r <= 0 else float(top_symbol["total_net_r"]) / total_r,
        "top_three_symbol_share": 0.0 if total_r <= 0 else float(top_three["total_net_r"].sum()) / total_r,
    }
    return metrics, by_symbol


def _year_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    data = frame.copy()
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    rows = []
    for year, group in data.groupby(data["exit_time_utc"].dt.year):
        net_r = group["net_r"]
        gross_loss = float(net_r[net_r < 0].sum())
        rows.append(
            {
                "year": str(year),
                "trades": int(len(group)),
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()),
                "win_rate": float((net_r > 0).mean()),
                "profit_factor": None if gross_loss == 0 else float(net_r[net_r > 0].sum()) / abs(gross_loss),
            }
        )
    return rows


def _is_recommended(row: dict[str, Any], concentration_warning_share: float) -> bool:
    return (
        int(row["negative_years"]) == 0
        and int(row["negative_symbols"]) == 0
        and float(row["top_year_share"]) <= concentration_warning_share
        and float(row["top_symbol_share"]) <= concentration_warning_share
    )


def run_relaxed_portfolio_analysis(
    trades: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pivot_strength = int(config["pivot_strength"])
    timeframes = [str(value) for value in config["timeframes"]]
    concentration_warning_share = float(config["concentration_warning_share"])
    base_trades = filter_trade_timeframes(trades, timeframes)
    base_trades = base_trades[base_trades["pivot_strength"].astype(int) == pivot_strength].copy()

    summary_rows: list[dict[str, Any]] = []
    accepted_frames: list[pd.DataFrame] = []
    symbol_frames: list[pd.DataFrame] = []
    underwater_frames: list[pd.DataFrame] = []
    yearly_frames: list[pd.DataFrame] = []

    for rule in _rules(config):
        result, selected = run_portfolio_rule(
            base_trades,
            rule=rule,
            pivot_strength=pivot_strength,
            max_drawdown_guardrail_r=10**9,
            max_underwater_guardrail_days=10**9,
        )
        selected = selected.copy()
        selected["pivot_strength"] = pivot_strength
        selected["portfolio_id"] = rule.portfolio_id
        accepted_frames.append(selected)

        exposure = exposure_metrics(selected, rule.risk_r_per_trade)
        periods = period_robustness(selected)
        symbol_metrics, symbols = ticker_robustness(selected)
        drawdown = closed_trade_drawdown_metrics(selected)
        top_underwater = top_underwater_periods(selected)
        year_rows = pd.DataFrame(_year_rows(selected))

        symbols["portfolio_id"] = rule.portfolio_id
        top_underwater["portfolio_id"] = rule.portfolio_id
        year_rows["portfolio_id"] = rule.portfolio_id
        symbol_frames.append(symbols)
        underwater_frames.append(top_underwater)
        yearly_frames.append(year_rows)

        row = asdict(result)
        row.update(exposure)
        row.update(periods)
        row.update(symbol_metrics)
        row.update(
            {
                "max_drawdown_start_utc": drawdown["max_drawdown_start_utc"],
                "max_drawdown_trough_utc": drawdown["max_drawdown_trough_utc"],
                "max_drawdown_recovery_utc": drawdown["max_drawdown_recovery_utc"],
            }
        )
        for risk_pct in config["risk_per_trade_pct_examples"]:
            label = str(risk_pct).replace(".", "p")
            risk = float(risk_pct)
            row[f"max_dd_pct_at_{label}pct"] = float(row["max_drawdown_r"]) * risk
            row[f"max_open_risk_pct_at_{label}pct"] = float(row["max_open_r"]) * risk
        row["robustness_pass"] = _is_recommended(row, concentration_warning_share)
        summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)
    summary["_order"] = summary["portfolio_id"].map(_portfolio_order)
    summary = summary.sort_values(["total_net_r", "return_to_drawdown"], ascending=False).drop(columns=["_order"])
    accepted = pd.concat(accepted_frames, ignore_index=True) if accepted_frames else pd.DataFrame()
    symbol_rows = pd.concat(symbol_frames, ignore_index=True) if symbol_frames else pd.DataFrame()
    underwater_rows = pd.concat(underwater_frames, ignore_index=True) if underwater_frames else pd.DataFrame()
    yearly_rows = pd.concat(yearly_frames, ignore_index=True) if yearly_frames else pd.DataFrame()
    return summary, accepted, symbol_rows, underwater_rows, yearly_rows


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


def _summary_table(frame: pd.DataFrame, *, limit: int | None = None) -> str:
    data = frame.copy()
    if limit is not None:
        data = data.head(limit)
    if data.empty:
        return "<p>No rows are available for this section.</p>"

    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(_profile_label(str(row["portfolio_id"]))),
                _fmt_int(row["trades_accepted"]),
                (_fmt_r(row["total_net_r"]), _metric_class(row["total_net_r"])),
                _fmt_pct(row["win_rate"]),
                _fmt_num(row["profit_factor"], 2),
                (_fmt_r(row["max_drawdown_r"]), "negative" if float(row["max_drawdown_r"]) > 0 else "neutral"),
                _fmt_num(row["longest_underwater_days"], 0),
                _fmt_num(row["return_to_drawdown"], 2),
                _fmt_int(row["negative_years"]),
                _fmt_int(row["negative_symbols"]),
                _fmt_pct(row["top_year_share"]),
                _fmt_pct(row["top_symbol_share"]),
                "Yes" if bool(row["robustness_pass"]) else "No",
            ]
        )
    return _table(
        [
            "Portfolio",
            "Trades",
            "Total R",
            "Win Rate",
            "PF",
            "Max DD",
            "Underwater Days",
            "Return/DD",
            "Neg Years",
            "Neg Symbols",
            "Top Year Share",
            "Top Symbol Share",
            "Robust",
        ],
        rows,
    )


def _comparison_table(summary: pd.DataFrame) -> str:
    wanted = ["take_all", "cap_4r", "cap_6r"]
    data = summary[summary["portfolio_id"].astype(str).isin(wanted)].copy()
    data["_order"] = data["portfolio_id"].map({value: idx for idx, value in enumerate(wanted)})
    data = data.sort_values("_order").drop(columns=["_order"])
    return _summary_table(data)


def _exposure_table(summary: pd.DataFrame, risk_examples: list[float]) -> str:
    data = summary.copy()
    data["_order"] = data["portfolio_id"].map(_portfolio_order)
    data = data.sort_values("_order").drop(columns=["_order"])
    headers = [
        "Portfolio",
        "Max Concurrent",
        "Max Open R",
        "Same Symbol Stack",
        "Max New Same Time",
        "Max DD",
    ]
    for risk_pct in risk_examples:
        headers.append(f"Max DD @ {risk_pct}%")
        headers.append(f"Max Open @ {risk_pct}%")

    rows = []
    for _, row in data.iterrows():
        base = [
            _escape(_profile_label(str(row["portfolio_id"]))),
            _fmt_int(row["max_concurrent_trades"]),
            _fmt_r(row["max_open_r"]),
            _fmt_int(row["max_same_symbol_stack"]),
            _fmt_int(row["max_new_trades_same_time"]),
            _fmt_r(row["max_drawdown_r"]),
        ]
        for risk_pct in risk_examples:
            label = str(risk_pct).replace(".", "p")
            base.append(f"{_fmt_num(row[f'max_dd_pct_at_{label}pct'], 1)}%")
            base.append(f"{_fmt_num(row[f'max_open_risk_pct_at_{label}pct'], 1)}%")
        rows.append(base)
    return _table(headers, rows)


def _period_table(summary: pd.DataFrame, underwater: pd.DataFrame) -> str:
    data = summary.copy()
    data["_order"] = data["portfolio_id"].map(_portfolio_order)
    data = data.sort_values("_order").drop(columns=["_order"])
    rows = []
    for _, row in data.iterrows():
        top = underwater[underwater["portfolio_id"] == row["portfolio_id"]].sort_values("days", ascending=False).head(1)
        if top.empty:
            top_period = ""
        else:
            item = top.iloc[0]
            top_period = f"{str(item['start_utc'])[:10]} to {str(item['end_utc'])[:10]} ({_fmt_num(item['days'], 0)}D)"
        rows.append(
            [
                _escape(_profile_label(str(row["portfolio_id"]))),
                _fmt_int(row["negative_years"]),
                _escape(row["worst_year"]),
                (_fmt_r(row["worst_year_r"]), _metric_class(row["worst_year_r"])),
                _fmt_int(row["negative_months"]),
                _escape(row["worst_month"]),
                (_fmt_r(row["worst_month_r"]), _metric_class(row["worst_month_r"])),
                _fmt_int(row["negative_quarters"]),
                _escape(row["worst_quarter"]),
                (_fmt_r(row["worst_quarter_r"]), _metric_class(row["worst_quarter_r"])),
                _escape(top_period),
            ]
        )
    return _table(
        [
            "Portfolio",
            "Neg Years",
            "Worst Year",
            "Worst Year R",
            "Neg Months",
            "Worst Month",
            "Worst Month R",
            "Neg Quarters",
            "Worst Quarter",
            "Worst Quarter R",
            "Longest Underwater Period",
        ],
        rows,
    )


def _ticker_table(summary: pd.DataFrame, symbol_rows: pd.DataFrame) -> str:
    data = summary.copy()
    data["_order"] = data["portfolio_id"].map(_portfolio_order)
    data = data.sort_values("_order").drop(columns=["_order"])
    rows = []
    for _, row in data.iterrows():
        symbols = symbol_rows[symbol_rows["portfolio_id"] == row["portfolio_id"]].copy()
        worst = symbols.sort_values("total_net_r").head(5)
        best = symbols.sort_values("total_net_r", ascending=False).head(5)
        worst_text = ", ".join(f"{item.symbol} {_fmt_r(item.total_net_r)}" for item in worst.itertuples())
        best_text = ", ".join(f"{item.symbol} {_fmt_r(item.total_net_r)}" for item in best.itertuples())
        rows.append(
            [
                _escape(_profile_label(str(row["portfolio_id"]))),
                _fmt_int(row["negative_symbols"]),
                _escape(str(row["worst_symbol"])),
                (_fmt_r(row["worst_symbol_r"]), _metric_class(row["worst_symbol_r"])),
                _escape(str(row["best_symbol"])),
                (_fmt_r(row["best_symbol_r"]), _metric_class(row["best_symbol_r"])),
                _fmt_pct(row["top_symbol_share"]),
                _fmt_pct(row["top_three_symbol_share"]),
                _escape(worst_text),
                _escape(best_text),
            ]
        )
    return _table(
        [
            "Portfolio",
            "Neg Symbols",
            "Worst Symbol",
            "Worst Symbol R",
            "Best Symbol",
            "Best Symbol R",
            "Top Symbol Share",
            "Top 3 Share",
            "Worst 5",
            "Best 5",
        ],
        rows,
    )


def _recommendation(summary: pd.DataFrame) -> pd.Series:
    robust = summary[summary["robustness_pass"].astype(bool)].copy()
    if robust.empty:
        return summary.sort_values(["total_net_r", "return_to_drawdown"], ascending=False).iloc[0]
    return robust.sort_values(["total_net_r", "return_to_drawdown"], ascending=False).iloc[0]


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
    config: dict[str, Any],
    summary: pd.DataFrame,
    symbol_rows: pd.DataFrame,
    underwater_rows: pd.DataFrame,
    *,
    current_page: str,
) -> str:
    try:
        page_metadata = dashboard_page(current_page)
    except KeyError:
        page_metadata = {
            "page": current_page,
            "nav_label": "Run",
            "title": "LP + Force Strike Relaxed Portfolio Dashboard",
            "status_label": "Run report",
            "status_kind": "neutral",
            "question": "Which relaxed portfolio rule is most practical?",
            "setup": "This is a run-local relaxed portfolio dashboard generated from existing trade logs.",
            "how_to_read": "Read the recommendation and exposure reality check before interpreting total R.",
            "conclusion": "No version-level conclusion is attached to this run-local page.",
            "action": "Use versioned docs pages for research conclusions.",
        }

    recommended = _recommendation(summary)
    risk_examples = [float(value) for value in config["risk_per_trade_pct_examples"]]
    recommended_label = _profile_label(str(recommended["portfolio_id"]))
    recommendation_text = "Use take-all" if str(recommended["portfolio_id"]) == "take_all" else f"Use {recommended_label}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V13 Relaxed Portfolio - by Cody</title>
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
    <h1>LP + Force Strike V13 Relaxed Portfolio - by Cody</h1>
    <p>Static V13 report generated from <code>{_escape(run_dir)}</code>. This page relaxes the old hard guardrails and ranks exposure rules by long-run trader practicality.</p>
    <nav aria-label="Dashboard pages">
      {dashboard_page_links(current_page)}
    </nav>
  </header>
  <main>
    {experiment_summary_html(page_metadata)}
    <section id="recommendation">
      <h2>Recommendation Card</h2>
      <div class="kpis">
        {_kpi("Recommendation", recommendation_text, "highest Total R after robustness checks")}
        {_kpi("Total R", _fmt_r(recommended["total_net_r"]), recommended_label)}
        {_kpi("Max DD", _fmt_r(recommended["max_drawdown_r"]), "closed-trade R")}
        {_kpi("Underwater", f"{_fmt_num(recommended['longest_underwater_days'], 0)}D", "longest below equity high")}
        {_kpi("Max Concurrent", _fmt_int(recommended["max_concurrent_trades"]), "open trades")}
      </div>
      <div class="note">Robustness checks require no negative years, no negative symbols, and no single year or symbol above {_fmt_pct(config["concentration_warning_share"])} of total R.</div>
    </section>
    <section id="leaderboard">
      <h2>Portfolio Rule Leaderboard</h2>
      <div class="note">Ranked by Total R after checking yearly, ticker, and concentration robustness. The old 30R / 180D rule is visible as context, not a hard selector here.</div>
      {_summary_table(summary)}
    </section>
    <section id="direct-comparison">
      <h2>Take-All vs Cap 4R vs Cap 6R</h2>
      <div class="note">This is the direct question raised after V10: whether cap 4R gives up too much return versus take-all or a looser cap.</div>
      {_comparison_table(summary)}
    </section>
    <section id="exposure">
      <h2>Exposure Reality Check</h2>
      <div class="note warning">Take-all allows same-symbol stacking and the highest concurrent exposure. This table converts R into account-risk examples so the operational tradeoff is explicit.</div>
      {_exposure_table(summary, risk_examples)}
    </section>
    <section id="period-robustness">
      <h2>Period Robustness</h2>
      <div class="note">Use this to catch period skew. A strong rule should not depend on one year or collapse in a specific regime.</div>
      {_period_table(summary, underwater_rows)}
    </section>
    <section id="ticker-robustness">
      <h2>Ticker Robustness</h2>
      <div class="note">Use this to catch ticker skew. A strong rule should not rely on one pair and should avoid negative-symbol pockets.</div>
      {_ticker_table(summary, symbol_rows)}
    </section>
  </main>
  <footer>Generated from existing V9 trade logs. No signal rerun was performed.</footer>
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

    summary, accepted, symbol_rows, underwater_rows, yearly_rows = run_relaxed_portfolio_analysis(trades, config)
    for row in summary.sort_values("total_net_r", ascending=False).itertuples():
        print(
            f"{row.portfolio_id}: trades={row.trades_accepted} total_r={row.total_net_r:.1f} "
            f"dd={row.max_drawdown_r:.1f} underwater={row.longest_underwater_days:.0f}d "
            f"neg_years={row.negative_years} neg_symbols={row.negative_symbols} robust={row.robustness_pass}"
        )

    _write_json(run_dir / "run_config.json", {"config_path": str(config_path), "config": config})
    _write_csv(run_dir / "relaxed_portfolio_summary.csv", summary)
    _write_csv(run_dir / "accepted_trades.csv", accepted)
    _write_csv(run_dir / "symbol_robustness.csv", symbol_rows)
    _write_csv(run_dir / "underwater_periods.csv", underwater_rows)
    _write_csv(run_dir / "yearly_returns.csv", yearly_rows)
    recommended = _recommendation(summary)
    run_summary = {
        "run_dir": str(run_dir),
        "input_trades_path": str(input_path),
        "summary_rows": int(len(summary)),
        "accepted_trade_rows": int(len(accepted)),
        "recommended_portfolio_id": str(recommended["portfolio_id"]),
        "recommended_total_net_r": float(recommended["total_net_r"]),
    }
    _write_json(run_dir / "run_summary.json", run_summary)

    html_text = _html_report(
        run_dir,
        config,
        summary,
        symbol_rows,
        underwater_rows,
        current_page="v13.html" if docs_output else "dashboard.html",
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
    run_config = _read_json(run_dir / "run_config.json")
    config = dict(run_config["config"])
    summary = _read_csv(run_dir / "relaxed_portfolio_summary.csv")
    symbol_rows = _read_csv(run_dir / "symbol_robustness.csv")
    underwater_rows = _read_csv(run_dir / "underwater_periods.csv")
    html_text = _html_report(
        run_dir,
        config,
        summary,
        symbol_rows,
        underwater_rows,
        current_page=docs_output.name,
    )
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V13 relaxed portfolio rule selection.")
    parser.add_argument("--config", help="Path to relaxed portfolio experiment config JSON.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v13.html.")
    parser.add_argument("--render-run-dir", help="Existing relaxed portfolio run directory to render without rerunning.")
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
