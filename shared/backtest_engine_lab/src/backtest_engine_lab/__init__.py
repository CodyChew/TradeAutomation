"""Shared OHLC backtest mechanics for TradeAutomation strategy research."""

from .engine import (
    BacktestFrameInfo,
    CostConfig,
    TradeRecord,
    TradeSetup,
    drop_incomplete_last_bar,
    is_latest_bar_complete,
    normalize_backtest_frame,
    simulate_bracket_trade,
)

__all__ = [
    "BacktestFrameInfo",
    "CostConfig",
    "TradeRecord",
    "TradeSetup",
    "drop_incomplete_last_bar",
    "is_latest_bar_complete",
    "normalize_backtest_frame",
    "simulate_bracket_trade",
]
