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
    simulate_bracket_trade_on_normalized_frame,
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
    "simulate_bracket_trade_on_normalized_frame",
]
