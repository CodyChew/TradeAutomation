from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "shared" / "market_data_lab" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import dataset_coverage_report, load_dataset_config


def _write_json(path: str | Path, payload) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report configured dataset coverage.")
    parser.add_argument("--config", required=True, help="Path to dataset config JSON.")
    parser.add_argument("--output", help="Optional path for the full JSON report.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report instead of a compact summary.")
    args = parser.parse_args()

    config = load_dataset_config(args.config)
    rows = dataset_coverage_report(config)
    if args.output:
        _write_json(args.output, rows)
    ready = [row for row in rows if row["backtest_ready"]]
    missing = [row for row in rows if not row["data_exists"]]
    partial = [row for row in rows if row["data_exists"] and not row["backtest_ready"]]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        print(f"datasets={len(rows)} ready={len(ready)} missing={len(missing)} partial={len(partial)}")
        if args.output:
            print(f"wrote={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
