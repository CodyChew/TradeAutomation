# LP Force Strike Experiment V5 H8 Bridge

This experiment checks whether native MT5 `H8` behaves like a practical bridge
between `H4` and `D1` for the current best V3 trade model.

## Commands

Pull native MT5 H8 candles:

```powershell
.\venv\Scripts\python scripts\pull_mt5_dataset.py --config configs\datasets\forex_major_crosses_10y_h8.json --output reports\datasets\forex_major_crosses_10y_h8_pull.json
```

Check coverage and quality:

```powershell
.\venv\Scripts\python scripts\report_dataset_coverage.py --config configs\datasets\forex_major_crosses_10y_h8.json --output reports\datasets\forex_major_crosses_10y_h8_coverage.json
.\venv\Scripts\python scripts\report_data_quality.py --config configs\datasets\forex_major_crosses_10y_h8.json --output-dir reports\datasets\data_quality_h8
```

Run the focused H8 bridge test:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_experiment.py --config configs\strategies\lp_force_strike_experiment_v5_h8_bridge.json
```

Build the dashboard:

```powershell
.\venv\Scripts\python scripts\build_lp_force_strike_dashboard.py --run-dir reports\strategies\lp_force_strike_experiment_v5_h8_bridge\20260428_184554 --output docs\v5.html
```

The GitHub Pages snapshot is `docs/v5.html`, linked from `docs/index.html`.

## Scope

- Symbols: clean FOREX major/cross subset.
- Excluded known-gap symbols: `GBPAUD`, `GBPNZD`, `NZDCAD`, `NZDCHF`.
- Timeframes: `H4`, `H8`, `D1`, `W1`.
- Entry: `0.5` signal-candle zone pullback.
- Stop: full Force Strike structure.
- Target: single `1R`.
- Costs: candle spread enabled; no added slippage or commission.
- Latest incomplete live bar is dropped.

## H8 Data Quality

Native MT5 `TIMEFRAME_H8` is available in the local FTMO terminal.

- H8 pull: 28/28 pairs succeeded.
- H8 coverage: 28/28 ready.
- H8 quality status: `OK_WITH_WARNINGS`.
- Warnings match the known dataset profile: long historical gaps in
  `GBPAUD`, `GBPNZD`, `NZDCAD`, and `NZDCHF`; large one-bar moves on several
  JPY/GBP symbols; incomplete live tail bars.

## Latest Result

Run folder:

`reports/strategies/lp_force_strike_experiment_v5_h8_bridge/20260428_184554`

High-level totals:

- datasets: 96
- failed datasets: 0
- signals: 11,391
- simulated trades: 9,221
- skipped setups: 2,170

Timeframe result for `signal_zone_0p5_pullback__fs_structure__1r`:

| Timeframe | Trades | Total R | Avg R | Win Rate | PF | Avg Bars |
|---|---:|---:|---:|---:|---:|---:|
| H4 | 5,642 | 475.9R | 0.084R | 56.9% | 1.185 | 2.0 |
| H8 | 2,554 | 235.0R | 0.092R | 56.3% | 1.203 | 2.2 |
| D1 | 855 | 177.5R | 0.208R | 61.2% | 1.527 | 2.0 |
| W1 | 170 | 42.9R | 0.252R | 62.9% | 1.678 | 1.9 |

## Read

H8 is only a modest improvement over H4 in this specific model, not a clean
midpoint between H4 and D1.

- H8 reduces trade count by about 55% versus H4.
- H8 PF improves from 1.185 to 1.203.
- H8 average R improves from 0.084R to 0.092R.
- D1 remains a much larger quality step at 1.527 PF and 0.208R average.

The result does not invalidate H8, but it does not currently justify treating
H8 as a major sweet spot. It is worth keeping as a comparison timeframe, not as
the main research focus yet.

## Next Research Use

Use this V5 run when comparing timeframe quality. For strategy development,
continue treating D1 and W1 as the cleaner higher-timeframe evidence, while H8
can be included when testing whether execution frequency can be increased
without falling back to H4 behavior.
