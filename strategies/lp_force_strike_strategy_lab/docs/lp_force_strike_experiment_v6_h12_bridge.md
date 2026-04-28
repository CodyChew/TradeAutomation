# LP Force Strike Experiment V6 H12 Bridge

This experiment checks whether native MT5 `H12` is a useful bridge between
`H8` and `D1` for the current best V3/V5 trade model.

## Commands

Pull native MT5 H12 candles:

```powershell
.\venv\Scripts\python scripts\pull_mt5_dataset.py --config configs\datasets\forex_major_crosses_10y_h12.json --output reports\datasets\forex_major_crosses_10y_h12_pull.json
```

Check coverage and quality:

```powershell
.\venv\Scripts\python scripts\report_dataset_coverage.py --config configs\datasets\forex_major_crosses_10y_h12.json --output reports\datasets\forex_major_crosses_10y_h12_coverage.json
.\venv\Scripts\python scripts\report_data_quality.py --config configs\datasets\forex_major_crosses_10y_h12.json --output-dir reports\datasets\data_quality_h12
```

Run the focused H12 bridge test:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_experiment.py --config configs\strategies\lp_force_strike_experiment_v6_h12_bridge.json
```

Build the dashboard:

```powershell
.\venv\Scripts\python scripts\build_lp_force_strike_dashboard.py --run-dir reports\strategies\lp_force_strike_experiment_v6_h12_bridge\20260428_191017 --output docs\v6.html
```

The GitHub Pages snapshot is `docs/v6.html`, linked from `docs/index.html`.

## Scope

- Symbols: clean FOREX major/cross subset.
- Excluded known-gap symbols: `GBPAUD`, `GBPNZD`, `NZDCAD`, `NZDCHF`.
- Timeframes: `H4`, `H8`, `H12`, `D1`, `W1`.
- LP lookback windows: `H4` uses 30 days, `H8` uses 60 days, `H12` uses 180
  days, `D1` uses 1 year, and `W1` uses 4 years.
- Entry: `0.5` signal-candle zone pullback.
- Stop: full Force Strike structure.
- Target: single `1R`.
- Costs: candle spread enabled; no added slippage or commission.
- Latest incomplete live bar is dropped.

## H12 Data Quality

Native MT5 `TIMEFRAME_H12` is available in the local FTMO terminal.

- H12 pull: 28/28 pairs succeeded.
- H12 coverage: 28/28 ready.
- H12 quality status: `OK_WITH_WARNINGS`.
- Warnings match the known dataset profile: long historical gaps in
  `GBPAUD`, `GBPNZD`, `NZDCAD`, and `NZDCHF`; large one-bar moves on several
  JPY/GBP symbols; incomplete live tail bars.

## Latest Result

Run folder:

`reports/strategies/lp_force_strike_experiment_v6_h12_bridge/20260428_191017`

High-level totals:

- datasets: 120
- failed datasets: 0
- signals: 13,815
- simulated trades: 11,185
- skipped setups: 2,630

Timeframe result for `signal_zone_0p5_pullback__fs_structure__1r`:

| Timeframe | Trades | Total R | Avg R | Win Rate | PF | Avg Bars |
|---|---:|---:|---:|---:|---:|---:|
| H4 | 5,642 | 475.9R | 0.084R | 56.9% | 1.185 | 2.0 |
| H8 | 2,674 | 265.6R | 0.099R | 56.7% | 1.221 | 2.2 |
| H12 | 1,844 | 290.1R | 0.157R | 59.2% | 1.375 | 2.0 |
| D1 | 855 | 177.5R | 0.208R | 61.2% | 1.527 | 2.0 |
| W1 | 170 | 42.9R | 0.252R | 62.9% | 1.678 | 1.9 |

## Read

H12 is a materially better bridge than H8 in this specific model.

- H12 produces fewer trades than H8, but still more than twice D1's trade
  count.
- H12 PF improves from H8's 1.221 to 1.375.
- H12 average R improves from H8's 0.099R to 0.157R.
- D1 is still cleaner at 1.527 PF and 0.208R average.

Current interpretation: H12 is worth keeping in the research set. It does not
replace D1, but it is the first intraday bridge timeframe that shows a clear
quality step above H4/H8.

## Next Research Use

Use V6 as the current timeframe comparison snapshot. Future experiments should
include `H12` when testing whether the strategy can keep enough trade frequency
without falling back to lower-quality H4/H8 behavior.
