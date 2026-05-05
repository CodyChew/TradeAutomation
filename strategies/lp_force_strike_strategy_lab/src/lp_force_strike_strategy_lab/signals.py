"""Signal study combining LP level traps with raw Force Strike patterns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from force_strike_pattern_lab import ForceStrikePattern, detect_force_strike_patterns
from lp_levels_lab import LPBreakEvent, lp_break_events_by_bar


SignalSide = Literal["bullish", "bearish"]
Scenario = Literal["force_bottom", "force_top"]


@dataclass(frozen=True)
class LPForceStrikeSignal:
    """One LP trap confirmed by a raw Force Strike signal candle."""

    side: SignalSide
    scenario: Scenario
    lp_price: float
    lp_break_index: int
    lp_break_time_utc: pd.Timestamp
    lp_pivot_index: int
    lp_pivot_time_utc: pd.Timestamp
    fs_mother_index: int
    fs_signal_index: int
    fs_mother_time_utc: pd.Timestamp
    fs_signal_time_utc: pd.Timestamp
    bars_from_lp_break: int
    fs_total_bars: int


@dataclass(frozen=True)
class _TrapWindow:
    side: SignalSide
    scenario: Scenario
    lp_event: LPBreakEvent


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"time_utc", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"LP Force Strike frame is missing required columns: {missing_text}")

    data = frame.loc[:, ["time_utc", "open", "high", "low", "close"]].copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)
    for column in ["open", "high", "low", "close"]:
        data[column] = data[column].astype(float)
    return data.sort_values("time_utc").reset_index(drop=True)


def _trap_windows_from_breaks(events: list[LPBreakEvent]) -> list[_TrapWindow]:
    supports = [event for event in events if event.side == "support"]
    resistances = [event for event in events if event.side == "resistance"]
    windows: list[_TrapWindow] = []
    if supports:
        windows.append(_TrapWindow(side="bullish", scenario="force_bottom", lp_event=min(supports, key=lambda event: event.price)))
    if resistances:
        windows.append(_TrapWindow(side="bearish", scenario="force_top", lp_event=max(resistances, key=lambda event: event.price)))
    return windows


def _pattern_by_signal_index(patterns: list[ForceStrikePattern]) -> dict[int, ForceStrikePattern]:
    by_index: dict[int, ForceStrikePattern] = {}
    for pattern in patterns:
        by_index.setdefault(pattern.signal_index, pattern)
    return by_index


def _window_matches_pattern(
    window: _TrapWindow,
    pattern: ForceStrikePattern,
    *,
    signal_close: float,
    max_bars_from_lp_break: int,
    require_lp_pivot_before_fs_mother: bool = True,
) -> bool:
    if window.side != pattern.side:
        return False
    if require_lp_pivot_before_fs_mother and window.lp_event.pivot_index >= pattern.mother_index:
        return False
    bars_from_break = pattern.signal_index - window.lp_event.break_index + 1
    if bars_from_break < 1 or bars_from_break > max_bars_from_lp_break:
        return False
    if window.side == "bullish":
        return signal_close >= window.lp_event.price
    return signal_close <= window.lp_event.price


def _signal_from_match(window: _TrapWindow, pattern: ForceStrikePattern) -> LPForceStrikeSignal:
    return LPForceStrikeSignal(
        side=window.side,
        scenario=window.scenario,
        lp_price=window.lp_event.price,
        lp_break_index=window.lp_event.break_index,
        lp_break_time_utc=window.lp_event.break_time_utc,
        lp_pivot_index=window.lp_event.pivot_index,
        lp_pivot_time_utc=window.lp_event.pivot_time_utc,
        fs_mother_index=pattern.mother_index,
        fs_signal_index=pattern.signal_index,
        fs_mother_time_utc=pattern.mother_time_utc,
        fs_signal_time_utc=pattern.signal_time_utc,
        bars_from_lp_break=pattern.signal_index - window.lp_event.break_index + 1,
        fs_total_bars=pattern.total_bars,
    )


def _select_matching_window(matches: list[_TrapWindow]) -> _TrapWindow:
    """Select the most extreme valid LP across the active trap window."""

    if not matches:
        raise ValueError("matches must not be empty.")
    side = matches[0].side
    if side == "bullish":
        return min(matches, key=lambda window: (window.lp_event.price, -window.lp_event.break_index))
    return max(matches, key=lambda window: (window.lp_event.price, window.lp_event.break_index))


def detect_lp_force_strike_signals(
    frame: pd.DataFrame,
    timeframe: str | int | float,
    *,
    pivot_strength: int = 3,
    max_bars_from_lp_break: int = 6,
    require_lp_pivot_before_fs_mother: bool = True,
) -> list[LPForceStrikeSignal]:
    """Detect LP trap signals confirmed by raw Force Strike patterns."""

    if max_bars_from_lp_break < 1:
        raise ValueError("max_bars_from_lp_break must be >= 1.")

    data = _normalise_frame(frame)
    if data.empty:
        return []

    break_events = lp_break_events_by_bar(data, timeframe, pivot_strength=pivot_strength)
    patterns = detect_force_strike_patterns(data)
    patterns_by_signal = _pattern_by_signal_index(patterns)
    closes = data["close"].tolist()

    open_windows: list[_TrapWindow] = []
    signals: list[LPForceStrikeSignal] = []

    for current_index, events in enumerate(break_events):
        open_windows.extend(_trap_windows_from_breaks(events))
        open_windows = [
            window
            for window in open_windows
            if current_index - window.lp_event.break_index + 1 <= max_bars_from_lp_break
        ]

        pattern = patterns_by_signal.get(current_index)
        if pattern is None:
            continue

        signal_close = closes[pattern.signal_index]
        matches = [
            window
            for window in open_windows
            if _window_matches_pattern(
                window,
                pattern,
                signal_close=signal_close,
                max_bars_from_lp_break=max_bars_from_lp_break,
                require_lp_pivot_before_fs_mother=require_lp_pivot_before_fs_mother,
            )
        ]
        if not matches:
            continue

        selected = _select_matching_window(matches)
        signals.append(_signal_from_match(selected, pattern))
        open_windows = [window for window in open_windows if window is not selected]

    return signals
