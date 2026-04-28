"""Left Precedence level detection for MT5-data research and strategies.

This module is the strategy/backtest implementation of the LP rules documented
in ``docs/lp_levels_spec.md``. It evaluates the OHLC frame passed into it, so
TradingView and MT5 can both be correct for their own candle streams even when
feed differences produce different levels.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

import pandas as pd


LPSide = Literal["resistance", "support"]


@dataclass(frozen=True)
class LPLevel:
    """One active Left Precedence support or resistance level."""

    side: LPSide
    price: float
    pivot_index: int
    pivot_time_utc: pd.Timestamp
    confirmed_index: int
    confirmed_time_utc: pd.Timestamp


@dataclass(frozen=True)
class LPBreakEvent:
    """One active LP level broken by wick touch on a bar."""

    side: LPSide
    price: float
    pivot_index: int
    pivot_time_utc: pd.Timestamp
    confirmed_index: int
    confirmed_time_utc: pd.Timestamp
    break_index: int
    break_time_utc: pd.Timestamp


def _timeframe_seconds(timeframe: str | int | float) -> int | None:
    """Parse common MT5 and TradingView timeframe strings into seconds."""

    if isinstance(timeframe, (int, float)):
        if timeframe <= 0:
            return None
        return int(timeframe) * 60

    value = str(timeframe).strip().upper()
    if not value:
        return None
    for prefix in ("PERIOD_", "TIMEFRAME_"):
        if value.startswith(prefix):
            value = value[len(prefix) :]

    if value.isdigit():
        return int(value) * 60

    monthly = re.fullmatch(r"MN(\d*)", value)
    if monthly:
        multiplier = int(monthly.group(1) or "1")
        return multiplier * 30 * 24 * 60 * 60

    unit_first = re.fullmatch(r"([MHDW])(\d*)", value)
    if unit_first:
        unit, raw_count = unit_first.groups()
        count = int(raw_count or "1")
        return _unit_seconds(unit, count)

    count_first = re.fullmatch(r"(\d+)([MHDW])", value)
    if count_first:
        raw_count, unit = count_first.groups()
        return _unit_seconds(unit, int(raw_count))

    return None


def _unit_seconds(unit: str, count: int) -> int | None:
    if count <= 0:
        return None
    if unit == "M":
        return count * 60
    if unit == "H":
        return count * 60 * 60
    if unit == "D":
        return count * 24 * 60 * 60
    if unit == "W":
        return count * 7 * 24 * 60 * 60
    return None


def lookback_days_for_timeframe(timeframe: str | int | float) -> int:
    """Return the LP rolling lookback window for a timeframe."""

    seconds = _timeframe_seconds(timeframe)
    if seconds is None:
        return 365
    if seconds <= 135 * 60:
        return 5
    if seconds == 8 * 60 * 60:
        return 60
    if seconds == 12 * 60 * 60:
        return 180
    if seconds <= 14 * 60 * 60:
        return 30
    if seconds <= 4 * 24 * 60 * 60 + 12 * 60 * 60:
        return 365
    return 1460


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"time_utc", "high", "low"}
    missing = required.difference(frame.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"LP frame is missing required columns: {missing_text}")

    data = frame.loc[:, ["time_utc", "high", "low"]].copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)
    data["high"] = data["high"].astype(float)
    data["low"] = data["low"].astype(float)
    return data.sort_values("time_utc").reset_index(drop=True)


def _is_strict_pivot_high(highs: list[float], pivot_index: int, strength: int) -> bool:
    pivot_high = highs[pivot_index]
    for distance in range(1, strength + 1):
        if pivot_high <= highs[pivot_index - distance] or pivot_high <= highs[pivot_index + distance]:
            return False
    return True


def _is_strict_pivot_low(lows: list[float], pivot_index: int, strength: int) -> bool:
    pivot_low = lows[pivot_index]
    for distance in range(1, strength + 1):
        if pivot_low >= lows[pivot_index - distance] or pivot_low >= lows[pivot_index + distance]:
            return False
    return True


def _level_is_breached(level: LPLevel, *, high: float, low: float) -> bool:
    if level.side == "resistance":
        return high >= level.price
    return low <= level.price


def _break_event_from_level(level: LPLevel, *, break_index: int, break_time: pd.Timestamp) -> LPBreakEvent:
    return LPBreakEvent(
        side=level.side,
        price=level.price,
        pivot_index=level.pivot_index,
        pivot_time_utc=level.pivot_time_utc,
        confirmed_index=level.confirmed_index,
        confirmed_time_utc=level.confirmed_time_utc,
        break_index=break_index,
        break_time_utc=break_time,
    )


def _lp_state_by_bar(
    frame: pd.DataFrame,
    timeframe: str | int | float,
    *,
    pivot_strength: int = 3,
) -> tuple[list[list[LPLevel]], list[list[LPBreakEvent]]]:
    if pivot_strength < 1:
        raise ValueError("pivot_strength must be >= 1.")

    data = _normalise_frame(frame)
    if data.empty:
        return [], []

    lookback_delta = pd.Timedelta(days=lookback_days_for_timeframe(timeframe))
    highs = data["high"].tolist()
    lows = data["low"].tolist()
    times = data["time_utc"].tolist()

    active: list[LPLevel] = []
    levels_by_bar: list[list[LPLevel]] = []
    breaks_by_bar: list[list[LPBreakEvent]] = []

    for current_index, current_time in enumerate(times):
        cutoff_time = current_time - lookback_delta
        current_high = highs[current_index]
        current_low = lows[current_index]

        current_breaks: list[LPBreakEvent] = []
        still_active: list[LPLevel] = []
        for level in active:
            if level.pivot_time_utc < cutoff_time:
                continue
            if _level_is_breached(level, high=current_high, low=current_low):
                current_breaks.append(_break_event_from_level(level, break_index=current_index, break_time=current_time))
            else:
                still_active.append(level)
        active = still_active

        pivot_index = current_index - pivot_strength
        if pivot_index >= pivot_strength:
            pivot_time = times[pivot_index]
            if pivot_time >= cutoff_time:
                if _is_strict_pivot_high(highs, pivot_index, pivot_strength):
                    active.append(
                        LPLevel(
                            side="resistance",
                            price=float(highs[pivot_index]),
                            pivot_index=pivot_index,
                            pivot_time_utc=pivot_time,
                            confirmed_index=current_index,
                            confirmed_time_utc=current_time,
                        )
                    )
                if _is_strict_pivot_low(lows, pivot_index, pivot_strength):
                    active.append(
                        LPLevel(
                            side="support",
                            price=float(lows[pivot_index]),
                            pivot_index=pivot_index,
                            pivot_time_utc=pivot_time,
                            confirmed_index=current_index,
                            confirmed_time_utc=current_time,
                        )
                    )

        levels_by_bar.append(list(active))
        breaks_by_bar.append(current_breaks)

    return levels_by_bar, breaks_by_bar


def active_lp_levels_by_bar(
    frame: pd.DataFrame,
    timeframe: str | int | float,
    *,
    pivot_strength: int = 3,
) -> list[list[LPLevel]]:
    """Return active LP levels available after each bar is processed.

    The function sorts input by ``time_utc`` and resets indexes internally. A
    pivot at index ``i`` is only added on bar ``i + pivot_strength``. Active
    levels are expired by rolling timeframe window and deleted on wick-touch
    breach before newly confirmed pivots are added.
    """

    levels_by_bar, _ = _lp_state_by_bar(frame, timeframe, pivot_strength=pivot_strength)
    return levels_by_bar


def lp_break_events_by_bar(
    frame: pd.DataFrame,
    timeframe: str | int | float,
    *,
    pivot_strength: int = 3,
) -> list[list[LPBreakEvent]]:
    """Return LP wick-break events by bar before breached levels are deleted."""

    _, breaks_by_bar = _lp_state_by_bar(frame, timeframe, pivot_strength=pivot_strength)
    return breaks_by_bar
