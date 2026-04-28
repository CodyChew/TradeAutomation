"""Stability analysis for LP + Force Strike trade experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StabilityFilter:
    """One symbol/timeframe filter learned from training-period trades."""

    filter_id: str
    include_all_pairs: bool = False
    min_trades: int = 0
    min_avg_net_r: float | None = None
    min_profit_factor: float | None = None
    min_total_net_r: float | None = None


@dataclass(frozen=True)
class StabilityAnalysisResult:
    """Output tables from a walk-forward stability analysis."""

    filter_results: pd.DataFrame
    allowed_pairs: pd.DataFrame


def normalise_trade_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the columns needed for stability analysis."""

    required = {"candidate_id", "symbol", "timeframe", "entry_time_utc", "net_r"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Trade frame is missing columns: {', '.join(sorted(missing))}")

    keep = ["candidate_id", "symbol", "timeframe", "entry_time_utc", "net_r"]
    for optional in ("bars_held", "exit_reason"):
        if optional in frame.columns:
            keep.append(optional)
    data = frame.loc[:, keep].copy()
    data["candidate_id"] = data["candidate_id"].astype(str)
    data["symbol"] = data["symbol"].astype(str).str.upper()
    data["timeframe"] = data["timeframe"].astype(str).str.upper()
    data["entry_time_utc"] = pd.to_datetime(data["entry_time_utc"], utc=True)
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    if "bars_held" not in data.columns:
        data["bars_held"] = 0.0
    data["bars_held"] = pd.to_numeric(data["bars_held"], errors="coerce").fillna(0.0)
    if "exit_reason" not in data.columns:
        data["exit_reason"] = ""
    return data.sort_values("entry_time_utc").reset_index(drop=True)


def summarize_trades(frame: pd.DataFrame, group_fields: list[str]) -> pd.DataFrame:
    """Summarize trade performance by the requested group fields."""

    columns = group_fields + [
        "trades",
        "wins",
        "losses",
        "win_rate",
        "total_net_r",
        "avg_net_r",
        "median_net_r",
        "profit_factor",
        "avg_bars_held",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(group_fields, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        net_r = group["net_r"]
        gross_win = float(net_r[net_r > 0].sum())
        gross_loss = float(net_r[net_r < 0].sum())
        trades = int(len(group))
        row = {field: value for field, value in zip(group_fields, keys)}
        row.update(
            {
                "trades": trades,
                "wins": int((net_r > 0).sum()),
                "losses": int((net_r < 0).sum()),
                "win_rate": float((net_r > 0).sum()) / trades if trades else 0.0,
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()) if trades else 0.0,
                "median_net_r": float(net_r.median()) if trades else 0.0,
                "profit_factor": _profit_factor(gross_win, gross_loss),
                "avg_bars_held": float(group["bars_held"].mean()) if trades else 0.0,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def run_stability_analysis(
    trades: pd.DataFrame,
    *,
    split_time_utc: str | pd.Timestamp,
    candidate_ids: list[str],
    filters: list[StabilityFilter],
) -> StabilityAnalysisResult:
    """Learn stable symbol/timeframe pairs on train data and evaluate train/test/full."""

    data = normalise_trade_frame(trades)
    split_time = pd.Timestamp(split_time_utc)
    if split_time.tzinfo is None:
        split_time = split_time.tz_localize("UTC")
    else:
        split_time = split_time.tz_convert("UTC")

    candidate_set = {str(candidate_id) for candidate_id in candidate_ids}
    if candidate_set:
        data = data[data["candidate_id"].isin(candidate_set)].copy()

    train = data[data["entry_time_utc"] < split_time].copy()
    test = data[data["entry_time_utc"] >= split_time].copy()
    train_pair_stats = summarize_trades(train, ["candidate_id", "symbol", "timeframe"])

    result_rows: list[dict[str, Any]] = []
    allowed_rows: list[dict[str, Any]] = []

    for candidate_id in sorted(data["candidate_id"].dropna().unique()):
        candidate_data = data[data["candidate_id"] == candidate_id]
        all_pairs = candidate_data.loc[:, ["symbol", "timeframe"]].drop_duplicates()
        candidate_pair_stats = train_pair_stats[train_pair_stats["candidate_id"] == candidate_id].copy()

        for rule in filters:
            allowed = all_pairs if rule.include_all_pairs else _filter_pairs(candidate_pair_stats, rule)
            for _, row in allowed.iterrows():
                stats = candidate_pair_stats[
                    (candidate_pair_stats["symbol"] == row["symbol"])
                    & (candidate_pair_stats["timeframe"] == row["timeframe"])
                ]
                stats_row = stats.iloc[0].to_dict() if not stats.empty else {}
                allowed_rows.append(
                    {
                        "candidate_id": candidate_id,
                        "filter_id": rule.filter_id,
                        "symbol": row["symbol"],
                        "timeframe": row["timeframe"],
                        "train_trades": stats_row.get("trades", 0),
                        "train_avg_net_r": stats_row.get("avg_net_r", 0.0),
                        "train_total_net_r": stats_row.get("total_net_r", 0.0),
                        "train_profit_factor": stats_row.get("profit_factor", None),
                    }
                )

            for partition_name, partition in [
                ("train", train),
                ("test", test),
                ("full", data),
            ]:
                scoped = _apply_allowed_pairs(
                    partition[partition["candidate_id"] == candidate_id],
                    allowed,
                )
                summary = _single_summary(scoped)
                summary.update(
                    {
                        "candidate_id": candidate_id,
                        "filter_id": rule.filter_id,
                        "partition": partition_name,
                        "allowed_pair_count": int(len(allowed)),
                    }
                )
                result_rows.append(summary)

    return StabilityAnalysisResult(
        filter_results=pd.DataFrame(result_rows),
        allowed_pairs=pd.DataFrame(allowed_rows),
    )


def _filter_pairs(pair_stats: pd.DataFrame, rule: StabilityFilter) -> pd.DataFrame:
    if pair_stats.empty:
        return pd.DataFrame(columns=["symbol", "timeframe"])
    data = pair_stats.copy()
    mask = data["trades"] >= rule.min_trades
    if rule.min_avg_net_r is not None:
        mask &= data["avg_net_r"] >= rule.min_avg_net_r
    if rule.min_profit_factor is not None:
        mask &= data["profit_factor"].fillna(float("inf")) >= rule.min_profit_factor
    if rule.min_total_net_r is not None:
        mask &= data["total_net_r"] >= rule.min_total_net_r
    return data.loc[mask, ["symbol", "timeframe"]].drop_duplicates().reset_index(drop=True)


def _apply_allowed_pairs(frame: pd.DataFrame, allowed_pairs: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or allowed_pairs.empty:
        return frame.iloc[0:0].copy()
    allowed = allowed_pairs.loc[:, ["symbol", "timeframe"]].drop_duplicates()
    return frame.merge(allowed, on=["symbol", "timeframe"], how="inner")


def _single_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_net_r": 0.0,
            "avg_net_r": 0.0,
            "median_net_r": 0.0,
            "profit_factor": None,
            "avg_bars_held": 0.0,
        }
    summary = summarize_trades(frame.assign(summary_group="all"), ["summary_group"])
    row = summary.iloc[0].to_dict()
    row.pop("summary_group", None)
    return row


def _profit_factor(gross_win: float, gross_loss: float) -> float | None:
    if gross_loss == 0:
        if gross_win > 0:
            return None
        return 0.0
    return gross_win / abs(gross_loss)
