# LPFS Lane Candle Snapshot Workflow Review

Date: 2026-07-04

## Change Gate

- State: `implemented`, pending final verification.
- Change type: research data / reporting evidence infrastructure.
- Lead owner: LPFS Strategy Improvement Agent.
- Reviewers/verifiers:
  - Independent Issue Verifier / Production Impact Assessor.
  - Documentation and Workflow Agent / Data Engineering reviewer.
  - Main thread integration and test owner.

## Problem

The diagnostics and factor-attribution builders now block workstation-local
MT5 candles for live-lane strategy conclusions, but the repo lacked a
maintained way to produce FTMO/IC lane-authoritative broker-feed candle roots.
Without a producer, the next offline RSI/MACD/EMA/volume/structure attribution
would either remain `DATA_GAP` or risk using unsafe local candles again.

## Role Feedback

Independent Issue Verifier:

- Confirmed the missing producer is a data-provenance repair, not live strategy
  execution.
- Classified VPS collection as production-adjacent read-only work.
- Required packet manifests, lane/server/company provenance, command sidecars,
  hashes, symbol/timeframe coverage, and strict STOP/DATA_GAP semantics.
- Flagged IC server expectation drift as a required validation point.

Documentation and Workflow / Data Engineering:

- Recommended a thin LPFS-specific wrapper around the generic
  `market_data_lab` puller rather than broadening the generic pull command.
- Recommended recent bounded lane snapshots by default, with longer pulls only
  when a research question needs them.
- Required docs that distinguish local unverified candles from
  `vps_lane_broker_feed` snapshots.
- Recommended documenting manifest sensitivity and strict lane validation.

## Objections And Resolutions

- Objection: a full 10-year VPS pull is too heavy as a default research step.
  Resolution: the collector defaults to `--history-years 1`; larger windows
  require explicit arguments.
- Objection: the generic puller can call `symbol_select`, which mutates
  terminal symbol visibility.
  Resolution: added `allow_symbol_select` to `market_data_lab`; existing
  generic defaults stay `true`, but the lane collector writes
  `allow_symbol_select=false`.
- Objection: IC expected server was inconsistent across old docs and current
  evidence.
  Resolution: collector and diagnostics guardrails use the current preserved
  live-status evidence server `ICMarketsSC-MT5-2` with Raw Trading metadata.

## Final Structure

- New collector: `scripts/collect_lpfs_lane_candle_snapshots.py`.
- Output root: ignored `reports/live_ops/lpfs_lane_candle_snapshots/<timestamp>`.
- Per-lane artifacts:
  - `request.json`;
  - `remote_collect.ps1`;
  - command/stdout/stderr/exit-code sidecars;
  - fetched `snapshot.zip`;
  - extracted `candles/<SYMBOL>/<TF>/...`;
  - `validation_summary.json`.
- Root artifacts:
  - `manifest.json`;
  - `manifest.sha256.txt`.

The collector marks a lane `PASS` only when every requested symbol/timeframe
manifest is present, source is `mt5`, row count is positive, data file exists,
and broker server/company metadata match the expected lane. Any missing,
cross-lane, malformed, partial, or tampered packet is `STOPPED` /
`safe_for_strategy_analysis=false`.

## IC Timeout Follow-Up

On the first full read-only run, FTMO produced a valid packet but IC timed out
before any manifest was returned. The failure exposed two collector robustness
gaps rather than a valid strategy-data result:

- the large remote PowerShell body was sent over SSH stdin, which could time
  out before the IC remote script body created its work directory;
- the first per-frame helper iteration assumed the VPS-side
  `DatasetConfig` accepted `allow_symbol_select`, while the deployed IC repo
  still had the older constructor.

Resolution:

- upload the reviewed PowerShell helper as a temporary script with `scp` and
  execute it with `powershell -File`, avoiding the long stdin transport path;
- run each requested symbol/timeframe through a bounded per-frame worker so a
  slow or failed MT5 history call is recorded in `pull_result.json` instead of
  hiding behind a lane-level timeout;
- use `copy_rates_from_pos` for recent `--history-years` snapshots, preserving
  the requested window in manifests while avoiding slow date-range history
  downloads where possible;
- keep `symbol_select` disabled and keep partial/failed lanes as `STOPPED`.
- rewrite packet-local metadata paths after the atomic move so manifests and
  validation summaries point at the final packet directory, not staging `.tmp`.

A small IC `EURUSD/H4` read-only probe passed after the fix. Full dual-lane
strategy evidence still requires a clean committed collector SHA and a fresh
full packet where both lanes pass validation.

## Safety Boundaries

This workflow does not approve or perform:

- live runner restart;
- scheduled-task change;
- kill-switch change;
- config change;
- runtime-state or production-journal mutation;
- broker order/position mutation;
- strategy/risk/sizing/SL/TP/broker-send change.

The collector uses SSH and MT5 read APIs when actually run against a VPS. That
run remains production-adjacent and should be reported as read-only evidence
collection, not a strategy or live-ops deployment.

## Verification Plan

Required before publish:

- `.\venv\Scripts\python -m unittest shared.market_data_lab.tests.test_datasets`
- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_lane_candle_snapshot_collector`
- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_diagnostic_logging`
- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_factor_attribution`
- `.\venv\Scripts\python scripts\audit_repo_process.py`
- `.\venv\Scripts\python scripts\run_core_coverage.py`
- `git diff --check`
- scope audit confirming no live runner, broker, strategy, risk, config,
  scheduler, VPS task, runtime-state, journal-artifact, or broker-artifact
  changes.

Optional after publish or explicit operator approval:

- Run the collector read-only against FTMO and IC.
- Use only `PASS` lane roots as `--candle-root LANE=...` with
  `--candle-source-provenance LANE=vps_lane_broker_feed`.
- If any lane fails, record `DATA_GAP` and do not substitute workstation-local
  MT5 candles.
