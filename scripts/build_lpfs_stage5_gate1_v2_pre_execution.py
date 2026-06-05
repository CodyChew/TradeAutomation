#!/usr/bin/env python3
"""Build the complete local-only LPFS Stage 5 Gate 1 v2 command bundle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from collect_lpfs_bounded_status_bundle import build_remote_status_command, render_command


PROFILE_ID = "stage5_gate1_dual_lane_contained_v2"
CONTRACT_ID = "stage5_gate1_v2_complete_read_only_v1"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PATH = (
    WORKSPACE_ROOT / "configs" / "operations" / "lpfs_stage5_resumption_safety_contract_profiles_v2.json"
)
DEFAULT_STATUS_SCRIPT_PATH = WORKSPACE_ROOT / "scripts" / "Get-LpfsLiveStatus.ps1"
COLLECTOR_PATH = WORKSPACE_ROOT / "scripts" / "collect_lpfs_bounded_status_bundle.py"

LANES: dict[str, dict[str, Any]] = {
    "FTMO": {
        "ssh_alias": "lpfs-vps",
        "repo_root": r"C:\TradeAutomation",
        "runtime_root": r"C:\TradeAutomationRuntime",
        "config_path": r"C:\TradeAutomation\config.local.json",
        "task_name": "LPFS_Live",
        "state_file_name": "lpfs_live_state.json",
        "journal_file_name": "lpfs_live_journal.jsonl",
        "heartbeat_file_name": "lpfs_live_heartbeat.json",
        "log_filter": "lpfs_live_*.log",
        "python_path": r"C:\TradeAutomation\venv\Scripts\python.exe",
        "magic": 131500,
        "comment_prefix": "LPFS",
    },
    "IC": {
        "ssh_alias": "lpfs-ic-vps",
        "repo_root": r"C:\TradeAutomation",
        "runtime_root": r"C:\TradeAutomationRuntimeIC",
        "config_path": r"C:\TradeAutomation\config.lpfs_icmarkets_raw_spread.local.json",
        "task_name": "LPFS_IC_Live",
        "state_file_name": "lpfs_ic_live_state.json",
        "journal_file_name": "lpfs_ic_live_journal.jsonl",
        "heartbeat_file_name": "lpfs_ic_live_heartbeat.json",
        "log_filter": "lpfs_ic_live_*.log",
        "python_path": r"C:\TradeAutomation\venv\Scripts\python.exe",
        "magic": 231500,
        "comment_prefix": "LPFSIC",
    },
}


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _strict_json_file(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_nonstandard_json_constant,
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell_array(values: list[str]) -> str:
    return "@(" + ",".join(_powershell_quote(value) for value in values) + ")"


def _encode_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def _ssh_command(alias: str, remote_command: list[str]) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        alias,
        *remote_command,
    ]


def _compact_containment_script(lane: dict[str, Any], critical_hashes: dict[str, str]) -> str:
    critical_paths = sorted(critical_hashes)
    return f"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Repo = {_powershell_quote(lane["repo_root"])}
$RuntimeRoot = {_powershell_quote(lane["runtime_root"])}
$ConfigPath = {_powershell_quote(lane["config_path"])}
$TaskName = {_powershell_quote(lane["task_name"])}
$StatePath = Join-Path $RuntimeRoot {_powershell_quote("data\\live\\" + lane["state_file_name"])}
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$Processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {{ $_.CommandLine }})
$Config = Get-Content -LiteralPath $ConfigPath -Raw -ErrorAction Stop | ConvertFrom-Json
$Document = Get-Content -LiteralPath $StatePath -Raw -ErrorAction Stop | ConvertFrom-Json
$State = if ($Document.state_schema_version -eq 2) {{ $Document.state }} else {{ $Document }}
$RepoHead = (& git -C $Repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($RepoHead)) {{ throw 'git rev-parse failed' }}
$TrackedStatus = @(& git -C $Repo status --porcelain=v1 --untracked-files=no)
if ($LASTEXITCODE -ne 0) {{ throw 'git tracked-worktree status failed' }}
$TrackedStatus = @($TrackedStatus | Where-Object {{ -not [string]::IsNullOrWhiteSpace($_) }})
$CriticalPaths = {_powershell_array(critical_paths)}
$CriticalHashes = [ordered]@{{}}
foreach ($RelativePath in $CriticalPaths) {{
    $FullPath = Join-Path $Repo ($RelativePath.Replace('/', '\\'))
    if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) {{ throw "missing critical runtime file: $RelativePath" }}
    $CriticalHashes[$RelativePath] = (Get-FileHash -LiteralPath $FullPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}}
$Output = [ordered]@{{
    checked_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    repo_head = $RepoHead
    kill_switch_active = (Test-Path -LiteralPath (Join-Path $RuntimeRoot 'data\\live\\KILL_SWITCH'))
    task_state = [string]$Task.State
    runner_process_count = @($Processes | Where-Object {{ $_.CommandLine -match 'run_lp_force_strike_live_executor\\.py' -and $_.CommandLine -match [regex]::Escape($RuntimeRoot) }}).Count
    watchdog_process_count = @($Processes | Where-Object {{ $_.CommandLine -match 'run_lpfs_live_forever\\.ps1' -and $_.CommandLine -match [regex]::Escape($RuntimeRoot) }}).Count
    market_recovery_mode = $Config.live_send.market_recovery_mode
    state_schema_version = $Document.state_schema_version
    state_pending_orders = @($State.pending_orders).Count
    state_active_positions = @($State.active_positions).Count
    tracked_worktree_clean = ($TrackedStatus.Count -eq 0)
    tracked_worktree_status = @($TrackedStatus)
    critical_runtime_file_hashes = $CriticalHashes
}}
Write-Output ('LPFS_GATE1_CONTAINMENT_JSON=' + ($Output | ConvertTo-Json -Compress -Depth 8))
"""


def _strict_mt5_script(lane: dict[str, Any]) -> str:
    return f"""import datetime as d
import json
import sys
from pathlib import Path

import MetaTrader5 as mt5

config = json.loads(Path(r"{lane["config_path"]}").read_text(encoding="utf-8"))
expected = config.get("mt5") or {{}}


def fail(reason):
    print(
        "LPFS_GATE1_MT5_JSON="
        + json.dumps({{"error": reason, "last_error": repr(mt5.last_error())}}, separators=(",", ":"))
    )
    raise SystemExit(2)


def keep_strategy_item(item):
    return int(getattr(item, "magic", 0) or 0) == {lane["magic"]} or str(
        getattr(item, "comment", "") or ""
    ).startswith("{lane["comment_prefix"]}")


def position_row(item):
    return {{
        "ticket": int(getattr(item, "ticket", 0) or 0),
        "identifier": int(getattr(item, "identifier", 0) or 0),
        "symbol": str(getattr(item, "symbol", "") or ""),
        "magic": int(getattr(item, "magic", 0) or 0),
        "comment": str(getattr(item, "comment", "") or ""),
        "volume": float(getattr(item, "volume", 0) or 0),
        "sl": float(getattr(item, "sl", 0) or 0),
        "tp": float(getattr(item, "tp", 0) or 0),
    }}


def order_row(item):
    return {{
        "ticket": int(getattr(item, "ticket", 0) or 0),
        "symbol": str(getattr(item, "symbol", "") or ""),
        "magic": int(getattr(item, "magic", 0) or 0),
        "comment": str(getattr(item, "comment", "") or ""),
        "volume": float(getattr(item, "volume_current", 0) or 0),
    }}


if not mt5.initialize():
    fail("initialize_ERROR_UNKNOWN")
try:
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    if account is None:
        fail("account_info_ERROR_UNKNOWN")
    if terminal is None:
        fail("terminal_info_ERROR_UNKNOWN")
    orders = mt5.orders_get()
    positions = mt5.positions_get()
    end = d.datetime.now(d.timezone.utc)
    start = end - d.timedelta(days=30)
    history_orders = mt5.history_orders_get(start, end)
    history_deals = mt5.history_deals_get(start, end)
    if orders is None:
        fail("orders_get_ERROR_UNKNOWN")
    if positions is None:
        fail("positions_get_ERROR_UNKNOWN")
    if history_orders is None:
        fail("history_orders_get_ERROR_UNKNOWN")
    if history_deals is None:
        fail("history_deals_get_ERROR_UNKNOWN")
    result = {{
        "read_only_contract": True,
        "collected_at_utc": end.isoformat(),
        "history_start_utc": start.isoformat(),
        "account_info": "OK",
        "terminal_info": "OK",
        "orders_get": "OK",
        "positions_get": "OK",
        "history_orders_get": "OK",
        "history_deals_get": "OK",
        "account_login": int(getattr(account, "login", 0) or 0),
        "account_server": str(getattr(account, "server", "") or ""),
        "account_matches_config": (
            str(getattr(account, "login", "") or "") == str(expected.get("expected_login") or "")
            and str(getattr(account, "server", "") or "") == str(expected.get("expected_server") or "")
        ),
        "terminal_connected": bool(getattr(terminal, "connected", False)),
        "terminal_trade_allowed": bool(getattr(terminal, "trade_allowed", False)),
        "counts": {{
            "orders": len(orders),
            "positions": len(positions),
            "history_orders_30d": len(history_orders),
            "history_deals_30d": len(history_deals),
        }},
        "strategy_orders": sorted(
            (order_row(item) for item in orders if keep_strategy_item(item)),
            key=lambda row: row["ticket"],
        ),
        "strategy_positions": sorted(
            (position_row(item) for item in positions if keep_strategy_item(item)),
            key=lambda row: row["ticket"],
        ),
        "last_error": repr(mt5.last_error()),
    }}
    print("LPFS_GATE1_MT5_JSON=" + json.dumps(result, separators=(",", ":"), allow_nan=False))
finally:
    mt5.shutdown()
"""


def _artifact_receipt(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_text(path: Path, payload: str) -> None:
    _write_bytes(path, payload.encode("utf-8"))


def _load_gate1_profile(profile_path: Path) -> dict[str, Any]:
    document = _strict_json_file(profile_path)
    if not isinstance(document, dict) or set(document) != {"schema_version", "profiles"}:
        raise ValueError("safety profile document has unexpected structure")
    profiles = document.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("safety profile document profiles must be an object")
    profile = profiles.get(PROFILE_ID)
    if not isinstance(profile, dict):
        raise ValueError(f"missing required profile: {PROFILE_ID}")
    if profile.get("profile_version") != 2:
        raise ValueError("Gate 1 v2 producer requires profile_version=2")
    if profile.get("required_steps") != [
        "FTMO/compact_containment",
        "FTMO/bounded_status",
        "FTMO/strict_mt5_probe",
        "IC/compact_containment",
        "IC/bounded_status",
        "IC/strict_mt5_probe",
    ]:
        raise ValueError("Gate 1 v2 profile required step set is incomplete or reordered")
    return profile


def _build_into(root: Path, profile_path: Path, status_script_path: Path) -> dict[str, Any]:
    profile = _load_gate1_profile(profile_path)
    status_implementation = status_script_path.read_bytes()
    status_sha256 = _sha256_bytes(status_implementation)
    artifacts: list[Path] = []

    shared_files = {
        root / "scripts" / "build_lpfs_stage5_gate1_v2_pre_execution.py": Path(__file__).read_bytes(),
        root / "scripts" / "collect_lpfs_bounded_status_bundle.py": COLLECTOR_PATH.read_bytes(),
        root / "scripts" / "Get-LpfsLiveStatus.ps1": status_implementation,
    }
    for path, payload in shared_files.items():
        _write_bytes(path, payload)
        artifacts.append(path)

    for lane_name, lane in LANES.items():
        lane_root = root / lane_name
        compact_step = profile["steps"][f"{lane_name}/compact_containment"]
        critical_hashes = compact_step["expectations"].get("critical_runtime_file_hashes")
        if not isinstance(critical_hashes, dict) or not critical_hashes:
            raise ValueError(f"{lane_name} compact containment lacks critical runtime hashes")
        compact_script = _compact_containment_script(lane, critical_hashes)
        compact_command = _ssh_command(
            lane["ssh_alias"],
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                _encode_powershell(compact_script),
            ],
        )
        compact_script_path = lane_root / "compact_containment.remote.ps1"
        compact_command_path = lane_root / "compact_containment.command.txt"
        _write_text(compact_script_path, compact_script)
        _write_text(compact_command_path, render_command(compact_command))
        artifacts.extend((compact_script_path, compact_command_path))

        bounded_step = profile["steps"][f"{lane_name}/bounded_status"]
        if bounded_step.get("expected_status_implementation_sha256") != status_sha256:
            raise ValueError(f"{lane_name} expected status implementation hash does not match reviewed bytes")
        bounded_command = build_remote_status_command(
            ssh_alias=lane["ssh_alias"],
            status_implementation=status_implementation,
            expected_status_sha256=status_sha256,
            runtime_root=lane["runtime_root"],
            state_file_name=lane["state_file_name"],
            journal_file_name=lane["journal_file_name"],
            heartbeat_file_name=lane["heartbeat_file_name"],
            log_filter=lane["log_filter"],
            journal_lines=5,
            log_lines=10,
        )
        bounded_command_text = render_command(bounded_command)
        bounded_command_sha256 = _sha256_bytes(bounded_command_text.encode("utf-8"))
        if bounded_command_sha256 != bounded_step.get("expected_command_sha256"):
            raise ValueError(
                f"{lane_name} bounded status command hash differs from reviewed profile: "
                f"expected={bounded_step.get('expected_command_sha256')} actual={bounded_command_sha256}"
            )
        bounded_command_path = lane_root / "bounded_status.command.txt"
        _write_text(bounded_command_path, bounded_command_text)
        artifacts.append(bounded_command_path)

        strict_script = _strict_mt5_script(lane)
        strict_command = _ssh_command(
            lane["ssh_alias"],
            [
                lane["python_path"],
                "-c",
                "import base64;exec(base64.b64decode("
                + repr(base64.b64encode(strict_script.encode("utf-8")).decode("ascii"))
                + "))",
            ],
        )
        strict_script_path = lane_root / "strict_mt5_probe.py"
        strict_command_path = lane_root / "strict_mt5_probe.command.txt"
        _write_text(strict_script_path, strict_script)
        _write_text(strict_command_path, render_command(strict_command))
        artifacts.extend((strict_script_path, strict_command_path))

    receipts = [_artifact_receipt(path, root) for path in sorted(artifacts)]
    manifest = {
        "schema_version": 1,
        "producer_kind": "lpfs_stage5_gate1_v2_pre_execution_bundle",
        "profile_id": PROFILE_ID,
        "contract_id": CONTRACT_ID,
        "executes_commands": False,
        "artifact_count": len(receipts),
        "artifacts": receipts,
    }
    _write_text(root / "producer_manifest.json", json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return manifest


def build_gate1_v2_pre_execution_bundle(
    output_root: str | Path,
    *,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    status_script_path: str | Path = DEFAULT_STATUS_SCRIPT_PATH,
) -> dict[str, Any]:
    output = Path(output_root)
    if output.exists():
        raise FileExistsError(f"output root already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent)))
    try:
        manifest = _build_into(staging, Path(profile_path), Path(status_script_path))
        os.replace(staging, output)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, help="New local staging directory to publish atomically.")
    parser.add_argument("--profile-file", default=str(DEFAULT_PROFILE_PATH))
    parser.add_argument("--status-script", default=str(DEFAULT_STATUS_SCRIPT_PATH))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_gate1_v2_pre_execution_bundle(
        args.output_root,
        profile_path=args.profile_file,
        status_script_path=args.status_script,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
