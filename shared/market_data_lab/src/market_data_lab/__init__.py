"""Shared MT5 market-data tools for TradeAutomation research."""

from .datasets import (
    DatasetConfig,
    DatasetPullItem,
    dataset_coverage_report,
    load_dataset_config,
    pull_mt5_dataset,
    resolve_date_window,
)
from .mt5 import MT5PullResult, MT5SymbolAvailability, check_mt5_symbols, pull_mt5_rates, pull_symbol_rates, query_mt5_symbol
from .schema import REQUIRED_RATE_COLUMNS, normalize_rates_frame, validate_rates_frame
from .symbols import FOREX_MAJOR_CROSS_PAIRS, FOREX_MAJOR_CURRENCIES
from .storage import (
    build_dataset_manifest,
    dataset_status,
    load_rates_csv,
    load_rates_parquet,
    manifest_path,
    rates_parquet_path,
    rates_csv_path,
    read_json,
    symbol_timeframe_dir,
    write_dataset_manifest,
    write_json,
    write_rates_csv,
    write_rates_parquet,
)
from .timeframes import TimeframeSpec, get_timeframe_spec, mt5_timeframe_value, normalize_timeframe

__all__ = [
    "MT5PullResult",
    "MT5SymbolAvailability",
    "REQUIRED_RATE_COLUMNS",
    "FOREX_MAJOR_CROSS_PAIRS",
    "FOREX_MAJOR_CURRENCIES",
    "DatasetConfig",
    "DatasetPullItem",
    "TimeframeSpec",
    "build_dataset_manifest",
    "check_mt5_symbols",
    "dataset_coverage_report",
    "dataset_status",
    "get_timeframe_spec",
    "load_rates_csv",
    "load_rates_parquet",
    "load_dataset_config",
    "manifest_path",
    "mt5_timeframe_value",
    "normalize_rates_frame",
    "normalize_timeframe",
    "pull_mt5_rates",
    "pull_mt5_dataset",
    "pull_symbol_rates",
    "query_mt5_symbol",
    "rates_parquet_path",
    "rates_csv_path",
    "read_json",
    "resolve_date_window",
    "symbol_timeframe_dir",
    "validate_rates_frame",
    "write_dataset_manifest",
    "write_json",
    "write_rates_csv",
    "write_rates_parquet",
]
