# LPFS First-Month Evidence Review - 2026-05-30

This review captures the first live-month evidence after the Saturday weekly
checkpoint. It exists in tracked documentation because generated files under
`reports/` are ignored by git.

## Inputs

- Live closed trades:
  `reports/live_ops/lpfs_trade_diagnostics/20260530_153500/closed_trade_diagnostics.csv`
- FTMO benchmark:
  `reports/strategies/lp_force_strike_account_commission_sensitivity/20260505_165121/ftmo_baseline_commission_adjusted_trades.csv`
- IC benchmark:
  `reports/strategies/lp_force_strike_account_commission_sensitivity/20260505_165121/ic_markets_raw_spread_commission_adjusted_trades.csv`

Benchmark method: use only the accepted V22 separated variant
`separation_variant_id=exclude_lp_pivot_inside_fs`, with
`commission_adjusted_net_r`, grouped by `exit_time_utc` calendar month.

Live method: use closed live rows from May 2026 UTC in
`closed_trade_diagnostics.csv`, grouped by `result_time_utc` calendar month.

## Live First-Month Result

| Lane | Live May 2026 closed trades | Live net R | Live PnL | Wins | Losses | Monthly percentile |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FTMO | 71 | -15.09R | -116.48 | 28 | 43 | p1.67 |
| IC | 61 | -13.47R | -73.66 | 25 | 36 | p0.83 |

## V22 Monthly Backtest Context

| Lane | Backtest months | Median month | p10 month | p5 month | Losing months | Worst month |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FTMO | 120 | +9.43R | -5.36R | -11.59R | 28 | -17.74R |
| IC | 121 | +11.59R | -2.76R | -8.98R | 20 | -17.83R |

The 10-year backtest did not make every month profitable. Losing months existed
in both broker-data lineages: FTMO had 28 losing months out of 120, and IC had
20 losing months out of 121.

However, the current live May result is near the lower tail of the monthly
distribution. FTMO is worse than the V22 p5 month and close to the worst few
historical months. IC is also worse than its V22 p5 month and has only one
historical month at or below the current live result.

## Interpretation

The weekly p10/p5 rules are not sufficient by themselves because they miss a
persistent below-median streak and month-to-date drawdown. The first-month
monthly evidence is strong enough to escalate from passive monitoring to an
offline cause-attribution investigation now.

This is not approval to change live production rules. A production heuristic
change still requires:

- FTMO and IC confluence;
- a concentrated cause such as timeframe, symbol, side, session, setup
  geometry, execution path, spread-risk, recovery path, or market regime;
- recent-window improvement, especially 3/6/12 month benchmark windows;
- no unacceptable degradation in the full 10-year V22 benchmark;
- explicit operator approval as a separate strategy-change plan.

## Next Action

Start offline first-month cause attribution from the diagnostic report and
benchmark rows. Keep live runners unchanged while the investigation runs.
