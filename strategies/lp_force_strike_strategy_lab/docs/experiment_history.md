# LPFS Experiment History

Last updated: 2026-07-04 ICT.

This file preserves LPFS research chronology that should not bloat current
first-read state. It is research history only. It does not approve live
strategy, risk, sizing, SL/TP, spread, recovery, config, or broker-send
changes.

Current strategy state lives in:

- `../PROJECT_STATE.md`
- `../../../docs/lpfs_strategy_iteration_context.md`
- `../../../docs/lpfs_strategy_improvement_workflow.md`
- `../../../docs/evidence_catalog.md`

## Current Baseline

The current LPFS baseline is V13 mechanics plus V15 risk buckets plus V22
LP/FS separation:

- LP3 take-all across H4/H8/H12/D1/W1
- selected LP pivot must be before the Force Strike mother bar
- `0.5` signal-candle pullback entry
- full Force Strike structure stop
- single `1R` target
- fixed 6-bar pullback wait

The current research queue keeps H8 compressed risk
(`timeframe=H8`, `risk_atr_bucket=lt_0p5`) as a research-only candidate and
rejects the simple H8 low-spread-only filter unless future evidence overturns
the 2026-06-27 closeout.

## Chronology

| Version | Research question | Durable outcome |
| --- | --- | --- |
| V1 | Could raw LP + Force Strike produce a practical baseline? | Established the first combined concept and backtest harness. |
| V2 | Could a narrower focus improve signal quality? | Preserved useful ideas but did not replace the baseline. |
| V3 | Entry and exit variants. | Informed later fixed pullback and bracket conventions. |
| V4 | Stability checks. | Helped separate promising shape from unstable variants. |
| V5 | H8 bridge. | H8 became important enough to monitor, not an automatic live target. |
| V6 | H12 bridge. | Added higher-timeframe comparison context. |
| Gap-symbol checks | Ad hoc symbol coverage and edge cases. | Kept as research context, not production rules. |
| V7/V8 | Entry wait alternatives. | Do not replace the fixed 6-bar pullback wait. |
| V9 | LP pivot strength. | Informed LP pivot selection without becoming the final baseline alone. |
| V10 | Portfolio baseline. | Shifted evaluation toward portfolio-level behavior. |
| V11 | Practical timeframe mix. | Supported the selected timeframe set. |
| V12 | LP pivot finalization. | Prepared the current LP-selection rule. |
| V13 | Relaxed portfolio rule selection. | Current mechanics baseline. |
| V14 | Risk sizing and drawdown. | Added account-risk sizing analysis. |
| V15 | Risk bucket sensitivity. | Current risk-bucket interpretation for research and live-validation scale. |
| V16 | Bid/ask execution realism. | Reinforced broker-side bid/ask realism as a research requirement. |
| V17 | LP/FS proximity tightening. | Did not replace the current baseline. |
| V18 | TP-near exit research. | Research-only evidence; no live rule adopted. |
| V19 | TP-near robustness backtest. | Research-only evidence; no live rule adopted. |
| V20 | Protection realism. | Research-only evidence; no live rule adopted. |
| V21 | BTC/ETH crypto broker-history test. | BTC/ETH were exploratory; SOL remained short-history exploratory context. |
| V22 | LP/FS separation rule. | Accepted the hard design rule that selected LP pivot must be before the Force Strike mother bar. |

## Rejected Or Blocked Current Ideas

- H8 low-spread-only filter: rejected on 2026-06-27 because it was live-weak
  but historically positive, making it a diagnostic proxy rather than a causal
  live filter.
- H8 compressed risk: active research candidate only. It has 3M/6M and
  long-history support, but live deployment is blocked by contradictory 12M
  evidence, asymmetric FTMO/IC long-history support, and broad H8 trade
  removal.

## Research Guardrails

- Review FTMO and IC together.
- Treat one-lane weakness first as possible broker/feed/execution divergence.
- Use recent 3, 6, and 12 month windows first, then the 10-year backtest as a
  robustness guardrail.
- Use timeframe-normalized views so lower-timeframe counts do not drown sparse
  higher-timeframe evidence.
- Do not deploy a strategy change without explicit approval, recent-window
  support, FTMO/IC confluence where comparable, and acceptable long-backtest
  behavior.
