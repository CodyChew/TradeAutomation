from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from run_lp_force_strike_bucket_sensitivity_experiment import (
    _baseline_row,
    _efficiency_recommendation,
    _recommendation,
    run_bucket_sensitivity_analysis,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "strategies" / "lp_force_strike_account_commission_sensitivity"
DEFAULT_BASELINE_RUN_DIR = REPO_ROOT / "reports" / "strategies" / "lp_force_strike_experiment_v22_lp_fs_separation" / "20260505_111005"
DEFAULT_NEW_RUN_DIR = REPO_ROOT / "reports" / "strategies" / "lp_force_strike_experiment_v22_new_mt5_account" / "20260505_160405"
DEFAULT_FTMO_DATA_ROOT = REPO_ROOT / "data" / "raw" / "ftmo" / "forex"
DEFAULT_IC_SPECS_CSV = REPO_ROOT / "reports" / "mt5_account_validation" / "lpfs_new_account" / "20260505_155656" / "symbol_specs.csv"
DEFAULT_BUCKET_CONFIG = REPO_ROOT / "configs" / "strategies" / "lp_force_strike_experiment_v15_bucket_sensitivity.json"
DEFAULT_VARIANT = "exclude_lp_pivot_inside_fs"


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    point: float
    trade_tick_size: float
    trade_tick_value: float

    @property
    def value_per_point_per_lot(self) -> float:
        return self.trade_tick_value * self.point / self.trade_tick_size


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _safe_float(value: Any, *, default: float = math.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _spec_from_mapping(row: dict[str, Any]) -> SymbolSpec:
    symbol = str(row["symbol"])
    point = _safe_float(row.get("point"))
    tick_size = _safe_float(row.get("trade_tick_size"))
    tick_value = _safe_float(row.get("trade_tick_value"))
    if point <= 0 or tick_size <= 0 or tick_value <= 0:
        raise ValueError(f"Invalid symbol spec for {symbol}: point={point}, tick_size={tick_size}, tick_value={tick_value}")
    return SymbolSpec(symbol=symbol, point=point, trade_tick_size=tick_size, trade_tick_value=tick_value)


def load_symbol_specs_from_csv(path: Path) -> dict[str, SymbolSpec]:
    rows = list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))
    return {_spec_from_mapping(row).symbol: _spec_from_mapping(row) for row in rows}


def load_symbol_specs_from_manifest_root(root: Path) -> dict[str, SymbolSpec]:
    specs: dict[str, SymbolSpec] = {}
    for manifest in sorted(root.glob("*/*/manifest.json")):
        payload = _read_json(manifest)
        symbol = str(payload.get("symbol") or manifest.parents[1].name)
        if symbol in specs:
            continue
        metadata = payload.get("symbol_metadata") or {}
        metadata["symbol"] = symbol
        specs[symbol] = _spec_from_mapping(metadata)
    return specs


def _profit_factor(values: pd.Series) -> float | None:
    wins = values[values > 0].sum()
    losses = values[values < 0].sum()
    if losses == 0:
        return None if wins <= 0 else math.inf
    return float(wins / abs(losses))


def _max_drawdown(values: pd.Series) -> float:
    equity = values.cumsum()
    peak = equity.cummax()
    drawdown = peak - equity
    return float(drawdown.max()) if not drawdown.empty else 0.0


def _aggregate(data: pd.DataFrame, group_cols: list[str], r_column: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if data.empty:
        return pd.DataFrame(rows)
    for keys, group in data.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        net_r = pd.to_numeric(group[r_column], errors="coerce").fillna(0.0)
        row = {column: key for column, key in zip(group_cols, keys)}
        row.update(
            {
                "trades": int(len(group)),
                "wins": int((net_r > 0).sum()),
                "losses": int((net_r < 0).sum()),
                "win_rate": float((net_r > 0).mean()) if len(group) else 0.0,
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()) if len(group) else 0.0,
                "profit_factor": _profit_factor(net_r),
                "max_drawdown_r": _max_drawdown(net_r.reset_index(drop=True)),
                "total_commission_r": float(pd.to_numeric(group["modeled_commission_r"], errors="coerce").fillna(0.0).sum()),
                "avg_commission_r": float(pd.to_numeric(group["modeled_commission_r"], errors="coerce").fillna(0.0).mean()),
            }
        )
        row["return_to_drawdown_r"] = None if row["max_drawdown_r"] <= 0 else row["total_net_r"] / row["max_drawdown_r"]
        rows.append(row)
    return pd.DataFrame(rows)


def apply_commission_model(trades: pd.DataFrame, specs: dict[str, SymbolSpec], round_turn_per_lot: float) -> pd.DataFrame:
    data = trades.copy()
    data["risk_distance"] = pd.to_numeric(data["risk_distance"], errors="coerce")
    data["fill_r"] = pd.to_numeric(data["fill_r"], errors="coerce")
    data["original_commission_r"] = pd.to_numeric(data.get("commission_r", 0.0), errors="coerce").fillna(0.0)
    data["original_net_r"] = pd.to_numeric(data.get("net_r", data["fill_r"]), errors="coerce")
    data["modeled_round_turn_per_lot"] = float(round_turn_per_lot)

    value_per_point: list[float] = []
    commission_points: list[float] = []
    commission_r: list[float] = []
    missing_specs: set[str] = set()
    for row in data.itertuples(index=False):
        symbol = str(getattr(row, "symbol"))
        spec = specs.get(symbol)
        risk_distance = _safe_float(getattr(row, "risk_distance"))
        if spec is None:
            missing_specs.add(symbol)
            value_per_point.append(math.nan)
            commission_points.append(math.nan)
            commission_r.append(math.nan)
            continue
        point_value = spec.value_per_point_per_lot
        risk_money_per_lot = risk_distance / spec.trade_tick_size * spec.trade_tick_value if risk_distance > 0 else math.nan
        value_per_point.append(point_value)
        commission_points.append(round_turn_per_lot / point_value)
        commission_r.append(round_turn_per_lot / risk_money_per_lot if risk_money_per_lot > 0 else math.nan)
    if missing_specs:
        raise KeyError(f"Missing symbol specs for: {', '.join(sorted(missing_specs))}")

    data["value_per_point_per_lot"] = value_per_point
    data["modeled_commission_points"] = commission_points
    data["modeled_commission_r"] = commission_r
    data["commission_adjusted_net_r"] = data["fill_r"] - data["modeled_commission_r"]
    return data


def _variant_row(summary: pd.DataFrame, variant: str) -> dict[str, Any]:
    rows = summary[summary["separation_variant_id"] == variant]
    if rows.empty:
        raise KeyError(f"Variant {variant!r} not found in commission summary.")
    return rows.iloc[0].to_dict()


def _metric_delta(metric: str, baseline: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    baseline_value = _safe_float(baseline.get(metric), default=math.nan)
    new_value = _safe_float(new.get(metric), default=math.nan)
    delta = new_value - baseline_value if math.isfinite(baseline_value) and math.isfinite(new_value) else None
    pct_delta = None
    if delta is not None and baseline_value != 0:
        pct_delta = delta / abs(baseline_value)
    return {
        "metric": metric,
        "baseline": baseline_value if math.isfinite(baseline_value) else None,
        "new_account": new_value if math.isfinite(new_value) else None,
        "delta": delta,
        "pct_delta": pct_delta,
    }


def _account_result(
    *,
    label: str,
    run_dir: Path,
    specs: dict[str, SymbolSpec],
    round_turn_per_lot: float,
    output_dir: Path,
) -> dict[str, Any]:
    trades = pd.read_csv(run_dir / "trades.csv")
    adjusted = apply_commission_model(trades, specs, round_turn_per_lot)
    safe_label = label.lower().replace(" ", "_").replace("/", "_")
    adjusted.to_csv(output_dir / f"{safe_label}_commission_adjusted_trades.csv", index=False)
    by_variant = _aggregate(adjusted, ["separation_variant_id", "separation_variant_label"], "commission_adjusted_net_r")
    by_symbol_timeframe = _aggregate(
        adjusted,
        ["separation_variant_id", "symbol", "timeframe"],
        "commission_adjusted_net_r",
    )
    by_variant.to_csv(output_dir / f"{safe_label}_summary_by_variant.csv", index=False)
    by_symbol_timeframe.to_csv(output_dir / f"{safe_label}_summary_by_symbol_timeframe.csv", index=False)
    return {
        "label": label,
        "run_dir": str(run_dir),
        "round_turn_commission_per_lot": round_turn_per_lot,
        "commission_adjusted_trades_path": str(output_dir / f"{safe_label}_commission_adjusted_trades.csv"),
        "summary_by_variant": by_variant.to_dict(orient="records"),
        "summary_by_symbol_timeframe_path": str(output_dir / f"{safe_label}_summary_by_symbol_timeframe.csv"),
    }


def _schedule_id_from_risks(lower: float, middle: float, w1: float) -> str:
    def token(value: float) -> str:
        return f"{value:.2f}".replace(".", "p")

    return f"bucket_ltf{token(lower)}_h12_d1{token(middle)}_w1{token(w1)}"


def _schedule_row(summary: pd.DataFrame, schedule_id: str, label: str) -> dict[str, Any]:
    rows = summary[summary["schedule_id"] == schedule_id]
    if rows.empty:
        raise KeyError(f"Schedule {schedule_id!r} not found in bucket summary.")
    row = rows.iloc[0].to_dict()
    row["comparison_label"] = label
    return row


def _study_rows(label: str, summary: pd.DataFrame, config: dict[str, Any]) -> list[dict[str, Any]]:
    adopted = _schedule_row(summary, _schedule_id_from_risks(0.20, 0.30, 0.75), "Adopted live row")
    growth = _schedule_row(summary, _schedule_id_from_risks(0.25, 0.30, 0.60), "Growth alternative")
    efficient = _efficiency_recommendation(summary).to_dict()
    efficient["comparison_label"] = "Most-efficient practical row"
    top_return = _recommendation(summary).to_dict()
    top_return["comparison_label"] = "Highest-return practical row"
    baseline = _baseline_row(summary, config)
    rows = [adopted, growth, efficient, top_return]
    if baseline is not None:
        baseline_row = baseline.to_dict()
        baseline_row["comparison_label"] = "V14 tight baseline"
        rows.append(baseline_row)
    for row in rows:
        row["account"] = label
    return rows


def _risk_bucket_study(
    *,
    label: str,
    adjusted_trades_path: Path,
    bucket_config: dict[str, Any],
    output_dir: Path,
    variant: str,
) -> dict[str, Any]:
    trades = pd.read_csv(adjusted_trades_path)
    trades = trades[trades["separation_variant_id"].astype(str) == variant].copy()
    trades["net_r"] = pd.to_numeric(trades["commission_adjusted_net_r"], errors="coerce").fillna(0.0)
    summary, timeframe_rows, ticker_rows = run_bucket_sensitivity_analysis(trades, bucket_config)
    safe_label = label.lower().replace(" ", "_").replace("/", "_")
    summary.to_csv(output_dir / f"{safe_label}_risk_bucket_summary.csv", index=False)
    timeframe_rows.to_csv(output_dir / f"{safe_label}_risk_bucket_timeframe_contribution.csv", index=False)
    ticker_rows.to_csv(output_dir / f"{safe_label}_risk_bucket_ticker_contribution.csv", index=False)
    selected_rows = _study_rows(label, summary, bucket_config)
    _write_csv(output_dir / f"{safe_label}_risk_bucket_selected_rows.csv", selected_rows)
    adopted = next(row for row in selected_rows if row["comparison_label"] == "Adopted live row")
    growth = next(row for row in selected_rows if row["comparison_label"] == "Growth alternative")
    efficient = next(row for row in selected_rows if row["comparison_label"] == "Most-efficient practical row")
    top_return = next(row for row in selected_rows if row["comparison_label"] == "Highest-return practical row")
    return {
        "label": label,
        "variant": variant,
        "trades": int(len(trades)),
        "summary_path": str(output_dir / f"{safe_label}_risk_bucket_summary.csv"),
        "selected_rows_path": str(output_dir / f"{safe_label}_risk_bucket_selected_rows.csv"),
        "practical_rows": int(summary["passes_practical_filters"].astype(bool).sum()),
        "adopted_live_row": adopted,
        "growth_alternative": growth,
        "most_efficient_practical_row": efficient,
        "highest_return_practical_row": top_return,
    }


def _risk_metric_delta(metric: str, baseline_row: dict[str, Any], new_row: dict[str, Any]) -> dict[str, Any]:
    return _metric_delta(metric, baseline_row, new_row)


def _risk_bucket_comparison_rows(baseline_study: dict[str, Any], new_study: dict[str, Any]) -> list[dict[str, Any]]:
    pairs = [
        ("adopted_live_row", "Adopted live row"),
        ("growth_alternative", "Growth alternative"),
        ("most_efficient_practical_row", "Most-efficient practical row"),
        ("highest_return_practical_row", "Highest-return practical row"),
    ]
    rows: list[dict[str, Any]] = []
    for key, label in pairs:
        baseline = baseline_study[key]
        new = new_study[key]
        row = {
            "comparison_label": label,
            "baseline_schedule_id": baseline["schedule_id"],
            "new_account_schedule_id": new["schedule_id"],
            "baseline_h4_h8_risk_pct": baseline["lower_risk_pct"],
            "baseline_h12_d1_risk_pct": baseline["middle_risk_pct"],
            "baseline_w1_risk_pct": baseline["w1_risk_pct"],
            "new_account_h4_h8_risk_pct": new["lower_risk_pct"],
            "new_account_h12_d1_risk_pct": new["middle_risk_pct"],
            "new_account_w1_risk_pct": new["w1_risk_pct"],
        }
        for metric in (
            "total_return_pct",
            "realized_max_drawdown_pct",
            "reserved_max_drawdown_pct",
            "max_reserved_open_risk_pct",
            "worst_month_pct",
            "return_to_reserved_drawdown",
        ):
            delta = _risk_metric_delta(metric, baseline, new)
            row[f"{metric}_baseline"] = delta["baseline"]
            row[f"{metric}_new_account"] = delta["new_account"]
            row[f"{metric}_delta"] = delta["delta"]
            row[f"{metric}_pct_delta"] = delta["pct_delta"]
        rows.append(row)
    return rows


def run_sensitivity(
    *,
    baseline_run_dir: Path,
    baseline_manifest_root: Path,
    baseline_round_turn_per_lot: float,
    new_run_dir: Path,
    new_symbol_specs_csv: Path,
    new_round_turn_per_lot: float,
    bucket_config_path: Path,
    output_dir: Path | None,
    variant: str,
) -> Path:
    target = output_dir or (DEFAULT_OUTPUT_ROOT / datetime.now(UTC).strftime("%Y%m%d_%H%M%S"))
    target.mkdir(parents=True, exist_ok=True)
    baseline_specs = load_symbol_specs_from_manifest_root(baseline_manifest_root)
    new_specs = load_symbol_specs_from_csv(new_symbol_specs_csv)
    baseline_result = _account_result(
        label="FTMO baseline",
        run_dir=baseline_run_dir,
        specs=baseline_specs,
        round_turn_per_lot=baseline_round_turn_per_lot,
        output_dir=target,
    )
    new_result = _account_result(
        label="IC Markets Raw Spread",
        run_dir=new_run_dir,
        specs=new_specs,
        round_turn_per_lot=new_round_turn_per_lot,
        output_dir=target,
    )

    baseline_summary = pd.DataFrame(baseline_result["summary_by_variant"])
    new_summary = pd.DataFrame(new_result["summary_by_variant"])
    baseline_variant = _variant_row(baseline_summary, variant)
    new_variant = _variant_row(new_summary, variant)
    metric_rows = [
        _metric_delta(metric, baseline_variant, new_variant)
        for metric in (
            "trades",
            "win_rate",
            "total_net_r",
            "avg_net_r",
            "profit_factor",
            "max_drawdown_r",
            "return_to_drawdown_r",
            "total_commission_r",
            "avg_commission_r",
        )
    ]
    _write_csv(target / "commission_adjusted_comparison.csv", metric_rows)
    bucket_config = _read_json(bucket_config_path)
    baseline_bucket_study = _risk_bucket_study(
        label="FTMO baseline",
        adjusted_trades_path=Path(baseline_result["commission_adjusted_trades_path"]),
        bucket_config=bucket_config,
        output_dir=target,
        variant=variant,
    )
    new_bucket_study = _risk_bucket_study(
        label="IC Markets Raw Spread",
        adjusted_trades_path=Path(new_result["commission_adjusted_trades_path"]),
        bucket_config=bucket_config,
        output_dir=target,
        variant=variant,
    )
    risk_rows = _risk_bucket_comparison_rows(baseline_bucket_study, new_bucket_study)
    _write_csv(target / "risk_bucket_comparison.csv", risk_rows)
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "variant": variant,
        "baseline": baseline_result,
        "new_account": new_result,
        "comparison": metric_rows,
        "risk_bucket_study": {
            "bucket_config_path": str(bucket_config_path),
            "baseline": baseline_bucket_study,
            "new_account": new_bucket_study,
            "comparison": risk_rows,
        },
        "method": {
            "formula": "commission_r = round_turn_commission_per_lot / (risk_distance / trade_tick_size * trade_tick_value)",
            "baseline_symbol_specs": str(baseline_manifest_root),
            "new_account_symbol_specs": str(new_symbol_specs_csv),
            "risk_bucket_formula": "account_return_pct = commission_adjusted_net_r * bucket_risk_pct",
        },
    }
    _write_json(target / "commission_sensitivity_summary.json", payload)
    (target / "README.md").write_text(
        f"""# LPFS Account Commission Sensitivity

Generated at: `{payload["generated_at_utc"]}`

- Baseline: `{baseline_run_dir}` with `${baseline_round_turn_per_lot:.2f}` round turn per lot.
- New account: `{new_run_dir}` with `${new_round_turn_per_lot:.2f}` round turn per lot.
- Variant: `{variant}`

This is a symbol-aware commission overlay on existing V22 trade rows. It does
not rerun signal detection because commission changes R after fill simulation,
not whether the candle hit entry/stop/target.

The risk-bucket study reuses the V15 64-row H4/H8, H12/D1, and W1 grid on the
commission-adjusted R stream for the selected V22 LP/FS-separated variant.
""",
        encoding="utf-8",
    )
    print(json.dumps({"output_dir": str(target), "variant": variant, "comparison": metric_rows}, indent=2, sort_keys=True))
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply symbol-aware commission sensitivity to LPFS V22 account comparisons.")
    parser.add_argument("--baseline-run-dir", default=str(DEFAULT_BASELINE_RUN_DIR))
    parser.add_argument("--baseline-manifest-root", default=str(DEFAULT_FTMO_DATA_ROOT))
    parser.add_argument("--baseline-round-turn-per-lot", type=float, default=5.0)
    parser.add_argument("--new-run-dir", default=str(DEFAULT_NEW_RUN_DIR))
    parser.add_argument("--new-symbol-specs-csv", default=str(DEFAULT_IC_SPECS_CSV))
    parser.add_argument("--new-round-turn-per-lot", type=float, default=7.0)
    parser.add_argument("--bucket-config", default=str(DEFAULT_BUCKET_CONFIG))
    parser.add_argument("--output-dir")
    parser.add_argument("--variant", default=DEFAULT_VARIANT)
    args = parser.parse_args()
    run_sensitivity(
        baseline_run_dir=Path(args.baseline_run_dir),
        baseline_manifest_root=Path(args.baseline_manifest_root),
        baseline_round_turn_per_lot=args.baseline_round_turn_per_lot,
        new_run_dir=Path(args.new_run_dir),
        new_symbol_specs_csv=Path(args.new_symbol_specs_csv),
        new_round_turn_per_lot=args.new_round_turn_per_lot,
        bucket_config_path=Path(args.bucket_config),
        output_dir=None if args.output_dir is None else Path(args.output_dir),
        variant=args.variant,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
