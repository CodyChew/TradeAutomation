from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [
    REPO_ROOT / "shared" / "market_data_lab" / "src",
    REPO_ROOT / "shared" / "backtest_engine_lab" / "src",
    REPO_ROOT / "concepts" / "lp_levels_lab" / "src",
    REPO_ROOT / "concepts" / "majority_flush_lab" / "src",
    REPO_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    REPO_ROOT / "strategies" / "majority_flush_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from backtest_engine_lab import CostConfig, drop_incomplete_last_bar  # noqa: E402
from majority_flush_strategy_lab import (  # noqa: E402
    SkippedTrade,
    baseline_candidate,
    run_majority_flush_experiment_on_frame,
    trade_report_row,
)
from market_data_lab import (  # noqa: E402
    load_dataset_config,
    load_rates_parquet,
    manifest_path,
    normalize_timeframe,
    read_json,
)


DEFAULT_CONFIG = REPO_ROOT / "configs" / "strategies" / "majority_flush_strategy_baseline_v1.json"


def _read_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=columns) if columns is not None else pd.DataFrame(rows)
    frame.to_csv(target, index=False)


def _parse_csv_arg(value: str | None) -> list[str] | None:
    if value is None or value.strip() == "":
        return None
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _selected_symbols(dataset_symbols: tuple[str, ...], config: dict[str, Any], override: list[str] | None) -> list[str]:
    if override is not None:
        symbols = override
    elif config.get("symbols") is None:
        symbols = list(dataset_symbols)
    else:
        symbols = [str(symbol).upper() for symbol in config.get("symbols", [])]

    excluded = {str(symbol).upper() for symbol in config.get("excluded_symbols", [])}
    return [symbol for symbol in symbols if symbol not in excluded]


def _selected_timeframes(config: dict[str, Any], override: list[str] | None) -> list[str]:
    raw = override if override is not None else config.get("timeframes", ["H4", "H8", "H12", "D1", "W1"])
    return [normalize_timeframe(timeframe) for timeframe in raw]


def _cost_config(payload: dict[str, Any]) -> CostConfig:
    costs = payload.get("costs", {})
    return CostConfig(
        use_candle_spread=bool(costs.get("use_candle_spread", True)),
        fallback_spread_points=float(costs.get("fallback_spread_points", 0.0)),
        entry_slippage_points=float(costs.get("entry_slippage_points", 0.0)),
        exit_slippage_points=float(costs.get("exit_slippage_points", 0.0)),
        round_turn_commission_points=float(costs.get("round_turn_commission_points", 0.0)),
    )


def _manifest(root: str | Path, symbol: str, timeframe: str) -> dict[str, Any]:
    return read_json(manifest_path(root, symbol, timeframe))


def _load_backtest_frame(data_root: str | Path, symbol: str, timeframe: str, *, drop_latest: bool) -> pd.DataFrame:
    frame = load_rates_parquet(data_root, symbol=symbol, timeframe=timeframe)
    manifest = _manifest(data_root, symbol, timeframe)
    point = manifest.get("symbol_metadata", {}).get("point")
    if point is not None:
        frame["point"] = float(point)

    if drop_latest:
        requested_end = manifest.get("requested_end_utc")
        if requested_end:
            frame = drop_incomplete_last_bar(frame, timeframe, as_of_time_utc=requested_end)
    return frame


def _signal_row(symbol: str, timeframe: str, pivot_strength: int, signal) -> dict[str, Any]:
    row = signal.to_dict()
    row["symbol"] = symbol
    row["timeframe"] = timeframe
    row["pivot_strength"] = pivot_strength
    return row


def _skipped_row(skipped: SkippedTrade, *, pivot_strength: int) -> dict[str, Any]:
    row = skipped.to_dict()
    row["pivot_strength"] = pivot_strength
    return row


def _trade_row(trade, *, pivot_strength: int) -> dict[str, Any]:
    row = trade_report_row(trade)
    row["pivot_strength"] = pivot_strength
    return row


def _skipped_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    summary = (
        frame.groupby(["reason", "timeframe"], dropna=False)
        .size()
        .reset_index(name="skipped")
        .sort_values(["skipped", "reason", "timeframe"], ascending=[False, True, True])
    )
    return summary.to_dict(orient="records")


def _decision(summary_by_candidate: list[dict[str, Any]], failed_count: int, signals: int) -> str:
    if failed_count:
        return "review_data_failures"
    if signals < 30:
        return "pause_low_signal_count"
    if not summary_by_candidate:
        return "pause_no_trades"
    row = summary_by_candidate[0]
    avg_r = float(row.get("avg_net_r") or 0.0)
    profit_factor = row.get("profit_factor")
    pf_value = 0.0 if profit_factor in (None, "") else float(profit_factor)
    if avg_r > 0.0 and pf_value > 1.0:
        return "continue_to_entry_iteration"
    return "reject_or_rework_baseline"


def _run(config_path: Path, *, symbol_override: list[str] | None, timeframe_override: list[str] | None, output_dir: Path | None) -> int:
    config = _read_config(config_path)
    dataset_config = load_dataset_config(REPO_ROOT / str(config["dataset_config"]))
    symbols = _selected_symbols(dataset_config.symbols, config, symbol_override)
    timeframes = _selected_timeframes(config, timeframe_override)
    pivot_strength = int(config.get("pivot_strength", 3))
    max_bars_from_lp_break = int(config.get("max_bars_from_lp_break", 6))
    candidate = baseline_candidate()
    costs = _cost_config(config)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir or (REPO_ROOT / str(config["report_root"]) / timestamp)
    run_dir.mkdir(parents=True, exist_ok=True)

    all_signal_rows: list[dict[str, Any]] = []
    all_trade_rows: list[dict[str, Any]] = []
    all_skipped_rows: list[dict[str, Any]] = []
    dataset_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            try:
                frame = _load_backtest_frame(
                    dataset_config.data_root,
                    symbol,
                    timeframe,
                    drop_latest=bool(config.get("drop_incomplete_latest_bar", True)),
                )
                result = run_majority_flush_experiment_on_frame(
                    frame,
                    symbol=symbol,
                    timeframe=timeframe,
                    candidates=[candidate],
                    pivot_strength=pivot_strength,
                    max_bars_from_lp_break=max_bars_from_lp_break,
                    costs=costs,
                )
                all_signal_rows.extend(_signal_row(symbol, timeframe, pivot_strength, signal) for signal in result.signals)
                all_trade_rows.extend(_trade_row(trade, pivot_strength=pivot_strength) for trade in result.trades)
                all_skipped_rows.extend(_skipped_row(skipped, pivot_strength=pivot_strength) for skipped in result.skipped)
                dataset_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "pivot_strength": pivot_strength,
                        "status": "ok",
                        "rows": int(len(frame)),
                        "signals": int(len(result.signals)),
                        "trades": int(len(result.trades)),
                        "skipped": int(len(result.skipped)),
                    }
                )
                print(
                    f"{symbol} {timeframe} MF{pivot_strength}: rows={len(frame)} signals={len(result.signals)} "
                    f"trades={len(result.trades)} skipped={len(result.skipped)}"
                )
            except Exception as exc:
                dataset_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "pivot_strength": pivot_strength,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                print(f"{symbol} {timeframe}: failed={exc}")

    summary_by_candidate = _summary_rows_from_report_rows(all_trade_rows, group_fields=["candidate_id"])
    summary_by_timeframe = _summary_rows_from_report_rows(all_trade_rows, group_fields=["timeframe"])
    summary_by_symbol = _summary_rows_from_report_rows(all_trade_rows, group_fields=["symbol"])
    summary_by_candidate_timeframe = _summary_rows_from_report_rows(all_trade_rows, group_fields=["candidate_id", "timeframe"])
    skipped_summary = _skipped_summary(all_skipped_rows)
    failed = [row for row in dataset_rows if row.get("status") != "ok"]
    decision = _decision(summary_by_candidate, len(failed), len(all_signal_rows))

    _write_json(
        run_dir / "run_config.json",
        {
            "config_path": str(config_path),
            "config": config,
            "symbols": symbols,
            "timeframes": timeframes,
            "pivot_strength": pivot_strength,
            "max_bars_from_lp_break": max_bars_from_lp_break,
            "candidate": asdict(candidate),
        },
    )
    _write_csv(run_dir / "datasets.csv", dataset_rows)
    _write_csv(run_dir / "signals.csv", all_signal_rows)
    _write_csv(run_dir / "trades.csv", all_trade_rows)
    _write_csv(run_dir / "skipped.csv", all_skipped_rows)
    _write_csv(run_dir / "candidates.csv", [asdict(candidate)])
    _write_csv(run_dir / "summary_by_candidate.csv", summary_by_candidate)
    _write_csv(run_dir / "summary_by_timeframe.csv", summary_by_timeframe)
    _write_csv(run_dir / "summary_by_symbol.csv", summary_by_symbol)
    _write_csv(run_dir / "summary_by_candidate_timeframe.csv", summary_by_candidate_timeframe)
    _write_csv(run_dir / "skipped_summary.csv", skipped_summary)

    summary = {
        "run_dir": str(run_dir),
        "datasets": len(dataset_rows),
        "failed_datasets": len(failed),
        "signals": len(all_signal_rows),
        "trades": len(all_trade_rows),
        "skipped": len(all_skipped_rows),
        "decision": decision,
        "candidate": candidate.candidate_id,
    }
    _write_json(run_dir / "run_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if failed else 0


def _summary_rows_from_report_rows(rows: list[dict[str, Any]], *, group_fields: list[str]) -> list[dict[str, Any]]:
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    frame["net_r"] = pd.to_numeric(frame["net_r"], errors="coerce").fillna(0.0)
    frame["bars_held"] = pd.to_numeric(frame["bars_held"], errors="coerce").fillna(0.0)
    groupby_key = group_fields[0] if len(group_fields) == 1 else group_fields
    output: list[dict[str, Any]] = []
    for keys, group in frame.groupby(groupby_key, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        ordered = group.sort_values(["exit_time_utc", "entry_time_utc", "setup_id"])
        net_r = ordered["net_r"]
        equity = net_r.cumsum()
        drawdown = equity.cummax() - equity
        gross_win = float(net_r[net_r > 0].sum())
        gross_loss = float(net_r[net_r < 0].sum())
        row = {field: value for field, value in zip(group_fields, keys)}
        row.update(
            {
                "trades": int(len(ordered)),
                "wins": int((net_r > 0).sum()),
                "losses": int((net_r < 0).sum()),
                "win_rate": float((net_r > 0).mean()),
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()),
                "median_net_r": float(net_r.median()),
                "profit_factor": None if gross_loss == 0 else float(gross_win / abs(gross_loss)),
                "max_closed_trade_drawdown_r": float(drawdown.max()),
                "avg_bars_held": float(ordered["bars_held"].mean()),
                "target_exits": int((ordered["exit_reason"] == "target").sum()),
                "stop_exits": int((ordered["exit_reason"] == "stop").sum()),
                "same_bar_stop_exits": int((ordered["exit_reason"] == "same_bar_stop_priority").sum()),
                "end_of_data_exits": int((ordered["exit_reason"] == "end_of_data").sum()),
            }
        )
        output.append(row)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Majority Flush V1 baseline experiment.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to experiment config JSON.")
    parser.add_argument("--symbols", help="Optional comma-separated symbol override, e.g. AUDCAD,EURUSD.")
    parser.add_argument("--timeframes", help="Optional comma-separated timeframe override, e.g. H4,D1.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    args = parser.parse_args()

    symbol_override = _parse_csv_arg(args.symbols)
    timeframe_override = _parse_csv_arg(args.timeframes)
    output_dir = None if args.output_dir is None else Path(args.output_dir)
    return _run(Path(args.config), symbol_override=symbol_override, timeframe_override=timeframe_override, output_dir=output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
