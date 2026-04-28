from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "shared" / "market_data_lab" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import get_timeframe_spec, load_dataset_config, load_rates_parquet, manifest_path, read_json


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row})
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _large_gap_tolerance(timeframe: str) -> pd.Timedelta:
    if timeframe == "W1":
        return pd.Timedelta(days=14)
    return pd.Timedelta(days=5)


def _pct(value: float) -> float:
    return float(value) * 100.0


def _requested_end(data_root: str | Path, symbol: str, timeframe: str) -> pd.Timestamp | None:
    path = manifest_path(data_root, symbol, timeframe)
    if not path.exists():
        return None
    payload = read_json(path)
    raw = payload.get("requested_end_utc")
    if raw is None:
        return None
    return pd.Timestamp(raw).tz_convert("UTC")


def _dataset_checks(config) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    summary_rows: list[dict[str, Any]] = []
    large_gap_rows: list[dict[str, Any]] = []
    suspicious_bar_rows: list[dict[str, Any]] = []
    for symbol in config.symbols:
        for timeframe in config.timeframes:
            label = str(timeframe)
            try:
                frame = load_rates_parquet(config.data_root, symbol=symbol, timeframe=label)
                frame = frame.sort_values("time_utc").reset_index(drop=True)
                frame["time_utc"] = pd.to_datetime(frame["time_utc"], utc=True)
                spec = get_timeframe_spec(label)
                deltas = frame["time_utc"].diff()
                gap_tolerance = _large_gap_tolerance(label)
                large_gaps = frame.loc[deltas > gap_tolerance, ["time_utc"]].copy()
                for idx, row in large_gaps.iterrows():
                    previous_time = frame.loc[idx - 1, "time_utc"]
                    gap_hours = float((row["time_utc"] - previous_time) / pd.Timedelta(hours=1))
                    large_gap_rows.append(
                        {
                            "symbol": symbol,
                            "timeframe": label,
                            "previous_time_utc": previous_time.isoformat(),
                            "next_time_utc": row["time_utc"].isoformat(),
                            "gap_hours": gap_hours,
                        }
                    )

                previous_close = frame["close"].shift(1)
                close_jump_pct = ((frame["close"] - previous_close).abs() / previous_close.abs()).fillna(0.0)
                range_pct = ((frame["high"] - frame["low"]) / previous_close.abs()).fillna(0.0)
                suspicious = frame.loc[(close_jump_pct > 0.10) | (range_pct > 0.10), ["time_utc", "open", "high", "low", "close"]]
                for idx, row in suspicious.iterrows():
                    suspicious_bar_rows.append(
                        {
                            "symbol": symbol,
                            "timeframe": label,
                            "time_utc": row["time_utc"].isoformat(),
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "close_jump_pct": _pct(close_jump_pct.loc[idx]),
                            "range_pct": _pct(range_pct.loc[idx]),
                        }
                    )

                requested_end = _requested_end(config.data_root, symbol, label)
                latest_time = frame["time_utc"].iloc[-1]
                expected_close_time = latest_time + spec.expected_delta
                tail_complete = None if requested_end is None else bool(expected_close_time <= requested_end)
                summary_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": label,
                        "status": "ok",
                        "rows": int(len(frame)),
                        "coverage_start_utc": frame["time_utc"].iloc[0].isoformat(),
                        "coverage_end_utc": latest_time.isoformat(),
                        "duplicates": int(frame["time_utc"].duplicated().sum()),
                        "max_gap_hours": float(deltas.max() / pd.Timedelta(hours=1)) if len(deltas.dropna()) else 0.0,
                        "large_gap_count": int(len(large_gaps)),
                        "largest_close_jump_pct": _pct(float(close_jump_pct.max())),
                        "largest_bar_range_pct": _pct(float(range_pct.max())),
                        "suspicious_bar_count": int(len(suspicious)),
                        "latest_bar_expected_close_utc": expected_close_time.isoformat(),
                        "latest_bar_complete_at_requested_end": tail_complete,
                    }
                )
            except Exception as exc:
                summary_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": label,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
    return summary_rows, large_gap_rows, suspicious_bar_rows


def _weekly_consistency(config) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summary_rows: list[dict[str, Any]] = []
    mismatch_rows: list[dict[str, Any]] = []
    for symbol in config.symbols:
        try:
            m30 = load_rates_parquet(config.data_root, symbol=symbol, timeframe="M30")
            w1 = load_rates_parquet(config.data_root, symbol=symbol, timeframe="W1")
            for frame in (m30, w1):
                frame["time_utc"] = pd.to_datetime(frame["time_utc"], utc=True)
            m30 = m30.sort_values("time_utc").reset_index(drop=True)
            w1 = w1.sort_values("time_utc").reset_index(drop=True)
            m30_latest = m30["time_utc"].iloc[-1]
            compared = 0
            skipped_incomplete = 0
            max_high_diff = 0.0
            max_low_diff = 0.0
            for idx, row in w1.iterrows():
                start = row["time_utc"]
                end = w1.loc[idx + 1, "time_utc"] if idx + 1 < len(w1) else start + pd.Timedelta(days=7)
                if end > m30_latest:
                    skipped_incomplete += 1
                    continue
                window = m30[(m30["time_utc"] >= start) & (m30["time_utc"] < end)]
                if window.empty:
                    continue
                compared += 1
                high_diff = abs(float(window["high"].max()) - float(row["high"]))
                low_diff = abs(float(window["low"].min()) - float(row["low"]))
                max_high_diff = max(max_high_diff, high_diff)
                max_low_diff = max(max_low_diff, low_diff)
                if high_diff > 1e-9 or low_diff > 1e-9:
                    mismatch_rows.append(
                        {
                            "symbol": symbol,
                            "week_start_utc": start.isoformat(),
                            "m30_high": float(window["high"].max()),
                            "w1_high": float(row["high"]),
                            "high_diff": high_diff,
                            "m30_low": float(window["low"].min()),
                            "w1_low": float(row["low"]),
                            "low_diff": low_diff,
                            "m30_bars_in_week": int(len(window)),
                        }
                    )
            summary_rows.append(
                {
                    "symbol": symbol,
                    "status": "ok",
                    "complete_weekly_candles_compared": compared,
                    "incomplete_tail_weekly_candles_skipped": skipped_incomplete,
                    "mismatch_count": len([row for row in mismatch_rows if row["symbol"] == symbol]),
                    "max_high_diff": max_high_diff,
                    "max_low_diff": max_low_diff,
                }
            )
        except Exception as exc:
            summary_rows.append({"symbol": symbol, "status": "failed", "error": str(exc)})
    return summary_rows, mismatch_rows


def _verdict(
    dataset_rows: list[dict[str, Any]],
    large_gap_rows: list[dict[str, Any]],
    suspicious_bar_rows: list[dict[str, Any]],
    weekly_rows: list[dict[str, Any]],
    weekly_mismatch_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_datasets = [row for row in dataset_rows if row.get("status") != "ok"]
    duplicate_datasets = [row for row in dataset_rows if int(row.get("duplicates", 0) or 0) > 0]
    failed_weekly = [row for row in weekly_rows if row.get("status") != "ok"]
    incomplete_tail = [row for row in dataset_rows if row.get("latest_bar_complete_at_requested_end") is False]
    large_gap_symbols = sorted({row["symbol"] for row in large_gap_rows})
    suspicious_symbols = sorted({row["symbol"] for row in suspicious_bar_rows})

    failures: list[str] = []
    warnings: list[str] = []
    if failed_datasets:
        failures.append(f"{len(failed_datasets)} datasets failed validation/load")
    if duplicate_datasets:
        failures.append(f"{len(duplicate_datasets)} datasets contain duplicate timestamps")
    if failed_weekly:
        failures.append(f"{len(failed_weekly)} symbols failed weekly aggregation checks")
    if weekly_mismatch_rows:
        failures.append(f"{len(weekly_mismatch_rows)} complete W1 candles differ from M30 aggregation")
    if large_gap_rows:
        warnings.append(f"{len(large_gap_rows)} large historical gaps across {len(large_gap_symbols)} symbols")
    if suspicious_bar_rows:
        warnings.append(f"{len(suspicious_bar_rows)} large one-bar moves across {len(suspicious_symbols)} symbols")
    if incomplete_tail:
        warnings.append(f"{len(incomplete_tail)} datasets end with an incomplete latest bar from live-ended pull")

    status = "OK"
    if failures:
        status = "FAIL"
    elif warnings:
        status = "OK_WITH_WARNINGS"
    return {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "dataset_count": len(dataset_rows),
        "weekly_symbols_checked": len(weekly_rows),
        "large_gap_symbols": large_gap_symbols,
        "suspicious_move_symbols": suspicious_symbols,
        "incomplete_tail_dataset_count": len(incomplete_tail),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run data-quality checks on a configured market-data dataset.")
    parser.add_argument("--config", required=True, help="Path to dataset config JSON.")
    parser.add_argument("--output-dir", default="reports/datasets/data_quality", help="Directory for quality report files.")
    parser.add_argument("--json", action="store_true", help="Print full verdict JSON.")
    args = parser.parse_args()

    config = load_dataset_config(args.config)
    output_dir = Path(args.output_dir)
    dataset_rows, large_gap_rows, suspicious_bar_rows = _dataset_checks(config)
    weekly_rows, weekly_mismatch_rows = _weekly_consistency(config)
    verdict = _verdict(dataset_rows, large_gap_rows, suspicious_bar_rows, weekly_rows, weekly_mismatch_rows)

    _write_csv(output_dir / "dataset_quality_summary.csv", dataset_rows)
    _write_csv(output_dir / "large_gaps.csv", large_gap_rows)
    _write_csv(output_dir / "suspicious_bars.csv", suspicious_bar_rows)
    _write_csv(output_dir / "m30_vs_w1_weekly_consistency.csv", weekly_rows)
    _write_csv(output_dir / "m30_vs_w1_weekly_mismatches.csv", weekly_mismatch_rows)
    _write_json(output_dir / "verdict.json", verdict)

    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
    else:
        print(f"status={verdict['status']}")
        print(f"datasets={verdict['dataset_count']} weekly_symbols_checked={verdict['weekly_symbols_checked']}")
        print(f"failures={len(verdict['failures'])} warnings={len(verdict['warnings'])}")
        for message in verdict["failures"]:
            print(f"failure: {message}")
        for message in verdict["warnings"]:
            print(f"warning: {message}")
        if verdict["large_gap_symbols"]:
            print("large_gap_symbols=" + ",".join(verdict["large_gap_symbols"]))
        if verdict["suspicious_move_symbols"]:
            print("suspicious_move_symbols=" + ",".join(verdict["suspicious_move_symbols"]))
        print(f"wrote={output_dir}")
    return 1 if verdict["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
