#!/usr/bin/env python3
"""Collect lane-authoritative LPFS candle snapshots from FTMO/IC VPS MT5 terminals.

This is a read-only research-data collector. It does not touch scheduled tasks,
kill switches, live configs, runtime state, production journals, broker orders,
or broker positions. It runs the existing MT5 candle dataset puller on the
selected VPS lane and validates the returned dataset manifests before marking
the local packet safe for strategy-analysis candle enrichment.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
MARKET_DATA_SRC = REPO_ROOT / "shared" / "market_data_lab" / "src"
if str(MARKET_DATA_SRC) not in sys.path:
    sys.path.insert(0, str(MARKET_DATA_SRC))

from market_data_lab import FOREX_MAJOR_CROSS_PAIRS, normalize_timeframe  # noqa: E402


DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "live_ops" / "lpfs_lane_candle_snapshots"
DEFAULT_TIMEFRAMES = ("H4", "H8", "H12", "D1", "W1")
DEFAULT_HISTORY_YEARS = 1
COLLECTOR_SCHEMA_VERSION = 1
REMOTE_MARKER = "LPFS_LANE_CANDLE_SNAPSHOT_JSON="
LANE_RE = re.compile(r"^[A-Z][A-Z0-9_-]*$")


class CandleSnapshotError(RuntimeError):
    """Raised when a lane candle snapshot cannot be collected or verified."""


@dataclass(frozen=True)
class LaneProfile:
    lane: str
    ssh_alias: str
    repo_path: str
    python_path: str
    expected_server: str
    expected_company_contains: str
    local_dir_name: str


@dataclass(frozen=True)
class LaneRequest:
    profile: LaneProfile
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    history_years: int
    date_start_utc: str | None
    date_end_utc: str | None
    collection_id: str
    frame_timeout_seconds: int


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    stdout: str
    stderr: str
    returncode: int


LANE_PROFILES: dict[str, LaneProfile] = {
    "FTMO": LaneProfile(
        lane="FTMO",
        ssh_alias="lpfs-vps",
        repo_path=r"C:\TradeAutomation",
        python_path=r"C:\TradeAutomation\venv\Scripts\python.exe",
        expected_server="FTMO-Server",
        expected_company_contains="FTMO",
        local_dir_name="ftmo_vps_broker_feed_candles",
    ),
    "IC": LaneProfile(
        lane="IC",
        ssh_alias="lpfs-ic-vps",
        repo_path=r"C:\TradeAutomation",
        python_path=r"C:\TradeAutomation\venv\Scripts\python.exe",
        expected_server="ICMarketsSC-MT5-2",
        expected_company_contains="Raw Trading",
        local_dir_name="ic_vps_broker_feed_candles",
    ),
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--lane", action="append", choices=sorted(LANE_PROFILES), help="Lane to collect. Defaults to both lanes.")
    parser.add_argument("--symbols", help="Comma-separated symbol override. Defaults to the LPFS 28 major/cross FX pairs.")
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES), help="Comma-separated timeframe list.")
    parser.add_argument(
        "--history-years",
        type=int,
        default=DEFAULT_HISTORY_YEARS,
        help="Recent bounded pull size. Defaults to 1 year; use a larger value only intentionally.",
    )
    parser.add_argument("--date-start-utc", default=None, help="Optional explicit dataset start timestamp.")
    parser.add_argument("--date-end-utc", default=None, help="Optional explicit dataset end timestamp.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--remote-root", default=r"C:\Windows\Temp\lpfs_lane_candle_snapshots")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument(
        "--frame-timeout",
        type=int,
        default=180,
        help="Per symbol/timeframe MT5 pull timeout inside the remote helper.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build and validate the request packet without SSH/SCP.")
    args = parser.parse_args(argv)

    try:
        lanes = tuple(args.lane or ("FTMO", "IC"))
        symbols = _parse_csv(args.symbols) if args.symbols else tuple(FOREX_MAJOR_CROSS_PAIRS)
        timeframes = tuple(normalize_timeframe(value) for value in _parse_csv(args.timeframes))
        if args.history_years <= 0:
            raise CandleSnapshotError("--history-years must be positive")
        if bool(args.date_start_utc) != bool(args.date_end_utc):
            raise CandleSnapshotError("--date-start-utc and --date-end-utc must be provided together")
        if args.frame_timeout <= 0:
            raise CandleSnapshotError("--frame-timeout must be positive")
        packet = collect_lane_candle_snapshots(
            lanes=lanes,
            symbols=symbols,
            timeframes=timeframes,
            history_years=args.history_years,
            date_start_utc=args.date_start_utc,
            date_end_utc=args.date_end_utc,
            output_root=Path(args.output_root),
            remote_root=args.remote_root,
            timeout=args.timeout,
            frame_timeout_seconds=args.frame_timeout,
            dry_run=args.dry_run,
        )
    except CandleSnapshotError as exc:
        parser.error(str(exc))
    print(f"packet={packet}")
    print(f"manifest={packet / 'manifest.json'}")
    print(f"manifest_sha256={packet / 'manifest.sha256.txt'}")
    return 0


def collect_lane_candle_snapshots(
    *,
    lanes: Sequence[str],
    symbols: Sequence[str],
    timeframes: Sequence[str],
    history_years: int,
    date_start_utc: str | None,
    date_end_utc: str | None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    remote_root: str = r"C:\Windows\Temp\lpfs_lane_candle_snapshots",
    timeout: int = 3600,
    frame_timeout_seconds: int = 180,
    dry_run: bool = False,
    now: datetime | None = None,
    runner: Callable[..., CommandResult] | None = None,
    fetcher: Callable[..., CommandResult] | None = None,
) -> Path:
    runner = runner or _run_ssh_powershell
    fetcher = fetcher or _run_scp_fetch
    collection_time = now or datetime.now(timezone.utc)
    collection_id = collection_time.strftime("%Y%m%d_%H%M%S")
    output_root.mkdir(parents=True, exist_ok=True)
    final_dir = output_root / collection_id
    staging_dir = output_root / f".{collection_id}.{os.getpid()}.tmp"
    if final_dir.exists() or staging_dir.exists():
        raise CandleSnapshotError(f"output packet already exists for timestamp {collection_id}")
    staging_dir.mkdir(parents=True)
    lane_results: list[dict[str, Any]] = []
    packet_result = "DRY_RUN" if dry_run else "PASS"
    try:
        for lane in lanes:
            lane_key = _lane_key(lane)
            profile = LANE_PROFILES.get(lane_key)
            if profile is None:
                raise CandleSnapshotError(f"unsupported lane {lane!r}")
            request = LaneRequest(
                profile=profile,
                symbols=tuple(str(symbol).upper() for symbol in symbols),
                timeframes=tuple(normalize_timeframe(timeframe) for timeframe in timeframes),
                history_years=history_years,
                date_start_utc=date_start_utc,
                date_end_utc=date_end_utc,
                collection_id=collection_id,
                frame_timeout_seconds=frame_timeout_seconds,
            )
            lane_dir = staging_dir / lane_key.lower()
            lane_dir.mkdir()
            lane_result = _collect_one_lane(
                request,
                lane_dir=lane_dir,
                remote_root=remote_root,
                timeout=timeout,
                dry_run=dry_run,
                runner=runner,
                fetcher=fetcher,
            )
            lane_results.append(lane_result)
            if not dry_run and lane_result["result"] != "PASS":
                packet_result = "STOPPED"
        os.replace(staging_dir, final_dir)
        lane_results = _rewrite_packet_local_paths(
            packet_dir=final_dir,
            old_root=staging_dir,
            new_root=final_dir,
            lane_results=lane_results,
        )
        _write_packet_manifest(
            final_dir,
            packet_result=packet_result,
            collection_time=collection_time,
            dry_run=dry_run,
            lane_results=lane_results,
        )
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return final_dir


def _collect_one_lane(
    request: LaneRequest,
    *,
    lane_dir: Path,
    remote_root: str,
    timeout: int,
    dry_run: bool,
    runner: Callable[..., CommandResult],
    fetcher: Callable[..., CommandResult],
) -> dict[str, Any]:
    script = build_remote_lane_script(request, remote_root=remote_root)
    (lane_dir / "remote_collect.ps1").write_text(script, encoding="utf-8")
    (lane_dir / "request.json").write_text(json.dumps(_request_payload(request), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if dry_run:
        summary = {
            "result": "DRY_RUN",
            "lane": request.profile.lane,
            "ssh_alias": request.profile.ssh_alias,
            "remote_zip_scp_path": "",
        }
        (lane_dir / "validation_summary.json").write_text(
            json.dumps({"result": "DRY_RUN", "failures": [], "remote_summary": summary}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {"lane": request.profile.lane, "result": "DRY_RUN", "failures": [], "local_candle_root": ""}

    command_result = runner(request.profile.ssh_alias, script, timeout=timeout)
    _write_command_result(lane_dir, "remote_collect", command_result)
    if command_result.returncode != 0:
        failure = f"remote collection failed with exit code {command_result.returncode}"
        _write_validation(lane_dir, "STOPPED", [failure], remote_summary=None)
        return {"lane": request.profile.lane, "result": "STOPPED", "failures": [failure], "local_candle_root": ""}
    remote_summary = _parse_remote_summary(command_result.stdout)
    remote_zip_path = str(remote_summary.get("remote_zip_scp_path") or "")
    if not remote_zip_path:
        failure = "remote summary did not include remote_zip_scp_path"
        _write_validation(lane_dir, "STOPPED", [failure], remote_summary=remote_summary)
        return {"lane": request.profile.lane, "result": "STOPPED", "failures": [failure], "local_candle_root": ""}
    local_zip = lane_dir / "snapshot.zip"
    fetch_result = fetcher(request.profile.ssh_alias, remote_zip_path, local_zip, timeout=timeout)
    _write_command_result(lane_dir, "scp_fetch", fetch_result)
    if fetch_result.returncode != 0 or not local_zip.is_file():
        failure = f"snapshot fetch failed with exit code {fetch_result.returncode}"
        _write_validation(lane_dir, "STOPPED", [failure], remote_summary=remote_summary)
        return {"lane": request.profile.lane, "result": "STOPPED", "failures": [failure], "local_candle_root": ""}
    expected_zip_hash = str(remote_summary.get("remote_zip_sha256") or "").lower()
    actual_zip_hash = _sha256_file(local_zip)
    if expected_zip_hash and expected_zip_hash != actual_zip_hash:
        failure = f"snapshot zip SHA-256 mismatch: expected={expected_zip_hash} actual={actual_zip_hash}"
        _write_validation(lane_dir, "STOPPED", [failure], remote_summary=remote_summary)
        return {"lane": request.profile.lane, "result": "STOPPED", "failures": [failure], "local_candle_root": ""}

    extract_dir = lane_dir / "extracted"
    with zipfile.ZipFile(local_zip) as archive:
        _safe_extract_zip(archive, extract_dir)
    candle_root = extract_dir / "candles"
    validation = validate_lane_candle_root(
        candle_root,
        request=request,
    )
    failures = list(validation["failures"])
    remote_result = str(remote_summary.get("result") or "")
    if remote_result != "PASS":
        failures.insert(0, f"remote collection result was {remote_result or 'UNKNOWN'}")
    result = "PASS" if not failures else "STOPPED"
    _write_validation(lane_dir, result, failures, remote_summary=remote_summary, validation=validation)
    return {
        "lane": request.profile.lane,
        "result": result,
        "failures": failures,
        "local_candle_root": str(candle_root),
        "manifest_count": validation["manifest_count"],
        "row_count": validation["row_count"],
    }


def build_remote_lane_script(request: LaneRequest, *, remote_root: str) -> str:
    payload = _request_payload(request)
    config = {
        "dataset_name": f"lpfs_{request.profile.lane.lower()}_lane_broker_feed_candles",
        "data_root": _windows_join(remote_root, request.collection_id, request.profile.lane.lower(), "candles"),
        "symbols": list(request.symbols),
        "timeframes": list(request.timeframes),
        "history_years": request.history_years,
        "date_start_utc": request.date_start_utc,
        "date_end_utc": request.date_end_utc,
        "source": "mt5",
        "allow_symbol_select": False,
    }
    if request.date_start_utc and request.date_end_utc:
        config.pop("history_years", None)
    config["frame_timeout_seconds"] = request.frame_timeout_seconds
    config_b64 = base64.b64encode(json.dumps(config, separators=(",", ":"), sort_keys=True).encode("utf-8")).decode("ascii")
    request_b64 = base64.b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")).decode("ascii")
    python_source = _remote_collect_python_source()
    python_source_b64 = base64.b64encode(python_source.encode("utf-8")).decode("ascii")
    python_source_sha256 = hashlib.sha256(python_source.encode("utf-8")).hexdigest()
    repo = _ps_quote(request.profile.repo_path)
    python = _ps_quote(request.profile.python_path)
    work_dir = _ps_quote(_windows_join(remote_root, request.collection_id, request.profile.lane.lower()))
    return f"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Repo = {repo}
$Python = {python}
$WorkDir = {work_dir}
$SharedMarketDataSrc = Join-Path $Repo 'shared\\market_data_lab\\src'
$ConfigPath = Join-Path $WorkDir 'dataset_config.json'
$RequestPath = Join-Path $WorkDir 'request.json'
$ResultPath = Join-Path $WorkDir 'pull_result.json'
$CollectScriptPath = Join-Path $WorkDir 'collect_lane_candles.py'
$DataRoot = Join-Path $WorkDir 'candles'
$ZipPath = Join-Path $WorkDir 'snapshot.zip'
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
if (-not (Test-Path -LiteralPath $Repo)) {{ throw "repo path not found: $Repo" }}
if (-not (Test-Path -LiteralPath $Python)) {{ throw "python path not found: $Python" }}
if (-not (Test-Path -LiteralPath $SharedMarketDataSrc)) {{ throw "market_data_lab source path not found: $SharedMarketDataSrc" }}
[IO.File]::WriteAllBytes($ConfigPath, [Convert]::FromBase64String('{config_b64}'))
[IO.File]::WriteAllBytes($RequestPath, [Convert]::FromBase64String('{request_b64}'))
[IO.File]::WriteAllBytes($CollectScriptPath, [Convert]::FromBase64String('{python_source_b64}'))
$CollectScriptHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $CollectScriptPath).Hash.ToLowerInvariant()
if ($CollectScriptHash -ne '{python_source_sha256}') {{ throw "collect script hash mismatch: $CollectScriptHash" }}
try {{
  $RepoHead = (& git -C $Repo rev-parse HEAD 2>$null)
}} catch {{
  $RepoHead = 'unknown'
}}
& $Python $CollectScriptPath --repo $Repo --config $ConfigPath --output $ResultPath
$PullExit = $LASTEXITCODE
if ($PullExit -ne 0) {{ throw "lane candle collection failed with exit code $PullExit" }}
if (Test-Path -LiteralPath $ZipPath) {{ Remove-Item -LiteralPath $ZipPath -Force }}
Compress-Archive -LiteralPath $DataRoot,$ConfigPath,$RequestPath,$ResultPath,$CollectScriptPath -DestinationPath $ZipPath -Force
$ZipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath).Hash.ToLowerInvariant()
$PullResult = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
$Summary = [ordered]@{{
  result = [string]$PullResult.result
  lane = '{request.profile.lane}'
  ssh_alias = '{request.profile.ssh_alias}'
  repo_head = [string]$RepoHead
  collect_script_sha256 = '{python_source_sha256}'
  remote_work_dir = $WorkDir
  remote_zip_path = $ZipPath
  remote_zip_scp_path = $ZipPath.Replace('\\', '/')
  remote_zip_sha256 = $ZipHash
  expected_server = '{request.profile.expected_server}'
  expected_company_contains = '{request.profile.expected_company_contains}'
  failed_item_count = [int]$PullResult.failed_item_count
  item_count = [int]$PullResult.item_count
}}
Write-Output ('{REMOTE_MARKER}' + ($Summary | ConvertTo-Json -Compress -Depth 8))
"""


def _remote_collect_python_source() -> str:
    return r'''#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time


class StrictMT5Proxy:
    def __init__(self, module):
        self._module = module

    def __getattr__(self, name):
        return getattr(self._module, name)

    def symbol_select(self, symbol, selected):
        raise RuntimeError(f"symbol {symbol} is not visible and symbol_select is disabled")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect LPFS lane candles without symbol_select.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frame-worker", action="store_true")
    parser.add_argument("--symbol")
    parser.add_argument("--timeframe")
    args = parser.parse_args()

    repo = Path(args.repo)
    sys.path.insert(0, str(repo / "shared" / "market_data_lab" / "src"))

    if args.frame_worker:
        return run_frame_worker(args)
    return run_parent(args)


def run_parent(args) -> int:
    from market_data_lab import (
        DatasetConfig,
        normalize_timeframe,
        resolve_date_window,
    )

    payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config_kwargs = {
        "dataset_name": str(payload["dataset_name"]),
        "data_root": str(payload["data_root"]),
        "symbols": tuple(str(symbol).upper() for symbol in payload["symbols"]),
        "timeframes": tuple(str(timeframe).upper() for timeframe in payload["timeframes"]),
        "history_years": payload.get("history_years"),
        "date_start_utc": payload.get("date_start_utc"),
        "date_end_utc": payload.get("date_end_utc"),
        "source": "mt5",
    }
    if "allow_symbol_select" in getattr(DatasetConfig, "__dataclass_fields__", {}):
        config_kwargs["allow_symbol_select"] = False
    config = DatasetConfig(**config_kwargs)
    start, end = resolve_date_window(config)
    data_root = Path(config.data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    item_root = data_root / "_pull_items"
    item_root.mkdir(parents=True, exist_ok=True)
    items = []
    failures = []
    frame_timeout = int(payload.get("frame_timeout_seconds") or 180)
    for symbol in config.symbols:
        for timeframe in config.timeframes:
            label = normalize_timeframe(timeframe)
            item_path = item_root / f"{symbol}_{label}.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--repo",
                str(args.repo),
                "--config",
                str(args.config),
                "--output",
                str(item_path),
                "--frame-worker",
                "--symbol",
                str(symbol).upper(),
                "--timeframe",
                label,
            ]
            started = time.perf_counter()
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=frame_timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                item = {
                    "symbol": str(symbol).upper(),
                    "timeframe": label,
                    "status": "failed",
                    "error_type": "TimeoutExpired",
                    "error": f"frame collection timed out after {frame_timeout}s",
                    "duration_seconds": round(time.perf_counter() - started, 3),
                    "stdout_tail": _tail_text(exc.stdout),
                    "stderr_tail": _tail_text(exc.stderr),
                }
            else:
                if completed.returncode == 0 and item_path.is_file():
                    item = json.loads(item_path.read_text(encoding="utf-8"))
                else:
                    item = {
                        "symbol": str(symbol).upper(),
                        "timeframe": label,
                        "status": "failed",
                        "error_type": "FrameWorkerFailed",
                        "error": f"frame worker exited {completed.returncode}",
                        "duration_seconds": round(time.perf_counter() - started, 3),
                        "stdout_tail": _tail_text(completed.stdout),
                        "stderr_tail": _tail_text(completed.stderr),
                    }
            if item.get("status") != "ok":
                failures.append(f"{symbol}:{label}: {item.get('error_type')}: {item.get('error')}")
            items.append(item)
    Path(args.output).write_text(
        json.dumps(
            {
                "result": "PASS" if not failures else "STOPPED",
                "allow_symbol_select": False,
                "storage_format": "csv",
                "pull_granularity": "per_frame_worker",
                "frame_timeout_seconds": frame_timeout,
                "item_count": len(items),
                "failed_item_count": len(failures),
                "failures": failures,
                "items": items,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def run_frame_worker(args) -> int:
    import pandas as pd
    import MetaTrader5 as mt5_module  # type: ignore
    from market_data_lab import (
        DatasetConfig,
        build_dataset_manifest,
        get_timeframe_spec,
        mt5_timeframe_value,
        normalize_rates_frame,
        normalize_timeframe,
        resolve_date_window,
        validate_rates_frame,
        write_dataset_manifest,
        write_rates_csv,
    )
    from market_data_lab.mt5 import account_metadata, ensure_symbol, pull_symbol_rates, symbol_metadata, terminal_metadata

    if not args.symbol or not args.timeframe:
        raise RuntimeError("--symbol and --timeframe are required for --frame-worker")
    payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config_kwargs = {
        "dataset_name": str(payload["dataset_name"]),
        "data_root": str(payload["data_root"]),
        "symbols": tuple(str(symbol).upper() for symbol in payload["symbols"]),
        "timeframes": tuple(str(timeframe).upper() for timeframe in payload["timeframes"]),
        "history_years": payload.get("history_years"),
        "date_start_utc": payload.get("date_start_utc"),
        "date_end_utc": payload.get("date_end_utc"),
        "source": "mt5",
    }
    if "allow_symbol_select" in getattr(DatasetConfig, "__dataclass_fields__", {}):
        config_kwargs["allow_symbol_select"] = False
    config = DatasetConfig(**config_kwargs)
    symbol = str(args.symbol).upper()
    label = normalize_timeframe(args.timeframe)
    if symbol not in config.symbols or label not in tuple(normalize_timeframe(tf) for tf in config.timeframes):
        raise RuntimeError(f"worker frame {symbol}:{label} is not in request config")
    strict_mt5 = StrictMT5Proxy(mt5_module)
    started = time.perf_counter()
    if not strict_mt5.initialize():
        raise RuntimeError(f"MetaTrader5 initialize failed: {strict_mt5.last_error()}")
    start, end = resolve_date_window(config)
    try:
        try:
            info = ensure_symbol(strict_mt5, symbol, allow_symbol_select=False)
        except TypeError:
            info = ensure_symbol(strict_mt5, symbol)
        account = account_metadata(strict_mt5.account_info())
        terminal = terminal_metadata(strict_mt5.terminal_info())
        pull_method = "copy_rates_range"
        bar_count_requested = None
        if config.date_start_utc is None and config.date_end_utc is None:
            pull_method = "copy_rates_from_pos"
            expected_delta = get_timeframe_spec(label).expected_delta
            window_seconds = max((end - start) / pd.Timedelta(seconds=1), 1.0)
            delta_seconds = max(expected_delta / pd.Timedelta(seconds=1), 1.0)
            bar_count_requested = max(int(math.ceil(window_seconds / delta_seconds)) + 20, 10)
            raw = strict_mt5.copy_rates_from_pos(
                symbol,
                mt5_timeframe_value(strict_mt5, label),
                0,
                int(bar_count_requested),
            )
            if raw is None:
                raise RuntimeError(f"copy_rates_from_pos failed for {symbol} {label}: {strict_mt5.last_error()}")
            frame = normalize_rates_frame(pd.DataFrame(raw), symbol=symbol, timeframe=label)
            timestamps = pd.to_datetime(frame["time_utc"], utc=True)
            frame = frame.loc[(timestamps >= start) & (timestamps <= end)].reset_index(drop=True)
            validate_rates_frame(frame, symbol=symbol, timeframe=label)
        else:
            frame = pull_symbol_rates(
                strict_mt5,
                symbol=symbol,
                timeframe=label,
                start=start.to_pydatetime(),
                end=end.to_pydatetime(),
            )
        data_path = write_rates_csv(config.data_root, frame, symbol=symbol, timeframe=label)
        manifest = build_dataset_manifest(
            frame,
            symbol=symbol,
            timeframe=label,
            source="mt5",
            data_path=data_path,
            requested_start_utc=start,
            requested_end_utc=end,
            symbol_metadata=symbol_metadata(info, symbol),
            account_metadata=account,
            terminal_metadata=terminal,
        )
        manifest["pull_method"] = pull_method
        if bar_count_requested is not None:
            manifest["bar_count_requested"] = int(bar_count_requested)
        manifest_path = write_dataset_manifest(config.data_root, manifest)
        item = {
            "symbol": symbol,
            "timeframe": label,
            "status": "ok",
            "rows": int(len(frame)),
            "data_path": str(data_path),
            "manifest_path": str(manifest_path),
            "coverage_start_utc": manifest["coverage_start_utc"],
            "coverage_end_utc": manifest["coverage_end_utc"],
            "pull_method": pull_method,
            "bar_count_requested": bar_count_requested,
            "duration_seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        strict_mt5.shutdown()
    Path(args.output).write_text(
        json.dumps(item, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _tail_text(value, limit=4000):
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[-limit:]


if __name__ == "__main__":
    raise SystemExit(main())
'''


def validate_lane_candle_root(candle_root: Path, *, request: LaneRequest) -> dict[str, Any]:
    failures: list[str] = []
    manifests = sorted(candle_root.glob("*/*/manifest.json"))
    expected_pairs = {(symbol.upper(), normalize_timeframe(timeframe)) for symbol in request.symbols for timeframe in request.timeframes}
    seen_pairs: set[tuple[str, str]] = set()
    total_rows = 0
    manifest_summaries: list[dict[str, Any]] = []
    if not candle_root.is_dir():
        failures.append(f"missing candle root: {candle_root}")
    if not manifests:
        failures.append("no candle manifest files found")
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"manifest unreadable: {manifest_path}: {exc}")
            continue
        if not isinstance(manifest, dict):
            failures.append(f"manifest is not an object: {manifest_path}")
            continue
        try:
            symbol = str(manifest.get("symbol") or "").upper()
            timeframe = normalize_timeframe(str(manifest.get("timeframe") or ""))
        except Exception as exc:
            failures.append(f"manifest has invalid symbol/timeframe: {manifest_path}: {exc}")
            continue
        pair = (symbol, timeframe)
        seen_pairs.add(pair)
        account = manifest.get("account_metadata") or {}
        terminal = manifest.get("terminal_metadata") or {}
        server = str(account.get("server") or "")
        company_text = " ".join(str(value or "") for value in (account.get("company"), terminal.get("company"), terminal.get("name")))
        rows = _int_value(manifest.get("rows"))
        total_rows += max(rows, 0)
        data_path = _local_data_path_for_manifest(candle_root, manifest_path, manifest)
        if manifest.get("source") != "mt5":
            failures.append(f"{manifest_path} source is not mt5")
        if server != request.profile.expected_server:
            failures.append(f"{manifest_path} server {server!r} does not match expected {request.profile.expected_server!r}")
        if request.profile.expected_company_contains not in company_text:
            failures.append(f"{manifest_path} company metadata does not contain {request.profile.expected_company_contains!r}")
        if rows <= 0:
            failures.append(f"{manifest_path} has no rows")
        if not data_path.is_file():
            failures.append(f"{manifest_path} data file missing: {data_path}")
        manifest_summaries.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": rows,
                "coverage_start_utc": manifest.get("coverage_start_utc"),
                "coverage_end_utc": manifest.get("coverage_end_utc"),
                "server": server,
                "company_text": company_text,
                "manifest_path": str(manifest_path),
                "data_path": str(data_path),
            }
        )
    missing = sorted(expected_pairs - seen_pairs)
    extras = sorted(seen_pairs - expected_pairs)
    if missing:
        failures.append("missing symbol/timeframe manifests: " + ",".join(f"{symbol}:{timeframe}" for symbol, timeframe in missing[:20]))
    if extras:
        failures.append("unexpected symbol/timeframe manifests: " + ",".join(f"{symbol}:{timeframe}" for symbol, timeframe in extras[:20]))
    return {
        "schema_version": COLLECTOR_SCHEMA_VERSION,
        "result": "PASS" if not failures else "STOPPED",
        "failures": failures,
        "lane": request.profile.lane,
        "candle_root": str(candle_root),
        "safe_for_strategy_analysis": not failures,
        "provenance": "vps_lane_broker_feed",
        "expected_server": request.profile.expected_server,
        "expected_company_contains": request.profile.expected_company_contains,
        "manifest_count": len(manifests),
        "expected_manifest_count": len(expected_pairs),
        "row_count": total_rows,
        "manifests": manifest_summaries,
    }


def _request_payload(request: LaneRequest) -> dict[str, Any]:
    return {
        "schema_version": COLLECTOR_SCHEMA_VERSION,
        "lane": request.profile.lane,
        "ssh_alias": request.profile.ssh_alias,
        "repo_path": request.profile.repo_path,
        "python_path": request.profile.python_path,
        "symbols": list(request.symbols),
        "timeframes": list(request.timeframes),
        "history_years": request.history_years,
        "date_start_utc": request.date_start_utc,
        "date_end_utc": request.date_end_utc,
        "provenance": "vps_lane_broker_feed",
        "expected_server": request.profile.expected_server,
        "expected_company_contains": request.profile.expected_company_contains,
        "allow_symbol_select": False,
        "non_actions": [
            "no_live_runner_change",
            "no_vps_task_change",
            "no_kill_switch_change",
            "no_config_change",
            "no_runtime_state_or_journal_mutation",
            "no_broker_order_or_position_mutation",
            "no_symbol_visibility_mutation",
            "no_strategy_logic_change",
        ],
    }


def _write_command_result(lane_dir: Path, stem: str, result: CommandResult) -> None:
    (lane_dir / f"{stem}.command.txt").write_text(subprocess.list2cmdline(list(result.args)) + "\n", encoding="utf-8")
    (lane_dir / f"{stem}.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (lane_dir / f"{stem}.stderr.txt").write_text(result.stderr, encoding="utf-8")
    (lane_dir / f"{stem}.exit_code.txt").write_text(str(result.returncode) + "\n", encoding="ascii")


def _write_validation(
    lane_dir: Path,
    result: str,
    failures: Sequence[str],
    *,
    remote_summary: dict[str, Any] | None,
    validation: dict[str, Any] | None = None,
) -> None:
    payload = {
        "schema_version": COLLECTOR_SCHEMA_VERSION,
        "result": result,
        "failures": list(failures),
        "remote_summary": remote_summary,
        "validation": validation,
    }
    (lane_dir / "validation_summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_packet_manifest(
    packet_dir: Path,
    *,
    packet_result: str,
    collection_time: datetime,
    dry_run: bool,
    lane_results: Sequence[dict[str, Any]],
) -> None:
    files = []
    for path in sorted(packet_dir.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", "manifest.sha256.txt"}:
            continue
        relative = path.relative_to(packet_dir).as_posix()
        files.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    manifest = {
        "schema_version": COLLECTOR_SCHEMA_VERSION,
        "result": packet_result,
        "dry_run": dry_run,
        "generated_at_utc": collection_time.isoformat(),
        "purpose": "lpfs_lane_authoritative_candle_snapshot",
        "provenance": "vps_lane_broker_feed",
        "collector_repo_head": _git_output("rev-parse", "HEAD") or "unknown",
        "collector_tracked_dirty": bool(_git_output("status", "--short", "--untracked-files=no")),
        "collector_script_path": str(Path(__file__).resolve()),
        "collector_script_sha256": _sha256_file(Path(__file__).resolve()),
        "lane_results": list(lane_results),
        "file_count": len(files),
        "files": files,
        "non_actions": [
            "no_live_runner_change",
            "no_vps_task_change",
            "no_kill_switch_change",
            "no_config_change",
            "no_runtime_state_or_journal_mutation",
            "no_broker_order_or_position_mutation",
            "no_symbol_visibility_mutation",
            "no_strategy_logic_change",
        ],
    }
    manifest_path = packet_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (packet_dir / "manifest.sha256.txt").write_text(_sha256_file(manifest_path) + "\n", encoding="ascii")


def _rewrite_packet_local_paths(
    *,
    packet_dir: Path,
    old_root: Path,
    new_root: Path,
    lane_results: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    old_text = str(old_root)
    new_text = str(new_root)
    rewritten_results = [_replace_string_prefixes(dict(result), old_text=old_text, new_text=new_text) for result in lane_results]
    for validation_path in packet_dir.glob("*/validation_summary.json"):
        try:
            payload = json.loads(validation_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rewritten = _replace_string_prefixes(payload, old_text=old_text, new_text=new_text)
        validation_path.write_text(json.dumps(rewritten, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return rewritten_results


def _replace_string_prefixes(value: Any, *, old_text: str, new_text: str) -> Any:
    if isinstance(value, str):
        return value.replace(old_text, new_text)
    if isinstance(value, list):
        return [_replace_string_prefixes(item, old_text=old_text, new_text=new_text) for item in value]
    if isinstance(value, dict):
        return {key: _replace_string_prefixes(item, old_text=old_text, new_text=new_text) for key, item in value.items()}
    return value


def _run_ssh_powershell(alias: str, script: str, *, timeout: int) -> CommandResult:
    script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()
    remote_script = f"C:/Windows/Temp/lpfs_lane_candle_snapshots_remote_{script_hash[:16]}_{os.getpid()}.ps1"
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        local_script = Path(handle.name)
    upload_args = (
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        str(local_script),
        f"{alias}:{remote_script}",
    )
    run_args = (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        alias,
        f"powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File {remote_script}",
    )
    args = upload_args + ("&&",) + run_args
    try:
        upload = subprocess.run(list(upload_args), capture_output=True, text=True, timeout=min(timeout, 300), check=False)
        if upload.returncode != 0:
            return CommandResult(
                args=args,
                stdout=upload.stdout,
                stderr=f"remote script upload failed with exit code {upload.returncode}\n{upload.stderr}",
                returncode=int(upload.returncode),
            )
        completed = subprocess.run(list(run_args), capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(args=args, stdout=exc.stdout or "", stderr=f"timeout after {timeout}s", returncode=124)
    finally:
        try:
            local_script.unlink()
        except OSError:
            pass
    return CommandResult(args=args, stdout=completed.stdout, stderr=completed.stderr, returncode=int(completed.returncode))


def _run_scp_fetch(alias: str, remote_path: str, local_zip: Path, *, timeout: int) -> CommandResult:
    args = (
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        f"{alias}:{remote_path}",
        str(local_zip),
    )
    try:
        completed = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(args=args, stdout=exc.stdout or "", stderr=f"timeout after {timeout}s", returncode=124)
    return CommandResult(args=args, stdout=completed.stdout, stderr=completed.stderr, returncode=int(completed.returncode))


def _parse_remote_summary(stdout: str) -> dict[str, Any]:
    payloads = [line.removeprefix(REMOTE_MARKER) for line in stdout.splitlines() if line.startswith(REMOTE_MARKER)]
    if len(payloads) != 1:
        raise CandleSnapshotError(f"expected exactly one {REMOTE_MARKER} marker, found {len(payloads)}")
    try:
        decoded = json.loads(payloads[0])
    except json.JSONDecodeError as exc:
        raise CandleSnapshotError("remote summary marker is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise CandleSnapshotError("remote summary marker must contain a JSON object")
    return dict(decoded)


def _safe_extract_zip(archive: zipfile.ZipFile, target: Path) -> None:
    root = target.resolve()
    for member in archive.infolist():
        destination = (target / member.filename).resolve()
        if root != destination and root not in destination.parents:
            raise CandleSnapshotError(f"zip member escapes target directory: {member.filename}")
    archive.extractall(target)


def _local_data_path_for_manifest(candle_root: Path, manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw = str(manifest.get("path") or "")
    suffix = Path(raw).suffix.lower()
    symbol = str(manifest.get("symbol") or "").upper()
    timeframe = normalize_timeframe(str(manifest.get("timeframe") or ""))
    if suffix == ".csv":
        return manifest_path.parent / f"{symbol}_{timeframe}.csv"
    return manifest_path.parent / f"{symbol}_{timeframe}.parquet"


def _parse_csv(value: str) -> tuple[str, ...]:
    items = tuple(item.strip().upper() for item in value.split(",") if item.strip())
    if not items:
        raise CandleSnapshotError("comma-separated value must not be empty")
    return items


def _lane_key(value: str) -> str:
    key = str(value).strip().upper()
    if not LANE_RE.fullmatch(key):
        raise CandleSnapshotError(f"invalid lane label {value!r}")
    return key


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _windows_join(*parts: str) -> str:
    path = PureWindowsPath(parts[0])
    for part in parts[1:]:
        path /= part
    return str(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
