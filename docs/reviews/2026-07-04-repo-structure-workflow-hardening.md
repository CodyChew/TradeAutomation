# Repo Structure And Workflow Hardening Review

Date: 2026-07-04 ICT.

## Change Type

Docs/process and repo-maintenance tooling. Material because it changes
onboarding, source-of-truth routing, decision-log expectations, and process
verification.

## Scope

Add a TradeAutomation-specific maintenance policy, lightweight decision-log
index, and local repo-process audit command with tests. Wire the new docs and
command into first-read/onboarding docs.

No strategy logic, risk sizing, SL/TP behavior, broker execution, MT5 behavior,
configs, scheduler, watchdog, VPS/runtime state, production journals, broker
artifacts, generated dashboard output, or live operation is in scope.

## Lead Owner

Documentation and Workflow Agent.

## Reviewers And Verifiers

- Documentation and Workflow Agent: lead owner for source-of-truth boundaries,
  onboarding clarity, and decision-log routing.
- Repo Auditor: reviews maintainability, generated/runtime artifact hygiene,
  and repo-health audit coverage.
- Main Orchestrator: classifies scope and integrates the accepted result.

Reliability Reviewer and Independent Issue Verifier are not required because
this change does not alter live operations, broker behavior, status logic,
journal/report evidence interpretation, or deployment readiness. Live-safety
wording is preserved rather than weakened.

## Evidence Used

- `AGENTS.md`
- `README.md`
- `PROJECT_STATE.md`
- `SESSION_HANDOFF.md`
- `strategies/lp_force_strike_strategy_lab/START_HERE.md`
- `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md`
- `docs/change_gate.md`
- `docs/lpfs_strategy_improvement_workflow.md`
- `docs/system_troubleshooting.md`
- `docs/codex_worktree_workflow.md`
- DayTrading reference docs under `C:\Trading\DayTrading`, used only for
  pattern comparison: concise current-state control, split history/backlog/
  tooling docs, review artifacts, decision log, and docs-audit command.

## Findings

1. Confirmed maintainability risk: TradeAutomation has clear source-of-truth
   docs, but current-state detail is duplicated and oversized across root
   `PROJECT_STATE.md`, `SESSION_HANDOFF.md`, LPFS `START_HERE.md`, and LPFS
   `PROJECT_STATE.md`.
2. Confirmed process gap: material review artifacts exist under
   `docs/reviews/`, but there is no concise decision-log index that lets a new
   agent find durable process decisions quickly.
3. Confirmed tooling gap: the repo has strong behavior tests and LPFS config
   audit tooling, but no lightweight process audit for required handoff files,
   current-state size drift, obvious secret patterns, or tracked runtime/evidence
   artifacts.
4. Role/team review: TradeAutomation should keep its existing focused LPFS
   roles. DayTrading's separate Documentation Steward and Workflow Auditor
   duties fit the existing Documentation and Workflow Agent plus Repo Auditor;
   adding more standing roles would add process noise.

## Changes Approved For Implementation

- Add `docs/repo_maintenance_policy.md`.
- Add `docs/decision_log.md`.
- Add `scripts/audit_repo_process.py`.
- Add focused unit tests for the new audit script.
- Update first-read/onboarding docs to reference the new policy, decision log,
  and audit command.
- Update `docs/change_gate.md` to clarify when `docs/decision_log.md` should be
  updated alongside review artifacts.

## Stop Conditions Checked

- Active checkout, branch, worktree, and `AGENTS.md` presence were confirmed
  before editing.
- No VPS, MT5, Task Scheduler, live runtime state, production journal, broker
  order, broker position, or kill-switch access is part of the work.
- No strategy, risk, sizing, SL/TP, broker-send, config, scheduler, watchdog,
  runtime-state, journal, broker-artifact, or generated-dashboard change is in
  scope.
- Existing DayTrading files are reference material only and will not be copied
  wholesale.

## Required Verification

- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_repo_process_audit`
- `.\venv\Scripts\python scripts\audit_repo_process.py`
- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages`
- `git diff --check`
- First-read drift check over the touched source-of-truth docs.
- Scope audit confirming no unrelated live/runtime/strategy/generated artifacts.

## Gate Decision

Approved for scoped docs/process and audit-tool implementation in the same chat,
subject to the verification above before closeout.

## Verification Results

- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_repo_process_audit`
  passed: `4` tests.
- `.\venv\Scripts\python scripts\audit_repo_process.py` exited `0` with
  `status=warn`. Warnings were expected advisory current-state size findings:
  root `PROJECT_STATE.md` (`1214` lines), `SESSION_HANDOFF.md` (`2217` lines),
  and LPFS `PROJECT_STATE.md` (`2294` lines) exceed the new maintenance
  targets.
- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages`
  passed: `32` tests.
- `.\venv\Scripts\python -m unittest discover -s strategies\lp_force_strike_strategy_lab\tests`
  passed: `542` tests.
- `.\venv\Scripts\python scripts\run_core_coverage.py` passed with
  `7181` statements, `2420` branches, and `100.00%` coverage.
- `git diff --check` passed with CRLF normalization warnings only.

## Team Review Follow-Up

After the user asked whether to make the audit clean, three read-only role
passes reviewed the current patch and the proposed cleanup:

- Documentation and Workflow Agent: no-go on shrinking oversized current-state
  files just to force `status=pass`; go on committing the current process
  hardening with size warnings treated as intentional maintenance debt.
- Reliability Reviewer: no live-safety blocker in the current process
  hardening; no-go on pushing any unseen broad cleanup that could weaken
  operator context or live-safety facts.
- Repo Auditor: no-go until the token-shaped test fixture was fixed and the
  new maintenance references were wired into first-read docs; after those fixes,
  go on commit/push with `status=warn`.

Decision: do not compress `PROJECT_STATE.md`, `SESSION_HANDOFF.md`, or LPFS
`PROJECT_STATE.md` in this patch. Keep the warnings visible and handle archival
as a separate scoped maintenance change.

## Scope Audit

No live operation was performed. The diff is limited to docs/process files, one
local repo-process audit script, and focused tests for that script. No strategy
logic, risk sizing, SL/TP behavior, broker execution, MT5 behavior, configs,
scheduler, watchdog, VPS/runtime state, production journals, broker artifacts,
generated dashboards, or ignored evidence packets are included.
