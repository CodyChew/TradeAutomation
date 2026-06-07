# LPFS C-01 Live-Safety Release

Last updated: 2026-06-07 ICT after LPFS minimum-safety resumption completed
for FTMO first and IC second.

## Current Objective

Repair C-01 before resuming LPFS production: MT5 epoch values were historically
relocalized through `Europe/Helsinki` even though MT5 Python epochs are UTC.
The release must preserve trustworthy diagnostic evidence for later
evidence-gated strategy research without changing LPFS entries, exits, risk
settings, timeframe mix, or strategy heuristics.

This is a live-safety release, not a strategy-improvement release.

## Stage 5 Minimum-Safety Resumption Completed

LPFS live data collection resumed on 2026-06-07 ICT. FTMO was resumed first
and proved clean before IC was touched. Both lanes were resumed from runtime
code SHA:

```text
e10f3043ca4d33654a94f567536586f6725b4604
```

Final state:

| Lane | Task | Kill switch | Runner path | LPFS broker pending | Active positions |
|---|---|---|---|---:|---:|
| FTMO | `LPFS_Live` running/enabled | clear | one logical path | 0 | 3 unchanged |
| IC | `LPFS_IC_Live` running/enabled | clear | one logical path | 0 | 2 unchanged |

FTMO final packet:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\ftmo_resume_minimal_20260607_102235
```

Use the packet's `manifest.sha256.txt` sidecar for the current FTMO
`manifest.json` SHA-256 because additional read-only proof artifacts may be
added during closeout.

IC final packet:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\ic_resume_minimal_20260607_103929
```

Use the packet's `manifest.sha256.txt` sidecar for the current IC
`manifest.json` SHA-256 because additional read-only proof artifacts may be
added during closeout.

Combined final validation packet:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\resume_final_20260607_104948
```

Use the packet's `manifest.sha256.txt` sidecar for the current combined
`manifest.json` SHA-256.

Final proof showed fresh running heartbeats, successful MT5
`account_info`, `terminal_info`, `orders_get`, and `positions_get`, pending
strategy orders `0`, unchanged active positions including SL/TP, no
order-like journal rows, and no unexplained broker exposure. No
reconciliation, canary, manual broker order/position modification, or
strategy/risk/sizing/SL/TP/broker-send change was performed.
A later docs-only closeout commit may advance `main`; it does not change live
runner behavior unless future runtime code changes are deliberately deployed
and the runners are restarted.

## Initial Contained Production State

Both VPS lanes were intentionally contained before implementation work. This
table is the approved Stage 0 baseline, not a fresh post-retry IC read:

| Lane | Task | Kill switch | Runner processes | LPFS broker pending | Active positions |
|---|---|---|---:|---:|---:|
| FTMO | `LPFS_Live` disabled | active | 0 | 0 | 3 |
| IC | `LPFS_IC_Live` disabled | active | 0 | 0 | 2 |

Both VPS machines remain powered on. Active positions are untouched and remain
supervised broker-side. Do not clear either kill switch, enable either task,
start a watchdog, restart a runner, modify broker orders, or rewrite runtime
state or journals until the reviewed release and deployment plan are approved.

Containment evidence:

- status packet:
  `reports/live_ops/lpfs_dual_vps_status_20260601_112826.md`
- FTMO strict broker export:
  `reports/live_ops/lpfs_c01_containment/20260601_112441/ftmo_mt5_evidence.json`
- IC strict broker export:
  `reports/live_ops/lpfs_c01_containment/20260601_112441/ic_mt5_evidence.json`

The evidence paths are ignored local artifacts. Runtime ignored configs were
updated in place to `live_send.market_recovery_mode="disabled"` while both
lanes were paused. Timestamped config backups were preserved on each VPS.

## Historical FTMO Stage 1 Stop And Forward-Fix Gate

An approved sequential deployment attempted FTMO-only Stage 1 on 2026-06-02
ICT and stopped before IC. FTMO pulled reviewed commit
`79a3b21548653c4729eda07dc5f6da066d8018be`, passed `100` VPS-focused tests,
passed strict read-only broker exports before and after `--reconcile-only`,
and preserved broker exposure unchanged: pending orders `0`, active positions
`3`, and no broker history delta. FTMO remains contained with `KILL_SWITCH`
active, `LPFS_Live` disabled, runner process count `0`, and recovery disabled.
IC was not touched after the stop condition.

Authoritative ignored local FTMO stop packet:

```text
reports/live_ops/lpfs_c01_deploy/20260602_003007/ftmo
```

Its `evidence_manifest.json` SHA-256 is:

```text
87192736fe10ed2179f1d74b7089b9d20adf4ba29d4ecfecddf82a6230d51c09
```

The stop exposed two forward-fix gaps:

- `Get-LpfsLiveStatus.ps1` assumed normal-cycle heartbeat counters and failed
  under strict mode when the reconciliation heartbeat omitted them.
- clean reconciliation with no stale local pending records returned before
  atomic v2 persistence, so schema-v1 state remained in place without a
  deterministic receipt or completion-row replay anchor.

The forward fix makes heartbeat rendering tolerant of absent optional counters
and commits one deterministic `clean_noop_migration` receipt through the same
atomic v2 path as pending cleanup. Replay remains idempotent and backfills
missing deterministic lifecycle rows without applying migration twice.

This historical stop gate was superseded by the reviewed contained retry
below. It remains recorded because it explains the forward fix.

## FTMO Stage 1 Retry Point-In-Time Pass

The approved FTMO-only contained retry completed on 2026-06-02 ICT from exact
reviewed SHA:

```text
3dd1895ca5300d448e4d100095b294e78679a6b9
```

FTMO passed `102` VPS-focused tests, bounded pre/post status, strict pre/post
MT5 exports, and exactly one `--reconcile-only` invocation. The post-reconcile
state has schema v2, minimum reader v2, the legacy-loader tripwire, one
deterministic `clean_noop_migration` receipt, a deterministic completion row,
a CLI completion row, and a reconciliation heartbeat.

Receipt operation ID:

```text
fa7afa51991ee1b1ca90cf5821f6a6a07bd131416798f396f50a62393360de42
```

Broker exposure remained unchanged: pending orders `0`, the same `3` active
positions, and identical historical order/deal ticket inventories. FTMO
remains contained with `KILL_SWITCH` active, `LPFS_Live` disabled, runner
count `0`, and recovery disabled. IC was not accessed.

The authoritative ignored packet was archived outside the disposable worktree:

```text
C:\TradeAutomationEvidence\lpfs_c01_deploy\20260602_160716\ftmo_stage1_retry
```

Its `evidence_manifest.json` SHA-256 is:

```text
f8155e042fb183070440f22516c05de8075203964217252edea19f05100e2341
```

All `41` declared payload hashes and byte counts revalidated after archive.
Keep the packet ignored and do not commit runtime config, journals, state, or
broker exports.

## IC Stage 3 Point-In-Time Pass

The approved IC-only contained Stage 3 run completed on 2026-06-02 ICT from
exact reviewed SHA:

```text
b02a3cb92a05e771782c7a9ca4e4339c9452969a
```

IC passed fresh pre-pull Stage 0 read-only checks, `102` VPS-focused tests,
bounded pre/post status, strict pre/post MT5 exports, and exactly one
`--reconcile-only` invocation. The post-reconcile state has schema v2,
minimum reader v2, the legacy-loader tripwire, one deterministic
`clean_noop_migration` receipt, a deterministic completion row, a CLI
completion row, and a reconciliation heartbeat.

Receipt operation ID:

```text
016bd67907de7987ad84ba6186ab60e2fd44f22ac3ae3cf7cc5cd94eb68619a2
```

Broker exposure remained unchanged: pending orders `0`, the same `2` active
positions, and unchanged historical order/deal counts (`232` / `129`). IC
remains contained with `KILL_SWITCH` active, `LPFS_IC_Live` disabled, runner
count `0`, watchdog count `0`, recovery disabled, and `26.24 GiB` free disk.
FTMO was not accessed.

The authoritative packet is archived outside the disposable worktree:

```text
C:\TradeAutomationEvidence\lpfs_c01_deploy\20260602_152110\ic_stage3
```

Its `evidence_manifest.json` SHA-256 is:

```text
033a67a66a5064015d38c5c1a69d084d21cc4130e1539040a854421ab8fb81ed
```

All `92` declared payload hashes and byte counts revalidated after archive.
Keep the packet ignored and do not commit runtime config, journals, state, or
broker exports.

Skip the IC Stage 4 canary by default. The owner-approved Stage 5 path is now
minimum-safety resumption: publish the narrow bounded-status CLIXML
collector/verifier consistency fix, collect fresh dual-lane minimum read-only
evidence, deploy the final approved `main` SHA under containment, resume FTMO
first, and touch IC only after FTMO post-start evidence is clean.

## Gate 1 V2 Strict-MT5 Transport Stop

The approved fresh Gate 1 v2 read-only collection stopped on 2026-06-05 ICT.

Authoritative ignored packet:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate1_v2_20260605_202849
```

Its `manifest.json` SHA-256 is:

```text
fcbf76b75a98bc01f745d7f77a2523b6fc01b97f99b0c24aea118f5fc0bcd36f
```

The packet is `STOPPED`: compact-containment and bounded-status artifacts were
not produced, and both strict MT5 probes exited `1`. Preserved stderr shows
Python received only `import` and raised `SyntaxError`, confirming that the
reviewed inline `python -c` strict-probe transport broke before MT5 evidence
was produced. No Gate 3 restart, watchdog start, task enablement,
kill-switch clear, reconciliation, canary, broker mutation, runtime-state
edit, or journal write occurred.

Do not retry Gate 1 using the inline strict MT5 transport. The offline
follow-up replaces strict MT5 execution with a hash-bound stdin transport:
the reviewed local `strict_mt5_probe.py` artifact is sent over SSH stdin,
verified remotely by SHA-256, then piped into the lane Python interpreter in
memory. The post-execution verifier requires manifest-bound command, script,
stdout, stderr, exit-code, timeout, and execution metadata artifacts plus
exactly one strict script verification marker and one `LPFS_GATE1_MT5_JSON=`
payload. This packet is historical; the current resumption path uses the
minimum read-only profile rather than the old strict Gate 1 V2 blocker.

The default pre-execution verifier allowlist no longer accepts stale
pre-hardening Gate 1 v2 contract hash
`f4a602aac651220fb599324edd9c284aaa19071737d7472f4468efc2012cc057`,
which pinned the old inline strict-MT5 command artifacts.

## Gate 1 V2 Evidence-Tooling Stop

The approved fresh Gate 1 v2 read-only collection stopped again on 2026-06-06
ICT.

Authoritative ignored packet:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate1_v2_20260606_020556
```

Its `manifest.json` SHA-256 is:

```text
d33094989b3f2ef1566f2e2e97c9015ebb5bd18f845a6d1d0f2630131590bcf2
```

The packet remains `STOPPED`. The strict MT5 steps are valid `PASS` evidence
for both lanes. Bounded-status steps produced valid stdout, exit `0`, and
PowerShell CLIXML host/progress/information records on stderr; the offline
verifier now preserves and classifies that stderr as safe only when it is
well-formed CLIXML with no error/exception/native-command records. FTMO
compact containment now verifies under explicit reviewed line-ending-aware
critical runtime hash variants; the raw observed `live_executor.py` CRLF hash
`ebd83b268e815dada781d35b813b0c80b2248db84082995f8ec09dd939f55d9e`
remains visible in receipts, and arbitrary edited hashes still fail.

IC compact containment timed out with exit `124`, empty stdout/stderr, and no
remote script-hash verification marker. Local artifacts do not prove whether
the timeout came from SSH stdin handling, remote command waiting behavior,
timeout length, or transient VPS behavior. Do not mask this: IC compact
timeout remains a hard strict-profile `STOPPED` condition. This packet is
historical evidence; the current resumption path uses the owner-approved
minimum read-only profile.

## FTMO Stage 5 Gate 3 Accepted Stop

The approved FTMO-only watchdog-resumption attempt stopped on 2026-06-04 ICT
before enabling or starting `LPFS_Live`.

Authoritative ignored packet:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\ftmo_gate3_20260604_100840
```

Its `manifest.json` SHA-256 is:

```text
85df11692de17e3d35b986dafee1ce729a15b822b8ce0f3c3ccea367eb27318e
```

Final evidence proves FTMO remains contained: `KILL_SWITCH` active,
`LPFS_Live` disabled, runner/watchdog process count `0`, broker pending orders
`0`, strict MT5 reads successful, correct account/server identity, and the
same three active positions with unchanged symbol, magic, comment, volume,
SL, and TP.

Fallback containment refreshed the FTMO `KILL_SWITCH` content and invoked
`Disable-ScheduledTask` while `LPFS_Live` was already disabled. No task
enable/start, kill-switch clear, IC access, reconciliation, canary, pull, or
broker mutation occurred.

The malformed ad hoc verification probe did not preserve its exact command,
stdout, stderr, and exit code in the authoritative packet. Its root cause
therefore cannot be independently verified from durable evidence. The
replacement offline verifier is `scripts/verify_lpfs_structured_command.py`.
It requires all four command artifacts, verifies packet hashes, accepts
exactly one structured JSON marker, and writes an atomic PASS/STOPPED receipt.

Do not retry Gate 3. Read `lpfs_stage5_gate3_retry_plan.md`. The previous Gate
1 evidence is stale, and `gate1_v2_20260606_020556` remains stopped for IC
compact timeout after the current offline evidence-tooling fixes. After this
verifier/tooling change is reviewed and published, collect a fresh dual-lane
Gate 1 read-only packet only with separate explicit approval and stop for
review before requesting another FTMO Gate 3 approval.

Current offline verifier validation passed: `65` focused Stage 5 verifier
tests; full LPFS suite `461` tests total (`459` passed, `2` skipped); and
strict core coverage at `6401` statements plus `2192` branches with `100.00%`.

## Approved Scope

Allowed changes:

- parse MT5 bars, ticks, positions, and deals directly as UTC epochs;
- retain a deprecated `broker_time_epoch_to_utc` compatibility wrapper;
- require `live_send.market_recovery_mode="disabled"` in code;
- write v2 production state atomically with a downgrade tripwire;
- fail closed when required MT5 reads return `None`;
- compare canonical and deterministic legacy Helsinki-shifted signal keys;
- normalize mixed legacy/v2 close cursors under recorded semantics;
- add an isolated `--reconcile-only` mode for proof-backed stale pending
  cleanup while `KILL_SWITCH` exists;
- add a guarded `--one-cycle-canary` acknowledgment contract;
- add read-only evidence export and immutable normalization tools;
- update tests, generated operations docs, and handoff docs.

Not allowed:

- strategy heuristic changes;
- entry, exit, timeframe, or risk-setting changes;
- broker order or active-position edits;
- runtime state or journal deletion, reset, or manual rewrite;
- enabling market recovery;
- VPS pull, live deploy, reconcile-only execution, live canary, runner restart,
  task enablement, or watchdog resumption without separate operator approval.

## Timestamp Contract

New sparse broker-derived rows use:

```text
mt5_epoch_utc_v2
```

Legacy shifted tracked records default to:

```text
legacy_helsinki_relocalized_v1
```

The historical compatibility transform is fixed to `Europe/Helsinki`; it does
not depend on the current configured broker timezone. New diagnostics preserve
raw `time`, raw `time_msc`, normalized UTC, timestamp semantics, and provenance
where MT5 supplies them. Missing broker timestamps are recorded as unavailable
or fail closed where lifecycle ordering requires a timestamp. They are not
fabricated with `now()`.

## V2 State And Rollback

Production state uses schema v2:

```json
{
  "state_schema_version": 2,
  "minimum_reader_schema_version": 2,
  "processed_signal_keys": null,
  "state": {
    "state_writer_timestamp_semantics_version": "mt5_epoch_utc_v2"
  }
}
```

The top-level `processed_signal_keys: null` is deliberate: legacy loaders fail
before scanning or sending. All v2 production writes require atomic
replacement. A failed atomic replace activates or preserves `KILL_SWITCH`,
journals `live_state_atomic_replace_failed` where possible, and returns a
terminal watchdog code.

After any v2 state write or v2 send, rollback is forward-fix only. Do not run an
old timestamp binary against v2 state.

## Reconcile-Only Contract

`scripts/run_lp_force_strike_live_executor.py --reconcile-only` is routed
before the normal kill-switch early exit. It requires the kill switch, takes
the normal state-adjacent lock, validates account identity and broker reads,
and refuses unexpected broker pending orders or active-position mismatches.

It does not scan setups or candles and does not call `order_check`,
`order_send`, or cancellation requests. A local stale pending record is removed
only when validated MT5 broker history proves a terminal outcome. This release
does not accept an operator-evidence fallback. Ambiguous records abort with
local state unchanged.

Each commit has a deterministic reconciliation operation ID and a receipt in
v2 state. Reruns backfill missing deterministic lifecycle rows without applying
cleanup twice.

## Canary Contract

A direct one-cycle live canary requires:

```text
--one-cycle-canary
--cycles 1
--canary-exposure-ack I_ACCEPT_ONE_CYCLE_MAY_PLACE_AND_FILL_MULTIPLE_REAL_ORDERS
```

This does not bypass `KILL_SWITCH`. The operator wrapper must clear the kill
switch only for the CLI invocation, restore it in `finally`, verify it exists
again, and immediately inventory broker pending orders and active positions.
Skip the canary if multi-order exposure is unacceptable.

## C-01 Deployment Order

For this release only, deploy and review `FTMO` first, then `IC`. Older
`IC`-first instructions in handoff history describe the earlier watchdog
rollout and do not apply to C-01. Keep both lanes contained until a separate
operator-approved deployment step begins.

## Evidence Tools

Read-only full MT5 export:

```powershell
.\venv\Scripts\python scripts\export_lpfs_mt5_evidence.py `
  --config config.local.json `
  --lane FTMO
```

Immutable legacy journal normalization:

```powershell
.\venv\Scripts\python scripts\normalize_lpfs_c01_evidence.py `
  --journal "<local-legacy-journal-copy>"
```

The normalizer is semantics-aware: it preserves `mt5_epoch_utc_v2`, corrects
only affected legacy broker/candle-derived fields, prefers raw MT5 epochs where
available, rebuilds timestamp-bearing signal and trade keys, and records
unresolved warnings for unsupported timestamp paths. Every historical `*_utc`
leaf is explicitly classified as corrected, preserved, or unresolved. It
fails closed on unknown semantics. It does not shift heartbeat timestamps,
collection metadata, `occurred_at_utc`, actual placement timestamps, or VPS
startup timestamps. Preserve raw evidence and use normalized evidence for
production-derived strategy conclusions.

Affected historical timestamp inventory:

- bar-derived setup paths: `lp_break_time_utc`, `fs_signal_time_utc`,
  `signal_time_utc`, `signal_closed_time_utc`,
  `latest_closed_candle_time_utc`, and `first_expired_bar_time_utc`;
- tick-derived paths: `market_time_utc`;
- broker lifecycle paths: `opened_utc`, `closed_utc`, expiration paths, and
  touch-path timestamps. Expiration paths explicitly include
  `expiration_utc`, `broker_backstop_expiration_utc`,
  `old_expiration_utc`, and `new_broker_backstop_expiration_utc`;
- timestamp-bearing identities: `signal_key`, embedded signal keys in
  `event_key`, and diagnostic `trade_key`. Embedded `event_key` rebuilding
  accepts both `T` and space-separated historical timestamp forms;
- explicitly preserved system paths: `occurred_at_utc`, `placed_time_utc`,
  `collected_at_utc`, `boot_time_utc`, `detected_at_utc`, and
  `restart_event_time_utc`.

Unsupported timestamp-bearing paths are preserved and emitted as unresolved
warnings. Do not use a normalized packet for strategy conclusions until its
warning inventory has been reviewed. The packet manifest records
`safe_for_strategy_analysis=false` whenever unresolved warnings exist.

The diagnostic builder intentionally retains flexible local `--journal`
inputs. Compact live summaries remain stricter: they consume
collector-manifest-backed local snapshots.

## Analysis Workflow After Recovery

Once both lanes are safely migrated and normalized evidence exists:

1. rebuild FTMO and IC diagnostics plus weekly and monthly reports;
2. compare matched cross-lane setups and isolate broker/feed execution
   divergence before calling a strategy defect;
3. emphasize recent `3`, `6`, and `12` month windows while retaining the
   10-year backtest as a guardrail;
4. research small reversible candidates only when FTMO/IC evidence is
   directionally confluent;
5. deploy no heuristic change without a separate approved strategy-change
   plan.

## Files To Inspect First

1. `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/timestamp_semantics.py`
2. `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_executor.py`
3. `scripts/run_lp_force_strike_live_executor.py`
4. `scripts/run_lpfs_live_forever.ps1`
5. `scripts/Get-LpfsDualVpsStatus.ps1`
6. `scripts/export_lpfs_mt5_evidence.py`
7. `scripts/normalize_lpfs_c01_evidence.py`
8. `strategies/lp_force_strike_strategy_lab/tests/test_c01_live_safety.py`

## Current Blockers And Open Questions

- FTMO Stage 1 reconciliation passed point-in-time. Do not rerun FTMO
  reconciliation.
- The default decision is to skip the multi-order FTMO canary.
- IC-only contained Stage 3 passed point-in-time. Do not rerun IC
  reconciliation.
- Skip the IC Stage 4 canary by default. Stop before Stage 5.
- Stage 5 watchdog resumption follows the owner-approved minimum-safety path:
  publish the narrow bounded-status CLIXML consistency fix; collect fresh
  dual-lane minimum read-only evidence; merge/deploy final approved `main`
  under containment; rerun the lane's minimum checks after deploy; resume
  FTMO first; touch IC only after FTMO post-start evidence is clean.
- Skip canaries by default. Do not run reconciliation. Do not manually close,
  cancel, or modify broker orders or positions without separate approval.
- Observability backlog: reconciliation snapshot `stable_hash()` currently
  includes full live position rows, including moving `price_current` and
  `profit`. The receipt chain is internally valid, but adjacent read-only
  exports cannot be expected to reproduce that snapshot hash exactly. Compare
  stable inventory fields for adjacent-export checks and review a narrower
  hash projection separately.
- Packet-capture backlog: suppress PowerShell progress noise, capture
  stdout/stderr separately, preserve explicit remote process exit-code
  sidecars, and classify expected CLIXML host-information serialization
  separately from fail-closed `ERROR/UNKNOWN`, exception, or native-command
  error text.
- Packet-capture status: Gate 1 v2 compact containment and strict MT5 no
  longer embed full reviewed scripts inside long inline commands. They use
  short hash-bound bootstraps, send reviewed local script artifacts over SSH
  stdin, verify the script SHA-256 remotely, and execute in memory. The
  bounded-status collector exposes these routes through explicit CLI modes
  `--mode compact-containment` and `--mode strict-mt5`. The post-execution
  verifier now classifies safe bounded-status PowerShell CLIXML and compares
  raw observed critical runtime hashes against explicit reviewed
  line-ending-equivalent variants. The owner-approved minimum read-only
  profile is the current resumption evidence gate.

## Verification Status

Completed locally on 2026-06-01 ICT:

```powershell
.\venv\Scripts\python -m unittest `
  strategies.lp_force_strike_strategy_lab.tests.test_c01_live_safety `
  strategies.lp_force_strike_strategy_lab.tests.test_diagnostic_logging `
  strategies.lp_force_strike_strategy_lab.tests.test_dry_run_executor `
  strategies.lp_force_strike_strategy_lab.tests.test_live_executor `
  strategies.lp_force_strike_strategy_lab.tests.test_live_runner `
  strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages `
  strategies.lp_force_strike_strategy_lab.tests.test_live_trade_summary `
  strategies.lp_force_strike_strategy_lab.tests.test_live_weekly_performance `
  strategies.lp_force_strike_strategy_lab.tests.test_notifications `
  strategies.lp_force_strike_strategy_lab.tests.test_live_policy_ledger
.\venv\Scripts\python -m unittest discover -s strategies\lp_force_strike_strategy_lab\tests
.\venv\Scripts\python scripts\run_core_coverage.py
git diff --check
```

Results:

- contained forward-fix targeted LPFS set: `140` tests passed;
- full LPFS suite: `461` tests total (`459` passed, `2` intentional skips);
- strict core coverage: `6401` statements and `2192` branches at `100.00%`;
- docs-only IC consistency dashboard checks: `28` tests passed;
- `docs/live_ops.html` regeneration produced SHA-256:
  `14AD7C0833D747FDE9932E36177CEE693177A9E78A3E8FD52A784C6133FAC3DC`;
- local archived-row normalization rehearsal: `275578` snapshot rows,
  `461270` deterministic changes, and `0` unresolved warnings;
- `git diff --check`: passed;
- manual scope audit: no strategy heuristic, entry/exit, timeframe-selection,
  risk-bucket, sizing-limit, or broker-send expansion.

The historical docs-only IC consistency follow-up added dashboard assertions
that required the then-current last-approved IC Stage 0 snapshot label and
rejected unqualified current-containment wording. The contained IC Stage 3
pass above supersedes that handoff boundary. It did not change runtime code or
VPS state.

The contained FTMO-only Stage 1 retry completed and is recorded above. IC was
not accessed. Production remains intentionally paused pending separate
operator approval for any next step.
