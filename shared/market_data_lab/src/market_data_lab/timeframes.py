"""Supported timeframe registry for shared market data."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TimeframeSpec:
    """One normalized timeframe definition."""

    label: str
    mt5_constant_name: str
    pandas_freq: str
    expected_delta: pd.Timedelta


SUPPORTED_TIMEFRAMES: dict[str, TimeframeSpec] = {
    "M1": TimeframeSpec("M1", "TIMEFRAME_M1", "1min", pd.Timedelta(minutes=1)),
    "M5": TimeframeSpec("M5", "TIMEFRAME_M5", "5min", pd.Timedelta(minutes=5)),
    "M15": TimeframeSpec("M15", "TIMEFRAME_M15", "15min", pd.Timedelta(minutes=15)),
    "M30": TimeframeSpec("M30", "TIMEFRAME_M30", "30min", pd.Timedelta(minutes=30)),
    "H1": TimeframeSpec("H1", "TIMEFRAME_H1", "1h", pd.Timedelta(hours=1)),
    "H4": TimeframeSpec("H4", "TIMEFRAME_H4", "4h", pd.Timedelta(hours=4)),
    "H8": TimeframeSpec("H8", "TIMEFRAME_H8", "8h", pd.Timedelta(hours=8)),
    "H12": TimeframeSpec("H12", "TIMEFRAME_H12", "12h", pd.Timedelta(hours=12)),
    "D1": TimeframeSpec("D1", "TIMEFRAME_D1", "1D", pd.Timedelta(days=1)),
    "W1": TimeframeSpec("W1", "TIMEFRAME_W1", "1W", pd.Timedelta(days=7)),
    "MN1": TimeframeSpec("MN1", "TIMEFRAME_MN1", "30D", pd.Timedelta(days=30)),
}


def normalize_timeframe(value: str | int | float) -> str:
    """Return the canonical supported timeframe label."""

    if isinstance(value, (int, float)):
        if int(value) != float(value):
            raise ValueError(f"Unsupported non-integer timeframe {value!r}.")
        label = str(int(value))
    else:
        label = str(value).strip().upper()

    for prefix in ("PERIOD_", "TIMEFRAME_"):
        if label.startswith(prefix):
            label = label[len(prefix) :]

    aliases = {
        "1": "M1",
        "M1": "M1",
        "1MIN": "M1",
        "1MINUTE": "M1",
        "5": "M5",
        "5M": "M5",
        "M5": "M5",
        "5MIN": "M5",
        "15": "M15",
        "15M": "M15",
        "M15": "M15",
        "15MIN": "M15",
        "30": "M30",
        "30M": "M30",
        "M30": "M30",
        "30MIN": "M30",
        "60": "H1",
        "1H": "H1",
        "H1": "H1",
        "240": "H4",
        "4H": "H4",
        "H4": "H4",
        "480": "H8",
        "8H": "H8",
        "H8": "H8",
        "720": "H12",
        "12H": "H12",
        "H12": "H12",
        "D": "D1",
        "1D": "D1",
        "D1": "D1",
        "DAILY": "D1",
        "W": "W1",
        "1W": "W1",
        "W1": "W1",
        "WEEKLY": "W1",
        "MN": "MN1",
        "MN1": "MN1",
        "1MO": "MN1",
        "MONTHLY": "MN1",
    }
    if label not in aliases:
        supported = ", ".join(sorted(SUPPORTED_TIMEFRAMES))
        raise ValueError(f"Unsupported timeframe {value!r}; supported: {supported}")
    return aliases[label]


def get_timeframe_spec(value: str | int | float) -> TimeframeSpec:
    """Return the registry entry for a supported timeframe."""

    return SUPPORTED_TIMEFRAMES[normalize_timeframe(value)]


def mt5_timeframe_value(mt5_module, timeframe: str | int | float) -> int:
    """Resolve a timeframe to a MetaTrader5 constant value."""

    spec = get_timeframe_spec(timeframe)
    if not hasattr(mt5_module, spec.mt5_constant_name):
        raise ValueError(f"MetaTrader5 module does not expose {spec.mt5_constant_name}.")
    return int(getattr(mt5_module, spec.mt5_constant_name))
