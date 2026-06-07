# TradeAutomation System Troubleshooting Map

Last updated: 2026-06-07 after LPFS minimum-safety resumption completed for
FTMO first and IC second.

This map is for future developers and AI agents who need to understand or
troubleshoot the existing TradeAutomation systems without accidentally changing
live trading state.

## C-01 Containment

Read `lpfs_c01_live_safety_release.md` first. LPFS minimum-safety resumption
completed on 2026-06-07 ICT. Both VPS lanes were resumed from runtime code SHA
`e10f3043ca4d33654a94f567536586f6725b4604` and both live data-collection
tasks are running: FTMO `LPFS_Live` and IC `LPFS_IC_Live`. A later docs-only
closeout commit may advance `main` without changing live runner behavior.
FTMO was resumed first and proved clean before IC was touched. Skip canaries
by default. Do not run reconcile-only mode, a live canary, or manual broker
order/position changes unless a separate operator-approved step authorizes it.

Authoritative final packets:

- FTMO:
  `C:\TradeAutomationEvidence\lpfs_c01_stage5\ftmo_resume_minimal_20260607_102235`,
  manifest SHA-256
  `094bb379265ebab4fa083ed8532799018c5277227c72134205c4c3d690618c2c`
- IC:
  `C:\TradeAutomationEvidence\lpfs_c01_stage5\ic_resume_minimal_20260607_103929`,
  manifest SHA-256
  `66d2c0af3e42647ff09a457b5cb9cc7383765dd3b053c220ac6e6ed9ea09669e`
- Combined final validation:
  `C:\TradeAutomationEvidence\lpfs_c01_stage5\resume_final_20260607_104948`,
  manifest SHA-256
  `0b4e85e7948111ad16baebb9106065af01be3249015c0f19a41116ff516226f99`

Final proof showed one logical runner path per lane, fresh running heartbeats,
MT5 identity and reads `OK`, pending strategy orders `0`, unchanged active
positions, no order-like journal rows, and no unexplained broker exposure.

FTMO Stage 5 Gate 3 is accepted as `STOPPED`; do not retry it. Read
`lpfs_stage5_gate3_retry_plan.md`. The authoritative ignored packet is
`C:\TradeAutomationEvidence\lpfs_c01_stage5\ftmo_gate3_20260604_100840`,
manifest SHA-256
`85df11692de17e3d35b986dafee1ce729a15b822b8ce0f3c3ccea367eb27318e`.
Fallback containment refreshed the FTMO `KILL_SWITCH` content and invoked
`Disable-ScheduledTask` while the task was already disabled. No enable/start,
kill-switch clear, IC access, reconciliation, canary, pull, or broker mutation
occurred.

FTMO-only Stage 1 retry passed point-in-time from exact SHA
`3dd1895ca5300d448e4d100095b294e78679a6b9`. FTMO state is schema v2 with
one deterministic `clean_noop_migration` receipt. FTMO remains contained; IC
was not touched. The authoritative archived packet is
`C:\TradeAutomationEvidence\lpfs_c01_deploy\20260602_160716\ftmo_stage1_retry`
with manifest SHA-256
`f8155e042fb183070440f22516c05de8075203964217252edea19f05100e2341`.
Do not rerun either lane reconciliation or perform any resumption action
without separate approval.

`Get-LpfsLiveStatus.ps1` must render normal-cycle, reconciliation-only, and
error heartbeats. Reconciliation and error heartbeats may omit
`completed_cycles` and `requested_cycles`; treat those counters as optional,
not as evidence that the heartbeat is malformed.

For broker status, `None` from MT5 `orders_get`, `positions_get`,
`history_orders_get`, or `history_deals_get` is `ERROR/UNKNOWN`, never zero.
Use strict read-only evidence exports before drawing conclusions.

For future Stage 5 pre-resumption packets, redirect stdout/stderr to separate
packet files and record the explicit remote process exit code. Safe
PowerShell CLIXML host/progress/information records on bounded-status stderr
are transport noise, not broker evidence. Malformed CLIXML, error records,
exception text, native-command errors, timeouts, nonzero exits, missing
stdout, or missing hash markers remain fail-closed.

Do not use ad hoc verification commands before a Stage 5 mutation. Capture
`<step>.command.txt`, `<step>.stdout.txt`, `<step>.stderr.txt`, and
`<step>.exit_code.txt`, then run
`scripts/verify_lpfs_structured_command.py`. It fails closed on missing,
malformed, nonzero, unsafe-stderr, or ambiguous-output bundles.

## First Boundary Check

Identify the target before running commands.

- Local development repo:
  `C:\Users\Cody\OneDrive\Desktop\TradeAutomation`
- FTMO production lane:
  `lpfs-vps`, repo `C:\TradeAutomation`, runtime
  `C:\TradeAutomationRuntime`, scheduled task `LPFS_Live`
- IC production lane:
  `lpfs-ic-vps`, repo `C:\TradeAutomation`, runtime
  `C:\TradeAutomationRuntimeIC`, scheduled task `LPFS_IC_Live`

Local file edits do not affect production until they are committed, pushed,
pulled on a VPS checkout, and any required runner restart is explicitly done.
VPS runtime files, MT5 broker state, journals, state files, and Task Scheduler
tasks are production-adjacent.

## Live Runner Map

LP + Force Strike is the only strategy with live Python runners right now.

- Live executor entry point:
  `scripts/run_lp_force_strike_live_executor.py`
- Watchdog launcher:
  `scripts/run_lpfs_live_forever.ps1`
- Status snapshot:
  `scripts/Get-LpfsLiveStatus.ps1`
- Dual-VPS status snapshot:
  `scripts/Get-LpfsDualVpsStatus.ps1`
- Kill switch helper:
  `scripts/Set-LpfsKillSwitch.ps1`
- Startup alert helper:
  `scripts/send_lpfs_vps_startup_alert.py`
- Startup alert task installer:
  `scripts/Install-LpfsStartupAlertTask.ps1`
- Core live implementation:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_executor.py`
- Dry-run implementation:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/dry_run_executor.py`
- Execution contract:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/execution_contract.py`
- Notification contract:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/notifications.py`
- Diagnostic logging contract:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/diagnostic_logging.py`
- Diagnostic logging docs:
  `docs/lpfs_diagnostic_logging.md`

Ignored local configs such as `config.local.json`,
`config.lpfs_icmarkets_raw_spread.local.json`, and
`config.lpfs_icmarkets_raw_spread.live_smoke.local.json` are real-account
capable. Do not run live-send locally while production VPS runners are active
unless the user has approved a separate smoke-test plan with its own account,
runtime root, state, journal, and reconciliation path.

## Read-Only Live Audit Commands

Run from the local repo when checking existing production state:

```powershell
ssh lpfs-vps hostname
ssh lpfs-vps whoami
ssh lpfs-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
ssh lpfs-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 40 -LogLines 80"
ssh lpfs-ic-vps hostname
ssh lpfs-ic-vps whoami
ssh lpfs-ic-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
ssh lpfs-ic-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntimeIC -StateFileName lpfs_ic_live_state.json -JournalFileName lpfs_ic_live_journal.jsonl -HeartbeatFileName lpfs_ic_live_heartbeat.json -LogFilter 'lpfs_ic_live_*.log' -JournalLines 40 -LogLines 80"
.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 20 -LogLines 40
```

These commands should not edit MT5 orders, positions, journals, state, runtime
files, or scheduled tasks.

The LPFS status packet includes VPS disk free-space fields. Treat
`disk_status=warn` as a cleanup or sizing-review trigger, and
`disk_status=action_required` as a blocker for heavy report scans, deploys, or
large data collection until free space is addressed. Current policy is warn
below `15 GB` or `25%` free, and action below `10 GB` or `15%` free.

## Live Journal Read Safety

Production LPFS journals and state files are actively written by the live
runners. Reads can still become operationally unsafe if they open the files
without sharing modes that permit the writer to continue.

Known unsafe patterns against `C:\TradeAutomationRuntime*\data\live\*.jsonl`
or live state files:

- `[System.IO.File]::OpenText($path)`;
- `Get-Content -Raw` on large live files;
- unbounded `Select-String` scans of full live JSONL journals;
- any custom script that reads the whole live journal and does not explicitly
  open with `FileShare.ReadWrite`.

Safe patterns:

- prefer `scripts/Get-LpfsDualVpsStatus.ps1` for current status;
- prefer `scripts/summarize_lpfs_live_gate_attribution.py --tail-lines 200000`
  for remote gate-attribution reads; it uses `FileShare.ReadWrite`, but the
  tail limit bounds returned rows rather than remote source work. It still
  streams the full journal before returning its tail. Byte-bounded
  gate-attribution optimization is deferred;
- collect routine compact-summary evidence with
  `scripts/collect_lpfs_live_journal_snapshots.py`. It captures a fixed
  point-in-time source range through `FileShare.ReadWrite`, defaults to an
  exact `64 MiB` suffix, excludes high-volume `market_snapshot` rows by
  default, validates complete JSONL rows locally, and publishes ignored local
  snapshots with a sibling `manifest.json`;
- run `scripts/summarize_lpfs_live_trades.py` only with
  `--journal-snapshot` pointing to a collector-produced local snapshot. The
  compact reader rejects missing or mismatched manifests and rejects
  `--days` / `--weeks` requests when a truncated snapshot cannot prove the
  requested historical coverage;
- use `--max-source-bytes` for an explicitly larger bounded snapshot. Use
  collector `--allow-full-scan` only after explicit approval, and add
  `--include-market-snapshots` only for forensic evidence that needs those
  high-volume rows;
- prefer bounded tails or already-generated report packets for historical
  evidence;
- when a full scan is explicitly approved, open with
  `[System.IO.FileStream]::new($path, [System.IO.FileMode]::Open,
  [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)` and stream
  line by line;
- immediately run `.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 5
  -LogLines 5` afterward and record the packet path.

`scripts/build_lpfs_trade_diagnostics.py --journal` remains an offline,
operator-supplied evidence tool for archived, historical, synthetic, or safely
collected local copies. It intentionally does not require a collector manifest.
Never pass it an active VPS runtime path.

The heavier weekly performance collector remains operationally separate and
unchanged. Its calculations and explicit shared-read behavior are not replaced
by the compact-summary snapshot workflow.

Incident reference: on 2026-05-23, an LPFS weekly-report collection attempt
used an unsafe live-file open while scanning production journals and both live
tasks were later found stopped. The runners were restarted and verified healthy
in `reports/live_ops/lpfs_dual_vps_status_20260523_140154.md`.

## Common Troubleshooting Paths

Runner appears duplicated:

- On Windows, one healthy logical runner can appear as a venv launcher process
  plus its child Python interpreter.
- Confirm `parent_pid`, executable paths, heartbeat freshness, log freshness,
  runtime root, and single-runner lock before calling it a duplicate.
- Confirm the dual-VPS status packet reports
  `task_multiple_instances=IgnoreNew`. The live task should reject overlapping
  Task Scheduler launches, the watchdog should stop on child exit code `2`, and
  the Python runner lock remains the final pre-MT5 safety boundary.

Heartbeat is stale or missing:

- Check Task Scheduler state for `LPFS_Live` or `LPFS_IC_Live`.
- Check the relevant `KILL_SWITCH` file first.
- Read the latest runtime log through `Get-LpfsLiveStatus.ps1`.
- Confirm MT5 is logged in, connected, and trade-allowed.
- Verify broker orders and positions against runtime state before restarting.

A trade looks missed, delayed, or different between brokers:

- Treat TradingView and Telegram as alerts, not proof.
- Verify MT5 order history, deal history, current orders, positions, and
  executable Bid/Ask behavior where available.
- Compare the relevant JSONL journal rows, spread snapshots, rejection fields,
  and both VPS status packets.
- Do not patch strategy or execution behavior from a single chart visual,
  rollover event, one broker-feed divergence, or Bid-only candle touch.

Dashboard appears stale:

- Static HTML under `docs/` is generated output.
- Edit the relevant builder script under `scripts/`, then regenerate the HTML.
- `docs/live_weekly_performance.html` is a read-only live monitor page; use
  timestamped packets under `reports/live_ops/lpfs_weekly_performance/` for
  historical evidence.
- Do not regenerate live weekly performance against production journals without
  treating it as a live-adjacent operation and verifying both runners afterward.

LPFS underperformance analysis:

- Start with `docs/live_weekly_performance.html` and the latest packet under
  `reports/live_ops/lpfs_weekly_performance/`.
- Use `docs/lpfs_diagnostic_logging.md` before changing journal/report fields.
- Build per-trade diagnostic reports with
  `scripts/build_lpfs_trade_diagnostics.py` from safely collected local journal
  copies.
- Do not change live heuristics until enriched diagnostics are compared against
  the 10-year backtest and a separate strategy-change plan is approved.

Backtest data looks wrong:

```powershell
.\venv\Scripts\python.exe scripts\verify_dataset_fingerprint.py
.\venv\Scripts\python.exe scripts\report_dataset_coverage.py --config configs\datasets\forex_major_crosses_10y.json --output reports\datasets\forex_major_crosses_10y_coverage.json
.\venv\Scripts\python.exe scripts\report_data_quality.py --config configs\datasets\forex_major_crosses_10y.json --output-dir reports\datasets\data_quality
```

Known dataset caveat: `GBPAUD`, `GBPNZD`, `NZDCAD`, and `NZDCHF` have long
historical gaps in the current FTMO FOREX dataset. Treat results for those
symbols separately when needed.

Tests or core behavior changed:

```powershell
.\venv\Scripts\python.exe scripts\run_core_coverage.py
```

The core gate is expected to maintain 100% line and branch coverage for scoped
Python packages. If a runner grows reusable behavior, move that behavior into a
package under `src/` and cover it there.

## Do Not Do Without Explicit Approval

- Do not edit VPS runtime state, JSONL journals, MT5 order history, MT5 deal
  history, broker orders, or broker positions.
- Do not clear a production kill switch or restart a production runner without
  an operator plan.
- Do not run the native MQL5 EA on FTMO or IC live charts. The EA lane is
  Strategy Tester-only until separately approved.
- Do not run local LPFS live-send while VPS production runners are active.
- Do not run unbounded live journal scans or custom remote journal readers
  against production files unless they use `FileShare.ReadWrite` and the user
  has approved the operational risk.
- Do not turn the upcoming Majority Flush research lane into a live runner by
  copying LPFS execution code. It must pass separate research, dashboard,
  dry-run, and deployment gates first.
