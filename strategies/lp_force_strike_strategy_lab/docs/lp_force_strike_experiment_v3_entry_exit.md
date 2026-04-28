# LP Force Strike Experiment V3 Entry/Exit

This experiment keeps the V2 scope but tests trade construction variants:
signal-candle entry zones, ATR risk-width filters, and MT5-portable partial
exits.

## Command

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_experiment.py --config configs\strategies\lp_force_strike_experiment_v3_entry_exit.json
```

Build the dashboard for the completed run:

```powershell
.\venv\Scripts\python scripts\build_lp_force_strike_dashboard.py --run-dir reports\strategies\lp_force_strike_experiment_v3_entry_exit\20260428_163456 --output docs\v3.html
```

The GitHub Pages snapshot is `docs/v3.html`, linked from `docs/index.html`.

## Scope

- Symbols: clean FOREX major/cross subset from V1 and V2.
- Excluded known-gap symbols: `GBPAUD`, `GBPNZD`, `NZDCAD`, `NZDCHF`.
- Timeframes: `H4`, `D1`, `W1`.
- Entry model: `signal_zone_pullback`.
- Entry zones: `0.5`, `0.6`, `0.7` of the signal candle range.
- Stops:
  - full FS structure;
  - full FS structure with max risk filters at `0.75`, `1.0`, and `1.25` ATR.
- Exit models:
  - single target;
  - 50% at `1R`, 50% runner to the final target.
- Final targets: `1R`, `1.25R`, `1.5R`, `1.7R`, `2R`.

## Latest Result

Run folder:

`reports/strategies/lp_force_strike_experiment_v3_entry_exit/20260428_163456`

High-level totals:

- datasets: 72
- failed datasets: 0
- signals: 8,203
- simulated candidate trades: 619,092
- skipped signal/candidate combinations: 266,832

Top overall candidates:

| Candidate | Trades | Avg R | PF | Notes |
|---|---:|---:|---:|---|
| `signal_zone_0p5_pullback__fs_structure__1r` | 6,667 | 0.104R | 1.235 | Best overall average R. |
| `signal_zone_0p5_pullback__fs_structure_max_1p25atr__1r` | 6,315 | 0.104R | 1.234 | Very close, slightly fewer trades. |
| `signal_zone_0p5_pullback__fs_structure_max_1atr__1r` | 5,870 | 0.102R | 1.229 | Strong ATR-filtered candidate. |

Top candidate by timeframe:

| Timeframe | Candidate | Avg R | PF |
|---|---|---:|---:|
| H4 | `signal_zone_0p5_pullback__fs_structure__1r` | 0.084R | 1.185 |
| D1 | `signal_zone_0p5_pullback__fs_structure_max_1atr__1r` | 0.212R | 1.540 |
| W1 | `signal_zone_0p5_pullback__fs_structure_max_1atr__1r` | 0.283R | 1.791 |

## Read

- The `0.5` entry zone remains the strongest entry family.
- The `0.6` and `0.7` entry zones degrade materially, especially on H4.
- Single-target `1R` remains the strongest individual candidate family.
- Partial exits improve broad group averages, but did not beat the best
  individual `1R` single-target candidates in this run.
- `1.0` ATR and `1.25` ATR filters remain worth keeping. W1 especially favors
  the `1.0` ATR filter, while H4 still prefers the unfiltered structure stop in
  the top candidate.

## MT5 Portability

The V3 mechanics are implementable in MT5:

- Entry zones become pending limit orders calculated from the signal candle OHLC.
- ATR filters are checked before placing the order.
- Partial exits can be implemented with two child positions or one position
  with a partial close at `1R` and a runner target.

This is still a research simulation. It does not yet include portfolio-level
position limits, FTMO risk rules, session filters, or live order management.

## Next Decision

Use V3 as the current reference for trade construction. The next useful pass is
to inspect symbol and side stability for the `0.5` zone family, then test a
smaller V4 matrix instead of adding many new filters at once.
