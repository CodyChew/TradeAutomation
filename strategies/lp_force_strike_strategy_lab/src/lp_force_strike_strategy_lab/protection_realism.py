"""Lower-timeframe protection realism research for LP + Force Strike.

This module is research-only. It replays completed LPFS setups on a lower
timeframe so stop-protection variants do not assume an impossible instant
broker-side stop modification.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import pandas as pd

from backtest_engine_lab import CostConfig, TradeRecord, TradeSetup

from .execution_contract import timeframe_delta
from .execution_realism import (
    _bid_ask_entry_hit,
    _bid_ask_exit_hits,
    _build_bid_ask_trade_setup_from_prepared_frame,
    _record_bid_ask_trade,
    _risk_distance,
    _validate_setup,
    simulate_bid_ask_bracket_trade_on_normalized_frame,
    spread_price_from_row,
)
from .experiment import LPForceStrikeExperimentResult, SkippedTrade, TradeModelCandidate, add_atr
from .signals import LPForceStrikeSignal, detect_lp_force_strike_signals


ProtectionMode = Literal["control", "lock_r_protect"]
ActivationModel = Literal["next_m30_open", "same_m30_assumed"]


@dataclass(frozen=True)
class ProtectionRealismVariant:
    """One lower-timeframe protection replay variant."""

    variant_id: str
    mode: ProtectionMode
    threshold_r: float = 0.9
    lock_r: float = 0.5
    activation_delay_m30_bars: int = 0
    activation_model: ActivationModel = "next_m30_open"
    min_stop_distance_spread_mult: float = 0.0
    retry_rejected_modification: bool = False


def simulate_protection_realism_on_m30_frame(
    frame: pd.DataFrame,
    setup: TradeSetup,
    variant: ProtectionRealismVariant,
    *,
    costs: CostConfig | None = None,
) -> TradeRecord:
    """Replay one setup on M30 candles with optional delayed stop protection.

    OHLC is treated as Bid and Ask is approximated from the candle spread. A
    lock-stop trigger is only allowed to modify the stop on a later M30 candle.
    If price snaps from the trigger area back through the proposed locked stop
    before that later candle, the protection is rejected instead of credited.
    """

    data = _normalise_replay_frame(frame)
    _validate_setup(setup, len(data))
    _validate_variant(variant)
    cost_config = costs or CostConfig()
    variant_setup = _setup_for_variant(setup, variant)
    if variant.mode == "control":
        return _with_protection_metadata(
            simulate_bid_ask_bracket_trade_on_normalized_frame(data, variant_setup, costs=cost_config),
            trigger_index=None,
            trigger_price=None,
            activation_index=None,
            activation_status="not_triggered",
            rejected_attempts=0,
            protected_stop=float(variant_setup.stop_price),
        )

    risk = _risk_distance(variant_setup)
    protected_stop = _protected_stop_price(variant_setup, variant, risk)
    protection_active = False
    trigger_index: int | None = None
    trigger_price: float | None = None
    activation_index: int | None = None
    pending_activation_index: int | None = None
    activation_status = "not_triggered"
    rejected_attempts = 0

    for index in range(int(variant_setup.entry_index), len(data)):
        row = data.iloc[index]
        if (
            pending_activation_index is not None
            and not protection_active
            and index >= pending_activation_index
            and activation_status != "rejected_too_late"
        ):
            allowed, reason = _stop_modification_allowed(
                variant_setup,
                row,
                protected_stop,
                variant,
                cost_config,
            )
            if allowed:
                protection_active = True
                activation_index = index
                activation_status = "activated"
                pending_activation_index = None
            else:
                rejected_attempts += 1
                activation_status = reason
                if variant.retry_rejected_modification:
                    pending_activation_index = index + 1
                else:
                    pending_activation_index = None

        active_setup = replace(variant_setup, stop_price=protected_stop) if protection_active else variant_setup
        stop_hit, target_hit = _bid_ask_exit_hits(active_setup, row, cost_config)
        if stop_hit:
            reason = "same_bar_stop_priority" if target_hit else ("tp_near_lock_stop" if protection_active else "stop")
            trade = _record_bid_ask_trade(
                setup=active_setup,
                data=data,
                exit_index=index,
                exit_reference=float(active_setup.stop_price),
                exit_reason=reason,
                risk=risk,
            )
            return _with_protection_metadata(
                trade,
                trigger_index=trigger_index,
                trigger_price=trigger_price,
                activation_index=activation_index,
                activation_status=activation_status,
                rejected_attempts=rejected_attempts,
                protected_stop=protected_stop,
            )
        if target_hit:
            trade = _record_bid_ask_trade(
                setup=variant_setup,
                data=data,
                exit_index=index,
                exit_reference=float(variant_setup.target_price),
                exit_reason="target",
                risk=risk,
            )
            return _with_protection_metadata(
                trade,
                trigger_index=trigger_index,
                trigger_price=trigger_price,
                activation_index=activation_index,
                activation_status=activation_status,
                rejected_attempts=rejected_attempts,
                protected_stop=protected_stop,
            )

        near_price = _near_trigger_price(variant_setup, variant, risk)
        if trigger_index is None and _near_target_hit(variant_setup, row, near_price, cost_config):
            trigger_index = index
            trigger_price = near_price
            if variant.activation_model == "same_m30_assumed" and int(variant.activation_delay_m30_bars) == 0:
                protection_active = True
                activation_index = index
                activation_status = "activated_same_m30_assumed"
            else:
                activation_status = "pending"
                pending_activation_index = index + 1 + int(variant.activation_delay_m30_bars)

    final_index = len(data) - 1
    trade = _record_bid_ask_trade(
        setup=variant_setup,
        data=data,
        exit_index=final_index,
        exit_reference=float(data.iloc[final_index]["close"]),
        exit_reason="end_of_data",
        risk=risk,
    )
    return _with_protection_metadata(
        trade,
        trigger_index=trigger_index,
        trigger_price=trigger_price,
        activation_index=activation_index,
        activation_status=activation_status,
        rejected_attempts=rejected_attempts,
        protected_stop=protected_stop,
    )


def run_lp_force_strike_m30_protection_realism_on_frame(
    frame: pd.DataFrame,
    m30_frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    candidate: TradeModelCandidate,
    variants: list[ProtectionRealismVariant],
    pivot_strength: int = 3,
    max_bars_from_lp_break: int = 6,
    atr_period: int = 14,
    max_entry_wait_bars: int = 6,
    costs: CostConfig | None = None,
) -> LPForceStrikeExperimentResult:
    """Run M30 replay protection variants for one LPFS symbol/timeframe."""

    if not variants:
        raise ValueError("At least one protection realism variant is required.")
    for variant in variants:
        _validate_variant(variant)

    data = add_atr(frame, period=atr_period)
    replay = _normalise_replay_frame(m30_frame)
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
        high_setup = _build_bid_ask_trade_setup_from_prepared_frame(
            data,
            signal,
            candidate,
            symbol=symbol,
            timeframe=timeframe,
            costs=cost_config,
            max_entry_wait_bars=max_entry_wait_bars,
            stop_buffer_spread_mult=0.0,
        )
        if isinstance(high_setup, SkippedTrade):
            skipped.extend(_skipped_with_variant(high_setup, variant) for variant in variants)
            continue
        replay_setup = _m30_replay_setup(
            replay,
            high_setup,
            signal,
            timeframe=timeframe,
            max_entry_wait_bars=max_entry_wait_bars,
            costs=cost_config,
        )
        if isinstance(replay_setup, SkippedTrade):
            skipped.extend(_skipped_with_variant(replay_setup, variant) for variant in variants)
            continue
        trades.extend(
            simulate_protection_realism_on_m30_frame(replay, replay_setup, variant, costs=cost_config)
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


def _normalise_replay_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"time_utc", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"M30 replay frame is missing required columns: {missing_text}")
    data = frame.copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)
    for column in ["open", "high", "low", "close"]:
        data[column] = data[column].astype(float)
    return data.sort_values("time_utc").reset_index(drop=True)


def _validate_variant(variant: ProtectionRealismVariant) -> None:
    if not variant.variant_id:
        raise ValueError("Protection variant_id is required.")
    if variant.mode not in {"control", "lock_r_protect"}:
        raise ValueError(f"Unsupported protection mode {variant.mode!r}.")
    if variant.mode == "control":
        return
    if not 0 < float(variant.threshold_r) <= 1.0:
        raise ValueError("threshold_r must be between 0 and 1.")
    if not 0 <= float(variant.lock_r) < 1.0:
        raise ValueError("lock_r must be between 0 and 1.")
    if variant.lock_r >= variant.threshold_r:
        raise ValueError("lock_r must be below threshold_r.")
    if int(variant.activation_delay_m30_bars) != variant.activation_delay_m30_bars or variant.activation_delay_m30_bars < 0:
        raise ValueError("activation_delay_m30_bars must be a non-negative integer.")
    if variant.activation_model not in {"next_m30_open", "same_m30_assumed"}:
        raise ValueError(f"Unsupported activation_model {variant.activation_model!r}.")
    if variant.activation_model == "same_m30_assumed" and variant.min_stop_distance_spread_mult > 0:
        raise ValueError("same_m30_assumed cannot model broker min-stop-distance checks without sub-M30 data.")
    if variant.min_stop_distance_spread_mult < 0:
        raise ValueError("min_stop_distance_spread_mult must be non-negative.")


def _setup_for_variant(setup: TradeSetup, variant: ProtectionRealismVariant) -> TradeSetup:
    metadata = dict(setup.metadata)
    metadata.update(_variant_metadata(variant))
    return replace(setup, setup_id=f"{setup.setup_id}__{variant.variant_id}", metadata=metadata)


def _variant_metadata(variant: ProtectionRealismVariant) -> dict[str, object]:
    return {
        "tp_near_variant_id": variant.variant_id,
        "tp_near_mode": "control" if variant.mode == "control" else "m30_lock_r_protect",
        "tp_near_threshold_mode": "percent_to_target",
        "tp_near_threshold_value": float(variant.threshold_r),
        "tp_near_lock_r": float(variant.lock_r),
        "tp_near_activation_delay_bars": int(variant.activation_delay_m30_bars),
        "tp_near_full_target_priority": True,
        "tp_near_triggered": False,
        "protection_replay_timeframe": "M30",
        "protection_activation_model": variant.activation_model,
        "protection_min_stop_distance_spread_mult": float(variant.min_stop_distance_spread_mult),
        "protection_retry_rejected_modification": bool(variant.retry_rejected_modification),
        "protection_activated": False,
        "protection_activation_status": "not_triggered",
        "protection_rejected_attempts": 0,
    }


def _m30_replay_setup(
    replay: pd.DataFrame,
    high_setup: TradeSetup,
    signal: LPForceStrikeSignal,
    *,
    timeframe: str,
    max_entry_wait_bars: int,
    costs: CostConfig,
) -> TradeSetup | SkippedTrade:
    signal_time = _as_utc(signal.fs_signal_time_utc)
    duration = timeframe_delta(timeframe)
    window_start = signal_time + duration
    window_end = signal_time + duration * (max_entry_wait_bars + 1)
    window = replay[(replay["time_utc"] >= window_start) & (replay["time_utc"] < window_end)]
    if window.empty:
        return _replay_skip(high_setup, signal, "m30_entry_window_empty")
    for entry_index, row in window.iterrows():
        if _bid_ask_entry_hit(signal, float(high_setup.entry_price), row, costs):
            metadata = dict(high_setup.metadata)
            metadata.update(
                {
                    "replay_timeframe": "M30",
                    "replay_entry_model": "first_m30_bid_ask_touch",
                    "high_timeframe_entry_index": int(high_setup.entry_index),
                    "high_timeframe_entry_time_utc": str(high_setup.metadata.get("fs_signal_time_utc", "")),
                    "m30_entry_index": int(entry_index),
                    "m30_entry_time_utc": str(row["time_utc"]),
                    "m30_entry_window_start_utc": str(window_start),
                    "m30_entry_window_end_utc": str(window_end),
                }
            )
            return replace(
                high_setup,
                setup_id=f"{high_setup.setup_id}__m30_replay",
                entry_index=int(entry_index),
                metadata=metadata,
            )
    return _replay_skip(high_setup, signal, "m30_entry_not_reached")


def _replay_skip(high_setup: TradeSetup, signal: LPForceStrikeSignal, reason: str) -> SkippedTrade:
    return SkippedTrade(
        candidate_id=str(high_setup.metadata.get("candidate_id", "unknown_candidate")),
        symbol=high_setup.symbol,
        timeframe=high_setup.timeframe,
        side=high_setup.side,
        signal_index=int(signal.fs_signal_index),
        signal_time_utc=signal.fs_signal_time_utc,
        reason=reason,
        detail=f"replay_timeframe=M30; high_setup_id={high_setup.setup_id}",
    )


def _skipped_with_variant(skipped: SkippedTrade, variant: ProtectionRealismVariant) -> SkippedTrade:
    detail = skipped.detail
    variant_detail = f"tp_near_variant_id={variant.variant_id}; protection_replay_timeframe=M30"
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


def _with_protection_metadata(
    trade: TradeRecord,
    *,
    trigger_index: int | None,
    trigger_price: float | None,
    activation_index: int | None,
    activation_status: str,
    rejected_attempts: int,
    protected_stop: float,
) -> TradeRecord:
    metadata = dict(trade.metadata)
    if trigger_index is not None:
        metadata.update(
            {
                "tp_near_triggered": True,
                "tp_near_trigger_index": int(trigger_index),
                "tp_near_trigger_price": float(trigger_price),
            }
        )
    metadata.update(
        {
            "tp_near_protected_stop": float(protected_stop),
            "protection_activated": activation_index is not None,
            "protection_activation_index": activation_index,
            "protection_activation_status": activation_status,
            "protection_rejected_attempts": int(rejected_attempts),
        }
    )
    return replace(trade, metadata=metadata)


def _near_trigger_price(setup: TradeSetup, variant: ProtectionRealismVariant, risk: float) -> float:
    if setup.side == "long":
        return float(setup.entry_price + risk * float(variant.threshold_r))
    return float(setup.entry_price - risk * float(variant.threshold_r))


def _near_target_hit(setup: TradeSetup, row: pd.Series, trigger_price: float, costs: CostConfig) -> bool:
    spread = spread_price_from_row(row, costs)
    if setup.side == "long":
        return float(row["high"]) >= trigger_price
    return float(row["low"]) + spread <= trigger_price


def _protected_stop_price(setup: TradeSetup, variant: ProtectionRealismVariant, risk: float) -> float:
    if setup.side == "long":
        return float(setup.entry_price + risk * float(variant.lock_r))
    return float(setup.entry_price - risk * float(variant.lock_r))


def _stop_modification_allowed(
    setup: TradeSetup,
    row: pd.Series,
    protected_stop: float,
    variant: ProtectionRealismVariant,
    costs: CostConfig,
) -> tuple[bool, str]:
    spread = spread_price_from_row(row, costs)
    min_distance = spread * float(variant.min_stop_distance_spread_mult)
    bid_open = float(row["open"])
    ask_open = bid_open + spread
    if setup.side == "long":
        if bid_open <= protected_stop:
            return False, "rejected_too_late"
        if bid_open - protected_stop < min_distance:
            return False, "rejected_min_stop_distance"
        return True, "activated"
    if ask_open >= protected_stop:
        return False, "rejected_too_late"
    if protected_stop - ask_open < min_distance:
        return False, "rejected_min_stop_distance"
    return True, "activated"


def _as_utc(value: pd.Timestamp | str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")
