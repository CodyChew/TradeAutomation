# LP Force Strike Experiment V1

This experiment is the first systematic trade-model study for the LP + raw
Force Strike signal. It is Python-first and uses MT5 candle data from
`shared/market_data_lab`.

## Command

Run the configured baseline:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_experiment.py --config configs\strategies\lp_force_strike_experiment_v1.json
```

For a quick smoke run:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_experiment.py --config configs\strategies\lp_force_strike_experiment_v1.json --symbols AUDCAD --timeframes W1
```

Reports are written under `reports/strategies/lp_force_strike_experiment_v1/`
with a timestamped run folder.

## Trade Models

Entry models:

- `next_open`: enter at the next candle open after the FS signal candle.
- `signal_midpoint_pullback`: enter only if price returns to the signal candle
  midpoint within the configured wait window. This approximates the first
  "top half" bullish or "bottom half" bearish execution filter.

Stop models:

- `fs_structure`: stop below the full FS structure for longs, or above the full
  FS structure for shorts.
- `fs_structure_max_atr`: same structure stop, but skip the trade when the risk
  distance is wider than the configured ATR multiple.

Targets are tested as fixed R multiples from the configured list.

## Current Baseline Scope

The baseline config runs M30, H4, D1, and W1 across the FOREX major/cross-pair
dataset. It excludes symbols with known long historical gaps from the first
clean-data baseline:

- `GBPAUD`
- `GBPNZD`
- `NZDCAD`
- `NZDCHF`

Run a separate sensitivity pass with those symbols included before deciding
whether the gaps matter.

## Assumptions

- Every signal/candidate pair is simulated independently.
- Overlapping trades are allowed in this experiment.
- Same-bar stop/target ambiguity is handled by the shared backtest engine using
  conservative stop-first behavior.
- Costs use candle spread when available and the symbol point from MT5
  manifests.
- The latest incomplete live candle is dropped before backtesting.

This experiment compares trade-structuring heuristics. It is not yet a final
strategy, portfolio model, or EA execution rule set.

## Latest Local Baseline

The latest completed local run is:

`reports/strategies/lp_force_strike_experiment_v1/20260428_144145`

High-level totals:

- datasets: 96
- failed datasets: 0
- signals: 57,340
- simulated candidate trades: 864,520
- skipped signal/candidate combinations: 282,280

First-pass observation:

- M30 is negative across the tested candidates.
- H4, D1, and W1 favor `signal_midpoint_pullback` entries.
- The strongest tested candidates are generally 1R exits with the FS structure
  stop, optionally filtered by max 1 ATR risk.

Do not treat this as a finished strategy conclusion. Next passes should slice by
symbol, side, session, spread, signal quality, and market regime before deciding
what to keep.
