# LPFS Candle Provenance Guardrail Review

Date: 2026-07-04  
Status: implemented for review  
Materiality: research data, reporting evidence, workflow/process

## Summary

A strategy-diagnostics refresh used workstation-local MT5 candle datasets for
FTMO/IC lane attribution. The live lifecycle and broker facts were still read
from the intended lane evidence paths, but the candle-derived RSI, MACD, EMA,
ATR, volume, and candle-structure tags were not proven lane-authoritative.

This is a data-integrity failure in strategy research workflow. It is not a
broker mutation and did not change live strategy behavior, VPS tasks, runtime
state, journals, orders, positions, configs, sizing, SL/TP, or market recovery.

## Team Review

Main Orchestrator:

- Finding: The original workflow incorrectly treated the local workstation
  candle root as acceptable lane context after live evidence was collected from
  FTMO/IC.
- Required correction: add code guardrails, tests, evidence classification,
  and process documentation.

LPFS Strategy Improvement Agent:

- Finding: Candle-derived factor attribution is useful only when the market
  context is traceable to the lane feed or to an explicitly labeled reference
  dataset.
- Classification: old candle factors from the affected packets are
  quarantined; live lifecycle facts and broker-result rows remain separately
  usable according to their packet provenance.
- Required correction: future strategy candidates must not rely on unverified
  workstation candle enrichment.

Independent Issue Verifier:

- Finding: The issue is confirmed and occurred in generated research outputs.
  It is not live-execution exposed.
- Evidence classification: `candle_*` fields and candle-factor conclusions in
  the pre-guardrail diagnostics are questionable/quarantined; non-candle
  lifecycle fields are conditionally reliable when traceable to their source
  packet.
- Required correction: no default local candle roots; explicit `LANE=path`;
  provenance validation; downstream factor-attribution refusal when unsafe.

Documentation And Workflow Agent:

- Finding: The repo needed a tracked evidence-catalog entry and decision-log
  record so future agents do not consume quarantined candle factors.
- Required correction: document the source policy and update the change gate.

Repo Auditor:

- Finding: The vulnerable surface was the diagnostics/factor-attribution
  tooling, not live executor logic.
- Required correction: tests must prove cross-lane broker metadata is rejected
  and candle factors are stripped downstream when provenance is not safe.

Reliability Reviewer:

- Finding: The patch must not touch broker-send behavior, strategy rules,
  live configs, scheduler/watchdog behavior, runtime state, production
  journals, or evidence packets.
- Deployment boundary: no live deployment is needed for this offline/reporting
  guardrail.

## What Changed

- `scripts/build_lpfs_trade_diagnostics.py`
  - Removed implicit default local candle roots.
  - Requires `--candle-root LANE=path`.
  - Requires matching `--candle-source-provenance LANE=...`.
  - Blocks `local_unverified` sources from candle enrichment.
  - Validates `vps_lane_broker_feed` manifests against expected lane broker
    metadata.
  - Records candle source provenance, validation status, validation error, and
    safe-for-strategy-analysis flags in rows and manifests.

- `scripts/build_lpfs_factor_attribution.py`
  - Drops candle-derived factor dimensions unless the source diagnostics
    manifest proves safe candle-source provenance.
  - Emits `candle_source_provenance_unverified` as a data-validity flag when
    candle dimensions are stripped.

- Tests
  - Missing explicit provenance fails.
  - Unverified candle sources are recorded but blocked.
  - FTMO-labeled candle roots with IC broker metadata are blocked.
  - Factor attribution strips unsafe candle dimensions and keeps safe ones.

- Docs/process
  - `AGENTS.md`, `docs/change_gate.md`, diagnostic logging docs, workflow docs,
    evidence catalog, and decision log now document the guardrail.

## Data Classification

Quarantined for strategy conclusions:

- Candle-derived fields and conclusions from:
  - `reports/live_ops/lpfs_trade_diagnostics/20260627_121200`
  - `reports/live_ops/lpfs_trade_diagnostics/20260704_082040`
  - `reports/live_ops/lpfs_strategy_diagnostics_refresh/20260704_195931`

Conditionally usable:

- Live weekly/broker/lifecycle facts from their own packets when those packets
  are complete, eligible, and traceable to the correct FTMO/IC lane evidence.
- Non-candle cohort groupings from the affected diagnostics when they do not
  depend on `candle_*` enrichment.

Not repaired by relabeling:

- Existing local candle datasets under ignored `data/raw/...` cannot be made
  lane-authoritative by renaming or relabeling. Correctness requires
  recollection from a validated lane source or explicit reference dataset.

## Guardrail Rules

- Live-lane candle attribution must use an explicit lane-authoritative source,
  such as `vps_lane_broker_feed`, with broker/account/server metadata proving
  the lane.
- Workstation-local MT5 candle data is `local_unverified` unless separately
  proven by manifest-backed lane metadata.
- Missing, unlabeled, cross-lane, or unverified candle sources are `DATA_GAP`
  for indicator/structure/momentum/volume attribution.
- Strategy changes must not use quarantined candle factors.

## Non-Actions

- No VPS access.
- No MT5 access.
- No broker mutation.
- No live runner, task, watchdog, kill-switch, or scheduler change.
- No runtime-state edit.
- No production journal edit.
- No live config change.
- No strategy, risk, sizing, SL/TP, broker-send, or recovery change.
- No historical journal or evidence-packet rewrite.

## Verification

Required before publication:

```powershell
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_diagnostic_logging strategies.lp_force_strike_strategy_lab.tests.test_factor_attribution
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages
.\venv\Scripts\python scripts\audit_repo_process.py
.\venv\Scripts\python -m unittest discover -s strategies\lp_force_strike_strategy_lab\tests
.\venv\Scripts\python scripts\run_core_coverage.py
git diff --check
```

Scope audit must confirm the patch is limited to offline diagnostics,
factor-attribution safeguards, tests, and documentation/process updates.

