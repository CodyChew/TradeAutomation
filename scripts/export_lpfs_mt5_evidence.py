"""Export a strict, read-only MT5 evidence packet for LPFS C-01 audits."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [
    ROOT / "concepts" / "lp_levels_lab" / "src",
    ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    ROOT / "shared" / "backtest_engine_lab" / "src",
    ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab import initialize_mt5_session, load_dry_run_settings  # noqa: E402


SCHEMA_VERSION = 1


class EvidenceExportError(RuntimeError):
    """Raised when broker truth cannot be exported completely."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _item_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "_asdict"):
        return dict(item._asdict())
    if hasattr(item, "__dict__"):
        return dict(vars(item))
    return {"repr": repr(item)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _required_read(mt5: Any, operation: str, *args: Any, **kwargs: Any) -> tuple[Any, ...]:
    result = getattr(mt5, operation)(*args, **kwargs)
    if result is None:
        raise EvidenceExportError(f"MT5 {operation} returned ERROR/UNKNOWN; last_error={mt5.last_error()!r}.")
    return tuple(result)


def export_evidence(
    mt5: Any,
    *,
    lane: str,
    output_root: Path,
    history_start_utc: datetime,
    history_end_utc: datetime,
) -> Path:
    """Publish one complete packet atomically after every required read succeeds."""

    collected_at = _utc_now()
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    if account is None:
        raise EvidenceExportError(f"MT5 account_info returned ERROR/UNKNOWN; last_error={mt5.last_error()!r}.")
    if terminal is None:
        raise EvidenceExportError(f"MT5 terminal_info returned ERROR/UNKNOWN; last_error={mt5.last_error()!r}.")
    orders = _required_read(mt5, "orders_get")
    positions = _required_read(mt5, "positions_get")
    history_orders = _required_read(mt5, "history_orders_get", history_start_utc, history_end_utc)
    history_deals = _required_read(mt5, "history_deals_get", history_start_utc, history_end_utc)

    stamp = collected_at.strftime("%Y%m%d_%H%M%S")
    final_dir = output_root / stamp
    staging_dir = output_root / f".{stamp}.{os.getpid()}.tmp"
    if final_dir.exists() or staging_dir.exists():
        raise EvidenceExportError(f"Evidence packet output already exists for {stamp}.")
    staging_dir.mkdir(parents=True)
    try:
        evidence_path = staging_dir / "mt5_evidence.json"
        payload = {
            "schema_version": SCHEMA_VERSION,
            "lane": lane,
            "collected_at_utc": collected_at.isoformat(),
            "history_start_utc": history_start_utc.isoformat(),
            "history_end_utc": history_end_utc.isoformat(),
            "read_only_contract": True,
            "account": _item_dict(account),
            "terminal": _item_dict(terminal),
            "last_error": mt5.last_error(),
            "orders": [_item_dict(item) for item in orders],
            "positions": [_item_dict(item) for item in positions],
            "history_orders": [_item_dict(item) for item in history_orders],
            "history_deals": [_item_dict(item) for item in history_deals],
        }
        _atomic_write_json(evidence_path, payload)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "lane": lane,
            "collected_at_utc": collected_at.isoformat(),
            "read_only_contract": True,
            "files": {
                evidence_path.name: {
                    "bytes": evidence_path.stat().st_size,
                    "sha256": _sha256(evidence_path),
                }
            },
            "counts": {
                "orders": len(orders),
                "positions": len(positions),
                "history_orders": len(history_orders),
                "history_deals": len(history_deals),
            },
        }
        _atomic_write_json(staging_dir / "manifest.json", manifest)
        os.replace(staging_dir, final_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return final_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.local.json", help="Ignored local config with expected MT5 identity.")
    parser.add_argument("--lane", required=True, help="Stable lane label, for example FTMO or IC.")
    parser.add_argument(
        "--output-root",
        default="reports/live_ops/lpfs_c01_mt5_evidence",
        help="Local ignored evidence root.",
    )
    parser.add_argument("--history-start-utc", default="2000-01-01T00:00:00+00:00")
    args = parser.parse_args()

    import MetaTrader5 as mt5

    settings = load_dry_run_settings(args.config)
    initialize_mt5_session(mt5, settings.local)
    try:
        packet = export_evidence(
            mt5,
            lane=str(args.lane).upper(),
            output_root=Path(args.output_root),
            history_start_utc=datetime.fromisoformat(args.history_start_utc.replace("Z", "+00:00")),
            history_end_utc=_utc_now(),
        )
    finally:
        mt5.shutdown()
    print(packet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
