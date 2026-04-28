# LP Force Strike Experiment V2 Focus

This experiment narrows the first baseline to the part that behaved best:
midpoint-pullback entries on H4, D1, and W1.

## Command

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_experiment.py --config configs\strategies\lp_force_strike_experiment_v2_focus.json
```

Build the dashboard for the completed run:

```powershell
.\venv\Scripts\python scripts\build_lp_force_strike_dashboard.py --run-dir reports\strategies\lp_force_strike_experiment_v2_focus\20260428_161441
```

The GitHub Pages snapshot is generated from this run into `docs/index.html`.

## Scope

- Symbols: clean FOREX major/cross subset from V1.
- Excluded known-gap symbols: `GBPAUD`, `GBPNZD`, `NZDCAD`, `NZDCHF`.
- Timeframes: `H4`, `D1`, `W1`.
- Entry: `signal_midpoint_pullback`.
- Stops:
  - full FS structure;
  - full FS structure with max risk filters at `0.5`, `0.75`, `1.0`, and
    `1.25` ATR.
- Targets: `1R`, `1.25R`, `1.5R`, `1.7R`, `2R`.

## Latest Result

Run folder:

`reports/strategies/lp_force_strike_experiment_v2_focus/20260428_161441`

High-level totals:

- datasets: 72
- failed datasets: 0
- signals: 8,203
- simulated candidate trades: 128,685
- skipped signal/candidate combinations: 76,390

Top robust candidates across H4, D1, and W1:

| Candidate | Avg Focus R | Worst Focus R | Notes |
|---|---:|---:|---|
| `signal_midpoint_pullback__fs_structure_max_1atr__1r` | 0.191R | 0.080R | Best average focus R. |
| `signal_midpoint_pullback__fs_structure_max_1p25atr__1r` | 0.190R | 0.083R | Very close, slightly more trades. |
| `signal_midpoint_pullback__fs_structure__1r` | 0.181R | 0.084R | No ATR filter, most trades. |

First read:

- 1R remains the strongest target family.
- The 1.0 ATR and 1.25 ATR risk filters are both worth keeping.
- 0.75 ATR is cleaner but may remove too many otherwise good H4 trades.
- H4 is the weakest focused timeframe but remains positive for the top models.

## Next Decision

Before adding live execution or a TradingView combined strategy, inspect:

- symbol stability;
- long vs short stability;
- whether weak symbols should be excluded;
- whether H4 needs a separate filter from D1/W1;
- whether 1R should be fixed or paired with partial exits/runners.

The next experiment should not add SMA, trend, or session filters until this
symbol/side stability check is complete.
