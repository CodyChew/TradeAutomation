# 2026-07-04 Context Architecture Hardening Review

Status: role-reviewed, approved for scoped docs/process implementation.

Scope: context architecture, first-read routing, evidence indexing, and repo
process audit hardening. This review does not authorize live operations,
strategy changes, broker actions, VPS actions, Task Scheduler actions, runtime
state edits, journal edits, report-output changes, generated-dashboard changes,
config changes, or deployment.

## Baseline

Repository baseline before implementation:

- checkout: `C:\Users\Cody\OneDrive\Desktop\TradeAutomation`
- branch: `main...origin/main`
- prior commit: `5329bdbb8cb719e0305c09effe418884f2cc9075`
- `scripts/audit_repo_process.py`: `status=warn`
- warnings:
  - `PROJECT_STATE.md`: 1214 lines, advisory limit 650
  - `SESSION_HANDOFF.md`: 2217 lines, advisory limit 1200
  - `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md`: 2294 lines,
    advisory limit 1200

No live/runtime/broker/journal/VPS state was accessed during review.

## Team Review

| Role | Decision | Required preservation | Resolution |
| --- | --- | --- | --- |
| Main Orchestrator | Approve | Keep the work docs/process-only and route it through the change gate. | This artifact records the material review before first-read compression. |
| Documentation and Workflow Agent | Approve with conditions | Standing role/safety rules, latest operational boundary, packet hashes, strategy state, journal safety, verification commands. | Add a source-of-truth map, evidence catalog, and concise first-read owners. |
| Repo Auditor | Approve with conditions | Current safety/strategy/evidence anchors, no tracked raw reports or runtime artifacts. | Add audit hardening for required context anchors and keep generated/runtime artifacts untouched. |
| Reliability Reviewer | Approve with conditions | Live-operation prohibitions, FTMO-first deployment gate, recovery disabled, packet proof, status-script contract, unsafe journal-read guardrails. | Preserve these in first-read files and audit anchors. |
| Independent Issue Verifier | Approve with conditions | Broker-truth hierarchy, packet provenance, fresh dual-status requirement, no live exposure. | Classify bloat as `Confirmed but not live-exposed`; preserve packet facts as historical unless freshly verified. |
| QA / Test Engineer | Approve with conditions | Stale-current-state tests and operator-doc safety phrases must remain meaningful. | Run process audit, process-audit tests, dashboard page tests, and `git diff --check`. |
| LPFS Strategy Improvement Agent | Approve with conditions | H8 compressed risk active, H8 low-spread-only rejected, no live strategy change approved, FTMO/IC confluence and guardrails. | Keep current strategy queue in first-read docs and `docs/lpfs_strategy_iteration_context.md`. |
| Risk Manager | Changes required | Source-of-truth map and review artifact before implementation. | Add `docs/context_architecture.md` and this review artifact before first-read edits. |
| Strategy Trader | Approve with guardrails | No stale packet or one-lane weak bucket may become an implied strategy signal. | Keep no-live-change status, rejected hypothesis, and next criteria visible. |
| Data Engineer | Changes required | Evidence-index schema and migration audit before first-read compression. | Add `docs/evidence_catalog.md` with schema and packet index; this artifact includes the migration audit below. |

No role objected to the hardening direction after the required safeguards were
included. The Data Engineer and Risk Manager conditions are implemented as
preconditions to first-read compression.

## Agreed Plan

1. Add `docs/context_architecture.md` as the compact routing and ownership map.
2. Add `docs/evidence_catalog.md` as the durable evidence index and schema.
3. Add `docs/history/lpfs_operations.md` for old operational/deployment and
   incident history that should not live in volatile handoff files.
4. Add
   `strategies/lp_force_strike_strategy_lab/docs/experiment_history.md` for
   V1-V22 research chronology.
5. Compress `PROJECT_STATE.md`, `SESSION_HANDOFF.md`, and LPFS
   `PROJECT_STATE.md` into current-state control files that link to the new
   archives and catalog.
6. Harden `scripts/audit_repo_process.py` so future cleanups keep required
   context anchors and required references.
7. Update `docs/decision_log.md` and related routing docs.

## Evidence Catalog Schema

The evidence catalog must preserve one row per important packet or reviewed
artifact with these fields:

- `id`
- `date`
- `domain`
- `lane`
- `status`
- `current_label`
- `path`
- `hash_or_manifest`
- `question_answered`
- `non_actions`
- `canonical_reference`

Rules:

- Use `current_label=current` only for the latest context pointer that first
  readers may use as the current handoff boundary.
- Use `current_label=historical` for packet facts that are not live broker
  truth until refreshed.
- Preserve explicit non-actions where a packet proves nothing live-changing was
  done.
- Raw ignored packets remain untracked; the catalog tracks paths and hashes
  only.

## Migration Audit

| Original first-read section | New owner | Preservation status |
| --- | --- | --- |
| `SESSION_HANDOFF.md` AI Agent Continuity Rules | `SESSION_HANDOFF.md` current capsule plus `docs/evidence_catalog.md` | Latest operational facts retained; historical packet detail indexed. |
| `SESSION_HANDOFF.md` old C-01, Stage 5, telemetry, active-position, market-data, and RA deployment detail | `docs/history/lpfs_operations.md` and `docs/evidence_catalog.md` | Packet paths, hashes, outcomes, and non-actions retained as historical facts. |
| `SESSION_HANDOFF.md` historical remote/VPS and old operational checkpoint narratives | `docs/history/lpfs_operations.md` and relevant runbooks | Summarized as dated history; current access stays in root `PROJECT_STATE.md`. |
| Root `PROJECT_STATE.md` Immediate LPFS Safety State | Root `PROJECT_STATE.md`, `SESSION_HANDOFF.md`, and `docs/evidence_catalog.md` | Current safety capsule retained; repeated proof prose moved to catalog/history. |
| Root `PROJECT_STATE.md` Current Operations Access | Root `PROJECT_STATE.md` | Current lanes, task names, hosts, and approval boundary retained. |
| Root `PROJECT_STATE.md` LPFS reporting and weekly review detail | `docs/lpfs_strategy_iteration_context.md`, `docs/evidence_catalog.md`, root `PROJECT_STATE.md` | Current weekly packet and strategy decision retained; old incident history archived. |
| Root `PROJECT_STATE.md` long execution readiness and suggested prompt sections | `docs/context_architecture.md`, `docs/history/lpfs_operations.md`, LPFS `START_HERE.md` | Durable routing retained; volatile old prompts removed from current state. |
| LPFS `PROJECT_STATE.md` Current Live-Ops State | LPFS `PROJECT_STATE.md`, `SESSION_HANDOFF.md`, and `docs/evidence_catalog.md` | Current live boundary retained; old packet detail indexed. |
| LPFS `PROJECT_STATE.md` 2026-05-23, 2026-05-30, 2026-06-27 weekly checkpoints | `docs/history/lpfs_operations.md`, `docs/lpfs_strategy_iteration_context.md`, `docs/evidence_catalog.md` | Current candidate and latest packet retained; older caveats preserved in history. |
| LPFS `PROJECT_STATE.md` V1-V22 experiment chronology | `strategies/lp_force_strike_strategy_lab/docs/experiment_history.md` | Research decisions retained as chronology; current baseline retained in LPFS state. |
| LPFS `PROJECT_STATE.md` MT5/Telegram/execution contracts | Existing contract docs and LPFS `START_HERE.md` | Contract docs remain canonical; LPFS state keeps pointers only. |

## Stop Conditions

Stop and ask for user direction if implementation requires any live action,
strategy behavior change, broker/order/position access, runtime-state mutation,
production-journal access, generated-dashboard regeneration, raw report
promotion, config change, scheduler/watchdog action, or evidence packet edit.

## Verification Plan

Run after implementation:

```powershell
.\venv\Scripts\python -B scripts\audit_repo_process.py
.\venv\Scripts\python -B -m unittest strategies.lp_force_strike_strategy_lab.tests.test_repo_process_audit
.\venv\Scripts\python -B -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages
git diff --check
```

Manual scope audit:

- first-read drift audit across `AGENTS.md`, `SESSION_HANDOFF.md`, root
  `PROJECT_STATE.md`, LPFS `START_HERE.md`, LPFS `PROJECT_STATE.md`,
  `docs/lpfs_strategy_iteration_context.md`, and `docs/evidence_catalog.md`
- confirm no live/runtime/strategy/risk/sizing/SL/TP/broker-send/config/
  scheduler/watchdog/journal/generated-dashboard/broker-artifact changes
