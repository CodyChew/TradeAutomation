# LP + Force Strike Experiment V16 Bid/Ask Execution Realism

V16 tests whether the V15 baseline survives broker-side bid/ask execution
mechanics, and whether Force Strike structure stops should include a
spread-based buffer.

## Run

- config:
  `../../configs/strategies/lp_force_strike_experiment_v16_execution_realism.json`
- latest run:
  `../../reports/strategies/lp_force_strike_experiment_v16_execution_realism/20260501_060205`
- dashboard:
  `../../docs/v16.html`

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_v16_execution_realism.py --config configs\strategies\lp_force_strike_experiment_v16_execution_realism.json --docs-output docs\v16.html
```

## Execution Model

- OHLC is treated as Bid.
- Ask OHLC is approximated as Bid OHLC plus each bar's stored
  `spread_points * point`.
- Long entry: Ask low must touch the buy-limit entry.
- Long SL/TP: Bid touches SL/TP.
- Short entry: Bid high must touch the sell-limit entry.
- Short SL/TP: Ask touches SL/TP.
- Same-bar TP/SL conflicts remain stop-first.

Stop-buffer variants widen the Force Strike structure stop by `0.0x`, `0.5x`,
`1.0x`, `1.5x`, and `2.0x` the signal-candle spread. The 1R target is
recalculated from the wider risk distance.

## Result

| Variant | Trades | Total R | Avg R | PF | Missed vs V15 |
|---|---:|---:|---:|---:|---:|
| V15 OHLC baseline | 13,012 | 1,512.3 | 0.116 | 1.265 | 0 |
| V16 bid/ask, no buffer | 12,917 | 1,535.2 | 0.119 | 1.270 | 95 |
| V16 bid/ask, 0.5x buffer | 12,917 | 1,547.2 | 0.120 | 1.272 | 95 |
| V16 bid/ask, 1.0x buffer | 12,917 | 1,559.1 | 0.121 | 1.275 | 95 |
| V16 bid/ask, 1.5x buffer | 12,917 | 1,587.1 | 0.123 | 1.280 | 95 |
| V16 bid/ask, 2.0x buffer | 12,917 | 1,545.1 | 0.120 | 1.272 | 95 |

No-buffer bid/ask realism is not a material regression. It slightly improves
total R and PF while missing less than 1% of baseline trades.

The `1.5x` buffer produced the strongest raw R, but it changed `722` exit
reasons and `493` win/loss signs versus the V15 baseline. That is a large
behavioral change, so it should not be patched into live execution from this
one study alone.

## Decision

Keep the current live stop placement unchanged: no spread buffer beyond the
Force Strike structure stop.

V16 gives confidence that bid/ask mechanics do not invalidate V15. Spread
buffers remain a promising follow-up research line, especially by timeframe and
symbol group, but they are not yet the live default.
