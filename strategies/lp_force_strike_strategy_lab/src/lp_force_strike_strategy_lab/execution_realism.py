"""Bid/ask-aware execution realism research for LP + Force Strike."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import pandas as pd

from backtest_engine_lab import CostConfig, TradeRecord, TradeSetup

from .experiment import (
    LPForceStrikeExperimentResult,
    SkippedTrade,
    TradeModelCandidate,
    _setup_id,
    _skip,
    add_atr,
)
from .signals import LPForceStrikeSignal, detect_lp_force_strike_signals


@dataclass(frozen=True)
class ExecutionRealismVariant:
    """One execution-realism model variant."""

    execution_model: str
    stop_buffer_spread_mult: float = 0.0

    @property
    def variant_id(self) -> str:
        token = f"{float(self.stop_buffer_spread_mult):g}".replace(".", "p")
        return f"{self.execution_model}_buffer_{token}x"


def spread_price_from_row(row: pd.Series, costs: CostConfig) -> float:
    """Return the row's spread in price units using per-row point metadata."""

    point = point_from_row(row, costs)
    spread_points = spread_points_from_row(row, costs)
    return float(spread_points * point)


def point_from_row(row: pd.Series, costs: CostConfig) -> float:
    """Return the row's price point with the configured fallback."""

    return _finite_positive(row.get("point"), costs.point)


def spread_points_from_row(row: pd.Series, costs: CostConfig) -> float:
    """Return the row's spread points with the configured fallback."""

    if costs.use_candle_spread:
        return _finite_non_negative(row.get("spread_points"), costs.fallback_spread_points)
    return float(costs.fallback_spread_points)


def build_bid_ask_trade_setup(
    frame: pd.DataFrame,
    signal: LPForceStrikeSignal,
    candidate: TradeModelCandidate,
    *,
    symbol: str,
    timeframe: str,
    costs: CostConfig | None = None,
    atr_period: int = 14,
    max_entry_wait_bars: int = 6,
    stop_buffer_spread_mult: float = 0.0,
) -> TradeSetup | SkippedTrade:
    """Build a broker-side limit setup using bid/ask entry realism."""

    if max_entry_wait_bars < 1:
        raise ValueError("max_entry_wait_bars must be >= 1.")
    if stop_buffer_spread_mult < 0:
        raise ValueError("stop_buffer_spread_mult must be non-negative.")
    data = add_atr(frame, period=atr_period)
    return _build_bid_ask_trade_setup_from_prepared_frame(
        data,
        signal,
        candidate,
        symbol=symbol,
        timeframe=timeframe,
        costs=costs or CostConfig(),
        max_entry_wait_bars=max_entry_wait_bars,
        stop_buffer_spread_mult=stop_buffer_spread_mult,
    )


def simulate_bid_ask_bracket_trade_on_normalized_frame(
    frame: pd.DataFrame,
    setup: TradeSetup,
    *,
    costs: CostConfig | None = None,
) -> TradeRecord:
    """Simulate broker-side bracket exits on Bid/Ask candles.

    OHLC is treated as Bid. Ask is approximated as Bid plus the candle spread.
    Reference fill prices are broker order prices, so spread is not charged a
    second time as half-spread fill slippage.
    """

    data = frame
    _validate_setup(setup, len(data))
    cost_config = costs or CostConfig()
    risk = _risk_distance(setup)

    for index in range(int(setup.entry_index), len(data)):
        row = data.iloc[index]
        stop_hit, target_hit = _bid_ask_exit_hits(setup, row, cost_config)
        if stop_hit:
            reason = "same_bar_stop_priority" if target_hit else "stop"
            return _record_bid_ask_trade(
                setup=setup,
                data=data,
                exit_index=index,
                exit_reference=float(setup.stop_price),
                exit_reason=reason,
                risk=risk,
            )
        if target_hit:
            return _record_bid_ask_trade(
                setup=setup,
                data=data,
                exit_index=index,
                exit_reference=float(setup.target_price),
                exit_reason="target",
                risk=risk,
            )

    final_index = len(data) - 1
    return _record_bid_ask_trade(
        setup=setup,
        data=data,
        exit_index=final_index,
        exit_reference=float(data.iloc[final_index]["close"]),
        exit_reason="end_of_data",
        risk=risk,
    )


def run_lp_force_strike_execution_realism_on_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    candidate: TradeModelCandidate,
    variants: list[ExecutionRealismVariant],
    pivot_strength: int = 3,
    max_bars_from_lp_break: int = 6,
    atr_period: int = 14,
    max_entry_wait_bars: int = 6,
    costs: CostConfig | None = None,
    require_lp_pivot_before_fs_mother: bool = False,
) -> LPForceStrikeExperimentResult:
    """Run bid/ask execution-realism variants for one symbol/timeframe frame."""

    if not variants:
        raise ValueError("At least one execution realism variant is required.")
    data = add_atr(frame, period=atr_period)
    cost_config = costs or CostConfig()
    signals = detect_lp_force_strike_signals(
        data,
        timeframe,
        pivot_strength=pivot_strength,
        max_bars_from_lp_break=max_bars_from_lp_break,
        require_lp_pivot_before_fs_mother=require_lp_pivot_before_fs_mother,
    )
    trades: list[TradeRecord] = []
    skipped: list[SkippedTrade] = []
    for signal in signals:
        for variant in variants:
            if variant.execution_model != "bid_ask":
                raise ValueError(f"Unsupported execution realism model {variant.execution_model!r}.")
            setup = _build_bid_ask_trade_setup_from_prepared_frame(
                data,
                signal,
                candidate,
                symbol=symbol,
                timeframe=timeframe,
                costs=cost_config,
                max_entry_wait_bars=max_entry_wait_bars,
                stop_buffer_spread_mult=variant.stop_buffer_spread_mult,
            )
            if isinstance(setup, SkippedTrade):
                skipped.append(_with_variant_metadata(setup, variant))
                continue
            trades.append(simulate_bid_ask_bracket_trade_on_normalized_frame(data, setup, costs=cost_config))
    return LPForceStrikeExperimentResult(
        symbol=symbol,
        timeframe=timeframe,
        candidates=[candidate],
        signals=signals,
        trades=trades,
        skipped=skipped,
    )


def _build_bid_ask_trade_setup_from_prepared_frame(
    data: pd.DataFrame,
    signal: LPForceStrikeSignal,
    candidate: TradeModelCandidate,
    *,
    symbol: str,
    timeframe: str,
    costs: CostConfig,
    max_entry_wait_bars: int,
    stop_buffer_spread_mult: float,
) -> TradeSetup | SkippedTrade:
    signal_index = int(signal.fs_signal_index)
    if signal_index + 1 >= len(data):
        return _skip(candidate, symbol, timeframe, signal, "no_next_candle")

    side = "long" if signal.side == "bullish" else "short"
    signal_row = data.loc[signal_index]
    signal_point = point_from_row(signal_row, costs)
    signal_spread_points = spread_points_from_row(signal_row, costs)
    signal_spread_price = spread_price_from_row(signal_row, costs)
    stop_buffer_price = float(stop_buffer_spread_mult) * signal_spread_price
    structure_low = float(data.loc[signal.fs_mother_index : signal.fs_signal_index, "low"].min())
    structure_high = float(data.loc[signal.fs_mother_index : signal.fs_signal_index, "high"].max())
    stop_price = structure_low - stop_buffer_price if side == "long" else structure_high + stop_buffer_price
    entry = _resolve_bid_ask_entry(data, signal, candidate, max_entry_wait_bars=max_entry_wait_bars, costs=costs)
    if isinstance(entry, str):
        return _skip(candidate, symbol, timeframe, signal, entry)
    entry_index, entry_price = entry

    risk = float(entry_price - stop_price) if side == "long" else float(stop_price - entry_price)
    if risk <= 0:
        return _skip(candidate, symbol, timeframe, signal, "invalid_stop", detail=f"risk={risk:g}")

    atr = float(data.loc[entry_index, "atr"])
    if candidate.stop_model == "fs_structure_max_atr":
        if pd.isna(atr) or atr <= 0:
            return _skip(candidate, symbol, timeframe, signal, "missing_atr")
        assert candidate.max_risk_atr is not None
        max_risk = candidate.max_risk_atr * atr
        if risk > max_risk:
            return _skip(
                candidate,
                symbol,
                timeframe,
                signal,
                "risk_too_wide",
                detail=f"risk={risk:g} max_risk={max_risk:g} atr={atr:g}",
            )

    target_price = entry_price + risk * candidate.target_r if side == "long" else entry_price - risk * candidate.target_r
    variant = ExecutionRealismVariant("bid_ask", stop_buffer_spread_mult)
    return TradeSetup(
        setup_id=f"{_setup_id(candidate, symbol, timeframe, signal)}__{variant.variant_id}",
        side=side,
        entry_index=entry_index,
        entry_price=float(entry_price),
        stop_price=float(stop_price),
        target_price=float(target_price),
        symbol=symbol,
        timeframe=timeframe,
        signal_index=signal.fs_signal_index,
        metadata={
            "candidate_id": candidate.candidate_id,
            "execution_model": "bid_ask",
            "execution_variant_id": variant.variant_id,
            "entry_model": candidate.entry_model,
            "entry_wait_mode": "fixed_bars",
            "entry_wait_same_bar_priority": "entry",
            "entry_zone": candidate.entry_zone,
            "stop_model": candidate.stop_model,
            "exit_model": candidate.exit_model,
            "target_r": candidate.target_r,
            "max_risk_atr": candidate.max_risk_atr,
            "partial_target_r": candidate.partial_target_r,
            "partial_fraction": candidate.partial_fraction,
            "stop_buffer_spread_mult": float(stop_buffer_spread_mult),
            "stop_buffer_price": stop_buffer_price,
            "signal_point": signal_point,
            "signal_spread_points": signal_spread_points,
            "signal_spread_price": signal_spread_price,
            "signal_spread_to_risk": None if risk <= 0 else signal_spread_price / risk,
            "lp_price": signal.lp_price,
            "lp_break_index": signal.lp_break_index,
            "lp_break_time_utc": str(signal.lp_break_time_utc),
            "fs_mother_index": signal.fs_mother_index,
            "fs_signal_index": signal.fs_signal_index,
            "fs_signal_time_utc": str(signal.fs_signal_time_utc),
            "fs_total_bars": signal.fs_total_bars,
            "bars_from_lp_break": signal.bars_from_lp_break,
            "structure_low": structure_low,
            "structure_high": structure_high,
            "atr": None if pd.isna(atr) else atr,
            "risk_atr": None if pd.isna(atr) or atr <= 0 else risk / atr,
        },
    )


def _resolve_bid_ask_entry(
    data: pd.DataFrame,
    signal: LPForceStrikeSignal,
    candidate: TradeModelCandidate,
    *,
    max_entry_wait_bars: int,
    costs: CostConfig,
) -> tuple[int, float] | str:
    next_index = int(signal.fs_signal_index) + 1
    if candidate.entry_model == "next_open":
        return next_index, float(data.loc[next_index, "open"])

    signal_row = data.loc[signal.fs_signal_index]
    signal_high = float(signal_row["high"])
    signal_low = float(signal_row["low"])
    if signal_high <= signal_low:
        return "invalid_entry_range"
    zone = 0.5 if candidate.entry_model == "signal_midpoint_pullback" else float(candidate.entry_zone or 0.5)
    if candidate.entry_model not in {"signal_midpoint_pullback", "signal_zone_pullback"}:
        return "unsupported_entry_model"
    entry_price = signal_low + (signal_high - signal_low) * zone
    if signal.side == "bearish":
        entry_price = signal_high - (signal_high - signal_low) * zone

    final_index = min(len(data) - 1, int(signal.fs_signal_index) + max_entry_wait_bars)
    for entry_index in range(next_index, final_index + 1):
        row = data.loc[entry_index]
        if _bid_ask_entry_hit(signal, entry_price, row, costs):
            return entry_index, float(entry_price)
    return "entry_not_reached"


def _bid_ask_entry_hit(signal: LPForceStrikeSignal, entry_price: float, row: pd.Series, costs: CostConfig) -> bool:
    spread = spread_price_from_row(row, costs)
    if signal.side == "bullish":
        ask_low = float(row["low"]) + spread
        return ask_low <= entry_price
    return float(row["high"]) >= entry_price


def _bid_ask_exit_hits(setup: TradeSetup, row: pd.Series, costs: CostConfig) -> tuple[bool, bool]:
    spread = spread_price_from_row(row, costs)
    bid_high = float(row["high"])
    bid_low = float(row["low"])
    ask_high = bid_high + spread
    ask_low = bid_low + spread
    if setup.side == "long":
        return bid_low <= setup.stop_price, bid_high >= setup.target_price
    return ask_high >= setup.stop_price, ask_low <= setup.target_price


def _record_bid_ask_trade(
    *,
    setup: TradeSetup,
    data: pd.DataFrame,
    exit_index: int,
    exit_reference: float,
    exit_reason: str,
    risk: float,
) -> TradeRecord:
    entry_row = data.iloc[setup.entry_index]
    exit_row = data.iloc[exit_index]
    reference_r = _reference_r(setup, exit_reference, risk)
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
        entry_fill_price=float(setup.entry_price),
        exit_reference_price=float(exit_reference),
        exit_fill_price=float(exit_reference),
        stop_price=float(setup.stop_price),
        target_price=float(setup.target_price),
        risk_distance=risk,
        reference_r=reference_r,
        fill_r=reference_r,
        commission_r=0.0,
        net_r=reference_r,
        bars_held=int(exit_index - setup.entry_index + 1),
        exit_reason=exit_reason,  # type: ignore[arg-type]
        metadata=dict(setup.metadata),
    )


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


def _reference_r(setup: TradeSetup, exit_reference: float, risk: float) -> float:
    if setup.side == "long":
        return float((exit_reference - setup.entry_price) / risk)
    return float((setup.entry_price - exit_reference) / risk)


def _with_variant_metadata(skipped: SkippedTrade, variant: ExecutionRealismVariant) -> SkippedTrade:
    detail = skipped.detail
    variant_detail = f"execution_variant_id={variant.variant_id}"
    detail = variant_detail if not detail else f"{detail}; {variant_detail}"
    return SkippedTrade(
        candidate_id=skipped.candidate_id,
        symbol=skipped.symbol,
        timeframe=skipped.timeframe,
        side=skipped.side,
        signal_index=skipped.signal_index,
        signal_time_utc=skipped.signal_time_utc,
        reason=skipped.reason,
        detail=detail,
    )


def _finite_positive(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(fallback)
    if math.isfinite(number) and number > 0:
        return number
    return float(fallback)


def _finite_non_negative(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(fallback)
    if math.isfinite(number) and number >= 0:
        return number
    return float(fallback)
