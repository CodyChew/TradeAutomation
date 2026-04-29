# LP + Force Strike Experiment V11 - Practical Timeframe Mix

Last updated: 2026-04-29.

## Question

Should the current V10 practical portfolio baseline keep trading all
`H4/H8/H12/D1/W1`, or should weaker lower-timeframe exposure be removed to
improve drawdown and underwater periods?

## Fixed Mechanics

- Input trades: V9 trade log only; no signal rerun.
- Primary row: LP pivot strength `3`.
- Portfolio rule: max open risk `4R`.
- One open trade per symbol.
- Same-symbol same-time priority: `W1 > D1 > H12 > H8 > H4`.
- Guardrails: max closed-trade drawdown `<= 30R` and longest underwater
  `<= 180D`.

## Run

- Config:
  `configs/strategies/lp_force_strike_experiment_v11_timeframe_mix.json`
- Report:
  `reports/strategies/lp_force_strike_experiment_v11_timeframe_mix/20260429_144259`
- Dashboard: `docs/v11.html`

## Main LP3 Results

| Timeframe Set | Trades | Total R | Max DD | Underwater | Pass |
|---|---:|---:|---:|---:|---|
| All H4/H8/H12/D1/W1 | 10,037 | 1,100.9R | 26.7R | 162D | Yes |
| Remove H4 | 5,361 | 792.6R | 23.5R | 159D | Yes |
| Remove H8 | 8,451 | 943.9R | 23.5R | 182D | No |
| Remove H4+H8 | 3,003 | 567.7R | 19.4R | 254D | No |
| H8+H12 | 4,789 | 655.0R | 25.3R | 172D | Yes |

## Interpretation

The all-timeframe LP3 cap 4R portfolio remains the practical baseline. It
passes both guardrails and has the highest Total R among passing main rows.

Removing H4 improves max drawdown by about `3.2R` and underwater by only about
`3D`, but gives up about `308R` of total return. That is not enough improvement
to replace the baseline.

Removing H8 improves drawdown, but misses the underwater guardrail by about
`2D` and gives up about `157R`. It is close enough to remain a diagnostic idea,
but not a replacement.

Removing both H4 and H8 is much smoother by drawdown, but the underwater period
gets worse and total return is roughly half the baseline. It is not the current
execution candidate.

## LP4/LP5 Diagnostics

| Diagnostic | Trades | Total R | Max DD | Underwater | Pass |
|---|---:|---:|---:|---:|---|
| LP4 all timeframes | 7,793 | 1,004.3R | 34.4R | 271D | No |
| LP4 remove H4 | 4,197 | 729.3R | 21.6R | 150D | Yes |
| LP5 all timeframes | 6,431 | 888.4R | 24.0R | 229D | No |
| LP5 remove H4 | 3,397 | 634.1R | 19.4R | 138D | Yes |

The no-H4 diagnostic set makes LP4 and LP5 viable under the V11 guardrails, but
they still produce less Total R than LP3 all timeframes. V12 should compare
LP3/LP4/LP5 using all timeframes and no-H4 as the main robustness contrast.

## Decision

Keep all `H4/H8/H12/D1/W1` timeframes for the current practical baseline.
Proceed to V12 only after treating V11 as a timeframe decision, not as final
strategy selection.
