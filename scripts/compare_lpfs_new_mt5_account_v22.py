from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_ROOT = REPO_ROOT / "reports" / "strategies" / "lp_force_strike_experiment_v22_lp_fs_separation"
DEFAULT_VARIANT = "exclude_lp_pivot_inside_fs"


METRICS = (
    "trades",
    "win_rate",
    "total_net_r",
    "avg_net_r",
    "profit_factor",
    "max_drawdown_r",
    "return_to_drawdown_r",
    "bucket_efficient_total_return_pct",
    "bucket_efficient_reserved_max_drawdown_pct",
    "bucket_efficient_return_to_reserved_drawdown",
)


def _latest_run_dir(root: Path) -> Path:
    runs = [path for path in root.iterdir() if path.is_dir() and (path / "summary_by_variant.csv").exists()]
    if not runs:
        raise FileNotFoundError(f"No V22 baseline report runs found under {root}")
    return sorted(runs, key=lambda path: path.name)[-1]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def _float(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _variant_row(run_dir: Path, variant: str) -> dict[str, str]:
    rows = _read_csv(run_dir / "summary_by_variant.csv")
    for row in rows:
        if row.get("separation_variant_id") == variant:
            return row
    raise KeyError(f"Variant {variant!r} not found in {run_dir / 'summary_by_variant.csv'}")


def _metric_delta(metric: str, baseline: dict[str, str], new: dict[str, str]) -> dict[str, Any]:
    baseline_value = _float(baseline, metric)
    new_value = _float(new, metric)
    delta = None if baseline_value is None or new_value is None else new_value - baseline_value
    pct_delta = None
    if baseline_value not in (None, 0.0) and delta is not None:
        pct_delta = delta / abs(baseline_value)
    return {
        "metric": metric,
        "baseline": baseline_value,
        "new_account": new_value,
        "delta": delta,
        "pct_delta": pct_delta,
    }


def _symbol_timeframe_deltas(baseline_dir: Path, new_dir: Path, variant: str) -> list[dict[str, Any]]:
    baseline_rows = [
        row for row in _read_csv(baseline_dir / "summary_by_symbol_timeframe.csv")
        if row.get("separation_variant_id") == variant
    ]
    new_rows = [
        row for row in _read_csv(new_dir / "summary_by_symbol_timeframe.csv")
        if row.get("separation_variant_id") == variant
    ]
    baseline_index = {(row["symbol"], row["timeframe"]): row for row in baseline_rows}
    new_index = {(row["symbol"], row["timeframe"]): row for row in new_rows}
    keys = sorted(set(baseline_index) | set(new_index))
    rows: list[dict[str, Any]] = []
    for symbol, timeframe in keys:
        base = baseline_index.get((symbol, timeframe), {})
        new = new_index.get((symbol, timeframe), {})
        row = {"symbol": symbol, "timeframe": timeframe}
        for metric in ("trades", "win_rate", "total_net_r", "avg_net_r", "profit_factor"):
            values = _metric_delta(metric, base, new)
            row[f"{metric}_baseline"] = values["baseline"]
            row[f"{metric}_new_account"] = values["new_account"]
            row[f"{metric}_delta"] = values["delta"]
        rows.append(row)
    return rows


def _read_run_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_readme(payload: dict[str, Any]) -> str:
    return f"""# LPFS New MT5 Account V22 Comparison

Generated at: `{payload["generated_at_utc"]}`

- Baseline run: `{payload["baseline_run_dir"]}`
- New-account run: `{payload["new_account_run_dir"]}`
- Variant: `{payload["variant"]}`

Use this as a first-pass broker-data similarity check. A similar result does
not approve live-send by itself; it only supports moving to local dry-run /
`order_check` validation.
"""


def compare_runs(*, baseline_run_dir: Path | None, new_run_dir: Path, output_dir: Path | None, variant: str) -> int:
    baseline_dir = baseline_run_dir or _latest_run_dir(DEFAULT_BASELINE_ROOT)
    target_dir = output_dir or (new_run_dir / "comparison_to_current_v22")
    baseline_summary = _variant_row(baseline_dir, variant)
    new_summary = _variant_row(new_run_dir, variant)
    metric_rows = [_metric_delta(metric, baseline_summary, new_summary) for metric in METRICS]
    symbol_timeframe_rows = _symbol_timeframe_deltas(baseline_dir, new_run_dir, variant)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_run_dir": str(baseline_dir),
        "new_account_run_dir": str(new_run_dir),
        "variant": variant,
        "baseline_run_summary": _read_run_summary(baseline_dir),
        "new_account_run_summary": _read_run_summary(new_run_dir),
        "metrics": metric_rows,
    }
    target_dir.mkdir(parents=True, exist_ok=True)
    _write_json(target_dir / "comparison_summary.json", payload)
    _write_csv(target_dir / "comparison_summary.csv", metric_rows)
    _write_csv(target_dir / "symbol_timeframe_delta.csv", symbol_timeframe_rows)
    (target_dir / "README.md").write_text(build_readme(payload), encoding="utf-8")
    print(json.dumps({"output_dir": str(target_dir), "variant": variant, "metrics": metric_rows}, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a new-account LPFS V22 run against the current V22 baseline.")
    parser.add_argument("--new-run-dir", required=True, help="New-account V22 report directory.")
    parser.add_argument("--baseline-run-dir", help="Baseline V22 report directory. Defaults to latest existing V22 baseline report.")
    parser.add_argument("--output-dir", help="Comparison output directory. Defaults under the new run directory.")
    parser.add_argument("--variant", default=DEFAULT_VARIANT, help="Variant to compare.")
    args = parser.parse_args()
    return compare_runs(
        baseline_run_dir=None if args.baseline_run_dir is None else Path(args.baseline_run_dir),
        new_run_dir=Path(args.new_run_dir),
        output_dir=None if args.output_dir is None else Path(args.output_dir),
        variant=args.variant,
    )


if __name__ == "__main__":
    raise SystemExit(main())
