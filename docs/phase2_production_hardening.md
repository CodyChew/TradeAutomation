# LPFS Phase 2 Production Hardening Plan

Last updated: 2026-05-01.

This document captures the next operational phase for LP + Force Strike after
V15/V16/V17 research and the first real-account live-send tests. It is a
production-readiness plan, not a strategy-rule change.

## Current Stage

LPFS is in controlled live validation.

The current strategy remains:

- V13 mechanics with V15 risk buckets.
- LP3, `take_all`, H4/H8/H12/D1/W1.
- 0.5 signal-candle pullback entry.
- Force Strike structure stop.
- 1R target.
- Fixed 6-bar pullback wait.
- Live test scale: `live_send.risk_bucket_scale=0.05`.

Recent research did not justify changing live rules:

- V16 bid/ask realism did not materially weaken V15.
- V16 spread-buffer variants are promising but too invasive to adopt directly.
- V17 LP-FS proximity filters did not beat current V15; do not require FS
  structure touch.

The live executor is real-order capable only when ignored local config enables
`LIVE_SEND` with the real-money acknowledgement and account/server match.

## Current Operational Safeguards

Already implemented:

- MT5 account login/server validation before live cycles.
- Single-runner lock beside the live state file.
- Immediate state persistence after broker-affecting safety mutations.
- OneDrive-safe fallback when atomic state replacement is denied by Windows.
- Broker duplicate/adoption guard before `order_send`.
- MT5 reconciliation for pending orders, positions, historical orders, and
  deals.
- Stricter pending-to-position matching by broker comment or history linkage.
- Manual or unknown exits rendered as `TRADE CLOSED`, not forced stop losses.
- Telegram lifecycle cards for order placed, adopted, entered, closed,
  cancelled, waiting, skipped, rejected, runner started, and runner stopped.
- JSONL journal as durable audit record.

## Phase 2 Goal

Make live operation resilient to normal production failures:

- local terminal closes;
- Python runner crashes;
- Windows restarts;
- MT5 disconnects;
- Telegram delivery fails;
- live state or journal files are locked;
- operator needs to stop the system quickly.

The goal is not perfect unattended autonomy. The goal is a fail-closed,
observable process that can be restarted safely.

## Recommended Path

Use a Windows VPS plus Task Scheduler and a watchdog launcher.

This keeps the current Python and MT5 architecture intact. The MT5 Python API
connects to a local terminal, so a Windows environment with the terminal
installed is the cleanest production host. MetaTrader built-in virtual hosting
is aimed at platform EAs/signals and is not a good fit for this external
Python runner unless the system is rewritten as MQL5.

## Options And Tradeoffs

| Option | Strength | Weakness | Recommendation |
|---|---|---|---|
| Local PC manual terminal | Fastest for current testing | Stops on sleep, reboot, terminal close | Keep for low-risk observation only |
| Local PC Task Scheduler | Auto-start after login/startup | Still depends on local PC power/sleep/network | Useful rehearsal step |
| Windows VPS Task Scheduler | Always-on MT5 + Python with minimal changes | Monthly cost and server maintenance | Best Phase 2 target |
| Windows service wrapper | Better process management | MT5 GUI/Python can be awkward in service sessions | Consider later |
| MetaTrader built-in VPS | Broker-near EA/signals hosting | Not designed for this external Python process | Do not use for current architecture |
| MQL5 rewrite | Native MT5 deployment | Large rewrite and weaker Python research loop | Long-term only |

## Implementation Checklist

Phase 2 should be implemented in this order:

1. Add a production PowerShell launcher, for example
   `scripts/run_lpfs_live_forever.ps1`.
2. Add a kill switch checked before MT5 initialization and before live cycles,
   for example `data/live/KILL_SWITCH`.
3. Add a watchdog wrapper that restarts the runner after unexpected crashes but
   does not restart when the kill switch is active.
4. Redirect stdout/stderr to timestamped files under `data/live/logs`.
5. Move production runtime state away from OneDrive, for example
   `C:\TradeAutomationRuntime\data\live`, while keeping code in Git.
6. Add a heartbeat file updated each cycle with latest cycle time, process ID,
   MT5 account/server, and last cycle result.
7. Add Task Scheduler setup for startup or logon.
8. Rehearse local restart behavior with live-send disabled or tiny risk:
   normal start, Ctrl+C, crash restart, reboot, kill-switch stop, stale lock,
   MT5 closed, and Telegram failure.
9. Move the same setup to a Windows VPS after local rehearsal passes.

## Acceptance Criteria

Phase 2 is ready when these are verified:

- The runner starts from Task Scheduler without manual terminal setup.
- Only one runner can run against the configured state path.
- The kill switch stops new cycles before any order send.
- A crash produces a Telegram/process alert and a log file.
- A watchdog restart does not duplicate orders.
- MT5 restart or disconnect fails closed or recovers without duplicate sends.
- State, journal, logs, and heartbeat survive reboot.
- Telegram is helpful but not required for state correctness.
- A restart reconciles existing MT5 pending orders and positions before
  scanning for new signals.

## Non-Goals For Phase 2

Do not change these as part of production hardening:

- signal rules;
- risk buckets;
- spread gate threshold;
- stop/target geometry;
- pending order expiration model;
- V15 baseline recommendation.

Research changes should remain separate V18+ studies.

## Immediate Next Work Item

Build and test the launcher/watchdog/kill-switch layer locally while keeping
the current low-risk live runner available for manual operation.

Do not migrate to VPS or increase risk until the local production wrapper has
passed the acceptance criteria above.
