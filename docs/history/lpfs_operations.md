# LPFS Operations History

Last updated: 2026-07-09 ICT.

This file preserves dated operational, deployment, and reporting history that
should not bloat current-state first-read files. Historical packet facts are
not current broker truth. Capture a fresh dual-VPS status packet before any
live operation, deployment, restart, reconciliation, canary, or broker-adjacent
decision.

## Current Operating Boundary

The current live-ops boundary is the 2026-07-09 operator-approved LPFS
flatten/hold. Both lane tasks are disabled, both kill switches are active, and
broker-authoritative LPFS pending orders and active positions are `0` on both
FTMO and IC. See `docs/evidence_catalog.md` row
`lpfs-flatten-hold-20260709`.

The latest accepted deployed robustness/runtime boundary before the hold
remains the 2026-06-15 RA-002/RA-003 deploy at runtime SHA
`6c4ecb131d7499e455ef42cfeb91ba0bc0a75490`.

Current first-read docs keep only the active safety capsule. Packet paths,
hashes, and non-actions are indexed in `docs/evidence_catalog.md`.

## Timeline

### 2026-07-09 Operator-Approved Flatten And Project Hold

The operator approved flattening both LPFS lanes and putting the project on
hold for planning. The operation targeted LPFS-managed exposure only:

- FTMO `131500` / `LPFS`, task `LPFS_Live`
- IC `231500` / `LPFSIC`, task `LPFS_IC_Live`

Sequence: capture pre-operation dual status, contain FTMO, flatten FTMO,
capture post-FTMO status, contain IC, flatten IC, capture final dual status.

Final proof:

- FTMO: kill switch active, `LPFS_Live` disabled, runner/watchdog rows `0`,
  broker `OK`, LPFS pending orders `0`, LPFS active positions `0`.
- IC: kill switch active, `LPFS_IC_Live` disabled, runner/watchdog rows `0`,
  broker `OK`, LPFS pending orders `0`, LPFS active positions `0`.
- Recovery remained disabled.

The final status is expected to be `AMBIGUOUS` because manual broker flatten
made local runtime state stale and runtime state/journals were intentionally
not rewritten. Treat state-not-in-broker entries as quarantined hold-state
evidence until a separate reviewed reconciliation/state-repair plan exists.

Evidence:

- packet: `reports/live_ops/lpfs_flatten_hold_20260709_050513`
- packet manifest SHA-256:
  `2e0cf51d45b705cef5a23f5126e330028cf69b3de006a874f6b29d698aef55c0`
- final dual-status report:
  `reports/live_ops/lpfs_flatten_hold_20260709_050513/final_dual_status/lpfs_dual_vps_status_20260709_051800.md`
- final dual-status SHA-256:
  `e8bba7a9dbdb5cdd37dc2332cff022becf29671a3dbdba644e7e96bc1939e7f1`

Non-actions: no reconciliation-only run, canary, market recovery enablement,
strategy/risk/sizing/SL/TP/broker-send/config change, production journal edit,
or runtime-state edit. Broker mutation was limited to the approved LPFS
flatten.

### 2026-06-27 Weekly Strategy Review And Research Readiness

The latest eligible weekly review packet showed FTMO positive and IC weak, with
complete weekly coverage on both lanes. It triggered offline research, not a
live strategy change. The readiness closeout rejected the simple H8
low-spread-only filter and kept H8 compressed risk as a research-only
candidate pending next eligible weekly criteria.

Canonical current strategy context:

- `docs/lpfs_strategy_iteration_context.md`
- `docs/lpfs_strategy_improvement_workflow.md`
- `docs/evidence_catalog.md`

### 2026-06-15 RA-002/RA-003 Robustness Deploy

RA-002 blocks final pre-send quote refresh failures retryably after
`order_check` and before `order_send`. RA-003 refreshes Stage 5
profile/contract pins for current read-only status artifacts.

Final proof showed both VPS lanes running, kill switches clear, broker status
`OK`, recovery disabled, telemetry failures `0`, market-data fetch failures
`0`, and active state/broker mismatch count `0`. Broker exposure counts in
that proof are historical packet facts only.

Non-actions: no reconciliation, canary, recovery enablement, manual broker
mutation, config change, strategy/risk/sizing/SL/TP change, or broker-send
expansion.

Evidence row: `docs/evidence_catalog.md` `lpfs-ra002-ra003-20260615`.

### 2026-06-12 Transient Market-Data Frame-Skip Deploy

The transient market-data frame-skip patch lets a cycle skip only failed
symbol/timeframe candle-history frames while continuing healthy frames.
Broker/account/order/position failures remain fail-closed.

Non-actions: no reconciliation, canary, recovery enablement, manual broker
mutation, strategy/risk/sizing/SL/TP/broker-send/config change.

Evidence row: `docs/evidence_catalog.md` `lpfs-frame-skip-20260612`.

### 2026-06-09 Active-Position State/Broker Repair

The active-position repair was deployed to both VPS lanes at exact SHA
`45efa748423f20881507cda9d4f81e4afe617bde`. Full MT5 close-deal volume proof is
required before local active state can remove a broker-missing position.

Status output exposes `state_not_in_broker`, `broker_not_in_state`,
`active_position_state_broker_mismatch_count`, and dual-status
`position_comparison.status` / `position_comparison.mismatch_count`. Any
nonzero mismatch makes the lane ambiguous and requires reviewer inspection
before live operations.

IC emitted broker-proven aggregate close rows for two stale local active
positions:

- `USDJPY H12 short`, position `4439978943`, close deal `4234438950`,
  `-1.0074349442379535R`, broker PnL `-3.38`
- `AUDCHF H8 long`, position `4440556829`, close deal `4234376721`, `-1.0R`,
  broker PnL `-3.11`

Non-actions: no recovery enablement, reconciliation-only run, canary, manual
broker mutation, config change, historical journal migration, or strategy/risk/
sizing/SL/TP/broker-send change.

Evidence rows:

- `lpfs-active-repair-ftmo-20260609`
- `lpfs-active-repair-ic-20260609`
- `lpfs-active-repair-final-20260609`

### 2026-06-07 Stage 5 Resumption And Phase 1 Telemetry Separation

Stage 5 minimum-safety resumption completed with FTMO first and IC only after
FTMO proof was clean. Phase 1 live quote telemetry separation was then deployed
on both lanes from runtime SHA `027e0afe932081713067dc24b2bc457cddf1041e`.

Future live `market_snapshot` rows route to separate market-snapshot journals.
Primary lifecycle journals remain append-only and no longer receive new live
`market_snapshot` rows. Historical mixed journals remain readable.

The phrase "Historical IC promotion state" belongs only to historical context:
it was superseded by Stage 5 resumption and the latest dual VPS status packet
for current IC.

Evidence rows:

- `lpfs-telemetry-ftmo-20260607`
- `lpfs-telemetry-ic-20260607`

### 2026-06-02 C-01 Contained FTMO Retry And IC Stage 3

FTMO contained retry and IC Stage 3 are superseded historical checkpoints. They
confirmed point-in-time C-01 reconciliation and state-schema behavior before
Stage 5 later resumed both lanes.

Do not use these paused-state packets as current live rollout gates.

Evidence rows:

- `lpfs-c01-ftmo-retry-20260602`
- `lpfs-c01-ic-stage3-20260602`

### 2026-05-31 Watchdog Hardening Deploy

Documentation PR `#1` was squash-merged as `9dcfafc`; watchdog PR `#2` was
squash-merged as `3657323`. Both VPS lanes pulled `3657323` with deliberate
kill-switch-first restarts, IC first as canary for that historical deployment.

Current live operations still require fresh status proof and explicit approval.

### 2026-05-30 Weekly Evidence Checkpoint

The generated weekly dashboard hit an FTMO fetch timeout. Use the supplemental
local-snapshot review for that FTMO checkpoint. That week was mixed rather than
a clean cross-lane strategy failure: FTMO was acceptable/normal variance and IC
was weak/watch but above p10.

This remains historical evidence and should not override the latest eligible
weekly packet.

### 2026-05-23 Weekly Reporting Incident

During a live weekly performance analysis, an unsafe remote report scan opened
production journal/state files without explicit shared-read semantics. Both
live runners were later found stopped, then restarted and verified healthy in a
dual-VPS status packet.

Standing lesson: do not scan active production journals with unsafe file-open
semantics. Use bounded status reads or `FileShare.ReadWrite` snapshot tooling
and follow production-adjacent journal/state reads with a fresh dual-VPS status
packet.

Evidence row: `docs/evidence_catalog.md` `lpfs-weekly-incident-20260523`.

## Operational Invariants To Preserve

- No VPS, MT5, Task Scheduler, live runtime state, production journals, broker
  orders, broker positions, kill switches, reconciliation, canaries, restarts,
  VPS pulls, broker mutation, runtime-state edits, or market recovery without
  explicit approval.
- Recovery remains disabled unless a separate reviewed plan enables it.
- `scripts/Get-LpfsDualVpsStatus.ps1` is the structured dual-lane status proof.
  Do not assume `scripts/Get-LpfsLiveStatus.ps1` emits
  `LPFS_SNAPSHOT_JSON`.
- Active JSONL journals are append-only and must not be hashed or scanned with
  unsafe full-file reads as health probes.
- Historical packet facts are not live broker truth.
