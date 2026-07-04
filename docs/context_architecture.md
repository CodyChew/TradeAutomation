# TradeAutomation Context Architecture

Last updated: 2026-07-04 ICT.

This map keeps first-read context short while preserving operational, strategy,
safety, and evidence history. It does not authorize live operations, strategy
changes, broker actions, VPS actions, runtime edits, journal edits, report
regeneration, or deployment.

## First-Read Route

Use this route for a new Codex or handoff session:

1. `AGENTS.md` for standing roles, live-safety rules, change gate, code-change
   boundaries, and verification expectations.
2. `SESSION_HANDOFF.md` for the latest volatile operational handoff.
3. `PROJECT_STATE.md` for the concise workspace control state.
4. `strategies/lp_force_strike_strategy_lab/START_HERE.md` for LPFS first-read
   routing, environment boundaries, and live-run safety.
5. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` for current LPFS
   live/research state.
6. `docs/lpfs_strategy_iteration_context.md` for the active strategy queue,
   evidence packets, blockers, and no-live-change status.
7. `docs/evidence_catalog.md` for packet paths, hashes, historical/current
   labels, and questions answered.

Task-specific docs still apply. Read `docs/change_gate.md` before material
changes and `docs/repo_maintenance_policy.md` before repo/process maintenance.

## Source-Of-Truth Owners

| Question | Canonical owner | Notes |
| --- | --- | --- |
| What are the standing safety rules? | `AGENTS.md` | Avoid volatile packet history here. |
| What is the latest handoff boundary? | `SESSION_HANDOFF.md` | Treat packet counts as historical until refreshed. |
| How is the repo organized? | `PROJECT_STATE.md` and `README.md` | Keep this concise and link deeper detail. |
| Which LPFS docs should I read? | LPFS `START_HERE.md` | This remains the LPFS first-read map. |
| What is the active LPFS strategy queue? | `docs/lpfs_strategy_iteration_context.md` | Current active/rejected candidates and blockers live here. |
| Which packet/hash supports a claim? | `docs/evidence_catalog.md` | Raw packets stay ignored; this file indexes them. |
| What changed historically? | `docs/history/lpfs_operations.md` and `strategies/lp_force_strike_strategy_lab/docs/experiment_history.md` | Historical facts are not current broker truth. |
| Why was a material decision made? | `docs/decision_log.md` and `docs/reviews/` | Decision log is the index; reviews hold detail. |
| How should tests be selected? | `docs/testing_strategy.md` and `AGENTS.md` | Broaden tests when behavior changes. |

## Current-State Rules

- First-read files carry current control facts and route to archives.
- Historical packet facts must be labeled historical unless a fresh status or
  broker read verifies them.
- Generated dashboards under `docs/` are versioned outputs; update builders or
  source metadata before regeneration.
- Raw report packets, journals, broker exports, runtime state, and local live
  configs remain ignored unless separately reviewed and intentionally promoted.
- Repeated context belongs in one canonical owner plus links, not copied into
  every first-read file.

## Role Ownership

- Main Orchestrator classifies scope and routes work.
- Documentation and Workflow Agent owns first-read clarity, source-of-truth
  routing, decision-log hygiene, and docs/process drift.
- Repo Auditor owns repo-health findings and `scripts/audit_repo_process.py`.
- Reliability Reviewer owns live-safety review for deployment, runtime, broker,
  journal, watchdog, scheduler, and operational wording changes.
- Independent Issue Verifier owns issue truth and production-impact
  classification.
- LPFS Strategy Improvement Agent owns evidence-backed strategy workflow, not
  live-rule approval.
- QA / Test Engineer owns verification sufficiency for changed surfaces.
- Risk Manager, Strategy Trader, and Data Engineer are called when a change can
  affect risk framing, strategy interpretation, or evidence lineage.

## Maintenance Checklist

For material context/process changes:

1. Create a dated `docs/reviews/` artifact before implementation.
2. Preserve packet paths, hashes, explicit non-actions, and current/rejected
   strategy decisions in `docs/evidence_catalog.md` or a linked artifact.
3. Update first-read docs only after the new owner/index exists.
4. Run the repo process audit and required focused tests.
5. Close with first-read drift and scope audits.
