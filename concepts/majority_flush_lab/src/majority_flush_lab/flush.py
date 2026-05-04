"""LP-based Majority Flush displacement detection.

Majority Flush is a concept layer, not a trading system. The detector finds
full upside/downside displacement legs that force active LP levels in their
path. Execution confirmation and trade management belong in strategy labs that
import this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from lp_levels_lab import LPLevel, active_lp_levels_by_bar


FlushSide = Literal["upside", "downside"]
ForcedLPSide = Literal["support", "resistance"]

MIDPOINT_FAILED = "midpoint_failed"
TWO_NO_PROGRESS = "two_no_progress_candles"
TWO_INSIDE_BARS = "two_inside_bars"
TOO_CONSTIPATED = "too_constipated"


@dataclass(frozen=True)
class MajorityFlushConfig:
    """Configuration for Majority Flush concept detection."""

    pivot_strength: int = 3
    include_rejected: bool = False
    max_constipated_bar_ratio: float = 0.35


@dataclass(frozen=True)
class ForcedLP:
    """One LP level forced by a Majority Flush leg."""

    lp_side: ForcedLPSide
    price: float
    pivot_index: int
    pivot_time_utc: pd.Timestamp
    confirmed_index: int
    confirmed_time_utc: pd.Timestamp
    midpoint: float
    first_force_index: int
    first_force_time_utc: pd.Timestamp
    first_force_price: float
    constipated_bar_ratio: float
    midpoint_passed: bool
    constipated_ratio_passed: bool
    invalidation_reason: str | None = None


@dataclass(frozen=True)
class MajorityFlushMove:
    """One full Majority Flush leg and the LPs forced by it."""

    side: FlushSide
    origin_index: int
    origin_time_utc: pd.Timestamp
    origin_price: float
    flush_start_index: int
    flush_start_time_utc: pd.Timestamp
    flush_start_price: float
    completion_index: int
    completion_time_utc: pd.Timestamp
    completion_price: float
    duration_bars: int
    leg_high: float
    leg_low: float
    forced_lps: tuple[ForcedLP, ...]


def detect_majority_flushes(
    frame: pd.DataFrame,
    timeframe: str | int | float,
    *,
    config: MajorityFlushConfig | None = None,
) -> list[MajorityFlushMove]:
    """Detect completed Majority Flush moves in an OHLC frame."""

    resolved_config = config or MajorityFlushConfig()
    if resolved_config.pivot_strength < 1:
        raise ValueError("pivot_strength must be >= 1.")
    if not 0.0 <= resolved_config.max_constipated_bar_ratio <= 1.0:
        raise ValueError("max_constipated_bar_ratio must be between 0 and 1.")

    data = _normalise_frame(frame)
    if data.empty:
        return []

    levels_by_bar = active_lp_levels_by_bar(
        data.loc[:, ["time_utc", "high", "low"]],
        timeframe,
        pivot_strength=resolved_config.pivot_strength,
    )

    moves: list[MajorityFlushMove] = []
    origin_index = 1
    while origin_index < len(data) - 1:
        move = _detect_from_origin(data, levels_by_bar, origin_index, "downside", resolved_config)
        if move is None:
            move = _detect_from_origin(data, levels_by_bar, origin_index, "upside", resolved_config)
        if move is not None:
            moves.append(move)
            origin_index = move.completion_index + 1
        else:
            origin_index += 1

    return moves


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"time_utc", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Majority Flush frame is missing required columns: {missing_text}")

    data = frame.loc[:, ["time_utc", "open", "high", "low", "close"]].copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)
    for column in ("open", "high", "low", "close"):
        data[column] = data[column].astype(float)
    return data.sort_values("time_utc").reset_index(drop=True)


def _detect_from_origin(
    data: pd.DataFrame,
    levels_by_bar: list[list[LPLevel]],
    origin_index: int,
    side: FlushSide,
    config: MajorityFlushConfig,
) -> MajorityFlushMove | None:
    start_index = origin_index + 1
    if side == "downside":
        if not _is_downside_origin(data, origin_index) or data.at[start_index, "low"] >= data.at[origin_index, "low"]:
            return None
        origin_price = float(data.at[origin_index, "high"])
        direction_level_side: ForcedLPSide = "support"
        completion_price_column = "low"
    else:
        if not _is_upside_origin(data, origin_index) or data.at[start_index, "high"] <= data.at[origin_index, "high"]:
            return None
        origin_price = float(data.at[origin_index, "low"])
        direction_level_side = "resistance"
        completion_price_column = "high"

    flush_start_price = float(data.at[start_index, "open"])
    best_direction_price = float(data.at[origin_index, completion_price_column])
    no_progress_count = 0
    inside_count = 0
    constipated_bar_count = 0
    forced: list[ForcedLP] = []

    for current_index in range(start_index, len(data)):
        current_high = float(data.at[current_index, "high"])
        current_low = float(data.at[current_index, "low"])
        current_open = float(data.at[current_index, "open"])
        current_close = float(data.at[current_index, "close"])
        previous_high = float(data.at[current_index - 1, "high"])
        previous_low = float(data.at[current_index - 1, "low"])

        made_progress = current_low < best_direction_price if side == "downside" else current_high > best_direction_price
        if made_progress:
            best_direction_price = current_low if side == "downside" else current_high
            no_progress_count = 0
        else:
            no_progress_count += 1

        if current_high <= previous_high and current_low >= previous_low:
            inside_count += 1
            inside_bar = True
        else:
            inside_count = 0
            inside_bar = False

        counter_body = current_close > current_open if side == "downside" else current_close < current_open
        if not made_progress or inside_bar or counter_body:
            constipated_bar_count += 1

        if no_progress_count >= 2 or inside_count >= 2:
            break

        duration_bars = current_index - origin_index
        constipated_bar_ratio = constipated_bar_count / duration_bars
        active_before_bar = levels_by_bar[current_index - 1] if current_index > 0 else []
        for level in active_before_bar:
            if level.side != direction_level_side:
                continue
            forced_lp = _forced_lp_for_level(
                data,
                level,
                side=side,
                origin_price=origin_price,
                flush_start_price=flush_start_price,
                current_index=current_index,
                constipated_bar_ratio=constipated_bar_ratio,
                max_constipated_bar_ratio=config.max_constipated_bar_ratio,
            )
            if forced_lp is None:
                continue
            if (forced_lp.midpoint_passed and forced_lp.constipated_ratio_passed) or config.include_rejected:
                forced.append(forced_lp)

    accepted = [item for item in forced if item.midpoint_passed and item.constipated_ratio_passed]
    if not accepted:
        return None

    included = forced if config.include_rejected else accepted
    included = _sort_forced_lps(included, side)
    completion_index = max(item.first_force_index for item in included)
    completion_price = float(data.at[completion_index, completion_price_column])
    leg_slice = data.iloc[origin_index : completion_index + 1]
    return MajorityFlushMove(
        side=side,
        origin_index=origin_index,
        origin_time_utc=data.at[origin_index, "time_utc"],
        origin_price=origin_price,
        flush_start_index=start_index,
        flush_start_time_utc=data.at[start_index, "time_utc"],
        flush_start_price=flush_start_price,
        completion_index=completion_index,
        completion_time_utc=data.at[completion_index, "time_utc"],
        completion_price=completion_price,
        duration_bars=completion_index - origin_index,
        leg_high=float(leg_slice["high"].max()),
        leg_low=float(leg_slice["low"].min()),
        forced_lps=tuple(included),
    )


def _sort_forced_lps(items: list[ForcedLP], side: FlushSide) -> list[ForcedLP]:
    if side == "downside":
        return sorted(items, key=lambda item: (item.first_force_index, -item.price, item.pivot_index))
    return sorted(items, key=lambda item: (item.first_force_index, item.price, item.pivot_index))


def _is_downside_origin(data: pd.DataFrame, origin_index: int) -> bool:
    origin_high = float(data.at[origin_index, "high"])
    return origin_high > float(data.at[origin_index - 1, "high"]) and origin_high > float(data.at[origin_index + 1, "high"])


def _is_upside_origin(data: pd.DataFrame, origin_index: int) -> bool:
    origin_low = float(data.at[origin_index, "low"])
    return origin_low < float(data.at[origin_index - 1, "low"]) and origin_low < float(data.at[origin_index + 1, "low"])


def _forced_lp_for_level(
    data: pd.DataFrame,
    level: LPLevel,
    *,
    side: FlushSide,
    origin_price: float,
    flush_start_price: float,
    current_index: int,
    constipated_bar_ratio: float,
    max_constipated_bar_ratio: float,
) -> ForcedLP | None:
    current_high = float(data.at[current_index, "high"])
    current_low = float(data.at[current_index, "low"])
    if side == "downside":
        if origin_price <= level.price or current_low > level.price:
            return None
        midpoint = (origin_price + level.price) / 2.0
        midpoint_passed = flush_start_price > midpoint
        force_price = current_low
    else:
        if origin_price >= level.price or current_high < level.price:
            return None
        midpoint = (origin_price + level.price) / 2.0
        midpoint_passed = flush_start_price < midpoint
        force_price = current_high

    constipated_ratio_passed = constipated_bar_ratio <= max_constipated_bar_ratio
    invalidation_reason = None
    if not midpoint_passed:
        invalidation_reason = MIDPOINT_FAILED
    elif not constipated_ratio_passed:
        invalidation_reason = TOO_CONSTIPATED

    return ForcedLP(
        lp_side=level.side,
        price=level.price,
        pivot_index=level.pivot_index,
        pivot_time_utc=level.pivot_time_utc,
        confirmed_index=level.confirmed_index,
        confirmed_time_utc=level.confirmed_time_utc,
        midpoint=midpoint,
        first_force_index=current_index,
        first_force_time_utc=data.at[current_index, "time_utc"],
        first_force_price=force_price,
        constipated_bar_ratio=constipated_bar_ratio,
        midpoint_passed=midpoint_passed,
        constipated_ratio_passed=constipated_ratio_passed,
        invalidation_reason=invalidation_reason,
    )
