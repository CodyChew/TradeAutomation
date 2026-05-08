from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import html
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from lp_force_strike_dashboard_metadata import (
    dashboard_base_css,
    dashboard_header_html,
    metric_glossary_html,
)
from run_lp_force_strike_risk_sizing_experiment import (
    _max_drawdown_from_curve,
    apply_risk_schedule,
    filter_baseline_trades,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "strategies" / "lpfs_ftmo_challenge_frontier"
DEFAULT_DOCS_OUTPUT = REPO_ROOT / "docs" / "ftmo_challenge_profiles.html"
DEFAULT_TRADES_PATH = (
    REPO_ROOT
    / "reports"
    / "strategies"
    / "lp_force_strike_account_commission_sensitivity"
    / "20260505_165121"
    / "ftmo_baseline_commission_adjusted_trades.csv"
)
DEFAULT_DATA_ROOT = REPO_ROOT / "data" / "raw" / "ftmo" / "forex"
DEFAULT_BUCKET_CONFIG = REPO_ROOT / "configs" / "strategies" / "lp_force_strike_experiment_v15_bucket_sensitivity.json"
DEFAULT_VARIANT = "exclude_lp_pivot_inside_fs"
ACCOUNT_SIZE = 100_000.0
MAX_DAILY_LOSS_PCT = 5.0
MAX_DAILY_LOSS_WARNING_PCT = 4.5
MAX_LOSS_PCT = 10.0
MAX_LOSS_WARNING_PCT = 9.5
SPREAD_MATERIAL_RETURN_RATIO = 0.85


@dataclass(frozen=True)
class RiskProfile:
    lower_risk_pct: float
    middle_risk_pct: float
    w1_risk_pct: float

    @property
    def profile_id(self) -> str:
        return (
            f"ltf{_pct_token(self.lower_risk_pct)}_"
            f"h12d1{_pct_token(self.middle_risk_pct)}_"
            f"w1{_pct_token(self.w1_risk_pct)}"
        )

    @property
    def label(self) -> str:
        return (
            f"H4/H8 {_fmt_plain_pct(self.lower_risk_pct)} / "
            f"H12/D1 {_fmt_plain_pct(self.middle_risk_pct)} / "
            f"W1 {_fmt_plain_pct(self.w1_risk_pct)}"
        )

    def schedule(self) -> dict[str, Any]:
        return {
            "schedule_id": self.profile_id,
            "label": self.label,
            "kind": "timeframe",
            "risk_by_timeframe": {
                "H4": self.lower_risk_pct,
                "H8": self.lower_risk_pct,
                "H12": self.middle_risk_pct,
                "D1": self.middle_risk_pct,
                "W1": self.w1_risk_pct,
            },
        }


def _pct_token(value: float) -> str:
    return f"{float(value):.3f}".replace(".", "p")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _escape(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return html.escape(str(value))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _fmt_plain_pct(value: Any, digits: int = 3) -> str:
    number = _to_float(value)
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _fmt_money_from_pct(value: Any, account_size: float = ACCOUNT_SIZE) -> str:
    amount = _to_float(value) / 100.0 * account_size
    return f"${amount:,.0f}"


def _fmt_num(value: Any, digits: int = 2) -> str:
    return f"{_to_float(value):,.{digits}f}"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    return f"{_to_float(value):.{digits}f}%"


def _table(headers: list[str], rows: list[list[Any]], *, class_name: str = "data-table") -> str:
    thead = "".join(f"<th>{_escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        cells = []
        for value in row:
            if isinstance(value, tuple):
                display, cell_class = value
                cells.append(f'<td class="{_escape(cell_class)}">{display}</td>')
            else:
                cells.append(f"<td>{value}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f'<div class="table-scroll"><table class="{_escape(class_name)}">'
        f"<thead><tr>{thead}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def frontier_risk_profiles(
    *,
    lower_values: list[float] | None = None,
    middle_values: list[float] | None = None,
    w1_values: list[float] | None = None,
) -> list[RiskProfile]:
    lower = lower_values or [0.10, 0.125, 0.15, 0.175, 0.20, 0.225, 0.25]
    middle = middle_values or [0.20, 0.225, 0.25, 0.275, 0.30, 0.325]
    w1 = w1_values or [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
    return [RiskProfile(l, m, w) for l in lower for m in middle for w in w1]


def spread_gate_pass(spread_to_risk: Any, *, max_spread_risk_fraction: float = 0.10) -> bool:
    try:
        value = float(spread_to_risk)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value <= max_spread_risk_fraction


def load_ftmo_trades(path: Path, *, variant: str, bucket_config: dict[str, Any]) -> pd.DataFrame:
    trades = pd.read_csv(path)
    trades = trades[trades["separation_variant_id"].astype(str) == variant].copy()
    trades["net_r"] = pd.to_numeric(trades["commission_adjusted_net_r"], errors="coerce").fillna(0.0)
    return filter_baseline_trades(trades, bucket_config)


def _manifest_point(manifest_path: Path) -> float:
    payload = _read_json(manifest_path)
    return float((payload.get("symbol_metadata") or {}).get("point", 0.0))


def add_signal_spread_gate(
    trades: pd.DataFrame,
    *,
    data_root: Path,
    max_spread_risk_fraction: float,
) -> pd.DataFrame:
    data = trades.copy()
    data["signal_spread_points"] = pd.NA
    data["signal_spread_price"] = pd.NA
    data["signal_spread_to_risk"] = pd.NA
    data["initial_spread_gate_pass"] = False
    if data.empty:
        return data

    for (symbol, timeframe), group in data.groupby(["symbol", "timeframe"], sort=True):
        symbol_text = str(symbol)
        timeframe_text = str(timeframe)
        parquet_path = data_root / symbol_text / timeframe_text / f"{symbol_text}_{timeframe_text}.parquet"
        manifest_path = data_root / symbol_text / timeframe_text / "manifest.json"
        if not parquet_path.exists() or not manifest_path.exists():
            continue
        point = _manifest_point(manifest_path)
        if point <= 0:
            continue
        bars = pd.read_parquet(parquet_path, columns=["spread_points"])
        signal_indices = pd.to_numeric(group["signal_index"], errors="coerce").astype("Int64")
        valid = signal_indices.notna() & (signal_indices >= 0) & (signal_indices < len(bars))
        if not valid.any():
            continue
        target_indexes = group.index[valid]
        bar_indexes = signal_indices[valid].astype(int).to_numpy()
        spread_points = bars.iloc[bar_indexes]["spread_points"].astype(float).to_numpy()
        spread_price = spread_points * point
        risk_distance = pd.to_numeric(data.loc[target_indexes, "risk_distance"], errors="coerce").astype(float).to_numpy()
        spread_to_risk = [
            float(spread / risk) if math.isfinite(float(risk)) and float(risk) > 0 else math.nan
            for spread, risk in zip(spread_price, risk_distance)
        ]
        data.loc[target_indexes, "signal_spread_points"] = spread_points
        data.loc[target_indexes, "signal_spread_price"] = spread_price
        data.loc[target_indexes, "signal_spread_to_risk"] = spread_to_risk
        data.loc[target_indexes, "initial_spread_gate_pass"] = [
            spread_gate_pass(value, max_spread_risk_fraction=max_spread_risk_fraction)
            for value in spread_to_risk
        ]

    return data


def risk_reserved_event_curve(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "time_utc",
                "realized_pct",
                "open_risk_pct",
                "equity_reserved_pct",
                "day_start_realized_pct",
            ]
        )

    events: list[dict[str, Any]] = []
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
    events.sort(key=lambda item: (item["time_utc"], item["sort_order"]))

    realized = 0.0
    open_risk = 0.0
    current_day = None
    day_start_realized = 0.0
    rows: list[dict[str, Any]] = []
    for event in events:
        event_time = pd.Timestamp(event["time_utc"])
        event_day = event_time.date()
        if current_day != event_day:
            current_day = event_day
            day_start_realized = realized
        realized += float(event["pnl_delta_pct"])
        open_risk += float(event["risk_delta_pct"])
        if abs(open_risk) < 1e-12:
            open_risk = 0.0
        rows.append(
            {
                "time_utc": event_time,
                "realized_pct": realized,
                "open_risk_pct": open_risk,
                "equity_reserved_pct": realized - open_risk,
                "day_start_realized_pct": day_start_realized,
            }
        )
    return pd.DataFrame(rows)


def realized_equity_curve_from_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["time_utc", "equity_pct"])
    data = trades.sort_values(["exit_time_utc", "entry_time_utc", "symbol", "timeframe"]).copy()
    data["equity_pct"] = data["pnl_pct"].cumsum()
    return data[["exit_time_utc", "equity_pct"]].rename(columns={"exit_time_utc": "time_utc"}).reset_index(drop=True)


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
        "max_reserved_open_risk_time_utc": None if max_risk_time is None else pd.Timestamp(max_risk_time).isoformat(),
        "max_new_trades_same_time": int(trades.groupby("entry_time_utc").size().max()),
    }


def daily_loss_stress(curve: pd.DataFrame) -> pd.DataFrame:
    if curve.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "day_start_realized_pct",
                "min_reserved_equity_pct",
                "daily_loss_stress_pct",
                "daily_loss_status",
            ]
        )
    data = curve.copy()
    data["date"] = pd.to_datetime(data["time_utc"], utc=True).dt.strftime("%Y-%m-%d")
    grouped = data.groupby("date", sort=True)
    rows = []
    for date, group in grouped:
        start = float(group["day_start_realized_pct"].iloc[0])
        minimum = float(group["equity_reserved_pct"].min())
        stress = max(0.0, start - minimum)
        rows.append(
            {
                "date": date,
                "day_start_realized_pct": start,
                "min_reserved_equity_pct": minimum,
                "daily_loss_stress_pct": stress,
                "daily_loss_status": classify_limit(
                    stress,
                    warning_threshold=MAX_DAILY_LOSS_WARNING_PCT,
                    breach_threshold=MAX_DAILY_LOSS_PCT,
                ),
            }
        )
    return pd.DataFrame(rows)


def classify_limit(value: Any, *, warning_threshold: float, breach_threshold: float) -> str:
    number = _to_float(value, default=0.0)
    if number >= breach_threshold:
        return "breach"
    if number >= warning_threshold:
        return "warning"
    return "pass"


def period_distribution(trades: pd.DataFrame, period: str) -> dict[str, Any]:
    if trades.empty:
        return {
            f"{period}_periods": 0,
            f"positive_{period}s": 0,
            f"positive_{period}_rate": 0.0,
            f"negative_{period}s": 0,
            f"worst_{period}": None,
            f"worst_{period}_pct": 0.0,
            f"avg_{period}_pct": 0.0,
            f"median_{period}_pct": 0.0,
            f"p10_{period}_pct": 0.0,
            f"p25_{period}_pct": 0.0,
            f"p75_{period}_pct": 0.0,
            f"p90_{period}_pct": 0.0,
        }
    exit_time = pd.to_datetime(trades["exit_time_utc"], utc=True).dt.tz_convert(None)
    if period == "week":
        keys = exit_time.dt.to_period("W").astype(str)
    elif period == "month":
        keys = exit_time.dt.strftime("%Y-%m")
    else:
        raise ValueError(f"Unsupported period: {period}")
    returns = trades.groupby(keys)["pnl_pct"].sum()
    return {
        f"{period}_periods": int(len(returns)),
        f"positive_{period}s": int((returns > 0).sum()),
        f"positive_{period}_rate": float((returns > 0).mean()) if len(returns) else 0.0,
        f"negative_{period}s": int((returns < 0).sum()),
        f"worst_{period}": None if returns.empty else str(returns.idxmin()),
        f"worst_{period}_pct": float(returns.min()) if len(returns) else 0.0,
        f"avg_{period}_pct": float(returns.mean()) if len(returns) else 0.0,
        f"median_{period}_pct": float(returns.median()) if len(returns) else 0.0,
        f"p10_{period}_pct": float(returns.quantile(0.10)) if len(returns) else 0.0,
        f"p25_{period}_pct": float(returns.quantile(0.25)) if len(returns) else 0.0,
        f"p75_{period}_pct": float(returns.quantile(0.75)) if len(returns) else 0.0,
        f"p90_{period}_pct": float(returns.quantile(0.90)) if len(returns) else 0.0,
    }


def analyze_challenge_profile(trades: pd.DataFrame, profile: RiskProfile, *, mode: str) -> tuple[dict[str, Any], pd.DataFrame]:
    schedule = profile.schedule()
    data = apply_risk_schedule(trades, schedule)
    realized_curve = realized_equity_curve_from_trades(data)
    curve = risk_reserved_event_curve(data)
    realized_dd = _max_drawdown_from_curve(realized_curve, "equity_pct")
    reserved_dd = _max_drawdown_from_curve(curve, "equity_reserved_pct")
    daily = daily_loss_stress(curve)
    total_return = float(data["pnl_pct"].sum()) if not data.empty else 0.0
    max_reserved_dd = float(reserved_dd["max_drawdown_pct"])
    max_daily_stress = float(daily["daily_loss_stress_pct"].max()) if not daily.empty else 0.0
    max_daily_rows = daily[daily["daily_loss_stress_pct"].eq(max_daily_stress)] if not daily.empty else daily
    row = {
        "schedule_id": profile.profile_id,
        "schedule_label": profile.label,
        "schedule_kind": "timeframe",
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
        "profile_id": profile.profile_id,
        "profile_label": profile.label,
        "mode": mode,
        "lower_risk_pct": profile.lower_risk_pct,
        "middle_risk_pct": profile.middle_risk_pct,
        "w1_risk_pct": profile.w1_risk_pct,
        "max_daily_loss_stress_pct": max_daily_stress,
        "max_daily_loss_date": None if max_daily_rows.empty else str(max_daily_rows.iloc[0]["date"]),
        "daily_loss_breach_days": int((daily["daily_loss_status"] == "breach").sum()) if not daily.empty else 0,
        "daily_loss_warning_days": int((daily["daily_loss_status"] == "warning").sum()) if not daily.empty else 0,
        "daily_loss_status": classify_limit(
            max_daily_stress,
            warning_threshold=MAX_DAILY_LOSS_WARNING_PCT,
            breach_threshold=MAX_DAILY_LOSS_PCT,
        ),
        "max_loss_status": classify_limit(
            max_reserved_dd,
            warning_threshold=MAX_LOSS_WARNING_PCT,
            breach_threshold=MAX_LOSS_PCT,
        ),
    }
    row.update(exposure_metrics(data))
    row["passes_ftmo_breach_checks"] = bool(
        row["daily_loss_breach_days"] == 0 and row["reserved_max_drawdown_pct"] < MAX_LOSS_PCT
    )
    row["passes_ftmo_warning_checks"] = bool(
        row["daily_loss_warning_days"] == 0
        and row["daily_loss_breach_days"] == 0
        and row["reserved_max_drawdown_pct"] < MAX_LOSS_WARNING_PCT
    )
    row.update(period_distribution(data, "week"))
    row.update(period_distribution(data, "month"))
    return row, daily.assign(profile_id=profile.profile_id, mode=mode)


def _spread_impact_rows(trades: pd.DataFrame, *, max_spread_risk_fraction: float) -> pd.DataFrame:
    data = trades.copy()
    data["signal_spread_to_risk"] = pd.to_numeric(data["signal_spread_to_risk"], errors="coerce")
    data["initial_spread_gate_pass"] = data["signal_spread_to_risk"].map(
        lambda value: spread_gate_pass(value, max_spread_risk_fraction=max_spread_risk_fraction)
    )
    group_cols = ["symbol", "timeframe"]
    rows = []
    for keys, group in data.groupby(group_cols, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        spread = group["signal_spread_to_risk"].dropna()
        rows.append(
            {
                "symbol": keys[0],
                "timeframe": keys[1],
                "trades": int(len(group)),
                "initial_spread_passes": int(group["initial_spread_gate_pass"].sum()),
                "initial_spread_failures": int((~group["initial_spread_gate_pass"]).sum()),
                "initial_spread_failure_rate": float((~group["initial_spread_gate_pass"]).mean()) if len(group) else 0.0,
                "avg_spread_to_risk_pct": float(spread.mean() * 100.0) if not spread.empty else None,
                "p90_spread_to_risk_pct": float(spread.quantile(0.90) * 100.0) if not spread.empty else None,
                "max_spread_to_risk_pct": float(spread.max() * 100.0) if not spread.empty else None,
            }
        )
    total = {
        "symbol": "ALL",
        "timeframe": "ALL",
        "trades": int(len(data)),
        "initial_spread_passes": int(data["initial_spread_gate_pass"].sum()),
        "initial_spread_failures": int((~data["initial_spread_gate_pass"]).sum()),
        "initial_spread_failure_rate": float((~data["initial_spread_gate_pass"]).mean()) if len(data) else 0.0,
        "avg_spread_to_risk_pct": float(data["signal_spread_to_risk"].mean() * 100.0),
        "p90_spread_to_risk_pct": float(data["signal_spread_to_risk"].quantile(0.90) * 100.0),
        "max_spread_to_risk_pct": float(data["signal_spread_to_risk"].max() * 100.0),
    }
    return pd.concat([pd.DataFrame([total]), pd.DataFrame(rows)], ignore_index=True)


def build_frontier(
    trades: pd.DataFrame,
    profiles: list[RiskProfile],
    *,
    max_spread_risk_fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_rows = []
    gated_rows = []
    daily_frames = []
    gated_trades = trades[trades["initial_spread_gate_pass"].astype(bool)].copy()
    for profile in profiles:
        base_row, base_daily = analyze_challenge_profile(trades, profile, mode="base")
        gated_row, gated_daily = analyze_challenge_profile(gated_trades, profile, mode="initial_spread_gated")
        base_rows.append(base_row)
        gated_rows.append(gated_row)
        daily_frames.extend([base_daily, gated_daily])
    summary = pd.DataFrame(base_rows + gated_rows)
    summary = _attach_spread_agreement(summary)
    daily = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    spread = _spread_impact_rows(trades, max_spread_risk_fraction=max_spread_risk_fraction)
    return summary.sort_values(["mode", "total_return_pct"], ascending=[True, False]).reset_index(drop=True), daily, spread


def _attach_spread_agreement(summary: pd.DataFrame) -> pd.DataFrame:
    data = summary.copy()
    base = data[data["mode"] == "base"].set_index("profile_id")
    gated = data[data["mode"] == "initial_spread_gated"].set_index("profile_id")
    ratios: dict[str, float] = {}
    conflicts: dict[str, bool] = {}
    for profile_id, base_row in base.iterrows():
        gated_row = gated.loc[profile_id]
        base_return = float(base_row["total_return_pct"])
        gated_return = float(gated_row["total_return_pct"])
        ratio = 0.0 if base_return <= 0 else gated_return / base_return
        ratios[profile_id] = ratio
        conflicts[profile_id] = bool(
            ratio < SPREAD_MATERIAL_RETURN_RATIO
            or (bool(base_row["passes_ftmo_breach_checks"]) and not bool(gated_row["passes_ftmo_breach_checks"]))
        )
    data["spread_gated_return_ratio"] = data["profile_id"].map(ratios).fillna(0.0)
    data["spread_material_conflict"] = data["profile_id"].map(conflicts).fillna(True)
    return data


def select_candidate_profiles(summary: pd.DataFrame, *, limit: int = 20) -> pd.DataFrame:
    base = summary[summary["mode"] == "base"].copy()
    eligible = base[
        base["passes_ftmo_breach_checks"].astype(bool)
        & ~base["spread_material_conflict"].astype(bool)
    ].copy()
    if eligible.empty:
        eligible = base.copy()

    fresh_pool = eligible[eligible["passes_ftmo_warning_checks"].astype(bool)].copy()
    if fresh_pool.empty:
        fresh_pool = eligible.copy()
    fresh = fresh_pool.sort_values(
        ["total_return_pct", "return_to_reserved_drawdown"],
        ascending=[False, False],
    ).head(1)
    aggressive = eligible.sort_values(
        ["total_return_pct", "return_to_reserved_drawdown"],
        ascending=[False, False],
    ).head(1)
    efficient = eligible.sort_values(
        ["return_to_reserved_drawdown", "total_return_pct"],
        ascending=[False, False],
    ).head(1)
    watchlist = eligible.sort_values(
        ["total_return_pct", "return_to_reserved_drawdown"],
        ascending=[False, False],
    ).head(limit)

    selected = pd.concat([fresh, aggressive, efficient, watchlist], ignore_index=True).drop_duplicates("profile_id")
    role_by_id: dict[str, list[str]] = {}
    if not fresh.empty:
        role_by_id.setdefault(str(fresh.iloc[0]["profile_id"]), []).append("fresh_challenge")
    if not aggressive.empty:
        role_by_id.setdefault(str(aggressive.iloc[0]["profile_id"]), []).append("aggressive_funded")
    if not efficient.empty:
        role_by_id.setdefault(str(efficient.iloc[0]["profile_id"]), []).append("efficient")
    selected["selection_role"] = selected["profile_id"].map(lambda value: ", ".join(role_by_id.get(str(value), ["watchlist"])))
    return selected.sort_values(["selection_role", "total_return_pct"], ascending=[True, False]).reset_index(drop=True)


def challenge_window_outcomes(
    trades: pd.DataFrame,
    profiles: list[RiskProfile],
    *,
    max_window_days: int = 365,
    start_frequency: str = "7D",
) -> pd.DataFrame:
    if trades.empty or not profiles:
        return pd.DataFrame()
    min_start = pd.to_datetime(trades["entry_time_utc"], utc=True).min().floor("D")
    max_start = pd.to_datetime(trades["entry_time_utc"], utc=True).max().floor("D")
    starts = pd.date_range(min_start, max_start, freq=start_frequency, tz="UTC")
    rows = []
    targets = [("challenge", 10.0), ("verification", 5.0)]
    for profile in profiles:
        data = apply_risk_schedule(trades, profile.schedule()).sort_values("entry_time_utc").reset_index(drop=True)
        entry_index = pd.DatetimeIndex(data["entry_time_utc"])
        for target_name, target_pct in targets:
            for start in starts:
                end = start + pd.Timedelta(days=max_window_days)
                start_pos = int(entry_index.searchsorted(start, side="left"))
                end_pos = int(entry_index.searchsorted(end, side="right"))
                window = data.iloc[start_pos:end_pos].copy()
                outcome = _evaluate_challenge_window(window, target_pct=target_pct)
                rows.append(
                    {
                        "profile_id": profile.profile_id,
                        "profile_label": profile.label,
                        "target_type": target_name,
                        "target_pct": target_pct,
                        "start_utc": start.isoformat(),
                        "max_window_days": max_window_days,
                        **outcome,
                    }
                )
    return pd.DataFrame(rows)


def _evaluate_challenge_window(trades: pd.DataFrame, *, target_pct: float) -> dict[str, Any]:
    if trades.empty:
        return {"outcome": "unresolved", "days_to_outcome": None, "max_daily_stress_pct": 0.0, "min_reserved_equity_pct": 0.0}
    curve = risk_reserved_event_curve(trades)
    curve["daily_stress_at_event_pct"] = (
        curve["day_start_realized_pct"].astype(float) - curve["equity_reserved_pct"].astype(float)
    ).clip(lower=0.0)
    max_daily = float(curve["daily_stress_at_event_pct"].max()) if not curve.empty else 0.0
    min_reserved = float(curve["equity_reserved_pct"].min()) if not curve.empty else 0.0
    first_time = pd.to_datetime(curve["time_utc"], utc=True).min()
    events: list[tuple[pd.Timestamp, int, str]] = []
    daily_fail = curve[curve["daily_stress_at_event_pct"] >= MAX_DAILY_LOSS_PCT]
    if not daily_fail.empty:
        events.append((pd.Timestamp(daily_fail.iloc[0]["time_utc"]), 0, "failed_daily_loss"))
    max_loss = curve[curve["equity_reserved_pct"].astype(float) <= -MAX_LOSS_PCT]
    if not max_loss.empty:
        events.append((pd.Timestamp(max_loss.iloc[0]["time_utc"]), 1, "failed_max_loss"))
    target = curve[(curve["realized_pct"].astype(float) >= target_pct) & (curve["open_risk_pct"].abs() < 1e-9)]
    if not target.empty:
        events.append((pd.Timestamp(target.iloc[0]["time_utc"]), 2, "hit_target"))
    if events:
        event_time, _priority, outcome = sorted(events, key=lambda item: (item[0], item[1]))[0]
        return {
            "outcome": outcome,
            "days_to_outcome": (event_time - first_time).total_seconds() / 86400.0,
            "max_daily_stress_pct": max_daily,
            "min_reserved_equity_pct": min_reserved,
        }
    return {
        "outcome": "unresolved",
        "days_to_outcome": None,
        "max_daily_stress_pct": max_daily,
        "min_reserved_equity_pct": min_reserved,
    }


def _challenge_summary_rows(windows: pd.DataFrame) -> list[dict[str, Any]]:
    if windows.empty:
        return []
    rows = []
    for keys, group in windows.groupby(["profile_id", "target_type"], sort=True):
        profile_id, target_type = keys
        hit = group[group["outcome"] == "hit_target"]
        rows.append(
            {
                "profile_id": profile_id,
                "target_type": target_type,
                "windows": int(len(group)),
                "hit_target": int((group["outcome"] == "hit_target").sum()),
                "failed_daily_loss": int((group["outcome"] == "failed_daily_loss").sum()),
                "failed_max_loss": int((group["outcome"] == "failed_max_loss").sum()),
                "unresolved": int((group["outcome"] == "unresolved").sum()),
                "hit_rate": float((group["outcome"] == "hit_target").mean()) if len(group) else 0.0,
                "median_days_to_target": None if hit.empty else float(hit["days_to_outcome"].median()),
                "p75_days_to_target": None if hit.empty else float(hit["days_to_outcome"].quantile(0.75)),
            }
        )
    return rows


def write_outputs(
    *,
    output_dir: Path,
    docs_output: Path,
    frontier: pd.DataFrame,
    candidates: pd.DataFrame,
    daily: pd.DataFrame,
    spread: pd.DataFrame,
    windows: pd.DataFrame,
    run_summary: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    frontier.to_csv(output_dir / "frontier_summary.csv", index=False, float_format="%.10g")
    candidates.to_csv(output_dir / "candidate_profiles.csv", index=False, float_format="%.10g")
    daily.to_csv(output_dir / "daily_loss_stress.csv", index=False, float_format="%.10g")
    spread.to_csv(output_dir / "spread_gate_impact.csv", index=False, float_format="%.10g")
    windows.to_csv(output_dir / "challenge_window_outcomes.csv", index=False, float_format="%.10g")
    _write_json(output_dir / "run_summary.json", run_summary)
    html_text = build_html_report(frontier=frontier, candidates=candidates, spread=spread, windows=windows, run_summary=run_summary)
    (output_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    docs_output.parent.mkdir(parents=True, exist_ok=True)
    docs_output.write_text(html_text, encoding="utf-8")


def _candidate_role(candidates: pd.DataFrame, role: str) -> dict[str, Any] | None:
    if candidates.empty:
        return None
    rows = candidates[candidates["selection_role"].astype(str).str.contains(role, regex=False)]
    return None if rows.empty else rows.iloc[0].to_dict()


def _candidate_table_rows(candidates: pd.DataFrame, *, limit: int = 12) -> list[list[Any]]:
    rows = []
    for row in candidates.head(limit).to_dict(orient="records"):
        rows.append(
            [
                _escape(row["selection_role"]),
                _escape(row["profile_label"]),
                _fmt_pct(row["total_return_pct"]),
                _fmt_pct(row["reserved_max_drawdown_pct"]),
                _fmt_pct(row["max_daily_loss_stress_pct"]),
                _fmt_pct(row["max_reserved_open_risk_pct"]),
                _fmt_pct(row["worst_month_pct"]),
                _fmt_money_from_pct(row["median_month_pct"]),
                _fmt_money_from_pct(row["p25_month_pct"]),
                _fmt_money_from_pct(row["p75_month_pct"]),
            ]
        )
    return rows


def _challenge_table_rows(windows: pd.DataFrame, candidates: pd.DataFrame) -> list[list[Any]]:
    if windows.empty or candidates.empty:
        return []
    names = candidates.set_index("profile_id")["profile_label"].to_dict()
    rows = []
    for row in _challenge_summary_rows(windows):
        rows.append(
            [
                _escape(names.get(row["profile_id"], row["profile_id"])),
                _escape(row["target_type"]),
                f"{row['hit_rate'] * 100.0:.1f}%",
                _escape(row["hit_target"]),
                _escape(row["failed_daily_loss"]),
                _escape(row["failed_max_loss"]),
                _escape(row["unresolved"]),
                "" if row["median_days_to_target"] is None else _fmt_num(row["median_days_to_target"], 1),
            ]
        )
    return rows


def build_html_report(
    *,
    frontier: pd.DataFrame,
    candidates: pd.DataFrame,
    spread: pd.DataFrame,
    windows: pd.DataFrame,
    run_summary: dict[str, Any],
) -> str:
    fresh = _candidate_role(candidates, "fresh_challenge")
    aggressive = _candidate_role(candidates, "aggressive_funded")
    total_spread = spread.iloc[0].to_dict() if not spread.empty else {}
    subtitle = (
        "FTMO 100k 2-Step profile frontier using V22 LPFS separated trades, "
        "FTMO commission-adjusted R, and an initial signal-candle spread-gate overlay."
    )
    extra_css = """
    .profile-callout {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
    }
    .profile-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fff;
    }
    .profile-card h3 { margin-top: 0; }
    .note-list li { margin: 6px 0; }
    .positive { color: var(--good); font-weight: 700; }
    .negative { color: var(--bad); font-weight: 700; }
    """
    profile_cards = []
    for title, row in [("Fresh FTMO Challenge", fresh), ("Aggressive / Funded", aggressive)]:
        if row is None:
            continue
        profile_cards.append(
            f"""
        <article class="profile-card">
          <h3>{_escape(title)}</h3>
          <p><strong>{_escape(row['profile_label'])}</strong></p>
          <p>10y return {_fmt_pct(row['total_return_pct'])}, reserved DD {_fmt_pct(row['reserved_max_drawdown_pct'])}, max daily stress {_fmt_pct(row['max_daily_loss_stress_pct'])}.</p>
          <p>Median month on $100k: <strong>{_fmt_money_from_pct(row['median_month_pct'])}</strong>; middle range {_fmt_money_from_pct(row['p25_month_pct'])} to {_fmt_money_from_pct(row['p75_month_pct'])}.</p>
        </article>
            """
        )
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LPFS FTMO Challenge Profiles</title>
  <style>
    {dashboard_base_css(table_min_width="1100px", extra_css=extra_css)}
  </style>
</head>
<body>
  {dashboard_header_html(
      title="LPFS FTMO Challenge Profiles",
      subtitle_html=_escape(subtitle),
      current_page="ftmo_challenge_profiles.html",
      section_links=[
          ("#recommendation", "Recommendation"),
          ("#candidates", "Candidates"),
          ("#challenge-windows", "Challenge Windows"),
          ("#spread", "Spread Gate"),
          ("#method", "Method"),
      ],
  )}
  <main>
    <section id="recommendation" aria-labelledby="recommendation-title">
      <h2 id="recommendation-title">Recommended Profiles</h2>
      <p class="callout">A profile is not marked usable unless it stays under the FTMO daily-loss and max-loss stress checks and the initial spread-gated approximation does not materially contradict the base V22 result.</p>
      <div class="profile-callout">{"".join(profile_cards)}</div>
    </section>

    <section id="candidates" aria-labelledby="candidates-title">
      <h2 id="candidates-title">Candidate Profiles</h2>
      {_table(
          ["Role", "Profile", "10y Return", "Reserved DD", "Max Daily Stress", "Max Open Risk", "Worst Month", "Median Month $", "P25 Month $", "P75 Month $"],
          _candidate_table_rows(candidates),
      )}
    </section>

    <section id="challenge-windows" aria-labelledby="challenge-windows-title">
      <h2 id="challenge-windows-title">Rolling Challenge Windows</h2>
      <p class="callout">Windows start weekly and run for up to 365 days. Targets require closed balance to reach 10% for Challenge or 5% for Verification with no open risk at that event.</p>
      {_table(
          ["Profile", "Target", "Hit Rate", "Hit", "Daily Loss Fail", "Max Loss Fail", "Unresolved", "Median Days"],
          _challenge_table_rows(windows, candidates),
      )}
    </section>

    <section id="spread" aria-labelledby="spread-title">
      <h2 id="spread-title">Spread Gate Overlay</h2>
      <p class="callout warning">This uses the signal candle spread-to-risk ratio with the live threshold of 10%. Live retry and market recovery can still place some rows that this conservative initial-gate overlay removes.</p>
      <ul class="note-list">
        <li>Total trades checked: {_escape(total_spread.get("trades", ""))}</li>
        <li>Initial spread failures: {_escape(total_spread.get("initial_spread_failures", ""))} ({_fmt_pct(_to_float(total_spread.get("initial_spread_failure_rate")) * 100.0)})</li>
        <li>Average spread-to-risk: {_fmt_pct(total_spread.get("avg_spread_to_risk_pct"))}</li>
        <li>90th percentile spread-to-risk: {_fmt_pct(total_spread.get("p90_spread_to_risk_pct"))}</li>
      </ul>
    </section>

    <section id="method" aria-labelledby="method-title">
      <h2 id="method-title">Method And Boundaries</h2>
      <ul class="note-list">
        <li>Source: FTMO V22 separated LPFS trade rows with commission-adjusted net R.</li>
        <li>FTMO rules modeled: 5% max daily loss and 10% max loss for 2-Step accounts.</li>
        <li>Risk buckets are account-percent targets before live broker volume rounding.</li>
        <li>No live configs, VPS runtime state, journals, orders, or scheduled tasks were touched.</li>
        <li>Generated at {_escape(run_summary["generated_at_utc"])} into {_escape(run_summary["output_dir"])}.</li>
      </ul>
    </section>
    {metric_glossary_html()}
  </main>
  <footer>Research-only FTMO challenge profile page. Use Live Ops for production runner state.</footer>
</body>
</html>
"""
    return "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"


def run_frontier(
    *,
    trades_path: Path = DEFAULT_TRADES_PATH,
    data_root: Path = DEFAULT_DATA_ROOT,
    bucket_config_path: Path = DEFAULT_BUCKET_CONFIG,
    output_dir: Path | None = None,
    docs_output: Path = DEFAULT_DOCS_OUTPUT,
    variant: str = DEFAULT_VARIANT,
    max_spread_risk_fraction: float = 0.10,
) -> Path:
    target = output_dir or (DEFAULT_OUTPUT_ROOT / datetime.now(UTC).strftime("%Y%m%d_%H%M%S"))
    bucket_config = _read_json(bucket_config_path)
    trades = load_ftmo_trades(trades_path, variant=variant, bucket_config=bucket_config)
    trades = add_signal_spread_gate(
        trades,
        data_root=data_root,
        max_spread_risk_fraction=max_spread_risk_fraction,
    )
    profiles = frontier_risk_profiles()
    frontier, daily, spread = build_frontier(
        trades,
        profiles,
        max_spread_risk_fraction=max_spread_risk_fraction,
    )
    candidates = select_candidate_profiles(frontier)
    selected_profiles = [
        RiskProfile(float(row.lower_risk_pct), float(row.middle_risk_pct), float(row.w1_risk_pct))
        for row in candidates.head(6).itertuples()
    ]
    profile_ids = {profile.profile_id for profile in selected_profiles}
    window_trades = trades.copy()
    windows = challenge_window_outcomes(window_trades, selected_profiles)
    run_summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "output_dir": str(target),
        "docs_output": str(docs_output),
        "trades_path": str(trades_path),
        "data_root": str(data_root),
        "variant": variant,
        "profiles_tested": len(profiles),
        "trade_rows": int(len(trades)),
        "max_spread_risk_fraction": max_spread_risk_fraction,
        "ftmo_rules": {
            "account_size": ACCOUNT_SIZE,
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
            "max_loss_pct": MAX_LOSS_PCT,
            "source": "https://ftmo.com/en/trading-objectives/",
        },
        "selected_profile_ids": sorted(profile_ids),
        "challenge_window_summary": _challenge_summary_rows(windows),
    }
    write_outputs(
        output_dir=target,
        docs_output=docs_output,
        frontier=frontier,
        candidates=candidates,
        daily=daily,
        spread=spread,
        windows=windows,
        run_summary=run_summary,
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LPFS FTMO challenge profile frontier study.")
    parser.add_argument("--trades-path", default=str(DEFAULT_TRADES_PATH))
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--bucket-config", default=str(DEFAULT_BUCKET_CONFIG))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--docs-output", default=str(DEFAULT_DOCS_OUTPUT))
    parser.add_argument("--variant", default=DEFAULT_VARIANT)
    parser.add_argument("--max-spread-risk-fraction", type=float, default=0.10)
    args = parser.parse_args()
    result = run_frontier(
        trades_path=Path(args.trades_path),
        data_root=Path(args.data_root),
        bucket_config_path=Path(args.bucket_config),
        output_dir=None if args.output_dir is None else Path(args.output_dir),
        docs_output=Path(args.docs_output),
        variant=args.variant,
        max_spread_risk_fraction=float(args.max_spread_risk_fraction),
    )
    print(f"ftmo_challenge_frontier={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
