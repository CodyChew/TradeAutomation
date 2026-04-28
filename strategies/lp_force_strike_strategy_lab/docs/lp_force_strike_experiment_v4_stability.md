# LP Force Strike Experiment V4 Stability

This experiment checks whether the weak symbol/timeframe pockets found in V3
should become a strategy filter.

It does not rerun the candle simulation. It reuses the completed V3 trade file,
splits trades chronologically, learns allowed symbol/timeframe pairs from the
training period only, and evaluates those filters on the later test period.

## Command

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_stability_experiment.py --config configs\strategies\lp_force_strike_experiment_v4_stability.json --docs-output docs\v4.html
```

## Scope

- Input run:
  `reports/strategies/lp_force_strike_experiment_v3_entry_exit/20260428_163456`
- Split time: `2023-01-01T00:00:00Z`
- Candidate family: current best V3 family only:
  - `0.5` signal-candle pullback
  - `1R` single target
  - structure stop plus `0.75`, `1.0`, and `1.25` ATR stop-width filters
- Filters tested:
  - no symbol/timeframe filter;
  - training `PF >= 1`, `Avg R >= 0`, minimum 5/15/30 trades;
  - training `PF >= 1.05`, `Avg R >= 0`, minimum 15 trades;
  - training `PF >= 1`, `Avg R >= 0.05`, minimum 15 trades.

## Latest Result

Run folder:

`reports/strategies/lp_force_strike_experiment_v4_stability/20260428_182026`

High-level totals:

- candidates: 4
- filters: 6
- filter result rows: 72
- allowed pair rows: 884

Best test-period rows:

| Candidate | Filter | Pairs | Test Trades | Test Avg R | Test PF |
|---|---|---:|---:|---:|---:|
| `signal_zone_0p5_pullback__fs_structure_max_1p25atr__1r` | `baseline_all_pairs` | 72 | 2,132 | 0.142R | 1.332 |
| `signal_zone_0p5_pullback__fs_structure_max_1atr__1r` | `baseline_all_pairs` | 72 | 1,975 | 0.141R | 1.330 |
| `signal_zone_0p5_pullback__fs_structure__1r` | `baseline_all_pairs` | 72 | 2,247 | 0.135R | 1.314 |

The learned stability filters improved the training-period numbers but reduced
test-period performance versus the unfiltered baseline.

## Read

- Do not add a symbol/timeframe stability filter yet.
- The weak V3 pockets are real, but this simple train/test filter did not
  improve out-of-sample performance.
- The current best research candidate remains the `0.5` zone, `1R`
  single-target family.
- Among the V4 test rows, the `1.25 ATR` and `1.0 ATR` max-risk variants were
  the strongest.

## Next Decision

The next experiment should avoid symbol/timeframe filtering and instead test
one of these controlled ideas:

- split H4, D1, and W1 into separate model choices;
- add a market-condition filter that is known at signal time;
- test realistic execution assumptions such as slippage or commission;
- validate on a separate symbol group before adding live execution work.
