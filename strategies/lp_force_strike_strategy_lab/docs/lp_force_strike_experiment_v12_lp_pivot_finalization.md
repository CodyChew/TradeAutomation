# LP + Force Strike Experiment V12 - LP Pivot Finalization

Last updated: 2026-04-30.

## Question

Should the practical strategy keep LP3 as the default LP pivot strength, or
should LP4/LP5 replace it after V10/V11 portfolio and timeframe mechanics are
fixed?

## Fixed Mechanics

- Input trades: V9 trade log only; no signal rerun.
- Portfolio rule: max open risk `4R`.
- One open trade per symbol.
- Same-symbol same-time priority: `W1 > D1 > H12 > H8 > H4`.
- Primary timeframe set: all `H4/H8/H12/D1/W1`.
- Diagnostic timeframe set: no H4, using `H8/H12/D1/W1`.
- Guardrails: max closed-trade drawdown `<= 30R` and longest underwater
  `<= 180D`.

## Run

- Config:
  `configs/strategies/lp_force_strike_experiment_v12_lp_pivot_finalization.json`
- Report:
  `reports/strategies/lp_force_strike_experiment_v12_lp_pivot_finalization/20260429_165713`
- Dashboard: `docs/v12.html`

## All-Timeframe Decision

| LP Pivot | Trades | Total R | PF | Max DD | Underwater | Pass |
|---:|---:|---:|---:|---:|---:|---|
| 3 | 10,037 | 1,100.9R | 1.248 | 26.7R | 162D | Yes |
| 4 | 7,793 | 1,004.3R | 1.293 | 34.4R | 271D | No |
| 5 | 6,431 | 888.4R | 1.322 | 24.0R | 229D | No |

LP4 and LP5 improve quality metrics, but they do not pass the all-timeframe
guardrails. LP4 fails both max drawdown and underwater. LP5 has acceptable max
drawdown but fails underwater.

## No-H4 Robustness Contrast

| LP Pivot | Trades | Total R | PF | Max DD | Underwater | Pass |
|---:|---:|---:|---:|---:|---:|---|
| 3 | 5,361 | 792.6R | 1.305 | 23.5R | 159D | Yes |
| 4 | 4,197 | 729.3R | 1.393 | 21.6R | 150D | Yes |
| 5 | 3,397 | 634.1R | 1.424 | 19.4R | 138D | Yes |

The no-H4 contrast makes LP4 and LP5 guardrail-viable and cleaner by quality,
but LP3 still has the highest Total R. The smoother LP4/LP5 variants are useful
as research references, not the current default.

## Decision

Keep LP3 as the practical LP pivot default.

Current baseline:

- LP3.
- All `H4/H8/H12/D1/W1`.
- Max open risk `4R`.
- One open trade per symbol.
- 0.5 signal-candle pullback.
- Full Force Strike structure stop.
- Single 1R target.
- Fixed 6-bar pullback wait.

Future work should now move away from LP pivot selection and toward execution
constraints, risk sizing, equity-curve behavior, or MT5 implementation
readiness.
