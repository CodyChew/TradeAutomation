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


REPO_ROOT = Path(__file__).resolve().parents[1]


def _display_path(path_value: str | Path) -> str:
    path = Path(path_value)
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


SRC_ROOTS = [
    REPO_ROOT / "shared" / "market_data_lab" / "src",
    REPO_ROOT / "shared" / "backtest_engine_lab" / "src",
    REPO_ROOT / "concepts" / "lp_levels_lab" / "src",
    REPO_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    REPO_ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from backtest_engine_lab import CostConfig  # noqa: E402
from lp_force_strike_dashboard_metadata import (  # noqa: E402
    dashboard_base_css,
    dashboard_header_html,
    metric_glossary_html,
)
from lp_force_strike_strategy_lab.execution_realism import (  # noqa: E402
    ExecutionRealismVariant,
    run_lp_force_strike_execution_realism_on_frame,
)
from lp_force_strike_strategy_lab.experiment import (  # noqa: E402
    SkippedTrade,
    make_trade_model_candidates,
    run_lp_force_strike_experiment_on_frame,
    trade_report_row,
)
from market_data_lab import load_dataset_config, normalize_timeframe  # noqa: E402
from run_lp_force_strike_bucket_sensitivity_experiment import (  # noqa: E402
    _baseline_row,
    _efficiency_recommendation,
    _recommendation,
    run_bucket_sensitivity_analysis,
)
from run_lp_force_strike_experiment import (  # noqa: E402
    _load_backtest_frame,
    _parse_csv_arg,
    _selected_symbols,
    _signal_row,
)


CONTROL_VARIANT_ID = "control_current"
SEPARATION_VARIANT_ID = "exclude_lp_pivot_inside_fs"


def _escape(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_csv(path: str | Path, frame: pd.DataFrame | list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    payload.to_csv(target, index=False)


def _fmt_int(value: Any) -> str:
    if value is None or pd.isna(value):
        return "0"
    return f"{int(float(value)):,}"


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,.{digits}f}"


def _fmt_pct(value: Any, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100.0:,.{digits}f}%"


def _fmt_pct_points(value: Any, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):,.{digits}f}%"


def _metric_class(value: Any) -> str:
    if value is None or pd.isna(value):
        return "neutral"
    number = float(value)
    if number > 0:
        return "good"
    if number < 0:
        return "bad"
    return "neutral"


def _table(frame: pd.DataFrame, columns: list[str], *, limit: int | None = None) -> str:
    if frame.empty:
        return '<p class="muted">No rows.</p>'
    data = frame.head(limit).copy() if limit is not None else frame.copy()
    header = "".join(f"<th>{_escape(column)}</th>" for column in columns)
    body = []
    for _, row in data.iterrows():
        cells = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, float):
                digits = 4 if abs(value) < 1 else 2
                value = _fmt_num(value, digits)
            cells.append(f"<td>{_escape(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="table-scroll">'
        f'<table class="data-table"><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table>'
        "</div>"
    )


def _cost_config(payload: dict[str, Any]) -> CostConfig:
    costs = payload.get("costs", {})
    return CostConfig(
        use_candle_spread=bool(costs.get("use_candle_spread", True)),
        fallback_spread_points=float(costs.get("fallback_spread_points", 0.0)),
        entry_slippage_points=float(costs.get("entry_slippage_points", 0.0)),
        exit_slippage_points=float(costs.get("exit_slippage_points", 0.0)),
        round_turn_commission_points=float(costs.get("round_turn_commission_points", 0.0)),
    )


def _selected_timeframes(dataset_timeframes: tuple[str, ...], config: dict[str, Any], override: list[str] | None) -> list[str]:
    raw = override if override is not None else config.get("timeframes", dataset_timeframes)
    return [normalize_timeframe(timeframe) for timeframe in raw]


def _make_candidate(config: dict[str, Any]):
    candidates = make_trade_model_candidates(
        entry_models=[str(config.get("entry_model", "signal_zone_pullback"))],
        stop_models=[str(config.get("stop_model", "fs_structure"))],
        target_rs=[float(config.get("target_r", 1.0))],
        max_risk_atrs=[float(value) for value in config.get("max_risk_atrs", [])],
        entry_zones=[float(config.get("entry_zone", 0.5))],
        exit_models=[str(config.get("exit_model", "single_target"))],
    )
    if len(candidates) != 1:
        raise ValueError("V22 expects exactly one unchanged LPFS baseline candidate.")
    return candidates[0]


def _variants(config: dict[str, Any]) -> list[dict[str, Any]]:
    variants = config.get("variants") or [
        {
            "variant_id": CONTROL_VARIANT_ID,
            "label": "Current V15 signal rules",
            "require_lp_pivot_before_fs_mother": False,
        },
        {
            "variant_id": SEPARATION_VARIANT_ID,
            "label": "Require LP pivot before FS mother",
            "require_lp_pivot_before_fs_mother": True,
        },
    ]
    found = {str(row["variant_id"]) for row in variants}
    if CONTROL_VARIANT_ID not in found or SEPARATION_VARIANT_ID not in found:
        raise ValueError("V22 requires control_current and exclude_lp_pivot_inside_fs variants.")
    return variants


def _trade_key(row: pd.Series | dict[str, Any]) -> str:
    get = row.get if isinstance(row, dict) else row.get
    return "|".join(
        [
            str(get("symbol")),
            str(get("timeframe")),
            str(get("side")),
            str(int(float(get("signal_index")))),
            str(int(float(get("pivot_strength")))),
            str(get("base_candidate_id")),
        ]
    )


def _signal_join_key(row: pd.Series | dict[str, Any]) -> str:
    get = row.get if isinstance(row, dict) else row.get
    return "|".join(
        [
            str(get("symbol")),
            str(get("timeframe")),
            str(int(float(get("fs_signal_index")))),
            str(int(float(get("pivot_strength")))),
        ]
    )


def _trade_signal_join_key(row: pd.Series | dict[str, Any]) -> str:
    get = row.get if isinstance(row, dict) else row.get
    return "|".join(
        [
            str(get("symbol")),
            str(get("timeframe")),
            str(int(float(get("signal_index")))),
            str(int(float(get("pivot_strength")))),
        ]
    )


def _signal_report_row(
    *,
    symbol: str,
    timeframe: str,
    pivot_strength: int,
    signal: Any,
    variant: dict[str, Any],
) -> dict[str, Any]:
    row = _signal_row(symbol, timeframe, pivot_strength, signal)
    row["separation_variant_id"] = str(variant["variant_id"])
    row["separation_variant_label"] = str(variant["label"])
    row["require_lp_pivot_before_fs_mother"] = bool(variant["require_lp_pivot_before_fs_mother"])
    row["signal_join_key"] = _signal_join_key(row)
    row["lp_is_fs_mother"] = int(row["lp_pivot_index"]) == int(row["fs_mother_index"])
    row["lp_inside_fs_formation"] = int(row["fs_mother_index"]) <= int(row["lp_pivot_index"]) <= int(row["fs_signal_index"])
    return row


def _trade_report_row(trade: Any, *, pivot_strength: int, variant: dict[str, Any]) -> dict[str, Any]:
    row = trade_report_row(trade)
    base_candidate_id = str(row.get("candidate_id", ""))
    row["base_candidate_id"] = base_candidate_id
    row["pivot_strength"] = int(pivot_strength)
    row["separation_variant_id"] = str(variant["variant_id"])
    row["separation_variant_label"] = str(variant["label"])
    row["require_lp_pivot_before_fs_mother"] = bool(variant["require_lp_pivot_before_fs_mother"])
    row["trade_key"] = _trade_key(row)
    row["signal_join_key"] = _trade_signal_join_key(row)
    return row


def _skipped_report_row(skipped: SkippedTrade, candidate: Any, *, pivot_strength: int, variant: dict[str, Any]) -> dict[str, Any]:
    row = skipped.to_dict()
    row["base_candidate_id"] = candidate.candidate_id
    row["candidate_id"] = candidate.candidate_id
    row["pivot_strength"] = int(pivot_strength)
    row["separation_variant_id"] = str(variant["variant_id"])
    row["separation_variant_label"] = str(variant["label"])
    row["require_lp_pivot_before_fs_mother"] = bool(variant["require_lp_pivot_before_fs_mother"])
    return row


def _profit_factor(values: pd.Series) -> float | None:
    gross_win = float(values[values > 0].sum())
    gross_loss = float(values[values < 0].sum())
    if gross_loss == 0:
        return None
    return gross_win / abs(gross_loss)


def _max_drawdown(values: pd.Series) -> float:
    if values.empty:
        return 0.0
    curve = values.cumsum()
    return float((curve.cummax() - curve).max())


def _worst_month(values: pd.DataFrame) -> float | None:
    if values.empty or "exit_time_utc" not in values.columns:
        return None
    data = values.copy()
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True, errors="coerce")
    data = data.dropna(subset=["exit_time_utc"])
    if data.empty:
        return None
    monthly = data.groupby(data["exit_time_utc"].dt.strftime("%Y-%m"))["net_r"].sum()
    return float(monthly.min()) if not monthly.empty else None


def _aggregate_trade_metrics(frame: pd.DataFrame, group_fields: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    data["bars_held"] = pd.to_numeric(data.get("bars_held", 0), errors="coerce").fillna(0.0)
    rows = []
    for keys, group in data.groupby(group_fields, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        net_r = group["net_r"]
        row = {field: value for field, value in zip(group_fields, keys)}
        row.update(
            {
                "trades": int(len(group)),
                "wins": int((net_r > 0).sum()),
                "losses": int((net_r < 0).sum()),
                "win_rate": float((net_r > 0).mean()) if len(group) else 0.0,
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()) if len(group) else 0.0,
                "profit_factor": _profit_factor(net_r),
                "avg_bars_held": float(group["bars_held"].mean()) if len(group) else 0.0,
                "target_exits": int((group["exit_reason"] == "target").sum()),
                "stop_exits": int((group["exit_reason"] == "stop").sum()),
                "same_bar_stop_exits": int((group["exit_reason"] == "same_bar_stop_priority").sum()),
                "end_of_data_exits": int((group["exit_reason"] == "end_of_data").sum()),
                "max_drawdown_r": _max_drawdown(net_r.reset_index(drop=True)),
                "worst_month_r": _worst_month(group),
            }
        )
        row["return_to_drawdown_r"] = None if row["max_drawdown_r"] <= 0 else row["total_net_r"] / row["max_drawdown_r"]
        rows.append(row)
    return pd.DataFrame(rows)


def _join_trade_signal_attrs(trades: pd.DataFrame, signals: pd.DataFrame, variant_id: str) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    current_trades = trades[trades["separation_variant_id"].eq(variant_id)].copy()
    current_signals = signals[signals["separation_variant_id"].eq(variant_id)].copy()
    if current_trades.empty:
        return current_trades
    attrs = [
        "signal_join_key",
        "lp_pivot_index",
        "lp_pivot_time_utc",
        "lp_break_index",
        "lp_break_time_utc",
        "fs_mother_index",
        "fs_signal_index",
        "lp_is_fs_mother",
        "lp_inside_fs_formation",
    ]
    available_attrs = [column for column in attrs if column in current_signals.columns]
    signal_attrs = current_signals[available_attrs].drop_duplicates("signal_join_key")
    return current_trades.merge(signal_attrs, on="signal_join_key", how="left", suffixes=("", "_signal"))


def _overlap_audit(trades: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant_id in [CONTROL_VARIANT_ID, SEPARATION_VARIANT_ID]:
        variant_trades = trades[trades["separation_variant_id"].eq(variant_id)].copy()
        variant_signals = signals[signals["separation_variant_id"].eq(variant_id)].copy()
        trade_duplicate_count = int(variant_trades["trade_key"].duplicated().sum()) if not variant_trades.empty else 0
        signal_duplicate_count = int(variant_signals["signal_join_key"].duplicated().sum()) if not variant_signals.empty else 0
        joined = _join_trade_signal_attrs(trades, signals, variant_id)
        missing_join_count = int(joined["lp_pivot_index"].isna().sum()) if not joined.empty else 0
        lp_is_mother_count = int(joined["lp_is_fs_mother"].fillna(False).sum()) if "lp_is_fs_mother" in joined.columns else 0
        lp_inside_count = int(joined["lp_inside_fs_formation"].fillna(False).sum()) if "lp_inside_fs_formation" in joined.columns else 0
        rows.extend(
            [
                {
                    "separation_variant_id": variant_id,
                    "audit_check": "duplicate_trade_keys",
                    "count": trade_duplicate_count,
                    "status": "pass" if trade_duplicate_count == 0 else "fail",
                },
                {
                    "separation_variant_id": variant_id,
                    "audit_check": "duplicate_signal_join_keys",
                    "count": signal_duplicate_count,
                    "status": "pass" if signal_duplicate_count == 0 else "fail",
                },
                {
                    "separation_variant_id": variant_id,
                    "audit_check": "missing_trade_to_signal_joins",
                    "count": missing_join_count,
                    "status": "pass" if missing_join_count == 0 else "fail",
                },
                {
                    "separation_variant_id": variant_id,
                    "audit_check": "lp_is_fs_mother_trades",
                    "count": lp_is_mother_count,
                    "status": "info",
                },
                {
                    "separation_variant_id": variant_id,
                    "audit_check": "lp_inside_fs_formation_trades",
                    "count": lp_inside_count,
                    "status": "info",
                },
            ]
        )
    return pd.DataFrame(rows)


def _old_vs_new_trade_delta(control_joined: pd.DataFrame, separated_joined: pd.DataFrame) -> pd.DataFrame:
    control = control_joined.copy()
    separated = separated_joined.copy()
    if control.empty:
        return pd.DataFrame()
    control = control.drop_duplicates("trade_key").set_index("trade_key")
    separated = separated.drop_duplicates("trade_key").set_index("trade_key") if not separated.empty else separated
    separated_keys = set(separated.index) if not separated.empty else set()
    rows = []
    for trade_key, base in control.iterrows():
        if trade_key in separated_keys:
            new = separated.loc[trade_key]
            base_lp = base.get("lp_pivot_index")
            new_lp = new.get("lp_pivot_index")
            change_type = "unchanged"
            if not pd.isna(base_lp) and not pd.isna(new_lp) and int(base_lp) != int(new_lp):
                change_type = "reselected_lp_same_trade_key"
            new_net_r = float(new["net_r"])
            new_exit = new["exit_reason"]
        else:
            change_type = "removed_by_separation"
            new_net_r = None
            new_exit = None
        control_net_r = float(base["net_r"])
        rows.append(
            {
                "trade_key": trade_key,
                "change_type": change_type,
                "symbol": base["symbol"],
                "timeframe": base["timeframe"],
                "side": base["side"],
                "signal_index": int(base["signal_index"]),
                "entry_time_utc": base["entry_time_utc"],
                "exit_time_utc": base["exit_time_utc"],
                "control_exit_reason": base["exit_reason"],
                "new_exit_reason": new_exit,
                "control_net_r": control_net_r,
                "new_net_r": new_net_r,
                "net_r_delta": None if new_net_r is None else float(new_net_r - control_net_r),
                "lp_pivot_index": base.get("lp_pivot_index"),
                "fs_mother_index": base.get("fs_mother_index"),
                "fs_signal_index": base.get("fs_signal_index"),
                "control_lp_pivot_index": base.get("lp_pivot_index"),
                "new_lp_pivot_index": None if trade_key not in separated_keys else new.get("lp_pivot_index"),
                "control_fs_mother_index": base.get("fs_mother_index"),
                "new_fs_mother_index": None if trade_key not in separated_keys else new.get("fs_mother_index"),
                "control_lp_is_fs_mother": bool(base.get("lp_is_fs_mother", False)),
                "new_lp_is_fs_mother": False if trade_key not in separated_keys else bool(new.get("lp_is_fs_mother", False)),
                "control_lp_inside_fs_formation": bool(base.get("lp_inside_fs_formation", False)),
                "new_lp_inside_fs_formation": False if trade_key not in separated_keys else bool(new.get("lp_inside_fs_formation", False)),
                "lp_is_fs_mother": bool(base.get("lp_is_fs_mother", False)),
                "lp_inside_fs_formation": bool(base.get("lp_inside_fs_formation", False)),
            }
        )
    if not separated.empty:
        added = sorted(set(separated.index).difference(set(control.index)))
        for trade_key in added:
            new = separated.loc[trade_key]
            rows.append(
                {
                    "trade_key": trade_key,
                    "change_type": "added_by_separation",
                    "symbol": new["symbol"],
                    "timeframe": new["timeframe"],
                    "side": new["side"],
                    "signal_index": int(new["signal_index"]),
                    "entry_time_utc": new["entry_time_utc"],
                    "exit_time_utc": new["exit_time_utc"],
                    "control_exit_reason": None,
                    "new_exit_reason": new["exit_reason"],
                    "control_net_r": None,
                    "new_net_r": float(new["net_r"]),
                    "net_r_delta": float(new["net_r"]),
                    "lp_pivot_index": new.get("lp_pivot_index"),
                    "fs_mother_index": new.get("fs_mother_index"),
                    "fs_signal_index": new.get("fs_signal_index"),
                    "control_lp_pivot_index": None,
                    "new_lp_pivot_index": new.get("lp_pivot_index"),
                    "control_fs_mother_index": None,
                    "new_fs_mother_index": new.get("fs_mother_index"),
                    "control_lp_is_fs_mother": False,
                    "new_lp_is_fs_mother": bool(new.get("lp_is_fs_mother", False)),
                    "control_lp_inside_fs_formation": False,
                    "new_lp_inside_fs_formation": bool(new.get("lp_inside_fs_formation", False)),
                    "lp_is_fs_mother": bool(new.get("lp_is_fs_mother", False)),
                    "lp_inside_fs_formation": bool(new.get("lp_inside_fs_formation", False)),
                }
            )
    return pd.DataFrame(rows)


def _year_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    data = trades.copy()
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True, errors="coerce")
    data = data.dropna(subset=["exit_time_utc"])
    data["exit_year"] = data["exit_time_utc"].dt.year
    return _aggregate_trade_metrics(data, ["separation_variant_id", "separation_variant_label", "exit_year"])


def _bucket_rows_by_variant(trades: pd.DataFrame, bucket_config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_rows = []
    summary_rows = []
    for variant_id in [CONTROL_VARIANT_ID, SEPARATION_VARIANT_ID]:
        variant_trades = trades[trades["separation_variant_id"].eq(variant_id)].copy()
        if variant_trades.empty:
            continue
        summary, _, _ = run_bucket_sensitivity_analysis(variant_trades, bucket_config)
        label = str(variant_trades["separation_variant_label"].iloc[0])
        summary = summary.copy()
        summary.insert(0, "separation_variant_id", variant_id)
        summary.insert(1, "separation_variant_label", label)
        all_rows.append(summary)
        highest = _recommendation(summary).to_dict()
        efficient = _efficiency_recommendation(summary).to_dict()
        baseline = _baseline_row(summary, bucket_config)
        row = {
            "separation_variant_id": variant_id,
            "separation_variant_label": label,
            "trades": int(len(variant_trades)),
            "highest_schedule_id": highest.get("schedule_id"),
            "highest_total_return_pct": highest.get("total_return_pct"),
            "highest_reserved_max_drawdown_pct": highest.get("reserved_max_drawdown_pct"),
            "highest_worst_month_pct": highest.get("worst_month_pct"),
            "highest_return_to_reserved_drawdown": highest.get("return_to_reserved_drawdown"),
            "efficient_schedule_id": efficient.get("schedule_id"),
            "efficient_total_return_pct": efficient.get("total_return_pct"),
            "efficient_reserved_max_drawdown_pct": efficient.get("reserved_max_drawdown_pct"),
            "efficient_worst_month_pct": efficient.get("worst_month_pct"),
            "efficient_return_to_reserved_drawdown": efficient.get("return_to_reserved_drawdown"),
        }
        if baseline is not None:
            row.update(
                {
                    "baseline_schedule_id": baseline["schedule_id"],
                    "baseline_total_return_pct": baseline["total_return_pct"],
                    "baseline_reserved_max_drawdown_pct": baseline["reserved_max_drawdown_pct"],
                    "baseline_worst_month_pct": baseline["worst_month_pct"],
                    "baseline_return_to_reserved_drawdown": baseline["return_to_reserved_drawdown"],
                }
            )
        summary_rows.append(row)
    return (
        pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame(),
        pd.DataFrame(summary_rows),
    )


def _execution_realism_by_variant(
    *,
    dataset_config: Any,
    symbols: list[str],
    timeframes: list[str],
    config: dict[str, Any],
    candidate: Any,
    cost_config: CostConfig,
    variants: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pivot_strength = int(config.get("pivot_strength", 3))
    bid_ask_variant = ExecutionRealismVariant("bid_ask", stop_buffer_spread_mult=0.0)
    trade_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            frame = _load_backtest_frame(
                dataset_config.data_root,
                symbol,
                timeframe,
                drop_latest=bool(config.get("drop_incomplete_latest_bar", True)),
            )
            for variant in variants:
                result = run_lp_force_strike_execution_realism_on_frame(
                    frame,
                    symbol=symbol,
                    timeframe=timeframe,
                    candidate=candidate,
                    variants=[bid_ask_variant],
                    pivot_strength=pivot_strength,
                    max_bars_from_lp_break=int(config.get("max_bars_from_lp_break", 6)),
                    atr_period=int(config.get("atr_period", 14)),
                    max_entry_wait_bars=int(config.get("max_entry_wait_bars", 6)),
                    costs=cost_config,
                    require_lp_pivot_before_fs_mother=bool(variant["require_lp_pivot_before_fs_mother"]),
                )
                for trade in result.trades:
                    row = trade_report_row(trade)
                    row["base_candidate_id"] = str(row.get("candidate_id", ""))
                    row["pivot_strength"] = pivot_strength
                    row["separation_variant_id"] = str(variant["variant_id"])
                    row["separation_variant_label"] = str(variant["label"])
                    row["execution_variant_id"] = str(row.get("meta_execution_variant_id", "bid_ask_buffer_0p00x"))
                    trade_rows.append(row)
                for skipped in result.skipped:
                    row = skipped.to_dict()
                    row["base_candidate_id"] = candidate.candidate_id
                    row["candidate_id"] = candidate.candidate_id
                    row["pivot_strength"] = pivot_strength
                    row["separation_variant_id"] = str(variant["variant_id"])
                    row["separation_variant_label"] = str(variant["label"])
                    row["execution_variant_id"] = bid_ask_variant.variant_id
                    skipped_rows.append(row)
    trades = pd.DataFrame(trade_rows)
    summary = _aggregate_trade_metrics(trades, ["separation_variant_id", "separation_variant_label", "execution_variant_id"])
    return summary, pd.DataFrame(skipped_rows)


def _research_revalidation_matrix() -> pd.DataFrame:
    rows = [
        {
            "research_branch": "V9 full signal/trade generation",
            "classification": "rerun_in_v22",
            "reason": "V22 reruns the full 10-year signal and trade population for current vs separation variants.",
            "next_action": "Use V22 comparison before any signal-rule decision.",
        },
        {
            "research_branch": "V15 risk bucket sensitivity",
            "classification": "rerun_in_v22",
            "reason": "V22 reruns bucket schedules on the separated trade population.",
            "next_action": "Compare bucket_sensitivity_by_variant.csv before changing risk assumptions.",
        },
        {
            "research_branch": "V16 bid/ask execution realism",
            "classification": "rerun_in_v22",
            "reason": "V22 reruns no-buffer bid/ask control for both signal populations.",
            "next_action": "Use execution_realism_by_variant.csv as the current execution-realism check.",
        },
        {
            "research_branch": "V17 LP/FS proximity",
            "classification": "stale_until_rerun",
            "reason": "V17 studied the old signal universe that allowed LP pivot inside the FS formation.",
            "next_action": "Rerun proximity on the accepted V22 signal universe before using it for a new live-rule decision.",
        },
        {
            "research_branch": "V18/V19 TP-near exits",
            "classification": "stale_until_rerun",
            "reason": "The TP-near trade population came from the old baseline.",
            "next_action": "Rerun TP-near on the accepted V22 signal universe before using it for a live TP/SL decision.",
        },
        {
            "research_branch": "V20 protection realism",
            "classification": "stale_until_rerun",
            "reason": "Protection timing used old signal candidates.",
            "next_action": "Rerun lower-timeframe protection on the accepted V22 signal universe.",
        },
        {
            "research_branch": "V21 crypto expansion",
            "classification": "stale_before_crypto_live_planning",
            "reason": "Crypto used the same signal-rule family and must be rechecked before crypto expansion decisions.",
            "next_action": "Rerun crypto transfer with the accepted V22 separation rule if crypto remains a priority.",
        },
        {
            "research_branch": "V1-V8 exploratory search history",
            "classification": "historical_context_only",
            "reason": "These explain the path to the baseline but are not current live-decision gates.",
            "next_action": "No rerun needed for the V22 rule decision.",
        },
    ]
    return pd.DataFrame(rows)


def _summary_by_variant(
    raw_summary: pd.DataFrame,
    delta: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    execution_summary: pd.DataFrame,
) -> pd.DataFrame:
    if raw_summary.empty:
        return pd.DataFrame()
    summary = raw_summary.copy()
    control = summary[summary["separation_variant_id"].eq(CONTROL_VARIANT_ID)].iloc[0].to_dict()
    delta_counts = delta["change_type"].value_counts().to_dict() if not delta.empty else {}
    removed = delta[delta["change_type"].eq("removed_by_separation")].copy() if not delta.empty else pd.DataFrame()
    reselected = delta[delta["change_type"].eq("reselected_lp_same_trade_key")].copy() if not delta.empty else pd.DataFrame()
    control_lp_mother = (
        delta[delta["control_lp_is_fs_mother"].fillna(False)].copy()
        if "control_lp_is_fs_mother" in delta.columns
        else pd.DataFrame()
    )
    control_lp_inside = (
        delta[delta["control_lp_inside_fs_formation"].fillna(False)].copy()
        if "control_lp_inside_fs_formation" in delta.columns
        else pd.DataFrame()
    )
    removed_lp_mother = int(removed["lp_is_fs_mother"].fillna(False).sum()) if not removed.empty else 0
    removed_lp_inside = int(removed["lp_inside_fs_formation"].fillna(False).sum()) if not removed.empty else 0
    reselected_lp_mother = int(reselected["control_lp_is_fs_mother"].fillna(False).sum()) if not reselected.empty else 0
    reselected_lp_inside = int(reselected["control_lp_inside_fs_formation"].fillna(False).sum()) if not reselected.empty else 0
    rows = []
    for _, row in summary.iterrows():
        item = row.to_dict()
        item["trade_delta_vs_control"] = int(item["trades"] - int(control["trades"]))
        item["win_rate_delta_vs_control"] = float(item["win_rate"] - float(control["win_rate"]))
        item["pf_delta_vs_control"] = None
        if item.get("profit_factor") is not None and control.get("profit_factor") is not None:
            item["pf_delta_vs_control"] = float(item["profit_factor"] - float(control["profit_factor"]))
        item["total_net_r_delta_vs_control"] = float(item["total_net_r"] - float(control["total_net_r"]))
        item["avg_net_r_delta_vs_control"] = float(item["avg_net_r"] - float(control["avg_net_r"]))
        item["lp_mother_trades_removed"] = removed_lp_mother if item["separation_variant_id"] == SEPARATION_VARIANT_ID else 0
        item["lp_inside_fs_trades_removed"] = removed_lp_inside if item["separation_variant_id"] == SEPARATION_VARIANT_ID else 0
        item["control_lp_mother_trade_keys"] = int(len(control_lp_mother)) if item["separation_variant_id"] == SEPARATION_VARIANT_ID else 0
        item["control_lp_inside_fs_trade_keys"] = int(len(control_lp_inside)) if item["separation_variant_id"] == SEPARATION_VARIANT_ID else 0
        item["lp_mother_trade_keys_reselected"] = reselected_lp_mother if item["separation_variant_id"] == SEPARATION_VARIANT_ID else 0
        item["lp_inside_fs_trade_keys_reselected"] = reselected_lp_inside if item["separation_variant_id"] == SEPARATION_VARIANT_ID else 0
        item["unchanged_trade_count"] = int(delta_counts.get("unchanged", 0)) if item["separation_variant_id"] == SEPARATION_VARIANT_ID else int(item["trades"])
        item["reselected_lp_same_trade_key_count"] = int(delta_counts.get("reselected_lp_same_trade_key", 0)) if item["separation_variant_id"] == SEPARATION_VARIANT_ID else 0
        bucket = bucket_summary[bucket_summary["separation_variant_id"].eq(item["separation_variant_id"])]
        if not bucket.empty:
            item.update({f"bucket_{key}": value for key, value in bucket.iloc[0].to_dict().items() if key not in item})
        execution = execution_summary[execution_summary["separation_variant_id"].eq(item["separation_variant_id"])]
        if not execution.empty:
            exec_row = execution.iloc[0].to_dict()
            item["bid_ask_trades"] = exec_row.get("trades")
            item["bid_ask_total_net_r"] = exec_row.get("total_net_r")
            item["bid_ask_profit_factor"] = exec_row.get("profit_factor")
            item["bid_ask_return_to_drawdown_r"] = exec_row.get("return_to_drawdown_r")
        rows.append(item)
    return pd.DataFrame(rows)


def _decision(summary: pd.DataFrame, criteria: dict[str, Any]) -> dict[str, Any]:
    if summary.empty or summary["separation_variant_id"].nunique() < 2:
        return {
            "status": "insufficient_data",
            "headline": "V22 did not produce enough comparable data.",
            "detail": "Both control and separated variants are required.",
            "follow_up": "Fix the report run before making a rule decision.",
        }
    control = summary[summary["separation_variant_id"].eq(CONTROL_VARIANT_ID)].iloc[0].to_dict()
    separated = summary[summary["separation_variant_id"].eq(SEPARATION_VARIANT_ID)].iloc[0].to_dict()
    r_delta = float(separated["total_net_r_delta_vs_control"])
    pf_delta = separated.get("pf_delta_vs_control")
    win_delta = float(separated["win_rate_delta_vs_control"])
    avg_r_delta = float(separated.get("avg_net_r_delta_vs_control", 0.0))
    return_dd_delta = None
    if separated.get("return_to_drawdown_r") is not None and control.get("return_to_drawdown_r") is not None:
        return_dd_delta = float(separated["return_to_drawdown_r"] - control["return_to_drawdown_r"])
    trade_cut_pct = 0.0 if float(control["trades"]) <= 0 else (float(control["trades"]) - float(separated["trades"])) / float(control["trades"]) * 100.0
    r_drop_pct = 0.0
    if float(control["total_net_r"]) > 0 and r_delta < 0:
        r_drop_pct = abs(r_delta) / float(control["total_net_r"]) * 100.0
    min_return_dd_delta = criteria.get("min_return_to_drawdown_delta")
    passes_return_dd = (
        True
        if min_return_dd_delta is None
        else return_dd_delta is None or return_dd_delta >= float(min_return_dd_delta)
    )
    passes_quality = (
        (pf_delta is not None and float(pf_delta) >= float(criteria.get("min_profit_factor_delta", 0.0)))
        and win_delta >= float(criteria.get("min_win_rate_delta", 0.0))
        and avg_r_delta >= float(criteria.get("min_avg_net_r_delta", 0.0))
        and passes_return_dd
    )
    passes_cost = (
        r_drop_pct <= float(criteria.get("max_total_net_r_drop_pct", 5.0))
        and trade_cut_pct <= float(criteria.get("max_trade_count_cut_pct", 20.0))
    )
    if r_delta > 0 and passes_quality:
        status = "live_rule_candidate"
        headline = "The separation rule improved the current backtest."
        follow_up = "Next: review removed trades, then draft a separate production-change plan if the rule looks conceptually correct."
    elif passes_quality and passes_cost:
        status = "accepted_quality_tradeoff"
        headline = "Accept the hard LP-before-FS rule for implementation planning."
        follow_up = "Next: deploy the hard rule intentionally, then rerun stale V17-V21 research on the accepted signal universe."
    elif r_delta < 0 and not passes_cost:
        status = "do_not_patch_live_yet"
        headline = "The rule weakens the current baseline too much for an immediate change."
        follow_up = "Next: study the removed profitable trades and decide whether a narrower rule than LP pivot before mother is needed."
    else:
        status = "mixed_result"
        headline = "The rule has mixed evidence."
        follow_up = "Next: inspect symbol/timeframe/year concentration before any implementation decision."
    return {
        "status": status,
        "headline": headline,
        "detail": (
            f"Separated variant changed total R by {r_delta:.1f}, PF by "
            f"{0.0 if pf_delta is None else float(pf_delta):.3f}, win rate by {win_delta * 100.0:.2f}pp, "
            f"and removed {trade_cut_pct:.1f}% of trades."
        ),
        "follow_up": follow_up,
        "trade_cut_pct": trade_cut_pct,
        "total_net_r_drop_pct": r_drop_pct,
        "return_to_drawdown_delta": return_dd_delta,
        "passes_quality": bool(passes_quality),
        "passes_cost": bool(passes_cost),
    }


def _comparison_table(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    columns = [
        "separation_variant_id",
        "separation_variant_label",
        "trades",
        "trade_delta_vs_control",
        "win_rate",
        "win_rate_delta_vs_control",
        "profit_factor",
        "pf_delta_vs_control",
        "total_net_r",
        "total_net_r_delta_vs_control",
        "avg_net_r",
        "avg_net_r_delta_vs_control",
        "target_exits",
        "stop_exits",
        "same_bar_stop_exits",
        "bucket_efficient_reserved_max_drawdown_pct",
        "bucket_efficient_return_to_reserved_drawdown",
        "bucket_efficient_worst_month_pct",
        "control_lp_mother_trade_keys",
        "lp_mother_trades_removed",
        "lp_mother_trade_keys_reselected",
    ]
    return summary.loc[:, [column for column in columns if column in summary.columns]].copy()


def _html_report(
    run_dir: Path,
    *,
    decision: dict[str, Any],
    comparison: pd.DataFrame,
    overlap_audit: pd.DataFrame,
    symbol_summary: pd.DataFrame,
    timeframe_summary: pd.DataFrame,
    symbol_timeframe_summary: pd.DataFrame,
    year_breakdown: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    execution_summary: pd.DataFrame,
    delta: pd.DataFrame,
    revalidation: pd.DataFrame,
    run_summary: dict[str, Any],
) -> str:
    separated = comparison[comparison["separation_variant_id"].eq(SEPARATION_VARIANT_ID)]
    separated_row = separated.iloc[0].to_dict() if not separated.empty else {}
    decision_badge_class = {
        "live_rule_candidate": "good",
        "accepted_quality_tradeoff": "good",
        "design_valid_but_small_tradeoff": "warn",
        "mixed_result": "warn",
        "do_not_patch_live_yet": "bad",
    }.get(str(decision.get("status")), "neutral")
    removed_samples = delta[delta["change_type"].eq("removed_by_separation")].copy() if not delta.empty else pd.DataFrame()
    if not removed_samples.empty:
        removed_samples = removed_samples.reindex(removed_samples["control_net_r"].abs().sort_values(ascending=False).index)
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V22 LP-FS Separation - by Cody</title>
  <style>
    {dashboard_base_css()}
    .badge {{ display:inline-block; padding:4px 8px; border-radius:4px; font-size:12px; font-weight:700; }}
    .badge.good {{ background:#dcfce7; color:#166534; }}
    .badge.warn {{ background:#fef3c7; color:#92400e; }}
    .badge.bad {{ background:#fee2e2; color:#991b1b; }}
    .badge.neutral {{ background:#e5e7eb; color:#374151; }}
  </style>
</head>
<body>
{dashboard_header_html(
    title="LP + Force Strike V22 LP-FS Separation - by Cody",
    subtitle_html="Research-only full 10-year test of requiring the LP pivot bar to be before the Force Strike mother bar.",
    current_page="v22.html",
    section_links=[
        ("#decision", "Decision"),
        ("#comparison", "Comparison"),
        ("#audit", "Overlap Audit"),
        ("#bucket", "V15 Rerun"),
        ("#execution", "V16 Rerun"),
        ("#breakdowns", "Breakdowns"),
        ("#revalidation", "Revalidation"),
        ("#follow-up", "Follow-Up"),
    ],
)}
<main>
<section id="decision">
  <h2>Decision Card</h2>
  <p class="callout"><span class="badge {decision_badge_class}">{_escape(str(decision.get('status', '')).replace('_', ' ').upper())}</span> <strong>{_escape(decision.get('headline'))}</strong> {_escape(decision.get('detail'))}</p>
  <div class="metric-grid">
    <div class="metric-card"><span>Trade Delta</span><strong>{_fmt_int(separated_row.get('trade_delta_vs_control'))}</strong></div>
    <div class="metric-card"><span>Total R Delta</span><strong class="{_metric_class(separated_row.get('total_net_r_delta_vs_control'))}">{_fmt_num(separated_row.get('total_net_r_delta_vs_control'))}</strong></div>
    <div class="metric-card"><span>PF Delta</span><strong class="{_metric_class(separated_row.get('pf_delta_vs_control'))}">{_fmt_num(separated_row.get('pf_delta_vs_control'), 3)}</strong></div>
    <div class="metric-card"><span>Win Rate Delta</span><strong>{_fmt_pct(separated_row.get('win_rate_delta_vs_control'), 2)}</strong></div>
    <div class="metric-card"><span>Reserved DD</span><strong>{_fmt_pct_points(separated_row.get('bucket_efficient_reserved_max_drawdown_pct'), 2)}</strong></div>
    <div class="metric-card"><span>Return/DD</span><strong>{_fmt_num(separated_row.get('bucket_efficient_return_to_reserved_drawdown'))}</strong></div>
  </div>
  <p class="muted">V22 accepted the hard LP-before-FS rule as the next baseline. Deployment still requires the live runner to be intentionally updated and restarted; existing live state, pending orders, and positions are not edited by this report.</p>
</section>
<section id="comparison">
  <h2>Comparison Table</h2>
  {_table(comparison, list(comparison.columns))}
</section>
<section id="audit">
  <h2>Overlap Audit</h2>
  <p class="callout">Duplicate join keys and missing trade-to-signal joins must be zero before reading the trade deltas.</p>
  {_table(overlap_audit, ["separation_variant_id", "audit_check", "count", "status"])}
</section>
<section id="bucket">
  <h2>V15 Bucket Sensitivity Rerun</h2>
  {_table(bucket_summary, ["separation_variant_id", "trades", "efficient_schedule_id", "efficient_total_return_pct", "efficient_reserved_max_drawdown_pct", "efficient_worst_month_pct", "efficient_return_to_reserved_drawdown"])}
</section>
<section id="execution">
  <h2>V16 Bid/Ask Execution Realism</h2>
  {_table(execution_summary, ["separation_variant_id", "execution_variant_id", "trades", "win_rate", "total_net_r", "avg_net_r", "profit_factor", "max_drawdown_r", "return_to_drawdown_r"])}
</section>
<section id="breakdowns">
  <h2>Symbol Breakdown</h2>
  {_table(symbol_summary.sort_values(["separation_variant_id", "total_net_r"], ascending=[True, False]), ["separation_variant_id", "symbol", "trades", "win_rate", "total_net_r", "avg_net_r", "profit_factor", "return_to_drawdown_r"], limit=40)}
  <h2>Timeframe Breakdown</h2>
  {_table(timeframe_summary.sort_values(["separation_variant_id", "timeframe"]), ["separation_variant_id", "timeframe", "trades", "win_rate", "total_net_r", "avg_net_r", "profit_factor", "return_to_drawdown_r"])}
  <h2>Symbol-Timeframe Breakdown</h2>
  {_table(symbol_timeframe_summary.sort_values("total_net_r", ascending=False), ["separation_variant_id", "symbol", "timeframe", "trades", "total_net_r", "avg_net_r", "profit_factor"], limit=40)}
  <h2>Year Breakdown</h2>
  {_table(year_breakdown.sort_values(["separation_variant_id", "exit_year"]), ["separation_variant_id", "exit_year", "trades", "win_rate", "total_net_r", "avg_net_r", "profit_factor"])}
</section>
<section id="removed">
  <h2>Removed Trade Samples</h2>
  <p class="callout">These are the largest-impact trades removed by requiring the LP pivot to be before the Force Strike mother.</p>
  {_table(removed_samples, ["symbol", "timeframe", "side", "signal_index", "control_exit_reason", "control_net_r", "lp_pivot_index", "fs_mother_index", "fs_signal_index", "lp_is_fs_mother", "lp_inside_fs_formation"], limit=25)}
</section>
<section id="revalidation">
  <h2>Research Revalidation Matrix</h2>
  {_table(revalidation, ["research_branch", "classification", "reason", "next_action"])}
</section>
<section id="follow-up">
  <h2>Follow-Up Section</h2>
  <p class="callout"><strong>{_escape(decision.get('follow_up'))}</strong></p>
  <p class="muted">Artifacts live under <code>{_escape(_display_path(run_dir))}</code>. Datasets: {_fmt_int(run_summary.get('datasets'))}; failed: {_fmt_int(run_summary.get('failed_datasets'))}; trades: {_fmt_int(run_summary.get('trades'))}; signals: {_fmt_int(run_summary.get('signals'))}.</p>
</section>
{metric_glossary_html()}
</main>
<footer>Generated from <code>{_escape(_display_path(run_dir))}</code>. Research-only evidence; production changes require a separate plan.</footer>
</body>
</html>
"""
    return body


def _run(
    config_path: Path,
    *,
    symbol_override: list[str] | None,
    timeframe_override: list[str] | None,
    output_dir: Path | None,
    docs_output: Path | None,
) -> int:
    config = _read_json(REPO_ROOT / config_path)
    dataset_config = load_dataset_config(REPO_ROOT / str(config["dataset_config"]))
    v15_config = _read_json(REPO_ROOT / str(config["v15_bucket_config"]))
    symbols = _selected_symbols(dataset_config.symbols, config, symbol_override)
    timeframes = _selected_timeframes(dataset_config.timeframes, config, timeframe_override)
    candidate = _make_candidate(config)
    variant_rows = _variants(config)
    pivot_strength = int(config.get("pivot_strength", 3))
    cost_config = _cost_config(config)
    run_dir = output_dir or (
        REPO_ROOT
        / str(config.get("report_root", "reports/strategies/lp_force_strike_experiment_v22_lp_fs_separation"))
        / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    all_signal_rows: list[dict[str, Any]] = []
    all_trade_rows: list[dict[str, Any]] = []
    all_skipped_rows: list[dict[str, Any]] = []
    dataset_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            try:
                frame = _load_backtest_frame(
                    dataset_config.data_root,
                    symbol,
                    timeframe,
                    drop_latest=bool(config.get("drop_incomplete_latest_bar", True)),
                )
                for variant in variant_rows:
                    result = run_lp_force_strike_experiment_on_frame(
                        frame,
                        symbol=symbol,
                        timeframe=timeframe,
                        candidates=[candidate],
                        pivot_strength=pivot_strength,
                        max_bars_from_lp_break=int(config.get("max_bars_from_lp_break", 6)),
                        atr_period=int(config.get("atr_period", 14)),
                        max_entry_wait_bars=int(config.get("max_entry_wait_bars", 6)),
                        costs=cost_config,
                        require_lp_pivot_before_fs_mother=bool(variant["require_lp_pivot_before_fs_mother"]),
                    )
                    all_signal_rows.extend(
                        _signal_report_row(
                            symbol=symbol,
                            timeframe=timeframe,
                            pivot_strength=pivot_strength,
                            signal=signal,
                            variant=variant,
                        )
                        for signal in result.signals
                    )
                    all_trade_rows.extend(
                        _trade_report_row(trade, pivot_strength=pivot_strength, variant=variant)
                        for trade in result.trades
                    )
                    all_skipped_rows.extend(
                        _skipped_report_row(skipped, candidate, pivot_strength=pivot_strength, variant=variant)
                        for skipped in result.skipped
                    )
                    dataset_rows.append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "separation_variant_id": str(variant["variant_id"]),
                            "status": "ok",
                            "rows": int(len(frame)),
                            "signals": int(len(result.signals)),
                            "trades": int(len(result.trades)),
                            "skipped": int(len(result.skipped)),
                        }
                    )
                    print(
                        f"{symbol} {timeframe} {variant['variant_id']}: rows={len(frame)} "
                        f"signals={len(result.signals)} trades={len(result.trades)} skipped={len(result.skipped)}"
                    )
            except Exception as exc:
                dataset_rows.append({"symbol": symbol, "timeframe": timeframe, "status": "failed", "error": str(exc)})
                print(f"{symbol} {timeframe}: failed={exc}")

    signals = pd.DataFrame(all_signal_rows)
    trades = pd.DataFrame(all_trade_rows)
    skipped = pd.DataFrame(all_skipped_rows)
    datasets = pd.DataFrame(dataset_rows)
    if trades.empty:
        raise ValueError("V22 produced no trades.")

    control_joined = _join_trade_signal_attrs(trades, signals, CONTROL_VARIANT_ID)
    separated_joined = _join_trade_signal_attrs(trades, signals, SEPARATION_VARIANT_ID)
    overlap = _overlap_audit(trades, signals)
    delta = _old_vs_new_trade_delta(control_joined, separated_joined)
    raw_summary = _aggregate_trade_metrics(trades, ["separation_variant_id", "separation_variant_label"])
    symbol_summary = _aggregate_trade_metrics(trades, ["separation_variant_id", "separation_variant_label", "symbol"])
    timeframe_summary = _aggregate_trade_metrics(trades, ["separation_variant_id", "separation_variant_label", "timeframe"])
    symbol_timeframe_summary = _aggregate_trade_metrics(
        trades,
        ["separation_variant_id", "separation_variant_label", "symbol", "timeframe"],
    )
    years = _year_breakdown(trades)
    bucket_sensitivity, bucket_summary = _bucket_rows_by_variant(trades, v15_config)
    execution_summary, execution_skipped = _execution_realism_by_variant(
        dataset_config=dataset_config,
        symbols=symbols,
        timeframes=timeframes,
        config=config,
        candidate=candidate,
        cost_config=cost_config,
        variants=variant_rows,
    )
    revalidation = _research_revalidation_matrix()
    summary = _summary_by_variant(raw_summary, delta, bucket_summary, execution_summary)
    comparison = _comparison_table(summary)
    decision = _decision(summary, config.get("decision_criteria", {}))

    failed = datasets[datasets.get("status").ne("ok")] if "status" in datasets.columns else pd.DataFrame()
    run_summary = {
        "run_dir": str(run_dir),
        "config_path": str(config_path),
        "experiment_name": config.get("experiment_name"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "datasets": int(len(datasets)),
        "failed_datasets": int(len(failed)),
        "symbols": symbols,
        "timeframes": timeframes,
        "signals": int(len(signals)),
        "trades": int(len(trades)),
        "skipped": int(len(skipped)),
        "decision": decision,
    }

    _write_json(
        run_dir / "run_config.json",
        {
            "config_path": str(config_path),
            "config": config,
            "symbols": symbols,
            "timeframes": timeframes,
            "candidate": asdict(candidate),
            "variants": variant_rows,
        },
    )
    _write_csv(run_dir / "datasets.csv", datasets)
    _write_csv(run_dir / "signals.csv", signals)
    _write_csv(run_dir / "trades.csv", trades)
    _write_csv(run_dir / "skipped.csv", skipped)
    _write_csv(run_dir / "overlap_audit.csv", overlap)
    _write_csv(run_dir / "summary_by_variant.csv", summary)
    _write_csv(run_dir / "old_vs_new_trade_delta.csv", delta)
    _write_csv(run_dir / "summary_by_symbol.csv", symbol_summary)
    _write_csv(run_dir / "summary_by_timeframe.csv", timeframe_summary)
    _write_csv(run_dir / "summary_by_symbol_timeframe.csv", symbol_timeframe_summary)
    _write_csv(run_dir / "year_breakdown.csv", years)
    _write_csv(run_dir / "bucket_sensitivity_by_variant.csv", bucket_sensitivity)
    _write_csv(run_dir / "execution_realism_by_variant.csv", execution_summary)
    _write_csv(run_dir / "execution_realism_skipped.csv", execution_skipped)
    _write_csv(run_dir / "research_revalidation_matrix.csv", revalidation)
    _write_json(run_dir / "run_summary.json", run_summary)

    html_report = _html_report(
        run_dir,
        decision=decision,
        comparison=comparison,
        overlap_audit=overlap,
        symbol_summary=symbol_summary,
        timeframe_summary=timeframe_summary,
        symbol_timeframe_summary=symbol_timeframe_summary,
        year_breakdown=years,
        bucket_summary=bucket_summary,
        execution_summary=execution_summary,
        delta=delta,
        revalidation=revalidation,
        run_summary=run_summary,
    )
    html_report = "\n".join(line.rstrip() for line in html_report.splitlines()) + "\n"
    (run_dir / "dashboard.html").write_text(html_report, encoding="utf-8")
    docs_target = docs_output
    if docs_target is None and config.get("docs_output_path"):
        docs_target = REPO_ROOT / str(config["docs_output_path"])
    if docs_target is not None:
        docs_target.parent.mkdir(parents=True, exist_ok=True)
        docs_target.write_text(html_report, encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True, default=str))
    return 1 if not failed.empty else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LPFS V22 LP/Force-Strike separation research.")
    parser.add_argument(
        "--config",
        default="configs/strategies/lp_force_strike_experiment_v22_lp_fs_separation.json",
        help="Path to V22 strategy config.",
    )
    parser.add_argument("--symbols", help="Optional comma-separated symbol override.")
    parser.add_argument("--timeframes", help="Optional comma-separated timeframe override.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    parser.add_argument("--docs-output", help="Optional docs HTML output path.")
    args = parser.parse_args()

    return _run(
        Path(args.config),
        symbol_override=_parse_csv_arg(args.symbols),
        timeframe_override=_parse_csv_arg(args.timeframes),
        output_dir=None if args.output_dir is None else Path(args.output_dir),
        docs_output=None if args.docs_output is None else Path(args.docs_output),
    )


if __name__ == "__main__":
    raise SystemExit(main())
