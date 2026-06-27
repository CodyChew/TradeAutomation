# LPFS Strategy Improvement Workflow

Last updated: 2026-06-27 ICT.

This document is the operating workflow for the LPFS Strategy Improvement
Agent. It exists so strategy improvement is not ad hoc and so another Codex
session can continue without this chat.

This workflow does not authorize live strategy changes, risk changes, config
changes, broker actions, VPS actions, reconciliation, canary runs, runtime-state
edits, production-journal edits, or market-recovery enablement.

## Goal And Accountability

The goal is to improve LPFS over time using trustworthy FTMO and IC live
evidence, broker facts, diagnostics, and backtests.

The LPFS Strategy Improvement Agent is accountable for:

- asking whether LPFS is improving, degrading, or experiencing normal variance;
- checking whether collected evidence can answer that question;
- identifying missing data or brittle workflow gaps;
- turning repeated weak evidence into offline research candidates;
- rejecting unsupported hypotheses;
- documenting active candidates, rejected hypotheses, packet paths, hashes,
  next review criteria, and explicit non-actions.

The human operator is accountable for:

- approving or rejecting live operations;
- approving or rejecting strategy, risk, sizing, SL/TP, broker-send, config, or
  deployment changes;
- deciding whether optional automations should be created or changed;
- providing RDP/login access only when a separately approved operation needs it;
- reviewing formal strategy-change proposals before implementation.

## Evidence Producers

LPFS has three separate evidence layers.

1. Continuous production evidence:
   - produced by the FTMO and IC live runners all week;
   - includes lifecycle journals, heartbeat/status, broker order/position facts,
     active state, market snapshot telemetry, and diagnostics.
2. Scheduled review evidence:
   - produced by read-only weekly or optional midweek automation;
   - stored under ignored `reports/live_ops` packets with manifests or hashes;
   - never mutates live broker state or production journals.
3. Offline research evidence:
   - produced only after review evidence triggers a research question;
   - includes trade diagnostics, indicator tags, candidate matrices, live-vs-
     backtest attribution, and readiness closeouts;
   - stays ignored unless code, docs, schemas, or small sanitized summaries are
     separately reviewed for commit.

## Cadence

### Continuous

The live runners collect data continuously while markets and VPSes are healthy.
The strategy agent is not continuously awake; it works when triggered by a
heartbeat automation or by the human operator.

If the strategy agent notices a data or workflow gap during any triggered work,
it must record the gap and propose the smallest safe fix. It should not wait for
the human to rediscover the same gap unless the fix needs approval.

### Weekly Strategy Review

Default cadence: Saturday 08:00 Asia/Bangkok after the weekly trading window.

Purpose: trigger and triage.

The weekly review must:

- read the first-read docs and current workflow docs;
- collect or inspect read-only weekly/status evidence;
- use only rows where `analysis_eligible=true` and
  `coverage_status=complete`;
- report FTMO, IC, and combined strategy benchmark metrics;
- report account outcome metrics and R/PnL alignment caveats;
- check open/pending exposure and live health from read-only status;
- update active watch items and research candidates;
- decide one of the triage outcomes below;
- post a concise Telegram summary only when existing ignored credentials are
  available and only as informational output.

The weekly review is not a full strategy-iteration cycle by default. It decides
whether deeper research is justified.

### Midweek Strategy Watch

Recommended when there is an active research candidate or suspected data gap.
Suggested cadence: Tuesday and Thursday 08:00 Asia/Bangkok while the candidate
is active.

Purpose: avoid sleeping through useful market-open evidence.

The midweek watch should be read-only and short:

- live health and data-integrity status;
- new closed trades since the last weekly review;
- current pending/open exposure;
- candidate-cohort accumulation, especially current active candidates;
- skipped/rejected setup patterns and market-data degradation;
- whether a fresh offline diagnostic packet is now useful.

The midweek watch must not clear or set kill switches, change tasks, pull code,
run reconciliation, run canary, edit configs, mutate broker state, or change
strategy logic.

### Monthly Strategy Review

Recommended cadence: first Saturday after month close, after the normal weekly
review.

Purpose: compare live month outcomes against monthly benchmark distributions
and decide whether candidate research should escalate.

The monthly review should:

- compare live monthly FTMO and IC performance with accepted benchmark
  distributions;
- separate strategy R from broker PnL and policy epochs;
- identify repeated weak cohorts across the month;
- decide whether to start or continue a formal candidate research pass.

### Candidate Research Pass

Triggered by weekly, midweek, or monthly evidence. Not scheduled by default.

A candidate research pass should:

- build or inspect offline diagnostics and indicator tags;
- compare FTMO and IC together;
- test recent 3, 6, and 12 month windows first;
- use long-history backtests as robustness guardrails;
- measure removal breadth and sample size;
- record decision status: rejected, active research candidate, or proposal
  ready.

## Triage Outcomes

Every weekly or midweek review should end with exactly one primary outcome.

- `NO_ACTION`: evidence is complete and normal; keep collecting.
- `WATCH`: weak or interesting evidence exists but sample size or confluence is
  insufficient.
- `RESEARCH_TRIGGERED`: evidence warrants an offline diagnostic or backtest
  matrix.
- `DATA_GAP`: analysis is blocked by missing, stale, unsafe, or misleading
  evidence; propose logging/reporting/tooling before strategy changes.
- `SAFETY_ISSUE`: operational or broker-state ambiguity blocks strategy
  interpretation; route to live-safety review.
- `PROPOSAL_READY`: a small reversible candidate has enough live, recent-window,
  and long-history evidence to draft a formal strategy-change proposal.

## Candidate Register Rules

Active candidates must be documented in `docs/lpfs_strategy_iteration_context.md`
or a linked packet summary with:

- candidate name and rule shape;
- status: watch, active research candidate, rejected, or proposal ready;
- evidence packet paths and hashes;
- FTMO/IC confluence status;
- recent 3/6/12 month support;
- long-history guardrail result;
- sample size and removal breadth;
- account-outcome caveats;
- next review criteria;
- explicit non-actions.

Rejected hypotheses should remain recorded so future agents do not repeat them
without new evidence.

Current candidate as of 2026-06-27:

- active research candidate: H8 compressed risk,
  `timeframe=H8` and `risk_atr_bucket=lt_0p5`, especially the low-spread
  intersection;
- rejected simple filter: H8 low-spread-only;
- no live strategy change is approved.

## Data Gap Escalation

When the strategy agent cannot answer a strategy question, it must classify the
reason before recommending any change:

- missing live fields;
- incomplete weekly coverage;
- unavailable broker facts;
- insufficient FTMO/IC confluence;
- small sample size;
- account-outcome divergence rather than strategy-shape weakness;
- unreliable or stale generated output;
- missing backtest or recent-window comparison;
- unsafe collection path.

The next action should be the smallest safe fix:

- documentation clarification;
- ignored offline report packet;
- reporting script enhancement;
- status/heartbeat field addition;
- journal diagnostic field addition;
- backtest/replay fixture;
- candidate matrix;
- issue-verifier review.

Do not add noisy logging that cannot answer a defined strategy question.

## Role Routing

- Strategy Improvement Agent: accountable owner for the research workflow,
  questions, candidates, and strategy evidence.
- Documentation and Workflow Agent: keeps first-read docs, workflow docs,
  handoff, and source-of-truth routing current.
- Independent Issue Verifier: verifies suspected bugs, data-integrity issues,
  or production-impact claims before fixes are treated as true.
- Reliability Reviewer: reviews live-safety, deployment, broker, status, and
  robustness changes before live use.
- Repo Auditor: periodically looks for hidden process, evidence, test, and
  source-of-truth risks.
- Human operator: approves live changes, strategy changes, deployment, broker
  actions, and new recurring automations.

## Human Operator Timeline

Normal week:

1. Monday-Friday:
   - no action unless a heartbeat reports a safety/data issue or the operator
     wants an ad hoc question answered;
   - live runners collect evidence.
2. Optional Tuesday/Thursday 08:00 Bangkok:
   - midweek strategy watch if an active candidate exists;
   - human reviews only if the agent reports `DATA_GAP`, `SAFETY_ISSUE`, or a
     research action requiring approval.
3. Saturday 08:00 Bangkok:
   - weekly strategy review runs;
   - human reads the summary and only acts if it asks for approval or flags a
     blocker.
4. First Saturday after month close:
   - monthly strategy review compares live month with benchmark distributions.
5. When `RESEARCH_TRIGGERED`:
   - agent runs offline diagnostics/backtests in ignored reports;
   - human reviews the candidate outcome.
6. When `PROPOSAL_READY`:
   - agent drafts a formal strategy-change proposal;
   - human approves or rejects before implementation.
7. When implementation is approved:
   - change is reviewed, tested, committed, and deployed only through separate
     safety-controlled workflow.

## What Good Looks Like

At any point, a new agent should be able to answer from the repo:

- what the current objective is;
- whether live operations are healthy enough for strategy analysis;
- what candidates are active or rejected;
- what evidence packets support that status;
- what data gaps remain;
- what the next scheduled review will ask;
- what the human operator must approve before anything live changes.
