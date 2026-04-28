"""Canonical candle schema and validation."""

from __future__ import annotations

import pandas as pd

from .timeframes import get_timeframe_spec, normalize_timeframe


REQUIRED_RATE_COLUMNS = [
    "time_utc",
    "symbol",
    "timeframe",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread_points",
    "real_volume",
]


def normalize_rates_frame(raw: pd.DataFrame, *, symbol: str, timeframe: str | int | float) -> pd.DataFrame:
    """Normalize raw MT5-style rates into the shared candle schema."""

    label = normalize_timeframe(timeframe)
    data = raw.copy()
    if "time_utc" not in data.columns:
        if "time" not in data.columns:
            raise ValueError("Rates frame must contain either time_utc or time.")
        data["time_utc"] = pd.to_datetime(data["time"], unit="s", utc=True)
    else:
        data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)

    if "spread" in data.columns and "spread_points" not in data.columns:
        data["spread_points"] = data["spread"]

    data["symbol"] = str(symbol).upper()
    data["timeframe"] = label
    for column in ("open", "high", "low", "close"):
        if column not in data.columns:
            raise ValueError(f"Rates frame missing required OHLC column {column!r}.")
        data[column] = pd.to_numeric(data[column], errors="coerce")

    for column in ("tick_volume", "spread_points", "real_volume"):
        if column not in data.columns:
            data[column] = pd.NA
        else:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    return (
        data.loc[:, REQUIRED_RATE_COLUMNS]
        .sort_values("time_utc")
        .drop_duplicates("time_utc", keep="last")
        .reset_index(drop=True)
    )


def validate_rates_frame(frame: pd.DataFrame, *, symbol: str, timeframe: str | int | float) -> None:
    """Raise if a canonical rates frame is not suitable for research."""

    missing = [column for column in REQUIRED_RATE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Rates frame missing columns: {missing}")
    label = normalize_timeframe(timeframe)
    if frame.empty:
        raise ValueError(f"No rows available for {symbol} {label}.")

    symbols = set(frame["symbol"].astype(str).str.upper())
    if symbols != {str(symbol).upper()}:
        raise ValueError(f"Rates frame contains symbols other than {symbol}.")

    timeframes = set(frame["timeframe"].astype(str).str.upper())
    if timeframes != {label}:
        raise ValueError(f"Rates frame contains timeframes other than {label}.")

    timestamps = pd.to_datetime(frame["time_utc"], utc=True)
    if timestamps.duplicated().any():
        raise ValueError("Rates frame contains duplicate timestamps.")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("Rates frame timestamps must be increasing.")

    for column in ("open", "high", "low", "close"):
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any():
            raise ValueError(f"Rates frame contains non-numeric {column} values.")

    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    open_ = frame["open"].astype(float)
    close = frame["close"].astype(float)
    if ((high < low) | (high < open_) | (high < close)).any():
        raise ValueError("Rates frame contains invalid high values.")
    if ((low > open_) | (low > close)).any():
        raise ValueError("Rates frame contains invalid low values.")

    for column in ("tick_volume", "spread_points", "real_volume"):
        values = pd.to_numeric(frame[column], errors="coerce")
        known = values.dropna()
        if (known < 0).any():
            raise ValueError(f"Rates frame contains negative {column} values.")

    deltas = timestamps.diff().dropna()
    if not deltas.empty:
        expected = get_timeframe_spec(label).expected_delta
        median = pd.to_timedelta(deltas.median())
        if median != expected:
            raise ValueError(f"Median bar spacing {median} does not match {label} ({expected}).")
