# LPFS Offline Factor Attribution Builder Review

Date: 2026-07-04 ICT

## Summary

Decision: approved for a narrow offline/reporting implementation.

This review covers adding a reusable local factor-attribution builder that
turns an existing `reports/live_ops/lpfs_trade_diagnostics/<timestamp>` packet
into lane-first and cross-lane factor matrices. The implementation is
research/reporting tooling only. It is not live approval, not deployment
approval, and not approval for any strategy, risk, sizing, SL/TP, recovery, or
broker-send change.

## Materiality

Material change type: research data, backtest, and reporting infrastructure.

Affected surfaces:

- new offline CLI under `scripts/`;
- focused tests under the LPFS test suite;
- this review artifact and a decision-log index entry.

No live operations, broker state, MT5 state, Task Scheduler state, runtime
state, production journals, configs, strategy logic, risk sizing, SL/TP,
scheduler, watchdog, recovery, or broker-send behavior are in scope.

## Role Provenance

- LPFS Strategy Improvement Agent: requested a maintained factor matrix so
  weak performance is converted into testable cohorts instead of ad hoc
  discussion.
- Independent Issue Verifier / Data Evidence Reviewer: approved with
  acceptance conditions. Required local diagnostics input, source-manifest hash
  validation, freshness caveats, excluded-row handling, one-lane versus
  cross-lane separation, recent-window and long-history context, and manifest
  non-actions.
- Documentation/Workflow + QA reviewer: approved a scoped offline/reporting
  implementation. Required this gate artifact, deterministic tests, explicit
  offline-only wording, output manifests, and no confusion with live or
  strategy-change approval.

## Required Input Contract

The builder must accept a local diagnostic packet only:

```text
reports/live_ops/lpfs_trade_diagnostics/<timestamp>/
```

Required files:

- `manifest.json`;
- `closed_trade_diagnostics.csv`;
- `backtest_diagnostics.csv`.

The source manifest must be checked against the local input file hashes before
analysis. Missing or tampered required inputs are a hard failure.

## Required Output Contract

Output packet:

```text
reports/live_ops/lpfs_factor_attribution/<timestamp>/
```

Required files:

- `factor_attribution_matrix.csv`;
- `cross_lane_factor_confluence.csv`;
- `summary.md`;
- `manifest.json`.

Outputs must state `scope=offline_read_only_factor_attribution`, preserve input
freshness and min/max timestamps, count excluded rows separately, include input
and output hashes, and record explicit non-actions.

## Stop Conditions

Stop before producing a clean report if:

- the source diagnostics manifest is missing or does not match required file
  hashes;
- required core columns are missing;
- no usable non-excluded live rows are available;
- no usable backtest rows are available;
- output would be written outside the requested output root;
- the implementation attempts SSH, MT5 import, runtime journal reads, config
  mutation, broker calls, or live operations.

Missing optional factor-enrichment columns are not treated as zero. They must
be reported as data-validity caveats.

## Tests Required

Focused tests must cover:

- deterministic CLI output from synthetic diagnostics;
- source-manifest hash mismatch failure;
- missing required core columns failure;
- missing optional factor fields reported as caveats;
- excluded rows counted but excluded from attribution math;
- both-lane weakness distinguished from one-lane divergence;
- separate all-history and 3/6/12-month backtest stats;
- output manifest with input fingerprints, row counts, data-validity flags,
  output hashes, scope, and non-actions.

## Final Gate Decision

Approved for implementation under the constraints above. Any future use of the
factor matrix to justify a live strategy change must pass a separate strategy
change gate with FTMO/IC evidence, recent-window support, long-history
guardrails, sample-size and removal-breadth checks, and explicit operator
approval.
