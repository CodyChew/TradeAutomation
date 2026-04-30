"""Raw Force Strike pattern detection for strategy research.

This module intentionally contains only the reusable bar pattern. SMA context,
ATR, entries, exits, and risk rules belong in strategy labs that import this
module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


PatternSide = Literal["bullish", "bearish"]
BreakoutSide = Literal["below_mother_low", "above_mother_high"]


@dataclass(frozen=True)
class ForceStrikePattern:
    """One raw Force Strike pattern signal."""

    side: PatternSide
    direction: int
    mother_index: int
    signal_index: int
    mother_time_utc: pd.Timestamp
    signal_time_utc: pd.Timestamp
    mother_high: float
    mother_low: float
    structure_high: float
    structure_low: float
    total_bars: int
    breakout_side: BreakoutSide


def close_location(open_: float, high: float, low: float, close: float) -> float:
    """Return close location in bar range, with zero-range bars neutral."""

    del open_
    bar_range = float(high) - float(low)
    if bar_range <= 0:
        return 0.5
    return (float(close) - float(low)) / bar_range


def is_bullish_signal_bar(open_: float, high: float, low: float, close: float) -> bool:
    """A bullish signal closes in or above the upper third of its range."""

    return float(high) > float(low) and close_location(open_, high, low, close) >= (2.0 / 3.0)


def is_bearish_signal_bar(open_: float, high: float, low: float, close: float) -> bool:
    """A bearish signal closes in or below the lower third of its range."""

    return float(high) > float(low) and close_location(open_, high, low, close) <= (1.0 / 3.0)


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"time_utc", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Force Strike frame is missing required columns: {missing_text}")

    data = frame.loc[:, ["time_utc", "open", "high", "low", "close"]].copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)
    for column in ["open", "high", "low", "close"]:
        data[column] = data[column].astype(float)
    return data.sort_values("time_utc").reset_index(drop=True)


def _inside_mother(row: pd.Series, mother_high: float, mother_low: float) -> bool:
    return float(row["high"]) <= mother_high and float(row["low"]) >= mother_low


def _close_inside_mother(row: pd.Series, mother_high: float, mother_low: float) -> bool:
    return mother_low <= float(row["close"]) <= mother_high


def _pattern_from_window(
    data: pd.DataFrame,
    *,
    mother_index: int,
    signal_index: int,
) -> ForceStrikePattern | None:
    mother = data.iloc[mother_index]
    signal = data.iloc[signal_index]
    mother_high = float(mother["high"])
    mother_low = float(mother["low"])
    window = data.iloc[mother_index : signal_index + 1]
    after_mother = data.iloc[mother_index + 1 : signal_index + 1]

    broke_low = bool((after_mother["low"] < mother_low).any())
    broke_high = bool((after_mother["high"] > mother_high).any())
    if broke_low and broke_high:
        return None
    if not _close_inside_mother(signal, mother_high, mother_low):
        return None

    side: PatternSide | None = None
    direction = 0
    breakout_side: BreakoutSide | None = None
    if broke_low and is_bullish_signal_bar(signal["open"], signal["high"], signal["low"], signal["close"]):
        side = "bullish"
        direction = 1
        breakout_side = "below_mother_low"
    elif broke_high and is_bearish_signal_bar(signal["open"], signal["high"], signal["low"], signal["close"]):
        side = "bearish"
        direction = -1
        breakout_side = "above_mother_high"

    if side is None or breakout_side is None:
        return None

    return ForceStrikePattern(
        side=side,
        direction=direction,
        mother_index=mother_index,
        signal_index=signal_index,
        mother_time_utc=mother["time_utc"],
        signal_time_utc=signal["time_utc"],
        mother_high=mother_high,
        mother_low=mother_low,
        structure_high=float(window["high"].max()),
        structure_low=float(window["low"].min()),
        total_bars=int(signal_index - mother_index + 1),
        breakout_side=breakout_side,
    )


def detect_force_strike_patterns(
    frame: pd.DataFrame,
    *,
    min_total_bars: int = 3,
    max_total_bars: int = 6,
) -> list[ForceStrikePattern]:
    """Detect raw Force Strike patterns with no lookahead beyond the signal bar."""

    if min_total_bars < 3:
        raise ValueError("min_total_bars must be >= 3.")
    if max_total_bars < min_total_bars:
        raise ValueError("max_total_bars must be >= min_total_bars.")

    data = _normalise_frame(frame)
    patterns: list[ForceStrikePattern] = []
    last_mother = len(data) - min_total_bars

    for mother_index in range(max(last_mother + 1, 0)):
        mother = data.iloc[mother_index]
        mother_high = float(mother["high"])
        mother_low = float(mother["low"])
        first_baby_index = mother_index + 1
        if first_baby_index >= len(data):  # pragma: no cover
            continue  # pragma: no cover
        if not _inside_mother(data.iloc[first_baby_index], mother_high, mother_low):
            continue

        max_signal_index = min(mother_index + max_total_bars - 1, len(data) - 1)
        for signal_index in range(mother_index + min_total_bars - 1, max_signal_index + 1):
            pattern = _pattern_from_window(data, mother_index=mother_index, signal_index=signal_index)
            if pattern is not None:
                patterns.append(pattern)
                break

    return patterns
