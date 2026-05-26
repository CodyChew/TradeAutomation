"""Majority Flush baseline strategy research."""

from .experiment import (
    MajorityFlushExperimentResult,
    SkippedTrade,
    TradeModelCandidate,
    build_trade_setup,
    baseline_candidate,
    run_majority_flush_experiment_on_frame,
    summary_rows,
    trade_report_row,
)
from .signals import (
    MajorityFlushSignal,
    detect_majority_flush_strategy_signals,
)

__all__ = [
    "MajorityFlushExperimentResult",
    "MajorityFlushSignal",
    "SkippedTrade",
    "TradeModelCandidate",
    "baseline_candidate",
    "build_trade_setup",
    "detect_majority_flush_strategy_signals",
    "run_majority_flush_experiment_on_frame",
    "summary_rows",
    "trade_report_row",
]
