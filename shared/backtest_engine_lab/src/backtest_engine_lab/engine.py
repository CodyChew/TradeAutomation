"""Strategy-neutral OHLC bracket-trade simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from typing import Any, Literal

import pandas as pd


TradeSide = Literal["long", "short"]
ExitReason = Literal["target", "stop", "same_bar_stop_priority", "end_of_data"]


@dataclass(frozen=True)
class CostConfig:
    """Cost assumptions for one backtest simulation."""

    point: float = 0.0
    use_candle_spread: bool = True
    fallback_spread_points: float = 0.0
    entry_slippage_points: float = 0.0
    exit_slippage_points: float = 0.0
    round_turn_commission_points: float = 0.0


@dataclass(frozen=True)
class TradeSetup:
    """One strategy-produced bracket trade setup."""

    setup_id: str
    side: TradeSide
    entry_index: int
    entry_price: float
    stop_price: float
    target_price: float
    symbol: str = ""
    timeframe: str = ""
    signal_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeRecord:
    """One completed simulated trade."""

    setup_id: str
    symbol: str
    timeframe: str
    side: TradeSide
    signal_index: int | None
    entry_index: int
    exit_index: int
    entry_time_utc: pd.Timestamp
    exit_time_utc: pd.Timestamp
    entry_reference_price: float
    entry_fill_price: float
    exit_reference_price: float
    exit_fill_price: float
    stop_price: float
    target_price: float
    risk_distance: float
    reference_r: float
    fill_r: float
    commission_r: float
    net_r: float
    bars_held: int
    exit_reason: ExitReason
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BacktestFrameInfo:
    """Information about latest-candle completeness."""

    latest_time_utc: pd.Timestamp | None
    expected_latest_close_utc: pd.Timestamp | None
    as_of_time_utc: pd.Timestamp
    latest_bar_complete: bool


def normalize_backtest_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a sorted, validated OHLC frame for backtesting."""

    required = {"time_utc", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Backtest frame is missing required columns: {missing_text}")

    keep = ["time_utc", "open", "high", "low", "close"]
    for optional in ("spread_points", "point"):
        if optional in frame.columns:
            keep.append(optional)
    data = frame.loc[:, keep].copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)
    for column in [col for col in keep if col != "time_utc"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.sort_values("time_utc").reset_index(drop=True)
    if data.empty:
        raise ValueError("Backtest frame is empty.")
    if data["time_utc"].duplicated().any():
        raise ValueError("Backtest frame contains duplicate timestamps.")
    for column in ("open", "high", "low", "close"):
        if data[column].isna().any():
            raise ValueError(f"Backtest frame contains non-numeric {column} values.")
    if ((data["high"] < data["low"]) | (data["high"] < data["open"]) | (data["high"] < data["close"])).any():
        raise ValueError("Backtest frame contains invalid high values.")
    if ((data["low"] > data["open"]) | (data["low"] > data["close"])).any():
        raise ValueError("Backtest frame contains invalid low values.")
    return data


def _timeframe_delta(timeframe: str | int | float) -> pd.Timedelta:
    if isinstance(timeframe, (int, float)):
        if timeframe <= 0:
            raise ValueError("timeframe must be positive.")
        return pd.Timedelta(minutes=int(timeframe))

    value = str(timeframe).strip().upper()
    for prefix in ("PERIOD_", "TIMEFRAME_"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    if value.isdigit():
        return pd.Timedelta(minutes=int(value))

    aliases = {
        "M1": pd.Timedelta(minutes=1),
        "M5": pd.Timedelta(minutes=5),
        "M15": pd.Timedelta(minutes=15),
        "M30": pd.Timedelta(minutes=30),
        "H1": pd.Timedelta(hours=1),
        "H4": pd.Timedelta(hours=4),
        "D": pd.Timedelta(days=1),
        "D1": pd.Timedelta(days=1),
        "W": pd.Timedelta(days=7),
        "W1": pd.Timedelta(days=7),
    }
    if value in aliases:
        return aliases[value]

    match = re.fullmatch(r"(\d+)([MHDW])", value)
    if match:
        count = int(match.group(1))
        unit = match.group(2)
        if unit == "M":
            return pd.Timedelta(minutes=count)
        if unit == "H":
            return pd.Timedelta(hours=count)
        if unit == "D":
            return pd.Timedelta(days=count)
        if unit == "W":
            return pd.Timedelta(days=7 * count)
    raise ValueError(f"Unsupported timeframe {timeframe!r}.")


def is_latest_bar_complete(
    frame: pd.DataFrame,
    timeframe: str | int | float,
    *,
    as_of_time_utc: Any,
) -> BacktestFrameInfo:
    """Return whether the latest candle is complete at ``as_of_time_utc``."""

    data = normalize_backtest_frame(frame)
    as_of = pd.Timestamp(as_of_time_utc)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    else:
        as_of = as_of.tz_convert("UTC")
    latest = data["time_utc"].iloc[-1]
    expected_close = latest + _timeframe_delta(timeframe)
    return BacktestFrameInfo(
        latest_time_utc=latest,
        expected_latest_close_utc=expected_close,
        as_of_time_utc=as_of,
        latest_bar_complete=expected_close <= as_of,
    )


def drop_incomplete_last_bar(
    frame: pd.DataFrame,
    timeframe: str | int | float,
    *,
    as_of_time_utc: Any,
) -> pd.DataFrame:
    """Drop the latest candle when it is still forming at ``as_of_time_utc``."""

    data = normalize_backtest_frame(frame)
    info = is_latest_bar_complete(data, timeframe, as_of_time_utc=as_of_time_utc)
    if info.latest_bar_complete:
        return data
    if len(data) == 1:
        raise ValueError("Cannot drop incomplete latest bar because it is the only row.")
    return data.iloc[:-1].reset_index(drop=True)


def _point(row: pd.Series, costs: CostConfig) -> float:
    value = row.get("point", costs.point)
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = costs.point
    return result if math.isfinite(result) and result > 0 else float(costs.point)


def _spread_points(row: pd.Series, costs: CostConfig) -> float:
    if costs.use_candle_spread and "spread_points" in row:
        value = row.get("spread_points")
        try:
            result = float(value)
        except (TypeError, ValueError):
            result = math.nan
        if math.isfinite(result) and result >= 0:
            return result
    return float(costs.fallback_spread_points)


def _half_spread_price(row: pd.Series, costs: CostConfig) -> float:
    return _spread_points(row, costs) * _point(row, costs) / 2.0


def _slippage_price(row: pd.Series, costs: CostConfig, *, entry: bool) -> float:
    points = costs.entry_slippage_points if entry else costs.exit_slippage_points
    return float(points) * _point(row, costs)


def _entry_fill(side: TradeSide, reference_price: float, row: pd.Series, costs: CostConfig) -> float:
    half_spread = _half_spread_price(row, costs)
    slippage = _slippage_price(row, costs, entry=True)
    if side == "long":
        return float(reference_price + half_spread + slippage)
    return float(reference_price - half_spread - slippage)


def _exit_fill(side: TradeSide, reference_price: float, row: pd.Series, costs: CostConfig) -> float:
    half_spread = _half_spread_price(row, costs)
    slippage = _slippage_price(row, costs, entry=False)
    if side == "long":
        return float(reference_price - half_spread - slippage)
    return float(reference_price + half_spread + slippage)


def _validate_setup(setup: TradeSetup, frame_length: int) -> None:
    if setup.side not in ("long", "short"):
        raise ValueError("TradeSetup.side must be 'long' or 'short'.")
    if setup.entry_index < 0 or setup.entry_index >= frame_length:
        raise ValueError("TradeSetup.entry_index is outside the backtest frame.")
    if setup.side == "long" and not (setup.stop_price < setup.entry_price < setup.target_price):
        raise ValueError("Long setup requires stop_price < entry_price < target_price.")
    if setup.side == "short" and not (setup.target_price < setup.entry_price < setup.stop_price):
        raise ValueError("Short setup requires target_price < entry_price < stop_price.")


def _risk_distance(setup: TradeSetup) -> float:
    if setup.side == "long":
        return float(setup.entry_price - setup.stop_price)
    return float(setup.stop_price - setup.entry_price)


def _bar_hits_exit(setup: TradeSetup, row: pd.Series) -> tuple[bool, bool]:
    high = float(row["high"])
    low = float(row["low"])
    if setup.side == "long":
        return low <= setup.stop_price, high >= setup.target_price
    return high >= setup.stop_price, low <= setup.target_price


def _reference_r(setup: TradeSetup, exit_reference: float, risk: float) -> float:
    if setup.side == "long":
        return float((exit_reference - setup.entry_price) / risk)
    return float((setup.entry_price - exit_reference) / risk)


def _fill_r(side: TradeSide, entry_fill: float, exit_fill: float, risk: float) -> float:
    if side == "long":
        return float((exit_fill - entry_fill) / risk)
    return float((entry_fill - exit_fill) / risk)


def _commission_r(row: pd.Series, costs: CostConfig, risk: float) -> float:
    commission_price = float(costs.round_turn_commission_points) * _point(row, costs)
    return float(commission_price / risk) if risk > 0 else 0.0


def _record(
    *,
    setup: TradeSetup,
    data: pd.DataFrame,
    exit_index: int,
    exit_reference: float,
    exit_reason: ExitReason,
    costs: CostConfig,
) -> TradeRecord:
    entry_row = data.iloc[setup.entry_index]
    exit_row = data.iloc[exit_index]
    risk = _risk_distance(setup)
    entry_fill = _entry_fill(setup.side, setup.entry_price, entry_row, costs)
    exit_fill = _exit_fill(setup.side, exit_reference, exit_row, costs)
    reference_r = _reference_r(setup, exit_reference, risk)
    fill_r = _fill_r(setup.side, entry_fill, exit_fill, risk)
    commission_r = _commission_r(entry_row, costs, risk)
    return TradeRecord(
        setup_id=setup.setup_id,
        symbol=setup.symbol,
        timeframe=setup.timeframe,
        side=setup.side,
        signal_index=setup.signal_index,
        entry_index=setup.entry_index,
        exit_index=exit_index,
        entry_time_utc=entry_row["time_utc"],
        exit_time_utc=exit_row["time_utc"],
        entry_reference_price=float(setup.entry_price),
        entry_fill_price=entry_fill,
        exit_reference_price=float(exit_reference),
        exit_fill_price=exit_fill,
        stop_price=float(setup.stop_price),
        target_price=float(setup.target_price),
        risk_distance=risk,
        reference_r=reference_r,
        fill_r=fill_r,
        commission_r=commission_r,
        net_r=float(fill_r - commission_r),
        bars_held=int(exit_index - setup.entry_index + 1),
        exit_reason=exit_reason,
        metadata=dict(setup.metadata),
    )


def simulate_bracket_trade(
    frame: pd.DataFrame,
    setup: TradeSetup,
    *,
    costs: CostConfig | None = None,
) -> TradeRecord:
    """Simulate one fixed-entry bracket trade on OHLC candles."""

    data = normalize_backtest_frame(frame)
    _validate_setup(setup, len(data))
    cost_config = costs or CostConfig()

    for index in range(setup.entry_index, len(data)):
        row = data.iloc[index]
        stop_hit, target_hit = _bar_hits_exit(setup, row)
        if stop_hit:
            reason: ExitReason = "same_bar_stop_priority" if target_hit else "stop"
            return _record(
                setup=setup,
                data=data,
                exit_index=index,
                exit_reference=float(setup.stop_price),
                exit_reason=reason,
                costs=cost_config,
            )
        if target_hit:
            return _record(
                setup=setup,
                data=data,
                exit_index=index,
                exit_reference=float(setup.target_price),
                exit_reason="target",
                costs=cost_config,
            )

    final_index = len(data) - 1
    return _record(
        setup=setup,
        data=data,
        exit_index=final_index,
        exit_reference=float(data.iloc[final_index]["close"]),
        exit_reason="end_of_data",
        costs=cost_config,
    )
