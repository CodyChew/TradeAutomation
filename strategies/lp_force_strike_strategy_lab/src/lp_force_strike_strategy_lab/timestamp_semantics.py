"""LPFS timestamp semantics and migration-safe signal-key helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


LEGACY_HELSINKI_RELOCALIZED_V1 = "legacy_helsinki_relocalized_v1"
MT5_EPOCH_UTC_V2 = "mt5_epoch_utc_v2"
SUPPORTED_TIMESTAMP_SEMANTICS = {
    LEGACY_HELSINKI_RELOCALIZED_V1,
    MT5_EPOCH_UTC_V2,
}
DEFAULT_LEGACY_BROKER_TIMEZONE = "Europe/Helsinki"


class TimestampSemanticsError(ValueError):
    """Raised when timestamp provenance cannot be interpreted safely."""


@dataclass(frozen=True)
class ParsedSignalKey:
    """Validated LPFS signal identity with an intact ISO timestamp remainder."""

    symbol: str
    timeframe: str
    signal_index: int
    side: str
    candidate_id: str
    signal_time_utc: pd.Timestamp

    def with_timestamp(self, timestamp: Any) -> "ParsedSignalKey":
        return ParsedSignalKey(
            symbol=self.symbol,
            timeframe=self.timeframe,
            signal_index=self.signal_index,
            side=self.side,
            candidate_id=self.candidate_id,
            signal_time_utc=as_utc_timestamp(timestamp),
        )

    def to_key(self) -> str:
        return (
            f"lpfs:{self.symbol}:{self.timeframe}:{self.signal_index}:"
            f"{self.side}:{self.candidate_id}:{self.signal_time_utc.isoformat()}"
        )

    def identity_tuple(self) -> tuple[str, str, int, str, str, pd.Timestamp]:
        return (
            self.symbol,
            self.timeframe,
            self.signal_index,
            self.side,
            self.candidate_id,
            self.signal_time_utc,
        )


def mt5_epoch_to_utc(raw_time: int | float | None, *, unit: str = "s") -> pd.Timestamp | None:
    """Parse an MT5 epoch value directly as UTC."""

    if raw_time in (None, 0):
        return None
    return pd.Timestamp(int(raw_time), unit=unit, tz="UTC")


def as_utc_timestamp(value: Any) -> pd.Timestamp:
    """Return a timezone-aware UTC timestamp or fail explicitly."""

    try:
        timestamp = pd.Timestamp(value)
    except Exception as exc:
        raise TimestampSemanticsError(f"Invalid timestamp {value!r}.") from exc
    if pd.isna(timestamp):
        raise TimestampSemanticsError(f"Invalid timestamp {value!r}.")
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def normalize_recorded_timestamp(
    value: Any,
    semantics: str,
    *,
    broker_timezone: str = DEFAULT_LEGACY_BROKER_TIMEZONE,
) -> pd.Timestamp:
    """Normalize a recorded LPFS timestamp according to its explicit semantics."""

    timestamp = as_utc_timestamp(value)
    if semantics == MT5_EPOCH_UTC_V2:
        return timestamp
    if semantics == LEGACY_HELSINKI_RELOCALIZED_V1:
        return timestamp.tz_convert(broker_timezone).tz_localize(None).tz_localize("UTC")
    raise TimestampSemanticsError(f"Unsupported timestamp semantics {semantics!r}.")


def legacy_equivalent_timestamp(
    canonical_value: Any,
    *,
    broker_timezone: str = DEFAULT_LEGACY_BROKER_TIMEZONE,
) -> pd.Timestamp:
    """Reproduce the historical Helsinki reinterpretation for duplicate checks."""

    canonical = as_utc_timestamp(canonical_value)
    return canonical.tz_localize(None).tz_localize(broker_timezone).tz_convert("UTC")


def parse_signal_key(raw_key: str) -> ParsedSignalKey:
    """Parse an LPFS signal key while preserving the ISO timestamp remainder."""

    parts = str(raw_key).split(":", 6)
    if len(parts) != 7 or parts[0] != "lpfs":
        raise TimestampSemanticsError(f"Malformed LPFS signal key {raw_key!r}.")
    _, symbol, timeframe, raw_index, side, candidate_id, raw_timestamp = parts
    if not symbol or not timeframe or not side or not candidate_id or not raw_timestamp:
        raise TimestampSemanticsError(f"Malformed LPFS signal key {raw_key!r}.")
    try:
        signal_index = int(raw_index)
    except (TypeError, ValueError) as exc:
        raise TimestampSemanticsError(f"Malformed LPFS signal key index in {raw_key!r}.") from exc
    return ParsedSignalKey(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        signal_index=signal_index,
        side=side.lower(),
        candidate_id=candidate_id,
        signal_time_utc=as_utc_timestamp(raw_timestamp),
    )


def canonical_signal_key(
    raw_key: str,
    semantics: str,
    *,
    broker_timezone: str = DEFAULT_LEGACY_BROKER_TIMEZONE,
) -> str:
    """Return a canonical v2 signal key for a recorded key and semantics."""

    parsed = parse_signal_key(raw_key)
    return parsed.with_timestamp(
        normalize_recorded_timestamp(
            parsed.signal_time_utc,
            semantics,
            broker_timezone=broker_timezone,
        )
    ).to_key()


def canonical_and_legacy_signal_keys(
    canonical_key: str,
    *,
    broker_timezone: str = DEFAULT_LEGACY_BROKER_TIMEZONE,
) -> tuple[str, str]:
    """Return deterministic canonical and legacy variants for a canonical key."""

    parsed = parse_signal_key(canonical_key)
    canonical = parsed.with_timestamp(parsed.signal_time_utc)
    legacy = parsed.with_timestamp(
        legacy_equivalent_timestamp(parsed.signal_time_utc, broker_timezone=broker_timezone)
    )
    return canonical.to_key(), legacy.to_key()


def signal_key_matches_canonical(
    recorded_key: str,
    canonical_key: str,
    *,
    recorded_semantics: str | None = None,
    broker_timezone: str = DEFAULT_LEGACY_BROKER_TIMEZONE,
) -> bool:
    """Return whether a recorded operational key represents a canonical setup."""

    recorded = parse_signal_key(recorded_key)
    canonical = parse_signal_key(canonical_key)
    if recorded.identity_tuple()[:-1] != canonical.identity_tuple()[:-1]:
        return False
    canonical_time = canonical.signal_time_utc
    if recorded_semantics is not None:
        recorded_time = normalize_recorded_timestamp(
            recorded.signal_time_utc,
            recorded_semantics,
            broker_timezone=broker_timezone,
        )
        return recorded_time == canonical_time
    return recorded.signal_time_utc in {
        canonical_time,
        legacy_equivalent_timestamp(canonical_time, broker_timezone=broker_timezone),
    }
