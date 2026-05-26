"""Baseline experiment harness for Majority Flush strategy research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import pandas as pd

from backtest_engine_lab import CostConfig, TradeRecord, TradeSetup, normalize_backtest_frame
from backtest_engine_lab import simulate_bracket_trade_on_normalized_frame

from .signals import MajorityFlushSignal, detect_majority_flush_strategy_signals


EntryModel = Literal["next_open"]
StopModel = Literal["flush_structure"]


@dataclass(frozen=True)
class TradeModelCandidate:
    """One Majority Flush baseline trade model."""

    candidate_id: str
    entry_model: EntryModel
    stop_model: StopModel
    target_r: float


@dataclass(frozen=True)
class SkippedTrade:
    """One signal skipped before simulation."""

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
class MajorityFlushExperimentResult:
    """Experiment output for one symbol/timeframe frame."""

    symbol: str
    timeframe: str
    candidates: list[TradeModelCandidate]
    signals: list[MajorityFlushSignal]
    trades: list[TradeRecord]
    skipped: list[SkippedTrade]


def baseline_candidate() -> TradeModelCandidate:
    """Return the fixed V1 baseline candidate."""

    return TradeModelCandidate(
        candidate_id="next_open__flush_structure__1r",
        entry_model="next_open",
        stop_model="flush_structure",
        target_r=1.0,
    )


def build_trade_setup(
    frame: pd.DataFrame,
    signal: MajorityFlushSignal,
    candidate: TradeModelCandidate,
    *,
    symbol: str,
    timeframe: str,
) -> TradeSetup | SkippedTrade:
    """Convert one Majority Flush signal into a fixed bracket setup."""

    data = normalize_backtest_frame(frame)
    return _build_trade_setup_on_normalized_frame(data, signal, candidate, symbol=symbol, timeframe=timeframe)


def _build_trade_setup_on_normalized_frame(
    data: pd.DataFrame,
    signal: MajorityFlushSignal,
    candidate: TradeModelCandidate,
    *,
    symbol: str,
    timeframe: str,
) -> TradeSetup | SkippedTrade:
    if candidate.entry_model != "next_open":
        return _skip(candidate, symbol, timeframe, signal, "unsupported_entry_model")
    if candidate.stop_model != "flush_structure":
        return _skip(candidate, symbol, timeframe, signal, "unsupported_stop_model")
    if candidate.target_r <= 0:
        return _skip(candidate, symbol, timeframe, signal, "invalid_target_r")

    entry_index = int(signal.execution_index) + 1
    if entry_index >= len(data):
        return _skip(candidate, symbol, timeframe, signal, "no_next_candle")

    entry_price = float(data.iloc[entry_index]["open"])
    stop_price = float(signal.structure_low if signal.side == "long" else signal.structure_high)
    risk = entry_price - stop_price if signal.side == "long" else stop_price - entry_price
    if risk <= 0:
        return _skip(candidate, symbol, timeframe, signal, "invalid_stop", detail=f"risk={risk:g}")

    target_price = entry_price + risk * candidate.target_r if signal.side == "long" else entry_price - risk * candidate.target_r
    return TradeSetup(
        setup_id=_setup_id(candidate, symbol, timeframe, signal),
        side=signal.side,
        entry_index=entry_index,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=float(target_price),
        symbol=symbol,
        timeframe=timeframe,
        signal_index=signal.execution_index,
        metadata={
            "candidate_id": candidate.candidate_id,
            "entry_model": candidate.entry_model,
            "stop_model": candidate.stop_model,
            "target_r": candidate.target_r,
            "flush_side": signal.flush_side,
            "lp_side": signal.lp_side,
            "lp_price": signal.lp_price,
            "lp_force_index": signal.lp_force_index,
            "lp_force_time_utc": str(signal.lp_force_time_utc),
            "origin_index": signal.origin_index,
            "origin_time_utc": str(signal.origin_time_utc),
            "flush_start_index": signal.flush_start_index,
            "flush_start_time_utc": str(signal.flush_start_time_utc),
            "execution_index": signal.execution_index,
            "execution_time_utc": str(signal.execution_time_utc),
            "bars_from_lp_break": signal.bars_from_lp_break,
            "structure_high": signal.structure_high,
            "structure_low": signal.structure_low,
            "forced_lp_count": signal.forced_lp_count,
        },
    )


def _skip(
    candidate: TradeModelCandidate,
    symbol: str,
    timeframe: str,
    signal: MajorityFlushSignal,
    reason: str,
    *,
    detail: str = "",
) -> SkippedTrade:
    return SkippedTrade(
        candidate_id=candidate.candidate_id,
        symbol=symbol,
        timeframe=timeframe,
        side=signal.side,
        signal_index=signal.execution_index,
        signal_time_utc=signal.execution_time_utc,
        reason=reason,
        detail=detail,
    )


def _setup_id(candidate: TradeModelCandidate, symbol: str, timeframe: str, signal: MajorityFlushSignal) -> str:
    return f"{symbol}_{timeframe}_{signal.execution_index}_{candidate.candidate_id}"


def run_majority_flush_experiment_on_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    candidates: list[TradeModelCandidate] | None = None,
    pivot_strength: int = 3,
    max_bars_from_lp_break: int = 6,
    costs: CostConfig | None = None,
) -> MajorityFlushExperimentResult:
    """Run configured Majority Flush trade-model candidates for one frame."""

    data = normalize_backtest_frame(frame)
    resolved_candidates = candidates or [baseline_candidate()]
    signals = detect_majority_flush_strategy_signals(
        data,
        timeframe,
        pivot_strength=pivot_strength,
        max_bars_from_lp_break=max_bars_from_lp_break,
    )
    cost_config = costs or CostConfig()
    trades: list[TradeRecord] = []
    skipped: list[SkippedTrade] = []
    for signal in signals:
        for candidate in resolved_candidates:
            setup = _build_trade_setup_on_normalized_frame(data, signal, candidate, symbol=symbol, timeframe=timeframe)
            if isinstance(setup, SkippedTrade):
                skipped.append(setup)
            else:
                trades.append(simulate_bracket_trade_on_normalized_frame(data, setup, costs=cost_config))
    return MajorityFlushExperimentResult(
        symbol=symbol,
        timeframe=timeframe,
        candidates=resolved_candidates,
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


def _max_closed_trade_drawdown(values: pd.Series) -> float:
    equity = values.cumsum()
    drawdown = equity.cummax() - equity
    return float(drawdown.max()) if len(drawdown) else 0.0


def summary_rows(trades: list[TradeRecord], *, group_fields: list[str]) -> list[dict[str, Any]]:
    """Aggregate trade records for reporting."""

    rows = [trade_report_row(trade) for trade in trades]
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    summaries: list[dict[str, Any]] = []
    groupby_key = group_fields[0] if len(group_fields) == 1 else group_fields
    for keys, group in frame.groupby(groupby_key, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        ordered = group.sort_values(["exit_time_utc", "entry_time_utc", "setup_id"])
        net_r = pd.to_numeric(ordered["net_r"], errors="coerce").fillna(0.0)
        gross_win = float(net_r[net_r > 0].sum())
        gross_loss = float(net_r[net_r < 0].sum())
        row = {field: value for field, value in zip(group_fields, keys)}
        row.update(
            {
                "trades": int(len(ordered)),
                "wins": int((net_r > 0).sum()),
                "losses": int((net_r < 0).sum()),
                "win_rate": float((net_r > 0).mean()) if len(ordered) else 0.0,
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()) if len(ordered) else 0.0,
                "median_net_r": float(net_r.median()) if len(ordered) else 0.0,
                "profit_factor": None if gross_loss == 0 else float(gross_win / abs(gross_loss)),
                "max_closed_trade_drawdown_r": _max_closed_trade_drawdown(net_r),
                "avg_bars_held": float(pd.to_numeric(ordered["bars_held"], errors="coerce").mean()),
                "target_exits": int((ordered["exit_reason"] == "target").sum()),
                "stop_exits": int((ordered["exit_reason"] == "stop").sum()),
                "same_bar_stop_exits": int((ordered["exit_reason"] == "same_bar_stop_priority").sum()),
                "end_of_data_exits": int((ordered["exit_reason"] == "end_of_data").sum()),
            }
        )
        summaries.append(row)
    return summaries
