"""LP + Force Strike trade-model experiment harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

import pandas as pd

from backtest_engine_lab import CostConfig, TradeRecord, TradeSetup, simulate_bracket_trade_on_normalized_frame

from .signals import LPForceStrikeSignal, detect_lp_force_strike_signals


EntryModel = Literal["next_open", "signal_midpoint_pullback", "signal_zone_pullback"]
StopModel = Literal["fs_structure", "fs_structure_max_atr"]
ExitModel = Literal["single_target", "partial_1r_runner"]


@dataclass(frozen=True)
class TradeModelCandidate:
    """One named trade-structuring candidate to test."""

    candidate_id: str
    entry_model: EntryModel
    stop_model: StopModel
    target_r: float
    max_risk_atr: float | None = None
    entry_zone: float | None = None
    exit_model: ExitModel = "single_target"
    partial_target_r: float = 1.0
    partial_fraction: float = 0.5


@dataclass(frozen=True)
class SkippedTrade:
    """One signal/candidate combination skipped before simulation."""

    candidate_id: str
    symbol: str
    timeframe: str
    side: str
    signal_index: int
    signal_time_utc: pd.Timestamp
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LPForceStrikeExperimentResult:
    """Experiment output for one symbol/timeframe frame."""

    symbol: str
    timeframe: str
    candidates: list[TradeModelCandidate]
    signals: list[LPForceStrikeSignal]
    trades: list[TradeRecord]
    skipped: list[SkippedTrade]


def make_trade_model_candidates(
    *,
    entry_models: list[str],
    stop_models: list[str],
    target_rs: list[float],
    max_risk_atrs: list[float],
    entry_zones: list[float] | None = None,
    exit_models: list[str] | None = None,
    partial_target_r: float = 1.0,
    partial_fraction: float = 0.5,
) -> list[TradeModelCandidate]:
    """Build candidate grid from config values."""

    if not 0 < partial_fraction < 1:
        raise ValueError("partial_fraction must be between 0 and 1.")
    zones = entry_zones or [0.5]
    for zone in zones:
        if not 0 < float(zone) < 1:
            raise ValueError("entry_zones must be between 0 and 1.")
    exits = exit_models or ["single_target"]
    for exit_model in exits:
        if exit_model not in {"single_target", "partial_1r_runner"}:
            raise ValueError(f"Unsupported exit model {exit_model!r}.")

    candidates: list[TradeModelCandidate] = []
    for entry_model in entry_models:
        if entry_model not in {"next_open", "signal_midpoint_pullback", "signal_zone_pullback"}:
            raise ValueError(f"Unsupported entry model {entry_model!r}.")
        entry_variants = zones if entry_model == "signal_zone_pullback" else [None]
        for stop_model in stop_models:
            if stop_model == "fs_structure":
                for entry_zone in entry_variants:
                    for exit_model in exits:
                        for target_r in _target_values_for_exit(target_rs, exit_model, partial_target_r):
                            candidates.append(
                                TradeModelCandidate(
                                    candidate_id=_candidate_id(
                                        entry_model,
                                        "fs_structure",
                                        target_r,
                                        entry_zone=entry_zone,
                                        exit_model=exit_model,
                                        partial_target_r=partial_target_r,
                                    ),
                                    entry_model=entry_model,  # type: ignore[arg-type]
                                    stop_model="fs_structure",
                                    target_r=float(target_r),
                                    entry_zone=None if entry_zone is None else float(entry_zone),
                                    exit_model=exit_model,  # type: ignore[arg-type]
                                    partial_target_r=float(partial_target_r),
                                    partial_fraction=float(partial_fraction),
                                )
                            )
            elif stop_model == "fs_structure_max_atr":
                for entry_zone in entry_variants:
                    for max_risk_atr in max_risk_atrs:
                        for exit_model in exits:
                            for target_r in _target_values_for_exit(target_rs, exit_model, partial_target_r):
                                candidates.append(
                                    TradeModelCandidate(
                                        candidate_id=_candidate_id(
                                            entry_model,
                                            "fs_structure_max_atr",
                                            target_r,
                                            entry_zone=entry_zone,
                                            max_risk_atr=max_risk_atr,
                                            exit_model=exit_model,
                                            partial_target_r=partial_target_r,
                                        ),
                                        entry_model=entry_model,  # type: ignore[arg-type]
                                        stop_model="fs_structure_max_atr",
                                        target_r=float(target_r),
                                        max_risk_atr=float(max_risk_atr),
                                        entry_zone=None if entry_zone is None else float(entry_zone),
                                        exit_model=exit_model,  # type: ignore[arg-type]
                                        partial_target_r=float(partial_target_r),
                                        partial_fraction=float(partial_fraction),
                                    )
                                )
            else:
                raise ValueError(f"Unsupported stop model {stop_model!r}.")
    return candidates


def _target_values_for_exit(target_rs: list[float], exit_model: str, partial_target_r: float) -> list[float]:
    values = [float(value) for value in target_rs]
    if exit_model == "partial_1r_runner":
        return [value for value in values if value > partial_target_r]
    return values


def _candidate_id(
    entry_model: str,
    stop_model: str,
    target_r: float,
    *,
    entry_zone: float | None = None,
    max_risk_atr: float | None = None,
    exit_model: str,
    partial_target_r: float,
) -> str:
    entry_label = entry_model
    if entry_model == "signal_zone_pullback":
        assert entry_zone is not None
        entry_label = f"signal_zone_{_number_label(entry_zone)}_pullback"

    if stop_model == "fs_structure":
        stop_label = "fs_structure"
    elif stop_model == "fs_structure_max_atr":
        assert max_risk_atr is not None
        stop_label = f"fs_structure_max_{_number_label(max_risk_atr)}atr"
    else:
        raise ValueError(f"Unsupported stop model {stop_model!r}.")

    if exit_model == "single_target":
        return f"{entry_label}__{stop_label}__{_target_label(target_r)}r"
    if exit_model == "partial_1r_runner":
        return f"{entry_label}__{stop_label}__partial_{_target_label(partial_target_r)}r_to_{_target_label(target_r)}r"
    raise ValueError(f"Unsupported exit model {exit_model!r}.")


def _number_label(value: float) -> str:
    return f"{float(value):g}".replace(".", "p")


def _target_label(value: float) -> str:
    return _number_label(value)


def _normalise_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"time_utc", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"LP Force Strike experiment frame is missing columns: {missing_text}")
    keep = ["time_utc", "open", "high", "low", "close"]
    for optional in ("spread_points", "point", "atr"):
        if optional in frame.columns:
            keep.append(optional)
    data = frame.loc[:, keep].copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)
    for column in [col for col in keep if col != "time_utc"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.sort_values("time_utc").reset_index(drop=True)


def add_atr(frame: pd.DataFrame, *, period: int = 14) -> pd.DataFrame:
    """Add a simple rolling ATR column with no future data."""

    if period < 1:
        raise ValueError("ATR period must be >= 1.")
    data = _normalise_frame(frame)
    if "atr" in data.columns:
        return data

    previous_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["atr"] = true_range.rolling(period, min_periods=period).mean()
    return data


def build_trade_setup(
    frame: pd.DataFrame,
    signal: LPForceStrikeSignal,
    candidate: TradeModelCandidate,
    *,
    symbol: str,
    timeframe: str,
    atr_period: int = 14,
    max_entry_wait_bars: int = 6,
) -> TradeSetup | SkippedTrade:
    """Convert one LP+FS signal and candidate into a fixed bracket setup."""

    if max_entry_wait_bars < 1:
        raise ValueError("max_entry_wait_bars must be >= 1.")
    data = add_atr(frame, period=atr_period)
    return _build_trade_setup_from_prepared_frame(
        data,
        signal,
        candidate,
        symbol=symbol,
        timeframe=timeframe,
        max_entry_wait_bars=max_entry_wait_bars,
    )


def _build_trade_setup_from_prepared_frame(
    data: pd.DataFrame,
    signal: LPForceStrikeSignal,
    candidate: TradeModelCandidate,
    *,
    symbol: str,
    timeframe: str,
    max_entry_wait_bars: int,
) -> TradeSetup | SkippedTrade:
    signal_index = int(signal.fs_signal_index)
    if signal_index + 1 >= len(data):
        return _skip(candidate, symbol, timeframe, signal, "no_next_candle")

    side = "long" if signal.side == "bullish" else "short"
    entry = _resolve_entry(data, signal, candidate, max_entry_wait_bars=max_entry_wait_bars)
    if isinstance(entry, str):
        return _skip(candidate, symbol, timeframe, signal, entry)
    entry_index, entry_price = entry

    structure_low = float(data.loc[signal.fs_mother_index : signal.fs_signal_index, "low"].min())
    structure_high = float(data.loc[signal.fs_mother_index : signal.fs_signal_index, "high"].max())
    stop_price = structure_low if side == "long" else structure_high
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
    setup_side = "long" if side == "long" else "short"
    return TradeSetup(
        setup_id=_setup_id(candidate, symbol, timeframe, signal),
        side=setup_side,
        entry_index=entry_index,
        entry_price=float(entry_price),
        stop_price=float(stop_price),
        target_price=float(target_price),
        symbol=symbol,
        timeframe=timeframe,
        signal_index=signal.fs_signal_index,
        metadata={
            "candidate_id": candidate.candidate_id,
            "entry_model": candidate.entry_model,
            "entry_zone": candidate.entry_zone,
            "stop_model": candidate.stop_model,
            "exit_model": candidate.exit_model,
            "target_r": candidate.target_r,
            "max_risk_atr": candidate.max_risk_atr,
            "partial_target_r": candidate.partial_target_r,
            "partial_fraction": candidate.partial_fraction,
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


def _resolve_entry(
    data: pd.DataFrame,
    signal: LPForceStrikeSignal,
    candidate: TradeModelCandidate,
    *,
    max_entry_wait_bars: int,
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

    final_index = min(len(data) - 1, signal.fs_signal_index + max_entry_wait_bars)
    for entry_index in range(next_index, final_index + 1):
        row = data.loc[entry_index]
        if signal.side == "bullish" and float(row["low"]) <= entry_price:
            return entry_index, entry_price
        if signal.side == "bearish" and float(row["high"]) >= entry_price:
            return entry_index, entry_price
    return "entry_not_reached"


def _skip(
    candidate: TradeModelCandidate,
    symbol: str,
    timeframe: str,
    signal: LPForceStrikeSignal,
    reason: str,
    *,
    detail: str = "",
) -> SkippedTrade:
    return SkippedTrade(
        candidate_id=candidate.candidate_id,
        symbol=symbol,
        timeframe=timeframe,
        side=signal.side,
        signal_index=signal.fs_signal_index,
        signal_time_utc=signal.fs_signal_time_utc,
        reason=reason,
        detail=detail,
    )


def _setup_id(candidate: TradeModelCandidate, symbol: str, timeframe: str, signal: LPForceStrikeSignal) -> str:
    return f"{symbol}_{timeframe}_{signal.fs_signal_index}_{candidate.candidate_id}"


def _target_price_for_r(setup: TradeSetup, target_r: float) -> float:
    risk = setup.entry_price - setup.stop_price if setup.side == "long" else setup.stop_price - setup.entry_price
    if setup.side == "long":
        return float(setup.entry_price + risk * target_r)
    return float(setup.entry_price - risk * target_r)


def _simulate_trade_setup(data: pd.DataFrame, setup: TradeSetup, candidate: TradeModelCandidate, costs: CostConfig) -> TradeRecord:
    if candidate.exit_model == "single_target":
        return simulate_bracket_trade_on_normalized_frame(data, setup, costs=costs)
    if candidate.exit_model == "partial_1r_runner":
        return _simulate_partial_1r_runner(data, setup, candidate, costs)
    raise ValueError(f"Unsupported exit model {candidate.exit_model!r}.")


def _simulate_partial_1r_runner(
    data: pd.DataFrame,
    setup: TradeSetup,
    candidate: TradeModelCandidate,
    costs: CostConfig,
) -> TradeRecord:
    if candidate.target_r <= candidate.partial_target_r:
        raise ValueError("Partial runner target_r must be greater than partial_target_r.")

    partial_target = _target_price_for_r(setup, candidate.partial_target_r)
    partial_setup = replace(
        setup,
        setup_id=f"{setup.setup_id}__partial",
        target_price=partial_target,
        metadata={**setup.metadata, "leg": "partial", "leg_fraction": candidate.partial_fraction},
    )
    runner_setup = replace(
        setup,
        setup_id=f"{setup.setup_id}__runner",
        metadata={**setup.metadata, "leg": "runner", "leg_fraction": 1.0 - candidate.partial_fraction},
    )
    partial = simulate_bracket_trade_on_normalized_frame(data, partial_setup, costs=costs)
    runner = simulate_bracket_trade_on_normalized_frame(data, runner_setup, costs=costs)
    first_weight = candidate.partial_fraction
    second_weight = 1.0 - candidate.partial_fraction
    exit_index = max(partial.exit_index, runner.exit_index)
    exit_row = data.iloc[exit_index]
    if partial.exit_reason == runner.exit_reason:
        exit_reason = partial.exit_reason
    else:
        exit_reason = "partial_exit"

    metadata = dict(setup.metadata)
    metadata.update(
        {
            "partial_exit": True,
            "partial_target_r": candidate.partial_target_r,
            "partial_fraction": candidate.partial_fraction,
            "partial_exit_index": partial.exit_index,
            "partial_exit_reason": partial.exit_reason,
            "runner_exit_index": runner.exit_index,
            "runner_exit_reason": runner.exit_reason,
            "runner_target_r": candidate.target_r,
        }
    )
    fill_r = partial.fill_r * first_weight + runner.fill_r * second_weight
    commission_r = partial.commission_r * first_weight + runner.commission_r * second_weight
    return TradeRecord(
        setup_id=setup.setup_id,
        symbol=setup.symbol,
        timeframe=setup.timeframe,
        side=setup.side,
        signal_index=setup.signal_index,
        entry_index=setup.entry_index,
        exit_index=int(exit_index),
        entry_time_utc=partial.entry_time_utc,
        exit_time_utc=exit_row["time_utc"],
        entry_reference_price=setup.entry_price,
        entry_fill_price=partial.entry_fill_price * first_weight + runner.entry_fill_price * second_weight,
        exit_reference_price=partial.exit_reference_price * first_weight + runner.exit_reference_price * second_weight,
        exit_fill_price=partial.exit_fill_price * first_weight + runner.exit_fill_price * second_weight,
        stop_price=setup.stop_price,
        target_price=setup.target_price,
        risk_distance=partial.risk_distance,
        reference_r=partial.reference_r * first_weight + runner.reference_r * second_weight,
        fill_r=fill_r,
        commission_r=commission_r,
        net_r=float(fill_r - commission_r),
        bars_held=int(exit_index - setup.entry_index + 1),
        exit_reason=exit_reason,  # type: ignore[arg-type]
        metadata=metadata,
    )


def run_lp_force_strike_experiment_on_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    candidates: list[TradeModelCandidate],
    pivot_strength: int = 3,
    max_bars_from_lp_break: int = 6,
    atr_period: int = 14,
    max_entry_wait_bars: int = 6,
    costs: CostConfig | None = None,
) -> LPForceStrikeExperimentResult:
    """Run all configured trade-model candidates for one symbol/timeframe."""

    data = add_atr(frame, period=atr_period)
    signals = detect_lp_force_strike_signals(
        data,
        timeframe,
        pivot_strength=pivot_strength,
        max_bars_from_lp_break=max_bars_from_lp_break,
    )
    trades: list[TradeRecord] = []
    skipped: list[SkippedTrade] = []
    cost_config = costs or CostConfig()
    for signal in signals:
        for candidate in candidates:
            setup = _build_trade_setup_from_prepared_frame(
                data,
                signal,
                candidate,
                symbol=symbol,
                timeframe=timeframe,
                max_entry_wait_bars=max_entry_wait_bars,
            )
            if isinstance(setup, SkippedTrade):
                skipped.append(setup)
                continue
            trades.append(_simulate_trade_setup(data, setup, candidate, cost_config))
    return LPForceStrikeExperimentResult(
        symbol=symbol,
        timeframe=timeframe,
        candidates=candidates,
        signals=signals,
        trades=trades,
        skipped=skipped,
    )


def trade_report_row(trade: TradeRecord) -> dict[str, Any]:
    """Flatten a trade record and metadata for CSV reports."""

    row = trade.to_dict()
    metadata = row.pop("metadata", {}) or {}
    for key, value in metadata.items():
        row[f"meta_{key}"] = value
    row["candidate_id"] = metadata.get("candidate_id", "")
    return row


def summary_rows(trades: list[TradeRecord], *, group_fields: list[str]) -> list[dict[str, Any]]:
    """Aggregate trade records for reporting."""

    rows = [trade_report_row(trade) for trade in trades]
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    summaries: list[dict[str, Any]] = []
    for keys, group in frame.groupby(group_fields, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        net_r = pd.to_numeric(group["net_r"], errors="coerce")
        wins = net_r[net_r > 0]
        losses = net_r[net_r < 0]
        gross_win = float(wins.sum())
        gross_loss = float(losses.sum())
        row = {field: value for field, value in zip(group_fields, keys)}
        row.update(
            {
                "trades": int(len(group)),
                "wins": int((net_r > 0).sum()),
                "losses": int((net_r < 0).sum()),
                "win_rate": float((net_r > 0).mean()) if len(group) else 0.0,
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()) if len(group) else 0.0,
                "median_net_r": float(net_r.median()) if len(group) else 0.0,
                "profit_factor": None if gross_loss == 0 else float(gross_win / abs(gross_loss)),
                "avg_bars_held": float(pd.to_numeric(group["bars_held"], errors="coerce").mean()),
                "target_exits": int((group["exit_reason"] == "target").sum()),
                "stop_exits": int((group["exit_reason"] == "stop").sum()),
                "same_bar_stop_exits": int((group["exit_reason"] == "same_bar_stop_priority").sum()),
                "end_of_data_exits": int((group["exit_reason"] == "end_of_data").sum()),
            }
        )
        summaries.append(row)
    return summaries
