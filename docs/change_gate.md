# TradeAutomation Change Gate

Material changes must pass a role-routing gate before implementation. This
policy adapts the useful parts of DayTrading's explicit change-gate model to
TradeAutomation without weakening the existing LPFS live-operations rules.

If this file conflicts with a stricter instruction in `AGENTS.md`, a live
runbook, a deployment plan, or an operator approval boundary, use the stricter
rule.

## What DayTrading Does Better

DayTrading's model is cleaner in four ways:

1. It separates `proposed`, `role-reviewed`, `implemented`, and `verified`
   states.
2. It treats role outputs as visible artifacts, not implied labels.
3. It makes materiality explicit before implementation.
4. It names stop conditions that force the Main Orchestrator to pause instead
   of backfilling review after a change.

TradeAutomation should use those mechanics, but keep its existing LPFS-specific
roles, broker-truth hierarchy, live-safety boundaries, and FTMO-before-IC
deployment discipline.

## Change States

Material changes move through:

```text
proposed -> role-reviewed -> implemented -> verified
```

The Main Orchestrator may gather context in `proposed`. It must not implement a
material change until required role outputs exist, are explicitly waived with a
reason, or the change is classified as non-material.

Non-material changes are limited to typo fixes, formatting-only edits,
broken-link fixes, or wording that does not change behavior, policy, scope,
current-state claims, live-safety claims, strategy claims, evidence
interpretation, generated output, or role routing.

Docs-only process changes are still material when they alter workflow,
role-routing, review gates, deployment expectations, live-safety wording, or
evidence interpretation. They may be implemented by the Documentation and
Workflow Agent in the same chat only when the scope is clearly docs-only and no
stop condition is triggered.

## Review Artifact

Every material change needs a visible gate record before implementation. Use a
dated `docs/reviews/` artifact for local review, a PR body when the change is
reviewed through GitHub, or a deployment evidence packet for live operations.
Future material process, role-routing, or change-gate edits should not rely on
the changed policy file alone as the gate record. When a material change creates
a durable project decision, add a concise index entry to `docs/decision_log.md`
and link to the detailed review or packet instead of duplicating it.

For non-material typo, formatting, or broken-link cleanup, the final response
or commit message can be enough when it states why the change is non-material.

The record should include:

- change type and materiality decision;
- affected files or operational surfaces;
- Lead Owner, Reviewers, and Verifiers;
- required roles and actual role outputs used;
- provenance for each role output, distinguishing internal Codex role passes
  from separate agents, humans, tools, runtime packets, or external sources;
- explicit approvals, rejections, waivers, and unresolved objections;
- stop conditions checked;
- tests, static checks, packet checks, or documented no-test reason;
- final gate decision.

Checkbox-only review is not enough for live, broker, strategy, risk, evidence,
or generated-artifact changes. Each required role must provide a finding,
verification result, rejection, or linked artifact.

## Material-Change Matrix

When a change touches multiple rows, use the union of required reviewers,
verifiers, evidence, and stop conditions.

| Change type | Examples | Required reviewers and verifiers | Required evidence and verification |
| --- | --- | --- | --- |
| Live/deployment changes | Deployments, VPS pulls, task restarts, watchdog changes, kill-switch handling, runtime SHA changes, status packets used for deployment decisions | Reliability Reviewer; Independent Issue Verifier when an issue, fix, or production impact claim is involved; Documentation and Workflow Agent for runbook/handoff accuracy; explicit user approval | Kill-switch-first plan; FTMO proof before IC; fresh dual-lane status; repo/config/task/runner/heartbeat/MT5/order/position/mismatch/telemetry proof; evidence packet with commands, stdout, stderr, exit codes, manifest, hashes, and scope audit |
| Broker/MT5/order behavior | `order_check`, `order_send`, duplicate prevention, reconciliation, pending-order lifecycle, fills, close proof, magic/comment family, symbol specs, spread/slippage/session assumptions | Independent Issue Verifier before fix truth or production impact is accepted; Reliability Reviewer before deployability; LPFS Strategy Improvement Agent if strategy evidence or rule shape is affected; explicit user approval for live broker operations | Repository path trace; focused executor/reconciliation tests; MT5/broker fact packet when live exposure matters; no manual broker mutation unless separately approved; scope audit for strategy/risk/sizing/SL/TP/broker-send boundaries |
| Strategy/risk/sizing changes | Entry/exit filters, stop or target rules, risk buckets, exposure limits, account allocation, timeframe mix, market recovery, live heuristic promotion | LPFS Strategy Improvement Agent as Lead Owner; Independent Issue Verifier for live issue/data truth; Reliability Reviewer for live-safety deployment; Documentation and Workflow Agent for evidence sufficiency; explicit user approval | FTMO and IC confluence where comparable; recent 3/6/12 month support; 10-year backtest guardrail; sample-size and uncertainty statement; no production change without approved implementation and verification plan |
| Research data, backtest, and transaction-cost infrastructure | `shared/market_data_lab`, `shared/backtest_engine_lab`, dataset manifests/fingerprints/configs, candle aggregation, simulator behavior, replay behavior, spread/commission/swap/slippage/cost assumptions, transaction-cost reports | LPFS Strategy Improvement Agent when results support strategy conclusions; Documentation and Workflow Agent for evidence sufficiency and source-of-truth routing; Independent Issue Verifier when data validity, issue truth, broker comparability, or production impact is claimed; Reliability Reviewer when the output supports live deployment or live-safety decisions; Repo Auditor for shared infrastructure drift | Dataset fingerprint or data-quality gate as applicable; focused simulator/data tests; `scripts/run_core_coverage.py` when shared core behavior changes; report manifests and exact input configs; broker-fact citations for cost assumptions; explicit statement that generated research output is not live approval |
| Journal/report/dashboard evidence changes | Lifecycle journal fields, diagnostics payloads, heartbeat/status fields, weekly review logic, live ops reports, dashboard interpretation, evidence packet parsing | Documentation and Workflow Agent; Independent Issue Verifier when data classification, issue truth, or production impact is claimed; Reliability Reviewer when live status, deployment readiness, or broker safety interpretation changes; Repo Auditor for broader source-of-truth drift | Backward-compatible schema plan; safe shared-read or bounded-snapshot collection for live files; focused report/dashboard tests; adjacent interpretation field check; first-read drift audit when current-state claims change |
| Native MQL5 EA and Strategy Tester work | `mql5/lpfs_ea`, MetaEditor compile helpers, parity fixtures, Strategy Tester smoke runs, EA inputs, tester-only guards, EA dashboards/docs | LPFS Strategy Improvement Agent when strategy parity or rule behavior is involved; Independent Issue Verifier for parity, bug, or production-impact claims; Reliability Reviewer for any live attach, demo/live deployment, broker-order path, or live-safety boundary; Documentation and Workflow Agent for EA boundary docs; explicit user approval before any non-tester execution | Python remains canonical until separately approved; compile and static/parity tests as applicable; Strategy Tester smoke evidence; tester-only/live-disabled guard verification; no FTMO/IC live chart attach, VPS/runtime/config/journal/broker change, or EA live-route promotion without a separate approved plan |
| Docs/process changes | `AGENTS.md`, first-read docs, runbooks, workflow docs, repo-maintenance policy, decision log, role-routing rules, change-gate policy, handoff wording | Documentation and Workflow Agent as Lead Owner and workflow-audit owner; Repo Auditor for onboarding/source-of-truth checks; Reliability Reviewer if operator-facing live-safety instructions change; Independent Issue Verifier if issue truth or production impact is asserted | Repo-evidence-backed wording; no runtime/code/config/generated changes unless separately scoped; first-read drift audit for current-looking claims; `scripts/audit_repo_process.py` for onboarding/workflow changes; dashboard pages test when required by `AGENTS.md`; `git diff --check` |
| Generated artifact changes | Dashboard HTML, generated report pages, generated docs, static index pages, derived summaries | Documentation and Workflow Agent or relevant builder owner; Repo Auditor for generated-artifact hygiene; Reliability Reviewer when generated output affects live status/deployment interpretation; Independent Issue Verifier when issue truth/data classification changes | Update source builder before generated output; regenerate intentionally; verify adjacent fields such as eligibility, coverage, confidence, stale/error text, packet paths, and source-start metadata; run focused builder/dashboard tests |

## Stop Conditions

Pause before implementation when any of these are true:

- required role output is missing and not explicitly waived;
- role provenance is unclear or a review says a role was consulted without a
  transcript, artifact, tool result, or named source;
- user approval is required but missing;
- the active checkout, branch, worktree, or presence of `AGENTS.md` has not
  been confirmed;
- the requested scope could touch VPS, MT5, Task Scheduler, live runtime state,
  journals, broker orders, broker positions, or kill switches without explicit
  operational approval;
- live status is ambiguous: duplicate runner, stale heartbeat, MT5
  `ERROR/UNKNOWN`, unexplained broker exposure, active-position drift, nonzero
  state/broker mismatch, telemetry failure, market-data degradation that
  affects the decision, or recovery-mode drift;
- a strategy, risk, broker, or data claim lacks supporting evidence;
- a strategy/risk/sizing change lacks explicit approval, comparable FTMO/IC
  evidence where available, recent-window support, or acceptable long-backtest
  guardrails;
- a research data, backtest, or transaction-cost change lacks reproducible
  inputs, dataset/data-quality checks, simulator tests, or broker-fact support
  for cost assumptions;
- live-lane candle-derived strategy attribution uses workstation-local,
  unlabeled, unverified, or cross-lane candle data instead of an explicit
  lane-authoritative source with broker/account/server provenance checks;
- a journal/report/dashboard change would read active production journals
  unsafely, rewrite append-only evidence, count unresolved audit rows as closed
  trades, or treat bounded current-week evidence as historical consistency;
- a native MQL5 EA change weakens tester-only/live-disabled boundaries, skips
  parity or compile evidence where applicable, or could touch FTMO/IC live
  charts, VPS runtime, live configs, journals, broker orders, or positions
  without a separately approved plan;
- a generated artifact change edits output without the source builder or skips
  adjacent interpretation checks;
- tests, packet verification, or a documented no-test reason are missing;
- the diff includes unrelated strategy, risk, sizing, SL/TP, broker-send,
  config, scheduler, watchdog, runtime-state, journal, VPS-local, broker
  artifact, or generated-output changes.

## Role And Team Audit

- keep: Main Orchestrator, LPFS Strategy Improvement Agent, Reliability
  Reviewer, Independent Issue Verifier, Documentation and Workflow Agent, and
  Repo Auditor.
- clarify: Main Orchestrator coordinates and integrates; it does not approve
  its own material work, live deployment, issue truth, strategy changes, or
  production safety.
- clarify: Documentation and Workflow Agent is the TradeAutomation workflow
  audit owner for process, role-routing, provenance, first-read drift, and
  change-gate checks. It does not approve live deployment by itself.
- merge: Do not add DayTrading's separate Documentation Steward or Workflow
  Auditor as new standing roles. Their useful duties fit the existing
  Documentation and Workflow Agent, with Repo Auditor used for broader
  independent checks.
- pause: Do not create standing subagents, routine process overhead, or broad
  role ceremonies for non-material typo/link cleanup. Use the gate when a
  change is material.
- add: Add this change-gate policy as the canonical matrix and require a
  visible gate record for material work.
- escalate: Live/deployment, broker/MT5/order, strategy/risk/sizing, evidence
  integrity, generated dashboard interpretation, or ambiguous process changes
  escalate to the required roles and to the user when approval is required.

TradeAutomation does not need a separate explicit Workflow Auditor role right
now. Assign that responsibility to the existing Documentation and Workflow
Agent, and require Repo Auditor or Reliability Reviewer review when the scope
crosses onboarding, generated artifacts, live safety, deployment readiness, or
production-impact claims.

## Minimal Docs-Only Verification

For a scoped docs-only process update, verify at minimum:

```powershell
.\venv\Scripts\python scripts\audit_repo_process.py
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages
git diff --check
```

Then perform a scope audit confirming the diff does not include runtime code,
strategy logic, risk sizing, SL/TP behavior, broker execution, configs,
scheduler, watchdog, VPS/runtime state, journals, broker artifacts, or
generated artifacts.
