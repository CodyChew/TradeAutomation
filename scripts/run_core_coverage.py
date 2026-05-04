"""Run the strict core strategy coverage gate."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COVERAGE_RC = ROOT / ".coveragerc"

SRC_ROOTS = [
    ROOT / "concepts" / "lp_levels_lab" / "src",
    ROOT / "concepts" / "majority_flush_lab" / "src",
    ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    ROOT / "shared" / "backtest_engine_lab" / "src",
    ROOT / "shared" / "market_data_lab" / "src",
    ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]

LABS = [
    ("lp_levels", ROOT / "concepts" / "lp_levels_lab" / "tests"),
    ("majority_flush", ROOT / "concepts" / "majority_flush_lab" / "tests"),
    ("force_strike", ROOT / "concepts" / "force_strike_pattern_lab" / "tests"),
    ("backtest_engine", ROOT / "shared" / "backtest_engine_lab" / "tests"),
    ("market_data", ROOT / "shared" / "market_data_lab" / "tests"),
    ("lp_force_strike_strategy", ROOT / "strategies" / "lp_force_strike_strategy_lab" / "tests"),
]


def _coverage_files() -> list[Path]:
    return list(ROOT.glob(".coverage*"))


def _clean_coverage_files() -> None:
    for path in _coverage_files():
        if path.name.startswith(".coveragerc"):
            continue
        path.unlink()


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    printable = " ".join(command)
    print(f"\n$ {printable}", flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    pythonpath = os.pathsep.join(str(path) for path in SRC_ROOTS)
    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = pythonpath + os.pathsep + base_env.get("PYTHONPATH", "")
    base_env["COVERAGE_RCFILE"] = str(COVERAGE_RC)

    _clean_coverage_files()
    for lab_name, test_dir in LABS:
        env = base_env.copy()
        env["COVERAGE_FILE"] = str(ROOT / f".coverage.{lab_name}")
        _run(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--branch",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(test_dir),
            ],
            env=env,
        )

    _run([sys.executable, "-m", "coverage", "combine"], env=base_env)
    _run([sys.executable, "-m", "coverage", "report", "--show-missing"], env=base_env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
