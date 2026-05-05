from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
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
from lp_force_strike_strategy_lab import (  # noqa: E402
    ExecutionRealismVariant,
    make_trade_model_candidates,
    run_lp_force_strike_execution_realism_on_frame,
    trade_report_row,
)
from lp_force_strike_strategy_lab.execution_contract import V15_EFFICIENT_RISK_BUCKET_PCT  # noqa: E402
from lp_force_strike_dashboard_metadata import (  # noqa: E402
    dashboard_base_css,
    dashboard_header_html,
    metric_glossary_html,
)
from market_data_lab import (  # noqa: E402
    dataset_coverage_report,
    load_dataset_config,
    load_rates_parquet,
    manifest_path,
    normalize_timeframe,
    read_json,
)
from report_data_quality import _dataset_checks, _verdict, _weekly_consistency  # noqa: E402
from run_lp_force_strike_experiment import (  # noqa: E402
    _load_backtest_frame,
    _parse_csv_arg,
    _signal_row,
)


CONTROL_VARIANT_ID = "control_bid_ask"
DECISION_ROLE = "decision"
EXPLORATORY_ROLE = "exploratory"
FX_V16_CONTROL_REPORT_DIR = (
    REPO_ROOT
    / "reports"
    / "strategies"
    / "lp_force_strike_experiment_v16_execution_realism"
    / "20260501_060205"
)
FX_V15_CANONICAL_BASELINE = {
    "comparison_row": "V15 canonical FX baseline",
    "scope": "28 FX pairs, H4/H8/H12/D1/W1, OHLC execution",
    "trades": 13012,
    "total_net_r": 1512.3,
    "avg_net_r": 0.116,
    "profit_factor": 1.265,
    "max_drawdown_r": 33.4,
    "return_to_drawdown": 45.3,
    "worst_month_r": None,
    "note": "Current strategy baseline before bid/ask execution realism.",
}
FX_V16_CONTROL_FALLBACK = {
    "comparison_row": "V16 FX bid/ask control",
    "scope": "28 FX pairs, H4/H8/H12/D1/W1, bid/ask no-buffer control",
    "trades": 12917,
    "total_net_r": 1535.2,
    "avg_net_r": 0.119,
    "profit_factor": 1.270,
    "max_drawdown_r": None,
    "return_to_drawdown": None,
    "worst_month_r": None,
    "note": "Closest execution-realistic control for current FX baseline.",
}


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


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isinf(number):
        return "inf"
    return f"{number:,.{digits}f}"


def _fmt_int(value: Any) -> str:
    if value is None or pd.isna(value):
        return "0"
    return f"{int(float(value)):,}"


def _fmt_pct(value: Any, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100.0:,.{digits}f}%"


def _cost_config(payload: dict[str, Any]) -> CostConfig:
    costs = payload.get("costs", {})
    return CostConfig(
        use_candle_spread=bool(costs.get("use_candle_spread", True)),
        fallback_spread_points=float(costs.get("fallback_spread_points", 0.0)),
        entry_slippage_points=float(costs.get("entry_slippage_points", 0.0)),
        exit_slippage_points=float(costs.get("exit_slippage_points", 0.0)),
        round_turn_commission_points=float(costs.get("round_turn_commission_points", 0.0)),
    )


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
        raise ValueError("V21 expects exactly one unchanged LPFS baseline candidate.")
    return candidates[0]


def _selected_timeframes(dataset_timeframes: tuple[str, ...], config: dict[str, Any], override: list[str] | None) -> list[str]:
    raw = override if override is not None else config.get("timeframes", dataset_timeframes)
    return [normalize_timeframe(timeframe) for timeframe in raw]


def _asset_role(symbol: str, decision_symbols: set[str], exploratory_symbols: set[str]) -> str:
    normalized = str(symbol).upper()
    if normalized in decision_symbols:
        return DECISION_ROLE
    if normalized in exploratory_symbols:
        return EXPLORATORY_ROLE
    return "excluded"


def _manifest(root: str | Path, symbol: str, timeframe: str) -> dict[str, Any]:
    return read_json(manifest_path(root, symbol, timeframe))


def _symbol_specs(config) -> pd.DataFrame:
    rows = []
    seen: set[str] = set()
    for symbol in config.symbols:
        if symbol in seen:
            continue
        seen.add(symbol)
        selected_manifest = None
        for timeframe in config.timeframes:
            path = manifest_path(config.data_root, symbol, timeframe)
            if path.exists():
                selected_manifest = read_json(path)
                break
        metadata = {} if selected_manifest is None else dict(selected_manifest.get("symbol_metadata", {}) or {})
        row = {
            "symbol": symbol,
            "status": "missing_manifest" if selected_manifest is None else "ok",
            "coverage_start_utc": None if selected_manifest is None else selected_manifest.get("coverage_start_utc"),
            "coverage_end_utc": None if selected_manifest is None else selected_manifest.get("coverage_end_utc"),
        }
        for key in [
            "digits",
            "point",
            "spread_points",
            "spread_float",
            "trade_tick_value",
            "trade_tick_size",
            "volume_min",
            "volume_max",
            "volume_step",
            "trade_contract_size",
            "trade_stops_level",
            "trade_freeze_level",
            "trade_mode",
        ]:
            row[key] = metadata.get(key)
        rows.append(row)
    return pd.DataFrame(rows)


def _trade_row(trade, *, pivot_strength: int, role_map: dict[str, str]) -> dict[str, Any]:
    row = trade_report_row(trade)
    raw_variant = str(row.get("meta_execution_variant_id", ""))
    row["raw_execution_variant_id"] = raw_variant
    row["execution_variant_id"] = CONTROL_VARIANT_ID
    row["pivot_strength"] = int(pivot_strength)
    row["asset_role"] = role_map.get(str(row.get("symbol", "")).upper(), "excluded")
    return row


def _skipped_row(skipped, candidate: Any, *, pivot_strength: int, role_map: dict[str, str]) -> dict[str, Any]:
    row = skipped.to_dict()
    row["base_candidate_id"] = candidate.candidate_id
    row["candidate_id"] = candidate.candidate_id
    row["pivot_strength"] = int(pivot_strength)
    row["execution_variant_id"] = CONTROL_VARIANT_ID
    row["asset_role"] = role_map.get(str(row.get("symbol", "")).upper(), "excluded")
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
    month_key = data["exit_time_utc"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("M")
    monthly = data.groupby(month_key)["net_r"].sum()
    return float(monthly.min()) if len(monthly) else None


def _aggregate(frame: pd.DataFrame, group_fields: list[str] | None = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    group_fields = group_fields or []
    grouped = [((), data)] if not group_fields else data.groupby(group_fields, dropna=False)
    rows = []
    for keys, group in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        net_r = group["net_r"]
        row = {field: value for field, value in zip(group_fields, keys)}
        max_dd = _max_drawdown(net_r.reset_index(drop=True))
        row.update(
            {
                "trades": int(len(group)),
                "wins": int((net_r > 0).sum()),
                "losses": int((net_r < 0).sum()),
                "win_rate": float((net_r > 0).mean()) if len(group) else 0.0,
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()) if len(group) else 0.0,
                "profit_factor": _profit_factor(net_r),
                "max_drawdown_r": max_dd,
                "return_to_drawdown": None if max_dd <= 0 else float(net_r.sum()) / max_dd,
                "worst_month_r": _worst_month(group),
                "target_exits": int(group["exit_reason"].eq("target").sum()) if "exit_reason" in group else 0,
                "stop_exits": int(group["exit_reason"].eq("stop").sum()) if "exit_reason" in group else 0,
                "same_bar_stop_exits": int(group["exit_reason"].eq("same_bar_stop_priority").sum()) if "exit_reason" in group else 0,
                "end_of_data_exits": int(group["exit_reason"].eq("end_of_data").sum()) if "exit_reason" in group else 0,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _risk_bucket_pct(timeframe: str, risk_bucket_scale: float) -> float:
    key = str(timeframe).upper()
    if key not in V15_EFFICIENT_RISK_BUCKET_PCT:
        raise ValueError(f"No V15 risk bucket for timeframe {timeframe!r}.")
    return float(V15_EFFICIENT_RISK_BUCKET_PCT[key]) * float(risk_bucket_scale)


def _round_volume_down(volume: float, step: float) -> float:
    if step <= 0:
        return 0.0
    return math.floor(float(volume) / float(step) + 1e-12) * float(step)


def _feasibility_row(
    row: pd.Series | dict[str, Any],
    symbol_specs: pd.DataFrame,
    *,
    account_equity: float | None,
    risk_bucket_scale: float,
    max_spread_risk_fraction: float,
) -> dict[str, Any]:
    get = row.get if isinstance(row, dict) else row.get
    symbol = str(get("symbol")).upper()
    timeframe = str(get("timeframe")).upper()
    specs = symbol_specs[symbol_specs["symbol"].astype(str).str.upper().eq(symbol)]
    target_risk_pct = _risk_bucket_pct(timeframe, risk_bucket_scale)
    base = {
        "symbol": symbol,
        "timeframe": timeframe,
        "asset_role": get("asset_role"),
        "side": get("side"),
        "signal_index": get("signal_index"),
        "entry_time_utc": get("entry_time_utc"),
        "target_risk_pct": target_risk_pct,
    }
    if specs.empty:
        return {**base, "feasibility_status": "missing_symbol_spec", "live_feasible": False}

    spec = specs.iloc[0]
    risk_distance = _safe_float(get("risk_distance"), 0.0) or 0.0
    tick_value = _safe_float(spec.get("trade_tick_value"), 0.0) or 0.0
    tick_size = _safe_float(spec.get("trade_tick_size"), 0.0) or 0.0
    volume_min = _safe_float(spec.get("volume_min"), 0.0) or 0.0
    volume_max = _safe_float(spec.get("volume_max"), 0.0) or 0.0
    volume_step = _safe_float(spec.get("volume_step"), 0.0) or 0.0
    spread_to_risk = _safe_float(get("meta_signal_spread_to_risk"), None)
    spread_ok = spread_to_risk is not None and spread_to_risk <= float(max_spread_risk_fraction)

    payload = {
        **base,
        "risk_distance": risk_distance,
        "trade_tick_value": tick_value,
        "trade_tick_size": tick_size,
        "volume_min": volume_min,
        "volume_step": volume_step,
        "volume_max": volume_max,
        "spread_to_risk": spread_to_risk,
        "spread_to_risk_pct": None if spread_to_risk is None else spread_to_risk * 100.0,
        "spread_ok": bool(spread_ok),
    }
    if risk_distance <= 0 or tick_value <= 0 or tick_size <= 0 or volume_min <= 0 or volume_step <= 0:
        return {**payload, "feasibility_status": "invalid_symbol_value", "live_feasible": False}

    risk_per_lot = risk_distance / tick_size * tick_value
    min_lot_risk_money = risk_per_lot * volume_min
    payload.update(
        {
            "risk_per_lot": risk_per_lot,
            "min_lot_risk_money": min_lot_risk_money,
            "account_equity": account_equity,
        }
    )
    if account_equity is None or account_equity <= 0:
        required_equity = min_lot_risk_money / (target_risk_pct / 100.0) if target_risk_pct > 0 else None
        status = "spread_too_wide" if not spread_ok else "requires_account_equity"
        return {
            **payload,
            "minimum_account_equity_required": required_equity,
            "feasibility_status": status,
            "sizeable": None,
            "live_feasible": False,
        }

    target_risk_money = float(account_equity) * target_risk_pct / 100.0
    raw_volume = target_risk_money / risk_per_lot
    rounded_volume = _round_volume_down(min(raw_volume, volume_max), volume_step)
    min_lot_risk_pct = min_lot_risk_money / float(account_equity) * 100.0
    actual_risk_pct = None if rounded_volume < volume_min else rounded_volume * risk_per_lot / float(account_equity) * 100.0
    sizeable = rounded_volume >= volume_min
    if not sizeable and not spread_ok:
        status = "not_sizeable_and_spread"
    elif not sizeable:
        status = "not_sizeable"
    elif not spread_ok:
        status = "spread_too_wide"
    else:
        status = "live_feasible"
    return {
        **payload,
        "target_risk_money": target_risk_money,
        "raw_volume": raw_volume,
        "rounded_volume": rounded_volume,
        "actual_risk_pct": actual_risk_pct,
        "min_lot_risk_pct": min_lot_risk_pct,
        "minimum_account_equity_required": min_lot_risk_money / (target_risk_pct / 100.0) if target_risk_pct > 0 else None,
        "sizeable": bool(sizeable),
        "live_feasible": bool(sizeable and spread_ok),
        "feasibility_status": status,
    }


def _feasibility_frame(
    trades: pd.DataFrame,
    symbol_specs: pd.DataFrame,
    *,
    account_equity: float | None,
    risk_bucket_scale: float,
    max_spread_risk_fraction: float,
) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = [
        _feasibility_row(
            row,
            symbol_specs,
            account_equity=account_equity,
            risk_bucket_scale=risk_bucket_scale,
            max_spread_risk_fraction=max_spread_risk_fraction,
        )
        for _, row in trades.iterrows()
    ]
    return pd.DataFrame(rows)


def _sizeability_breakdown(feasibility: pd.DataFrame) -> pd.DataFrame:
    if feasibility.empty:
        return pd.DataFrame()
    rows = []
    for keys, group in feasibility.groupby(["asset_role", "symbol", "timeframe"], dropna=False):
        asset_role, symbol, timeframe = keys
        total = int(len(group))
        rows.append(
            {
                "asset_role": asset_role,
                "symbol": symbol,
                "timeframe": timeframe,
                "trades": total,
                "live_feasible": int(group["live_feasible"].fillna(False).sum()),
                "live_feasible_rate": float(group["live_feasible"].fillna(False).mean()) if total else 0.0,
                "not_sizeable": int(group["feasibility_status"].astype(str).str.contains("not_sizeable").sum()),
                "spread_too_wide": int(group["feasibility_status"].astype(str).str.contains("spread").sum()),
                "median_min_lot_risk_pct": _safe_float(group.get("min_lot_risk_pct", pd.Series(dtype=float)).median(), None),
                "median_required_equity": _safe_float(
                    group.get("minimum_account_equity_required", pd.Series(dtype=float)).median(), None
                ),
            }
        )
    return pd.DataFrame(rows)


def _spread_breakdown(feasibility: pd.DataFrame) -> pd.DataFrame:
    if feasibility.empty:
        return pd.DataFrame()
    rows = []
    for keys, group in feasibility.groupby(["asset_role", "symbol", "timeframe"], dropna=False):
        asset_role, symbol, timeframe = keys
        spread = pd.to_numeric(group.get("spread_to_risk", pd.Series(dtype=float)), errors="coerce")
        rows.append(
            {
                "asset_role": asset_role,
                "symbol": symbol,
                "timeframe": timeframe,
                "trades": int(len(group)),
                "avg_spread_to_risk_pct": float(spread.mean() * 100.0) if spread.notna().any() else None,
                "max_spread_to_risk_pct": float(spread.max() * 100.0) if spread.notna().any() else None,
                "spread_failures": int((~group["spread_ok"].fillna(False)).sum()),
                "spread_failure_rate": float((~group["spread_ok"].fillna(False)).mean()) if len(group) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _load_v16_control_baseline() -> dict[str, Any]:
    row = dict(FX_V16_CONTROL_FALLBACK)
    summary_path = FX_V16_CONTROL_REPORT_DIR / "summary_by_variant.csv"
    trades_path = FX_V16_CONTROL_REPORT_DIR / "trades.csv"
    if summary_path.exists():
        summary = pd.read_csv(summary_path)
        control = summary[summary["execution_variant_id"].astype(str).eq("bid_ask_buffer_0x")]
        if not control.empty:
            payload = control.iloc[0]
            row.update(
                {
                    "trades": int(payload.get("trades")),
                    "total_net_r": _safe_float(payload.get("total_net_r"), row["total_net_r"]),
                    "avg_net_r": _safe_float(payload.get("avg_net_r"), row["avg_net_r"]),
                    "profit_factor": _safe_float(payload.get("profit_factor"), row["profit_factor"]),
                }
            )
    if trades_path.exists():
        trades = pd.read_csv(trades_path)
        trades = trades[trades["execution_variant_id"].astype(str).eq("bid_ask_buffer_0x")].copy()
        if not trades.empty:
            trades["net_r"] = pd.to_numeric(trades["net_r"], errors="coerce").fillna(0.0)
            row["max_drawdown_r"] = _max_drawdown(trades["net_r"].reset_index(drop=True))
            row["return_to_drawdown"] = None if not row["max_drawdown_r"] else float(row["total_net_r"]) / float(row["max_drawdown_r"])
            row["worst_month_r"] = _worst_month(trades)
    return row


def _baseline_comparison(btc_eth_summary: pd.DataFrame) -> pd.DataFrame:
    rows = [dict(FX_V15_CANONICAL_BASELINE), _load_v16_control_baseline()]
    if not btc_eth_summary.empty:
        crypto = btc_eth_summary.iloc[0].to_dict()
        rows.append(
            {
                "comparison_row": "V21 BTC/ETH crypto transfer",
                "scope": "BTCUSD + ETHUSD only, broker crypto history, bid/ask control",
                "trades": int(crypto.get("trades", 0)),
                "total_net_r": _safe_float(crypto.get("total_net_r"), 0.0),
                "avg_net_r": _safe_float(crypto.get("avg_net_r"), 0.0),
                "profit_factor": _safe_float(crypto.get("profit_factor"), None),
                "max_drawdown_r": _safe_float(crypto.get("max_drawdown_r"), None),
                "return_to_drawdown": _safe_float(crypto.get("return_to_drawdown"), None),
                "worst_month_r": _safe_float(crypto.get("worst_month_r"), None),
                "note": "Crypto decision set. Not apples-to-apples with FX because symbols/history differ.",
            }
        )
    return pd.DataFrame(rows)


def _decision(
    decision_trades: pd.DataFrame,
    decision_feasibility: pd.DataFrame,
    symbol_timeframe_summary: pd.DataFrame,
    criteria: dict[str, Any],
    *,
    account_equity: float | None,
) -> dict[str, Any]:
    if decision_trades.empty:
        return {
            "status": "reject",
            "headline": "Reject crypto for now.",
            "detail": "BTC/ETH produced no decision-population LPFS trades on this broker history.",
            "follow_up": "Do not add crypto to live. Revisit only with more broker history or a separate crypto model.",
        }
    total = _aggregate(decision_trades).iloc[0].to_dict()
    feasible_rate = (
        float(decision_feasibility["live_feasible"].fillna(False).mean()) if not decision_feasibility.empty and account_equity else 0.0
    )
    spread_fail_rate = (
        float((~decision_feasibility["spread_ok"].fillna(False)).mean()) if not decision_feasibility.empty else 1.0
    )
    positive = symbol_timeframe_summary[
        symbol_timeframe_summary["asset_role"].eq(DECISION_ROLE)
        & (pd.to_numeric(symbol_timeframe_summary["total_net_r"], errors="coerce") > 0)
    ].copy()
    top_share = 0.0
    if not positive.empty:
        total_positive = float(positive["total_net_r"].sum())
        top_share = 0.0 if total_positive <= 0 else float(positive["total_net_r"].max() / total_positive)
    passes = (
        int(total["trades"]) >= int(criteria.get("min_trades", 30))
        and float(total["total_net_r"]) >= float(criteria.get("min_total_net_r", 20.0))
        and float(total.get("profit_factor") or 0.0) >= float(criteria.get("min_profit_factor", 1.15))
        and float(total.get("return_to_drawdown") or 0.0) >= float(criteria.get("min_return_to_drawdown", 2.0))
        and account_equity is not None
        and feasible_rate >= float(criteria.get("min_sizeable_rate", 0.8))
        and spread_fail_rate <= float(criteria.get("max_spread_fail_rate", 0.2))
        and top_share <= float(criteria.get("max_top_symbol_timeframe_net_r_share", 0.6))
    )
    if passes:
        return {
            "status": "live_candidate",
            "headline": "BTC/ETH passed the V21 research gate.",
            "detail": "The unchanged LPFS baseline looks promising enough to design a separate crypto live-support plan.",
            "follow_up": "Next: design isolated crypto live configuration, risk caps, and a demo-only dry-run before any production use.",
            "feasible_rate": feasible_rate,
            "spread_fail_rate": spread_fail_rate,
            "top_symbol_timeframe_positive_delta_share": top_share,
            **{f"summary_{key}": value for key, value in total.items()},
        }
    if float(total["total_net_r"]) > 0:
        reason = "Account equity was not provided, so sizeability remains unresolved." if account_equity is None else "One or more execution gates failed."
        return {
            "status": "research_only",
            "headline": "Crypto is research-only for now.",
            "detail": f"BTC/ETH made positive R, but it is not cleared for live design. {reason}",
            "follow_up": "Next: inspect the weak symbol/timeframe rows and rerun with account equity if sizeability is missing.",
            "feasible_rate": feasible_rate,
            "spread_fail_rate": spread_fail_rate,
            "top_symbol_timeframe_positive_delta_share": top_share,
            **{f"summary_{key}": value for key, value in total.items()},
        }
    return {
        "status": "reject",
        "headline": "Reject crypto for now.",
        "detail": "The BTC/ETH decision set did not improve enough under unchanged LPFS rules.",
        "follow_up": "Do not add crypto to live. If crypto remains a priority, test a separate crypto-specific signal model.",
        "feasible_rate": feasible_rate,
        "spread_fail_rate": spread_fail_rate,
        "top_symbol_timeframe_positive_delta_share": top_share,
        **{f"summary_{key}": value for key, value in total.items()},
    }


def _table(frame: pd.DataFrame, columns: list[str], *, limit: int | None = None) -> str:
    if frame.empty:
        return "<p class=\"muted\">No rows.</p>"
    data = frame.head(limit).copy() if limit else frame.copy()
    header = "".join(f"<th>{_escape(column)}</th>" for column in columns)
    body = []
    for _, row in data.iterrows():
        cells = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, float):
                value = _fmt_num(value, 3 if abs(value) < 1 else 2)
            cells.append(f"<td>{_escape(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    body_html = "".join(body)
    return (
        '<div class="table-scroll">'
        f'<table class="data-table"><thead><tr>{header}</tr></thead><tbody>{body_html}</tbody></table>'
        "</div>"
    )


def _verdict_badge(status: str) -> str:
    css = {"live_candidate": "good", "research_only": "warn", "reject": "bad"}.get(status, "warn")
    return f"<span class=\"badge {css}\">{_escape(status.replace('_', ' ').upper())}</span>"


def _html_report(
    run_dir: Path,
    *,
    decision: dict[str, Any],
    btc_eth_summary: pd.DataFrame,
    baseline_comparison: pd.DataFrame,
    symbol_summary: pd.DataFrame,
    timeframe_summary: pd.DataFrame,
    symbol_timeframe_summary: pd.DataFrame,
    feasibility: pd.DataFrame,
    spread: pd.DataFrame,
    sizeability: pd.DataFrame,
    symbol_specs: pd.DataFrame,
    dataset_quality: pd.DataFrame,
    run_summary: dict[str, Any],
) -> str:
    decision_row = btc_eth_summary.iloc[0].to_dict() if not btc_eth_summary.empty else {}
    symbol_table = symbol_summary.sort_values(["asset_role", "total_net_r"], ascending=[True, False])
    timeframe_table = timeframe_summary.sort_values(["asset_role", "total_net_r"], ascending=[True, False])
    symbol_tf_table = symbol_timeframe_summary.sort_values("total_net_r", ascending=False)
    decision_feasibility = feasibility[feasibility["asset_role"].eq(DECISION_ROLE)].copy()
    sol_summary = symbol_summary[symbol_summary["symbol"].eq("SOLUSD")].copy()
    account_equity = run_summary.get("account_equity")
    equity_text = "not provided" if account_equity is None else "provided for local sizeability checks"
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V21 Crypto Research - by Cody</title>
  <style>
    {dashboard_base_css()}
    .badge {{ display:inline-block; padding:4px 8px; border-radius:4px; font-size:12px; font-weight:700; margin-right:8px; }}
    .badge.good {{ background:#dcfce7; color:#166534; }}
    .badge.warn {{ background:#fef3c7; color:#92400e; }}
    .badge.bad {{ background:#fee2e2; color:#991b1b; }}
  </style>
</head>
<body>
{dashboard_header_html(
    title='LP + Force Strike V21 Crypto Research - by Cody',
    subtitle_html='BTC/ETH broker-history backtest with unchanged LPFS rules.',
    current_page='v21.html',
    section_links=[
        ('#decision', 'Decision'),
        ('#summary', 'BTC/ETH'),
        ('#baseline', 'Baseline'),
        ('#symbols', 'Symbols'),
        ('#timeframes', 'Timeframes'),
        ('#execution', 'Execution'),
        ('#spread', 'Spread'),
        ('#sol', 'SOL'),
        ('#follow-up', 'Follow-Up'),
    ],
)}
<main>
<section id="decision">
  <h2>Decision Card</h2>
  <p class="callout">{_verdict_badge(str(decision.get('status', 'research_only')))} <strong>{_escape(decision.get('headline'))}</strong> {_escape(decision.get('detail'))}</p>
  <div class="metric-grid">
    <div class="metric-card"><span>Total R</span><strong>{_fmt_num(decision_row.get('total_net_r'))}</strong></div>
    <div class="metric-card"><span>Trades</span><strong>{_fmt_int(decision_row.get('trades'))}</strong></div>
    <div class="metric-card"><span>Profit Factor</span><strong>{_fmt_num(decision_row.get('profit_factor'))}</strong></div>
    <div class="metric-card"><span>Return / DD</span><strong>{_fmt_num(decision_row.get('return_to_drawdown'))}</strong></div>
    <div class="metric-card"><span>Max DD (R)</span><strong>{_fmt_num(decision_row.get('max_drawdown_r'))}</strong></div>
    <div class="metric-card"><span>Worst Month (R)</span><strong>{_fmt_num(decision_row.get('worst_month_r'))}</strong></div>
  </div>
  <p class="muted">Decision set: BTCUSD + ETHUSD. SOLUSD is short-history exploratory only. Account equity for sizeability: {equity_text}.</p>
</section>
<section id="summary">
  <h2>BTC/ETH Result Summary</h2>
  {_table(btc_eth_summary, ['asset_role', 'trades', 'wins', 'losses', 'win_rate', 'total_net_r', 'profit_factor', 'max_drawdown_r', 'return_to_drawdown', 'worst_month_r'])}
</section>
<section id="baseline">
  <h2>Baseline Comparison</h2>
  <p class="callout">This is the direct context for V21: current FX baseline performance is much larger and more proven. V21 BTC/ETH is positive, but far smaller in sample and not yet execution-cleared.</p>
  {_table(baseline_comparison, ['comparison_row', 'scope', 'trades', 'total_net_r', 'avg_net_r', 'profit_factor', 'max_drawdown_r', 'return_to_drawdown', 'worst_month_r', 'note'])}
</section>
<section id="symbols">
  <h2>Symbol Verdicts</h2>
  {_table(symbol_table, ['asset_role', 'symbol', 'trades', 'win_rate', 'total_net_r', 'profit_factor', 'max_drawdown_r', 'return_to_drawdown'])}
</section>
<section id="timeframes">
  <h2>Timeframe Breakdown</h2>
  {_table(timeframe_table, ['asset_role', 'timeframe', 'trades', 'win_rate', 'total_net_r', 'profit_factor', 'max_drawdown_r', 'return_to_drawdown'])}
  <h3>Symbol / Timeframe Edge Map</h3>
  {_table(symbol_tf_table, ['asset_role', 'symbol', 'timeframe', 'trades', 'total_net_r', 'profit_factor', 'max_drawdown_r', 'return_to_drawdown'], limit=20)}
</section>
<section id="execution">
  <h2>Execution Feasibility</h2>
  <p class="callout">This answers whether the backtested crypto setups are actually tradeable at current risk settings, especially with 0.01 minimum volume.</p>
  {_table(sizeability.sort_values(['asset_role', 'symbol', 'timeframe']), ['asset_role', 'symbol', 'timeframe', 'trades', 'live_feasible', 'live_feasible_rate', 'not_sizeable', 'spread_too_wide', 'median_min_lot_risk_pct', 'median_required_equity'])}
</section>
<section id="spread">
  <h2>Spread Risk</h2>
  {_table(spread.sort_values('max_spread_to_risk_pct', ascending=False), ['asset_role', 'symbol', 'timeframe', 'trades', 'avg_spread_to_risk_pct', 'max_spread_to_risk_pct', 'spread_failures', 'spread_failure_rate'], limit=20)}
</section>
<section id="sol">
  <h2>SOL Appendix</h2>
  <p class="callout">SOLUSD is not used in the V21 decision because broker history starts on 2025-04-17. Treat it as awareness only.</p>
  {_table(sol_summary, ['asset_role', 'symbol', 'trades', 'win_rate', 'total_net_r', 'profit_factor', 'max_drawdown_r', 'return_to_drawdown'])}
</section>
<section id="data">
  <h2>Data And Broker Specs</h2>
  <h3>Symbol Specs</h3>
  {_table(symbol_specs, ['symbol', 'digits', 'point', 'spread_points', 'trade_tick_value', 'trade_tick_size', 'volume_min', 'volume_step', 'volume_max', 'trade_contract_size', 'trade_stops_level', 'trade_freeze_level'])}
  <h3>Data Quality Snapshot</h3>
  {_table(dataset_quality.sort_values(['symbol', 'timeframe']), ['symbol', 'timeframe', 'status', 'rows', 'coverage_start_utc', 'coverage_end_utc', 'large_gap_count', 'suspicious_bar_count'], limit=30)}
</section>
<section id="follow-up">
  <h2>Follow-Up Section</h2>
  <p class="callout"><strong>{_escape(decision.get('follow_up'))}</strong></p>
  <p class="muted">Artifacts live under <code>{_escape(run_dir)}</code>. The current FX live strategy, VPS runtime, and TradingView scripts are not part of this research run.</p>
</section>
{metric_glossary_html()}
</main>
<footer>Generated from <code>{_escape(run_dir)}</code>. Research-only; no production execution modules are imported.</footer>
</body>
</html>
"""
    return body


def _run(
    config_path: Path,
    *,
    symbol_override: list[str] | None = None,
    timeframe_override: list[str] | None = None,
    output_dir: Path | None = None,
    docs_output: Path | None = None,
    account_equity_override: float | None = None,
) -> int:
    config = _read_json(REPO_ROOT / config_path)
    dataset_config = load_dataset_config(REPO_ROOT / str(config["dataset_config"]))
    decision_symbols = {str(symbol).upper() for symbol in config.get("decision_symbols", ["BTCUSD", "ETHUSD"])}
    exploratory_symbols = {str(symbol).upper() for symbol in config.get("exploratory_symbols", ["SOLUSD"])}
    symbols = symbol_override if symbol_override is not None else list(dataset_config.symbols)
    timeframes = _selected_timeframes(dataset_config.timeframes, config, timeframe_override)
    role_map = {symbol: _asset_role(symbol, decision_symbols, exploratory_symbols) for symbol in symbols}
    candidate = _make_candidate(config)
    variant = ExecutionRealismVariant("bid_ask", stop_buffer_spread_mult=0.0)
    pivot_strength = int(config.get("pivot_strength", 3))
    cost_config = _cost_config(config)
    account_equity = account_equity_override
    if account_equity is None:
        config_equity = config.get("account_equity")
        account_equity = None if config_equity in (None, "") else float(config_equity)

    run_dir = output_dir or (
        REPO_ROOT
        / str(config.get("report_root", "reports/strategies/lp_force_strike_experiment_v21_crypto_btc_eth"))
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
                result = run_lp_force_strike_execution_realism_on_frame(
                    frame,
                    symbol=symbol,
                    timeframe=timeframe,
                    candidate=candidate,
                    variants=[variant],
                    pivot_strength=pivot_strength,
                    max_bars_from_lp_break=int(config.get("max_bars_from_lp_break", 6)),
                    atr_period=int(config.get("atr_period", 14)),
                    max_entry_wait_bars=int(config.get("max_entry_wait_bars", 6)),
                    costs=cost_config,
                )
                role = role_map.get(symbol, "excluded")
                all_signal_rows.extend(
                    {**_signal_row(symbol, timeframe, pivot_strength, signal), "asset_role": role} for signal in result.signals
                )
                all_trade_rows.extend(_trade_row(trade, pivot_strength=pivot_strength, role_map=role_map) for trade in result.trades)
                all_skipped_rows.extend(
                    _skipped_row(skipped, candidate, pivot_strength=pivot_strength, role_map=role_map) for skipped in result.skipped
                )
                dataset_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "asset_role": role,
                        "status": "ok",
                        "rows": int(len(frame)),
                        "signals": int(len(result.signals)),
                        "trades": int(len(result.trades)),
                        "skipped": int(len(result.skipped)),
                    }
                )
                print(f"{symbol} {timeframe}: rows={len(frame)} signals={len(result.signals)} trades={len(result.trades)} skipped={len(result.skipped)}")
            except Exception as exc:
                dataset_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "asset_role": role_map.get(symbol, "excluded"),
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                print(f"{symbol} {timeframe}: failed={exc}")

    trades = pd.DataFrame(all_trade_rows)
    skipped = pd.DataFrame(all_skipped_rows)
    signals = pd.DataFrame(all_signal_rows)
    datasets = pd.DataFrame(dataset_rows)
    if trades.empty:
        raise ValueError("V21 produced no trades.")

    symbol_specs = _symbol_specs(dataset_config)
    feasibility = _feasibility_frame(
        trades,
        symbol_specs,
        account_equity=account_equity,
        risk_bucket_scale=float(config.get("risk_bucket_scale", 0.05)),
        max_spread_risk_fraction=float(config.get("max_spread_risk_fraction", 0.1)),
    )
    sizeability = _sizeability_breakdown(feasibility)
    spread = _spread_breakdown(feasibility)
    coverage = pd.DataFrame(dataset_coverage_report(dataset_config))
    data_quality_rows, large_gap_rows, suspicious_rows = _dataset_checks(dataset_config)
    weekly_rows, weekly_mismatch_rows = _weekly_consistency(dataset_config)
    data_quality = pd.DataFrame(data_quality_rows)
    quality_verdict = _verdict(data_quality_rows, large_gap_rows, suspicious_rows, weekly_rows, weekly_mismatch_rows)

    summary_all = _aggregate(trades)
    btc_eth_trades = trades[trades["asset_role"].eq(DECISION_ROLE)].copy()
    btc_eth_summary = _aggregate(btc_eth_trades, ["asset_role"])
    baseline_comparison = _baseline_comparison(btc_eth_summary)
    symbol_summary = _aggregate(trades, ["asset_role", "symbol"])
    timeframe_summary = _aggregate(trades, ["asset_role", "timeframe"])
    symbol_timeframe_summary = _aggregate(trades, ["asset_role", "symbol", "timeframe"])
    decision = _decision(
        btc_eth_trades,
        feasibility[feasibility["asset_role"].eq(DECISION_ROLE)].copy(),
        symbol_timeframe_summary,
        config.get("decision_criteria", {}),
        account_equity=account_equity,
    )
    run_summary = {
        "run_dir": str(run_dir),
        "experiment_name": config.get("experiment_name"),
        "dataset_config": config["dataset_config"],
        "symbols": symbols,
        "decision_symbols": sorted(decision_symbols),
        "exploratory_symbols": sorted(exploratory_symbols),
        "timeframes": timeframes,
        "pivot_strength": pivot_strength,
        "candidate": asdict(candidate),
        "execution_variant_id": CONTROL_VARIANT_ID,
        "risk_bucket_scale": float(config.get("risk_bucket_scale", 0.05)),
        "account_equity": account_equity,
        "datasets_failed": int(datasets["status"].ne("ok").sum()) if not datasets.empty else 0,
        "signals": int(len(signals)),
        "trades": int(len(trades)),
        "decision_trades": int(len(btc_eth_trades)),
        "skipped_trades": int(len(skipped)),
        "data_quality_verdict": quality_verdict,
        "decision": decision,
    }

    _write_json(run_dir / "run_config.json", {"config_path": str(config_path), "config": config})
    _write_json(run_dir / "run_summary.json", run_summary)
    _write_json(run_dir / "data_quality_verdict.json", quality_verdict)
    _write_json(run_dir / "pull_results.json", dataset_rows)
    _write_csv(run_dir / "datasets.csv", datasets)
    _write_csv(run_dir / "coverage_report.csv", coverage)
    _write_csv(run_dir / "data_quality_report.csv", data_quality)
    _write_csv(run_dir / "large_gaps.csv", pd.DataFrame(large_gap_rows))
    _write_csv(run_dir / "suspicious_bars.csv", pd.DataFrame(suspicious_rows))
    _write_csv(run_dir / "symbol_specs.csv", symbol_specs)
    _write_csv(run_dir / "signals.csv", signals)
    _write_csv(run_dir / "trades.csv", trades)
    _write_csv(run_dir / "skipped_trades.csv", skipped)
    _write_csv(run_dir / "summary_all.csv", summary_all)
    _write_csv(run_dir / "summary_btc_eth.csv", btc_eth_summary)
    _write_csv(run_dir / "baseline_comparison.csv", baseline_comparison)
    _write_csv(run_dir / "summary_by_symbol.csv", symbol_summary)
    _write_csv(run_dir / "summary_by_timeframe.csv", timeframe_summary)
    _write_csv(run_dir / "summary_by_symbol_timeframe.csv", symbol_timeframe_summary)
    _write_csv(run_dir / "execution_feasibility.csv", feasibility)
    _write_csv(run_dir / "spread_to_risk_breakdown.csv", spread)
    _write_csv(run_dir / "sizeability_breakdown.csv", sizeability)

    html_text = "\n".join(
        line.rstrip()
        for line in _html_report(
            run_dir,
            decision=decision,
            btc_eth_summary=btc_eth_summary,
            baseline_comparison=baseline_comparison,
            symbol_summary=symbol_summary,
            timeframe_summary=timeframe_summary,
            symbol_timeframe_summary=symbol_timeframe_summary,
            feasibility=feasibility,
            spread=spread,
            sizeability=sizeability,
            symbol_specs=symbol_specs,
            dataset_quality=data_quality,
            run_summary=run_summary,
        ).splitlines()
    ) + "\n"
    (run_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    if docs_output is not None:
        target = REPO_ROOT / docs_output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True, default=str))
    return 1 if run_summary["datasets_failed"] else 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    run_summary = _read_json(run_dir / "run_summary.json")
    decision = run_summary["decision"]
    html_text = "\n".join(
        line.rstrip()
        for line in _html_report(
            run_dir,
            decision=decision,
            btc_eth_summary=pd.read_csv(run_dir / "summary_btc_eth.csv"),
            baseline_comparison=(
                pd.read_csv(run_dir / "baseline_comparison.csv")
                if (run_dir / "baseline_comparison.csv").exists()
                else _baseline_comparison(pd.read_csv(run_dir / "summary_btc_eth.csv"))
            ),
            symbol_summary=pd.read_csv(run_dir / "summary_by_symbol.csv"),
            timeframe_summary=pd.read_csv(run_dir / "summary_by_timeframe.csv"),
            symbol_timeframe_summary=pd.read_csv(run_dir / "summary_by_symbol_timeframe.csv"),
            feasibility=pd.read_csv(run_dir / "execution_feasibility.csv"),
            spread=pd.read_csv(run_dir / "spread_to_risk_breakdown.csv"),
            sizeability=pd.read_csv(run_dir / "sizeability_breakdown.csv"),
            symbol_specs=pd.read_csv(run_dir / "symbol_specs.csv"),
            dataset_quality=pd.read_csv(run_dir / "data_quality_report.csv"),
            run_summary=run_summary,
        ).splitlines()
    ) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LPFS V21 crypto BTC/ETH broker-history backtest.")
    parser.add_argument(
        "--config",
        default="configs/strategies/lp_force_strike_experiment_v21_crypto_btc_eth.json",
        help="Path to V21 crypto config JSON.",
    )
    parser.add_argument("--symbols", help="Optional comma-separated symbol override.")
    parser.add_argument("--timeframes", help="Optional comma-separated timeframe override.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v21.html.")
    parser.add_argument("--render-run-dir", help="Existing V21 run directory to render without rerunning.")
    parser.add_argument("--account-equity", type=float, help="Optional current account equity for sizeability gates.")
    args = parser.parse_args()
    if args.render_run_dir:
        if args.docs_output is None:
            raise SystemExit("--docs-output is required with --render-run-dir")
        return _render_existing(Path(args.render_run_dir), Path(args.docs_output))
    return _run(
        Path(args.config),
        symbol_override=_parse_csv_arg(args.symbols),
        timeframe_override=_parse_csv_arg(args.timeframes),
        output_dir=None if args.output_dir is None else Path(args.output_dir),
        docs_output=None if args.docs_output is None else Path(args.docs_output),
        account_equity_override=args.account_equity,
    )


if __name__ == "__main__":
    raise SystemExit(main())
