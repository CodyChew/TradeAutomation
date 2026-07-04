# LPFS Research Data Provenance Ownership Review

Date: 2026-07-04  
Status: implemented for review  
Materiality: docs/process, strategy-analysis evidence interpretation

## Decision

This is not a team redesign. It is a workflow tightening.

The existing role model is sufficient if research-data provenance is treated as
a required pre-analysis checkpoint with named ownership:

- Strategy Improvement Agent owns running the provenance preflight for each
  strategy-analysis run.
- Documentation and Workflow Agent owns the standing rules and source maps.
- Independent Issue Verifier verifies provenance failures, repair claims, and
  production-impact claims.
- Repo Auditor periodically checks that packets, builders, and docs expose
  enough provenance metadata.
- Reliability Reviewer remains responsible for live-safety and deployment
  boundaries when research evidence supports a live-capable change.

No new standing role is added. If this becomes too much for the current roles,
the next escalation should be an explicit Data Engineer / Data Provenance Owner
role proposal with scope and verification duties.

## Why This Is Needed

The candle-provenance incident showed a responsibility gap:

- broker/lifecycle evidence was not separated strongly enough from
  market-context enrichment;
- local workstation candle data could be used in FTMO/IC attribution unless a
  human or agent remembered the boundary;
- derived strategy conclusions could inherit unsafe candle context.

The code guardrail now blocks unsafe candle enrichment, but the workflow also
needs a standing checkpoint so future analysis does not repeat the same pattern
with another data family.

## Team Responsibility Review

Main Orchestrator:

- Classifies strategy-analysis work as material when it changes evidence
  interpretation, source provenance, generated reports, or workflow rules.
- Routes provenance issues to the Strategy Improvement Agent, Independent Issue
  Verifier, Documentation and Workflow Agent, and Repo Auditor.
- Does not approve its own strategy evidence or production safety claims.

LPFS Strategy Improvement Agent:

- Owns the research question and the evidence chain.
- Runs the provenance preflight before diagnostics, factor attribution,
  live-vs-backtest divergence, candidate matrices, or indicator-tagged
  conclusions.
- Stops with `DATA_GAP` when required source truth is missing, stale,
  cross-lane, unverified, or quarantined.
- Must not recommend a strategy change from evidence that failed provenance.

Documentation and Workflow Agent:

- Keeps `AGENTS.md`, workflow docs, decision log, evidence catalog, and review
  artifacts aligned with the actual source-of-truth rules.
- Documents which data is broker/lifecycle truth, market-context enrichment, or
  derived strategy conclusion.
- Records quarantined packet interpretation so future agents do not consume it.

Independent Issue Verifier:

- Verifies whether a claimed provenance issue is real, occurred, or fixed.
- Separates live-execution impact from strategy-analysis impact.
- Classifies affected data as reliable, conditionally reliable, questionable,
  quarantined, or needing correction.

Repo Auditor:

- Checks for hidden source-of-truth drift, missing metadata, stale current
  claims, and builders that can output evidence without enough source
  provenance.
- Does not approve live deployment or strategy changes.

Reliability Reviewer:

- Reviews live-safety, deployment, broker, status, or runtime changes when
  strategy evidence is used to support live-capable work.
- Confirms broker-send, strategy/risk/sizing, config, scheduler, runtime-state,
  journal, and VPS boundaries are preserved.

Human Operator:

- Approves live operations, deployment, broker actions, new automations, and
  strategy/risk changes.
- Does not need to manually police every provenance field; the workflow and
  tests should surface `DATA_GAP` when provenance is not safe.

## Required Preflight

Before any strategy-analysis run that can influence candidates or conclusions,
classify every input as one of:

- broker/lifecycle truth;
- market-context enrichment;
- derived strategy conclusion.

Then verify, where applicable:

- source path or packet path;
- lane label;
- manifest/hash;
- account/server/feed provenance;
- `analysis_eligible` and `coverage_status`;
- `safe_for_strategy_analysis`;
- whether the packet is current, historical, superseded, partial, or
  quarantined;
- which downstream conclusions may use the input.

Stop as `DATA_GAP` when required input provenance is missing, stale,
ambiguous, unlabeled, cross-lane, unverified, or quarantined unless that input
family is explicitly excluded from the analysis.

## Objections And Resolution

Objection: adding a new data-provenance role may be overkill.

Resolution: do not add a new standing role now. Assign the duty to existing
roles and add a future escalation path only if the current role set cannot
maintain it.

Objection: this could slow down normal weekly reviews.

Resolution: the weekly review only needs to check the evidence fields it uses.
Full research provenance preflight is required for diagnostics/factor
attribution/candidate research, not for every read-only status summary.

Objection: docs-only changes do not prove correctness.

Resolution: correctness is enforced by the candle-provenance guardrail tests
and factor-attribution refusal logic. This docs/process patch makes the
responsibility durable for future data families and future agents.

## Non-Actions

- No VPS access.
- No MT5 access.
- No broker mutation.
- No live runner, task, watchdog, kill-switch, scheduler, or config change.
- No runtime-state edit.
- No production journal edit.
- No strategy, risk, sizing, SL/TP, broker-send, recovery, or market-data
  collector behavior change.
- No generated dashboard or evidence packet rewrite.

## Verification

Docs/process-only verification:

```powershell
.\venv\Scripts\python scripts\audit_repo_process.py
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages
git diff --check
```

Scope audit must confirm the diff is limited to role/workflow/process docs and
does not include runtime code, strategy logic, risk sizing, SL/TP behavior,
broker execution, configs, scheduler, watchdog, VPS/runtime state, journals,
broker artifacts, or generated artifacts.

