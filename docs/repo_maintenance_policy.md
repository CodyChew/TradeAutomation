# TradeAutomation Repo Maintenance Policy

Last updated: 2026-07-04 ICT.

This policy keeps TradeAutomation maintainable as live LPFS evidence, research
history, generated dashboards, and workflow rules grow. It adapts the useful
parts of the DayTrading maintenance pattern without changing TradeAutomation's
LPFS-specific live-safety gates.

This document does not authorize live operations, strategy changes, broker
actions, VPS actions, reconciliation, canary runs, runtime-state edits,
production-journal edits, market-recovery enablement, or deployment.

## Source-Of-Truth Boundaries

Use the narrowest durable source of truth for the question being answered.

| Artifact | Owns | Should avoid |
| --- | --- | --- |
| `AGENTS.md` | Standing role boundaries, live-safety rules, change-gate policy, and verification expectations | Volatile status, packet details, strategy-result history |
| `README.md` | New-human entry point, repo layout, common commands, and safety summary | Detailed handoff, live packet history, research logs |
| `PROJECT_STATE.md` | Workspace-level current state and next read path | Full LPFS history, full tooling inventory, every past packet |
| `SESSION_HANDOFF.md` | Latest operational handoff and volatile continuity facts | Becoming the only decision log or long-term policy source |
| `strategies/lp_force_strike_strategy_lab/START_HERE.md` | LPFS first-read map, environment boundaries, and resume prompts | Full research-history archive |
| `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` | Detailed LPFS current strategy/live/research state | Generic repo process policy and unrelated strategy lanes |
| `docs/change_gate.md` | Material-change routing, required evidence, stop conditions | One-off decision records |
| `docs/reviews/` | Detailed review artifacts for material changes | Replacing concise current-state docs |
| `docs/decision_log.md` | Concise index of durable material decisions and review links | Full review transcripts or packet manifests |
| `docs/repo_maintenance_policy.md` | Current-state size policy, repo-health audit, and maintenance cadence | Live-run procedures or strategy evidence |

Generated dashboard HTML under `docs/` is intentionally versioned output. Edit
the source builder or metadata before regenerating generated pages. Ignored
`data/`, `reports/`, runtime roots, broker exports, and evidence packets remain
outside tracked source unless a separate review explicitly promotes a sanitized
artifact.

## Current-State Size Targets

These are advisory limits, not emergency blockers. Exceeding them should create
a maintenance task or warning, not a rushed rewrite during live-sensitive work.

| File | Advisory limit | Current policy |
| --- | ---: | --- |
| `README.md` | 250 lines | Entry point only. |
| `PROJECT_STATE.md` | 650 lines | Keep as the concise workspace control file; archive old detail progressively. |
| `SESSION_HANDOFF.md` | 1,200 lines | Keep the newest operational facts near the top; archive old history when it blocks handoff clarity. |
| `strategies/lp_force_strike_strategy_lab/START_HERE.md` | 500 lines | Keep the first-read path and boundaries easy to scan. |
| `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` | 1,200 lines | Detailed LPFS state is allowed to be longer, but repeated historical sections should be moved to review artifacts or specific docs over time. |
| `AGENTS.md` | 800 lines | Standing instructions only. |

As of 2026-07-04, several current-state files exceed these advisory limits.
That is known maintenance debt, not a reason to remove safety-critical context
blindly. Future updates should reduce duplication opportunistically by moving
history, backlog, and tooling inventory into focused docs.

## Decision And Review Records

Material changes still require the review artifact, PR body, or deployment
packet described in `docs/change_gate.md`.

Use `docs/decision_log.md` as the concise index when a change creates a durable
project decision, such as:

- new or changed process gates;
- role/team responsibility changes;
- source-of-truth boundary changes;
- strategy/risk promotion or rejection decisions;
- live/deployment policy changes;
- generated-artifact or evidence-interpretation policy changes.

The decision log should link to the detailed review artifact instead of
duplicating it. Historical decisions do not need to be backfilled all at once;
add entries when touching nearby docs or when a new decision is made.

## Repo Process Audit

Run the lightweight audit before publishing process, onboarding, first-read, or
workflow-hardening changes:

```powershell
.\venv\Scripts\python scripts\audit_repo_process.py
```

The audit checks:

- critical first-read and process files exist;
- oversized current-state files are visible as warnings;
- obvious committed secret-token patterns are not present in tracked text;
- tracked runtime, evidence, local config, broker artifact, or generated
  coverage paths are not present;
- required docs reference the maintenance policy, change gate, decision log, or
  review artifacts where appropriate.

Default behavior fails only on errors. Current-state size drift is a warning so
known debt remains visible without blocking unrelated safe work. Use
`--fail-on-warning` for milestone cleanup work when the warning budget should
be enforced.

## Maintenance Cadence

For docs/process changes:

1. Use `docs/change_gate.md` when the change is material.
2. Create or update a dated `docs/reviews/` artifact before implementation.
3. Update `docs/decision_log.md` when the change is a durable decision.
4. Run `scripts/audit_repo_process.py`.
5. Run any required focused tests from `AGENTS.md`.
6. Close with a scope audit that confirms no unrelated live/runtime/strategy or
   generated artifacts are included.

For periodic repo audits:

- Review first-read docs for stale current-looking claims.
- Review whether `PROJECT_STATE.md` and `SESSION_HANDOFF.md` are still usable
  from the top without reading the whole file.
- Check that open process gaps have an owner, artifact, or next trigger.
- Confirm generated/runtime artifacts remain ignored unless intentionally
  versioned.
- Prefer targeted archival over broad doc rewrites.

## Role Ownership

Keep the existing TradeAutomation role model.

- Documentation and Workflow Agent owns this maintenance policy, onboarding
  clarity, source-of-truth routing, first-read drift checks, and decision-log
  hygiene.
- Repo Auditor owns periodic repo-health findings and the
  `scripts/audit_repo_process.py` signal.
- Main Orchestrator routes material work and integrates accepted outputs, but
  does not approve live deployment, issue truth, strategy changes, production
  safety, or its own material process work by itself.
- Reliability Reviewer and Independent Issue Verifier are called when the
  change affects live safety, deployment readiness, broker behavior, issue
  truth, production impact, or evidence interpretation.

Do not add a separate standing Documentation Steward or Workflow Auditor role
right now. Their useful responsibilities are covered by the Documentation and
Workflow Agent plus Repo Auditor in this repo.
