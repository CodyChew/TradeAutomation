"""LP to Force Strike proximity classification for research studies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import pandas as pd


PROXIMITY_VARIANTS: tuple[str, ...] = (
    "current_v15",
    "strict_touch",
    "gap_0p25_atr",
    "gap_0p50_atr",
    "gap_1p00_atr",
)

PROXIMITY_VARIANT_LABELS: dict[str, str] = {
    "current_v15": "Current V15",
    "strict_touch": "Strict touch",
    "gap_0p25_atr": "Gap <= 0.25 ATR",
    "gap_0p50_atr": "Gap <= 0.50 ATR",
    "gap_1p00_atr": "Gap <= 1.00 ATR",
}

_PROXIMITY_THRESHOLDS: dict[str, float | None] = {
    "current_v15": None,
    "strict_touch": 0.0,
    "gap_0p25_atr": 0.25,
    "gap_0p50_atr": 0.50,
    "gap_1p00_atr": 1.00,
}


@dataclass(frozen=True)
class LPFSProximity:
    """Distance between the selected LP and Force Strike structure."""

    side: str
    lp_price: float | None
    structure_low: float | None
    structure_high: float | None
    atr: float | None
    strict_touch: bool
    gap_price: float | None
    gap_atr: float | None
    quality_bucket: str
    status: str = "known"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_lp_fs_proximity(
    *,
    side: str,
    lp_price: Any,
    structure_low: Any,
    structure_high: Any,
    atr: Any,
) -> LPFSProximity:
    """Classify whether Force Strike structure touched the selected LP."""

    normalized_side = str(side).lower()
    lp = _finite_number(lp_price)
    low = _finite_number(structure_low)
    high = _finite_number(structure_high)
    atr_value = _finite_positive(atr)
    if normalized_side not in {"long", "short"}:
        return _unknown(normalized_side, lp, low, high, atr_value, "unsupported_side")
    if lp is None:
        return _unknown(normalized_side, lp, low, high, atr_value, "missing_lp_price")
    if normalized_side == "long" and low is None:
        return _unknown(normalized_side, lp, low, high, atr_value, "missing_structure_low")
    if normalized_side == "short" and high is None:
        return _unknown(normalized_side, lp, low, high, atr_value, "missing_structure_high")

    if normalized_side == "long":
        assert low is not None
        strict_touch = low <= lp
        gap_price = 0.0 if strict_touch else float(low - lp)
    else:
        assert high is not None
        strict_touch = high >= lp
        gap_price = 0.0 if strict_touch else float(lp - high)

    if strict_touch:
        return LPFSProximity(
            side=normalized_side,
            lp_price=lp,
            structure_low=low,
            structure_high=high,
            atr=atr_value,
            strict_touch=True,
            gap_price=0.0,
            gap_atr=0.0,
            quality_bucket="touched",
        )

    if atr_value is None:
        return LPFSProximity(
            side=normalized_side,
            lp_price=lp,
            structure_low=low,
            structure_high=high,
            atr=atr_value,
            strict_touch=False,
            gap_price=gap_price,
            gap_atr=None,
            quality_bucket="unknown",
            status="unknown",
            reason="missing_or_zero_atr",
        )

    gap_atr = float(gap_price / atr_value)
    return LPFSProximity(
        side=normalized_side,
        lp_price=lp,
        structure_low=low,
        structure_high=high,
        atr=atr_value,
        strict_touch=False,
        gap_price=gap_price,
        gap_atr=gap_atr,
        quality_bucket=quality_bucket_for_gap_atr(gap_atr),
    )


def classify_trade_row(row: pd.Series | dict[str, Any]) -> LPFSProximity:
    """Classify one flattened trade-report row."""

    get = row.get
    return classify_lp_fs_proximity(
        side=str(get("side", "")),
        lp_price=get("meta_lp_price"),
        structure_low=get("meta_structure_low"),
        structure_high=get("meta_structure_high"),
        atr=get("meta_atr"),
    )


def quality_bucket_for_gap_atr(gap_atr: float) -> str:
    if gap_atr <= 0.25:
        return "within_0p25_atr"
    if gap_atr <= 0.50:
        return "within_0p50_atr"
    if gap_atr <= 1.00:
        return "within_1p00_atr"
    return "farther_than_1p00_atr"


def add_proximity_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with proximity columns added from trade metadata."""

    if frame.empty:
        return frame.copy()
    rows = [classify_trade_row(row).to_dict() for _, row in frame.iterrows()]
    proximity = pd.DataFrame(rows, index=frame.index).add_prefix("proximity_")
    return pd.concat([frame.copy(), proximity], axis=1)


def proximity_variant_mask(frame: pd.DataFrame, variant_id: str) -> pd.Series:
    """Return rows accepted by one proximity variant."""

    if variant_id not in _PROXIMITY_THRESHOLDS:
        raise ValueError(f"Unsupported proximity variant {variant_id!r}.")
    if frame.empty:
        return pd.Series(dtype=bool, index=frame.index)
    threshold = _PROXIMITY_THRESHOLDS[variant_id]
    if threshold is None:
        return pd.Series(True, index=frame.index)
    strict_touch = frame["proximity_strict_touch"].astype(bool)
    if threshold == 0.0:
        return strict_touch
    gap_atr = pd.to_numeric(frame["proximity_gap_atr"], errors="coerce")
    return strict_touch | gap_atr.le(float(threshold)).fillna(False)


def proximity_variant_label(variant_id: str) -> str:
    return PROXIMITY_VARIANT_LABELS.get(variant_id, variant_id)


def _unknown(
    side: str,
    lp: float | None,
    low: float | None,
    high: float | None,
    atr: float | None,
    reason: str,
) -> LPFSProximity:
    return LPFSProximity(
        side=side,
        lp_price=lp,
        structure_low=low,
        structure_high=high,
        atr=atr,
        strict_touch=False,
        gap_price=None,
        gap_atr=None,
        quality_bucket="unknown",
        status="unknown",
        reason=reason,
    )


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_positive(value: Any) -> float | None:
    number = _finite_number(value)
    if number is None or number <= 0:
        return None
    return number
