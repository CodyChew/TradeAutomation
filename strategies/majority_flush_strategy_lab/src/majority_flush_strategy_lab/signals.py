"""Signal layer for the Majority Flush baseline strategy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import pandas as pd

from force_strike_pattern_lab import is_bearish_signal_bar, is_bullish_signal_bar
from majority_flush_lab import ForcedLP, MajorityFlushConfig, MajorityFlushMove, detect_majority_flushes


SignalSide = Literal["long", "short"]


@dataclass(frozen=True)
class MajorityFlushSignal:
    """One final-LP Majority Flush execution signal."""

    side: SignalSide
    flush_side: str
    lp_side: str
    lp_price: float
    lp_pivot_index: int
    lp_pivot_time_utc: pd.Timestamp
    lp_force_index: int
    lp_force_time_utc: pd.Timestamp
    origin_index: int
    origin_time_utc: pd.Timestamp
    origin_price: float
    flush_start_index: int
    flush_start_time_utc: pd.Timestamp
    flush_start_price: float
    execution_index: int
    execution_time_utc: pd.Timestamp
    bars_from_lp_break: int
    execution_open: float
    execution_high: float
    execution_low: float
    execution_close: float
    leg_high: float
    leg_low: float
    structure_high: float
    structure_low: float
    forced_lp_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"time_utc", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Majority Flush strategy frame is missing columns: {missing_text}")

    data = frame.loc[:, ["time_utc", "open", "high", "low", "close"]].copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)
    for column in ("open", "high", "low", "close"):
        data[column] = data[column].astype(float)
    return data.sort_values("time_utc").reset_index(drop=True)


def _final_forced_lp(move: MajorityFlushMove) -> ForcedLP:
    return move.forced_lps[-1]


def _execution_matches(side: SignalSide, row: pd.Series, lp_price: float) -> bool:
    open_ = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    if side == "short":
        return close < lp_price and is_bearish_signal_bar(open_, high, low, close)
    return close > lp_price and is_bullish_signal_bar(open_, high, low, close)


def _signal_from_execution(
    data: pd.DataFrame,
    move: MajorityFlushMove,
    forced_lp: ForcedLP,
    *,
    execution_index: int,
) -> MajorityFlushSignal:
    side: SignalSide = "short" if move.side == "upside" else "long"
    execution = data.iloc[execution_index]
    structure = data.iloc[move.origin_index : execution_index + 1]
    return MajorityFlushSignal(
        side=side,
        flush_side=move.side,
        lp_side=forced_lp.lp_side,
        lp_price=float(forced_lp.price),
        lp_pivot_index=int(forced_lp.pivot_index),
        lp_pivot_time_utc=forced_lp.pivot_time_utc,
        lp_force_index=int(forced_lp.first_force_index),
        lp_force_time_utc=forced_lp.first_force_time_utc,
        origin_index=int(move.origin_index),
        origin_time_utc=move.origin_time_utc,
        origin_price=float(move.origin_price),
        flush_start_index=int(move.flush_start_index),
        flush_start_time_utc=move.flush_start_time_utc,
        flush_start_price=float(move.flush_start_price),
        execution_index=int(execution_index),
        execution_time_utc=execution["time_utc"],
        bars_from_lp_break=int(execution_index - forced_lp.first_force_index + 1),
        execution_open=float(execution["open"]),
        execution_high=float(execution["high"]),
        execution_low=float(execution["low"]),
        execution_close=float(execution["close"]),
        leg_high=float(move.leg_high),
        leg_low=float(move.leg_low),
        structure_high=float(structure["high"].max()),
        structure_low=float(structure["low"].min()),
        forced_lp_count=int(len(move.forced_lps)),
    )


def detect_majority_flush_strategy_signals(
    frame: pd.DataFrame,
    timeframe: str | int | float,
    *,
    pivot_strength: int = 3,
    max_bars_from_lp_break: int = 6,
) -> list[MajorityFlushSignal]:
    """Detect final-LP Majority Flush execution signals."""

    if max_bars_from_lp_break < 1:
        raise ValueError("max_bars_from_lp_break must be >= 1.")

    data = _normalise_frame(frame)
    if data.empty:
        return []

    moves = detect_majority_flushes(
        data,
        timeframe,
        config=MajorityFlushConfig(pivot_strength=pivot_strength),
    )
    signals: list[MajorityFlushSignal] = []
    for move in moves:
        forced_lp = _final_forced_lp(move)
        side: SignalSide = "short" if move.side == "upside" else "long"
        final_index = min(len(data) - 1, forced_lp.first_force_index + max_bars_from_lp_break - 1)
        for execution_index in range(forced_lp.first_force_index, final_index + 1):
            if _execution_matches(side, data.iloc[execution_index], float(forced_lp.price)):
                signals.append(_signal_from_execution(data, move, forced_lp, execution_index=execution_index))
                break
    return signals
