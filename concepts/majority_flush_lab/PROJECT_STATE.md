# Majority Flush Lab Project State

Last updated: 2026-05-04 local time after creating the initial concept lab.

## Purpose

Majority Flush Lab defines an LP-based displacement concept. It is not a
trading strategy by itself. The concept identifies steep upside or downside
movement legs that force one or more active LP levels in the leg path.

## Current State

- Canonical rules/spec: `docs/majority_flush_spec.md`
- Python strategy/backtest module: `src/majority_flush_lab/flush.py`
- TradingView visual indicator: `tradingview/majority_flush.pine`
- TradingView usage notes: `tradingview/README.md`
- Tests: `tests/`

Python is the source of truth for research and future strategy work. The Pine
script is for chart-side visual review and alerts only.

## Current Defaults

- LP pivot strength: `3`
- LP source: active LP levels from `concepts/lp_levels_lab`
- Downside force: wick low reaches or breaches active support LP
- Upside force: wick high reaches or breaches active resistance LP
- 50% rule: evaluated per forced LP from the flush origin to that LP
- Stagnation invalidation: two consecutive no-progress candles or two
  consecutive inside bars before an LP is forced
- Congestion filter: no-progress, inside, or counter-direction body bars count
  as congested; default maximum congested bar ratio is `0.35`
- Fixed max duration: none
- Execution candle logic: excluded

## Architecture Guidance

Future UR1/DR1 strategy labs should import this concept rather than copying the
flush rules. Execution confirmation, sizing, order state, and lifecycle logic
belong in strategy or live execution layers, not in this concept.

## Next Best Work

1. Use this concept to label Majority Flush examples across the same symbols
   and timeframes used by LPFS.
2. Build UR1/DR1 as a separate strategy lab that imports Majority Flush and
   decides execution confirmation.
3. Keep TradingView scripts visual-only and reconcile any differences against
   Python/MT5 candle data before treating them as research evidence.
