from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


TIMEFRAME_PRIORITY = {
    "W1": 5,
    "D1": 4,
    "H12": 3,
    "H8": 2,
    "H4": 1,
}


@dataclass(frozen=True)
class PortfolioRule:
    portfolio_id: str
    max_open_r: float | None = None
    enforce_one_per_symbol: bool = False
    risk_r_per_trade: float = 1.0


@dataclass(frozen=True)
class PortfolioResult:
    portfolio_id: str
    pivot_strength: int
    trades_available: int
    trades_accepted: int
    rejected_symbol_overlap: int
    rejected_max_open_r: int
    total_net_r: float
    avg_net_r: float
    win_rate: float
    profit_factor: float | None
    max_drawdown_r: float
    longest_underwater_days: float
    return_to_drawdown: float | None
    passed_guardrails: bool


def _timeframe_priority(timeframe: str) -> int:
    return TIMEFRAME_PRIORITY.get(str(timeframe), 0)


def _required_trade_columns() -> set[str]:
    return {
        "symbol",
        "timeframe",
        "pivot_strength",
        "entry_time_utc",
        "exit_time_utc",
        "net_r",
    }


def normalize_trade_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(_required_trade_columns().difference(frame.columns))
    if missing:
        raise ValueError(f"Trade frame missing required columns: {missing}")

    data = frame.copy()
    data["symbol"] = data["symbol"].astype(str)
    data["timeframe"] = data["timeframe"].astype(str)
    data["pivot_strength"] = data["pivot_strength"].astype(int)
    data["entry_time_utc"] = pd.to_datetime(data["entry_time_utc"], utc=True)
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    data["_tf_priority"] = data["timeframe"].map(_timeframe_priority)
    return data.sort_values(
        ["entry_time_utc", "_tf_priority", "symbol", "exit_time_utc"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)


def select_portfolio_trades(frame: pd.DataFrame, rule: PortfolioRule) -> tuple[pd.DataFrame, dict[str, int]]:
    data = normalize_trade_frame(frame)
    if not rule.enforce_one_per_symbol and rule.max_open_r is None:
        selected = data.copy()
        selected["portfolio_id"] = rule.portfolio_id
        return selected.drop(columns=["_tf_priority"]), {
            "rejected_symbol_overlap": 0,
            "rejected_max_open_r": 0,
        }

    open_trades: list[dict[str, object]] = []
    selected_indices: list[int] = []
    rejected_symbol_overlap = 0
    rejected_max_open_r = 0

    for entry_time, entry_group in data.groupby("entry_time_utc", sort=True):
        open_trades = [trade for trade in open_trades if trade["exit_time_utc"] > entry_time]
        open_r = len(open_trades) * rule.risk_r_per_trade
        open_symbols = {str(trade["symbol"]) for trade in open_trades}
        accepted_symbols_at_time: set[str] = set()

        for row in entry_group.itertuples():
            symbol = str(row.symbol)
            if rule.enforce_one_per_symbol and (symbol in open_symbols or symbol in accepted_symbols_at_time):
                rejected_symbol_overlap += 1
                continue

            if rule.max_open_r is not None and open_r + rule.risk_r_per_trade > rule.max_open_r:
                rejected_max_open_r += 1
                continue

            selected_indices.append(int(row.Index))
            open_r += rule.risk_r_per_trade
            accepted_symbols_at_time.add(symbol)
            open_trades.append(
                {
                    "symbol": symbol,
                    "exit_time_utc": row.exit_time_utc,
                }
            )

    selected = data.loc[selected_indices].copy()
    selected["portfolio_id"] = rule.portfolio_id
    return selected.drop(columns=["_tf_priority"]), {
        "rejected_symbol_overlap": rejected_symbol_overlap,
        "rejected_max_open_r": rejected_max_open_r,
    }


def closed_trade_drawdown_metrics(frame: pd.DataFrame) -> dict[str, float | str | None]:
    if frame.empty:
        return {
            "max_drawdown_r": 0.0,
            "longest_underwater_days": 0.0,
            "max_drawdown_start_utc": None,
            "max_drawdown_trough_utc": None,
            "max_drawdown_recovery_utc": None,
        }

    data = frame.copy()
    data["entry_time_utc"] = pd.to_datetime(data["entry_time_utc"], utc=True)
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    data = data.sort_values(["exit_time_utc", "entry_time_utc", "symbol", "timeframe"]).reset_index(drop=True)
    data["equity_r"] = data["net_r"].cumsum()
    data["peak_r"] = data["equity_r"].cummax().clip(lower=0.0)
    data["drawdown_r"] = data["peak_r"] - data["equity_r"]

    max_idx = int(data["drawdown_r"].idxmax())
    max_row = data.loc[max_idx]
    max_drawdown = float(max_row["drawdown_r"])
    peak_value = float(max_row["peak_r"])
    peak_idx = 0
    if peak_value > 0:
        peak_matches = data.loc[:max_idx][data.loc[:max_idx, "equity_r"].eq(peak_value)]
        if not peak_matches.empty:
            peak_idx = int(peak_matches.index[0])
    recovery = data[(data.index > max_idx) & (data["equity_r"] >= peak_value)]

    in_drawdown = False
    period_start = None
    longest_underwater_days = 0.0
    for row in data.itertuples():
        drawdown = float(row.drawdown_r)
        current_time = row.exit_time_utc
        if drawdown > 1e-12 and not in_drawdown:
            in_drawdown = True
            period_start = current_time
        elif drawdown <= 1e-12 and in_drawdown:
            days = (current_time - period_start).total_seconds() / 86400
            longest_underwater_days = max(longest_underwater_days, days)
            in_drawdown = False
            period_start = None
    if in_drawdown and period_start is not None:
        days = (data.iloc[-1]["exit_time_utc"] - period_start).total_seconds() / 86400
        longest_underwater_days = max(longest_underwater_days, days)

    return {
        "max_drawdown_r": max_drawdown,
        "longest_underwater_days": longest_underwater_days,
        "max_drawdown_start_utc": data.loc[peak_idx, "exit_time_utc"].isoformat(),
        "max_drawdown_trough_utc": max_row["exit_time_utc"].isoformat(),
        "max_drawdown_recovery_utc": None if recovery.empty else recovery.iloc[0]["exit_time_utc"].isoformat(),
    }


def summarize_portfolio(
    selected: pd.DataFrame,
    *,
    portfolio_id: str,
    pivot_strength: int,
    trades_available: int,
    rejected_symbol_overlap: int,
    rejected_max_open_r: int,
    max_drawdown_guardrail_r: float,
    max_underwater_guardrail_days: float,
) -> PortfolioResult:
    trade_count = int(len(selected))
    net_r = pd.to_numeric(selected["net_r"], errors="coerce").fillna(0.0) if trade_count else pd.Series(dtype=float)
    gross_win = float(net_r[net_r > 0].sum()) if trade_count else 0.0
    gross_loss = float(net_r[net_r < 0].sum()) if trade_count else 0.0
    total_net_r = float(net_r.sum()) if trade_count else 0.0
    drawdown = closed_trade_drawdown_metrics(selected)
    max_drawdown = float(drawdown["max_drawdown_r"])
    longest_underwater = float(drawdown["longest_underwater_days"])
    passed = max_drawdown <= max_drawdown_guardrail_r and longest_underwater <= max_underwater_guardrail_days
    return_to_drawdown = None if max_drawdown <= 0 else total_net_r / max_drawdown

    return PortfolioResult(
        portfolio_id=portfolio_id,
        pivot_strength=pivot_strength,
        trades_available=trades_available,
        trades_accepted=trade_count,
        rejected_symbol_overlap=rejected_symbol_overlap,
        rejected_max_open_r=rejected_max_open_r,
        total_net_r=total_net_r,
        avg_net_r=float(net_r.mean()) if trade_count else 0.0,
        win_rate=float((net_r > 0).mean()) if trade_count else 0.0,
        profit_factor=None if gross_loss == 0 else gross_win / abs(gross_loss),
        max_drawdown_r=max_drawdown,
        longest_underwater_days=longest_underwater,
        return_to_drawdown=return_to_drawdown,
        passed_guardrails=passed,
    )


def run_portfolio_rule(
    frame: pd.DataFrame,
    *,
    rule: PortfolioRule,
    pivot_strength: int,
    max_drawdown_guardrail_r: float,
    max_underwater_guardrail_days: float,
) -> tuple[PortfolioResult, pd.DataFrame]:
    selected, rejected = select_portfolio_trades(frame, rule)
    result = summarize_portfolio(
        selected,
        portfolio_id=rule.portfolio_id,
        pivot_strength=pivot_strength,
        trades_available=int(len(frame)),
        rejected_symbol_overlap=rejected["rejected_symbol_overlap"],
        rejected_max_open_r=rejected["rejected_max_open_r"],
        max_drawdown_guardrail_r=max_drawdown_guardrail_r,
        max_underwater_guardrail_days=max_underwater_guardrail_days,
    )
    return result, selected
