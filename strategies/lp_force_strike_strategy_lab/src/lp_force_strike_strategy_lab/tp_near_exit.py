"""TP-near exit research for LP + Force Strike.

This module is deliberately research-only. It consumes historical candles and
`TradeSetup` objects; it does not know about MT5, live state, or broker orders.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import pandas as pd

from backtest_engine_lab import CostConfig, TradeRecord, TradeSetup

from .experiment import LPForceStrikeExperimentResult, SkippedTrade, TradeModelCandidate, add_atr
from .execution_realism import (
    _bid_ask_exit_hits,
    _build_bid_ask_trade_setup_from_prepared_frame,
    _record_bid_ask_trade,
    _risk_distance,
    _validate_setup,
    simulate_bid_ask_bracket_trade_on_normalized_frame,
    spread_price_from_row,
)
from .signals import detect_lp_force_strike_signals


TPNearMode = Literal["control", "close", "breakeven_protect", "lock_r_protect"]
TPNearThresholdMode = Literal["percent_to_target", "spread_multiple"]
TPNearOutcome = Literal[
    "unchanged",
    "saved_from_stop",
    "sacrificed_full_tp",
    "improved_end_of_data",
    "worsened_end_of_data",
    "same_bar_conflict",
]


@dataclass(frozen=True)
class TPNearExitVariant:
    """One V18 TP-near exit variant."""

    variant_id: str
    mode: TPNearMode
    threshold_mode: TPNearThresholdMode = "percent_to_target"
    threshold_value: float = 1.0
    lock_r: float = 0.0


def simulate_tp_near_exit_on_normalized_frame(
    frame: pd.DataFrame,
    setup: TradeSetup,
    variant: TPNearExitVariant,
    *,
    costs: CostConfig | None = None,
) -> TradeRecord:
    """Simulate one bid/ask bracket trade with optional TP-near behavior."""

    data = frame
    _validate_setup(setup, len(data))
    cost_config = costs or CostConfig()
    _validate_variant(variant)
    variant_setup = _setup_for_variant(setup, variant)
    if variant.mode == "control":
        return _with_variant_metadata(
            simulate_bid_ask_bracket_trade_on_normalized_frame(data, variant_setup, costs=cost_config),
            variant,
        )

    risk = _risk_distance(variant_setup)
    protection_active = False
    protected_stop = float(variant_setup.stop_price)
    protected_reason = "stop"
    trigger_index: int | None = None
    trigger_price: float | None = None

    for index in range(int(variant_setup.entry_index), len(data)):
        row = data.iloc[index]
        active_setup = (
            replace(variant_setup, stop_price=protected_stop)
            if protection_active
            else variant_setup
        )
        stop_hit, target_hit = _bid_ask_exit_hits(active_setup, row, cost_config)
        if stop_hit:
            reason = "same_bar_stop_priority" if target_hit else protected_reason
            trade = _record_bid_ask_trade(
                setup=replace(variant_setup, stop_price=protected_stop),
                data=data,
                exit_index=index,
                exit_reference=float(protected_stop),
                exit_reason=reason,
                risk=risk,
            )
            return _with_trigger_metadata(trade, trigger_index, trigger_price, protected_stop)
        if target_hit:
            trade = _record_bid_ask_trade(
                setup=variant_setup,
                data=data,
                exit_index=index,
                exit_reference=float(variant_setup.target_price),
                exit_reason="target",
                risk=risk,
            )
            return _with_trigger_metadata(trade, trigger_index, trigger_price, protected_stop)

        near_price = _near_trigger_price(variant_setup, row, variant, cost_config, risk)
        if _near_target_hit(variant_setup, row, near_price, cost_config):
            trigger_index = index
            trigger_price = near_price
            if variant.mode == "close":
                trade = _record_bid_ask_trade(
                    setup=variant_setup,
                    data=data,
                    exit_index=index,
                    exit_reference=near_price,
                    exit_reason="tp_near_close",
                    risk=risk,
                )
                return _with_trigger_metadata(trade, trigger_index, trigger_price, protected_stop)
            protection_active = True
            protected_stop = _protected_stop_price(variant_setup, variant, risk)
            protected_reason = (
                "tp_near_breakeven_stop"
                if variant.mode == "breakeven_protect"
                else "tp_near_lock_stop"
            )

    final_index = len(data) - 1
    trade = _record_bid_ask_trade(
        setup=variant_setup,
        data=data,
        exit_index=final_index,
        exit_reference=float(data.iloc[final_index]["close"]),
        exit_reason="end_of_data",
        risk=risk,
    )
    return _with_trigger_metadata(trade, trigger_index, trigger_price, protected_stop)


def _with_trigger_metadata(
    trade: TradeRecord,
    trigger_index: int | None,
    trigger_price: float | None,
    protected_stop: float,
) -> TradeRecord:
    if trigger_index is None:
        return trade
    metadata = dict(trade.metadata)
    metadata.update(
        {
            "tp_near_triggered": True,
            "tp_near_trigger_index": trigger_index,
            "tp_near_trigger_price": trigger_price,
            "tp_near_protected_stop": protected_stop,
        }
    )
    return replace(trade, metadata=metadata)


def classify_tp_near_outcome(control: TradeRecord, variant: TradeRecord) -> TPNearOutcome:
    """Classify how a V18 variant changed a control trade."""

    if (
        control.exit_reason == variant.exit_reason
        and control.exit_index == variant.exit_index
        and abs(float(control.net_r) - float(variant.net_r)) < 1e-9
    ):
        return "unchanged"
    if control.exit_reason == "same_bar_stop_priority" or variant.exit_reason == "same_bar_stop_priority":
        return "same_bar_conflict"
    if control.exit_reason == "stop" and float(variant.net_r) > float(control.net_r):
        return "saved_from_stop"
    if control.exit_reason == "target" and float(variant.net_r) < float(control.net_r):
        return "sacrificed_full_tp"
    if control.exit_reason == "end_of_data" and float(variant.net_r) > float(control.net_r):
        return "improved_end_of_data"
    if control.exit_reason == "end_of_data" and float(variant.net_r) < float(control.net_r):
        return "worsened_end_of_data"
    return "saved_from_stop" if float(variant.net_r) > float(control.net_r) else "sacrificed_full_tp"


def run_lp_force_strike_tp_near_exit_on_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    candidate: TradeModelCandidate,
    variants: list[TPNearExitVariant],
    pivot_strength: int = 3,
    max_bars_from_lp_break: int = 6,
    atr_period: int = 14,
    max_entry_wait_bars: int = 6,
    costs: CostConfig | None = None,
) -> LPForceStrikeExperimentResult:
    """Run V18 TP-near variants for one symbol/timeframe frame."""

    if not variants:
        raise ValueError("At least one TP-near variant is required.")
    for variant in variants:
        _validate_variant(variant)

    data = add_atr(frame, period=atr_period)
    cost_config = costs or CostConfig()
    signals = detect_lp_force_strike_signals(
        data,
        timeframe,
        pivot_strength=pivot_strength,
        max_bars_from_lp_break=max_bars_from_lp_break,
    )
    trades: list[TradeRecord] = []
    skipped: list[SkippedTrade] = []
    for signal in signals:
        setup = _build_bid_ask_trade_setup_from_prepared_frame(
            data,
            signal,
            candidate,
            symbol=symbol,
            timeframe=timeframe,
            costs=cost_config,
            max_entry_wait_bars=max_entry_wait_bars,
            stop_buffer_spread_mult=0.0,
        )
        if isinstance(setup, SkippedTrade):
            skipped.extend(_skipped_with_variant(setup, variant) for variant in variants)
            continue
        trades.extend(
            simulate_tp_near_exit_on_normalized_frame(data, setup, variant, costs=cost_config)
            for variant in variants
        )
    return LPForceStrikeExperimentResult(
        symbol=symbol,
        timeframe=timeframe,
        candidates=[candidate],
        signals=signals,
        trades=trades,
        skipped=skipped,
    )


def _validate_variant(variant: TPNearExitVariant) -> None:
    if not variant.variant_id:
        raise ValueError("TP-near variant_id is required.")
    if variant.mode not in {"control", "close", "breakeven_protect", "lock_r_protect"}:
        raise ValueError(f"Unsupported TP-near mode {variant.mode!r}.")
    if variant.mode == "control":
        return
    if variant.threshold_mode not in {"percent_to_target", "spread_multiple"}:
        raise ValueError(f"Unsupported TP-near threshold mode {variant.threshold_mode!r}.")
    if variant.threshold_value <= 0:
        raise ValueError("TP-near threshold_value must be positive.")
    if variant.threshold_mode == "percent_to_target" and variant.threshold_value > 1.0:
        raise ValueError("percent_to_target threshold_value must be <= 1.0.")
    if variant.mode == "lock_r_protect" and not (0.0 <= variant.lock_r < 1.0):
        raise ValueError("lock_r_protect requires 0 <= lock_r < 1.")


def _setup_for_variant(setup: TradeSetup, variant: TPNearExitVariant) -> TradeSetup:
    metadata = dict(setup.metadata)
    metadata.update(_variant_metadata(variant))
    return replace(setup, setup_id=f"{setup.setup_id}__{variant.variant_id}", metadata=metadata)


def _variant_metadata(variant: TPNearExitVariant) -> dict[str, object]:
    return {
        "tp_near_variant_id": variant.variant_id,
        "tp_near_mode": variant.mode,
        "tp_near_threshold_mode": variant.threshold_mode,
        "tp_near_threshold_value": float(variant.threshold_value),
        "tp_near_lock_r": float(variant.lock_r),
        "tp_near_triggered": False,
    }


def _with_variant_metadata(trade: TradeRecord, variant: TPNearExitVariant) -> TradeRecord:
    metadata = dict(trade.metadata)
    metadata.update(_variant_metadata(variant))
    return replace(trade, metadata=metadata)


def _near_trigger_price(
    setup: TradeSetup,
    row: pd.Series,
    variant: TPNearExitVariant,
    costs: CostConfig,
    risk: float,
) -> float:
    if variant.threshold_mode == "percent_to_target":
        return (
            float(setup.entry_price + risk * variant.threshold_value)
            if setup.side == "long"
            else float(setup.entry_price - risk * variant.threshold_value)
        )
    spread = spread_price_from_row(row, costs)
    distance = spread * float(variant.threshold_value)
    if setup.side == "long":
        return float(max(setup.entry_price, setup.target_price - distance))
    return float(min(setup.entry_price, setup.target_price + distance))


def _near_target_hit(setup: TradeSetup, row: pd.Series, trigger_price: float, costs: CostConfig) -> bool:
    spread = spread_price_from_row(row, costs)
    if setup.side == "long":
        return float(row["high"]) >= trigger_price
    ask_low = float(row["low"]) + spread
    return ask_low <= trigger_price


def _protected_stop_price(setup: TradeSetup, variant: TPNearExitVariant, risk: float) -> float:
    if variant.mode == "breakeven_protect":
        return float(setup.entry_price)
    if setup.side == "long":
        return float(setup.entry_price + risk * variant.lock_r)
    return float(setup.entry_price - risk * variant.lock_r)


def _skipped_with_variant(skipped: SkippedTrade, variant: TPNearExitVariant) -> SkippedTrade:
    detail = skipped.detail
    variant_detail = f"tp_near_variant_id={variant.variant_id}"
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
