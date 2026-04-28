from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "shared" / "market_data_lab" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import load_dataset_config, pull_mt5_dataset


def _write_json(path: str | Path, payload) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull a configured MT5 candle dataset.")
    parser.add_argument("--config", required=True, help="Path to dataset config JSON.")
    parser.add_argument("--output", help="Optional path for the full JSON result.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON result instead of a compact summary.")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop at the first failed symbol/timeframe.")
    args = parser.parse_args()

    config = load_dataset_config(args.config)
    results = pull_mt5_dataset(config, stop_on_error=args.stop_on_error)
    payload = [item.to_dict() for item in results]
    failures = [item for item in results if item.status != "ok"]
    if args.output:
        _write_json(args.output, payload)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"datasets={len(results)} ok={len(results) - len(failures)} failed={len(failures)}")
        if failures:
            print("failed=" + ",".join(f"{item.symbol}:{item.timeframe}" for item in failures[:20]))
        if args.output:
            print(f"wrote={args.output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
