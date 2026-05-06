# LPFS Native MQL5 EA Migration

This folder is the isolated native MQL5 migration workspace for LP + Force
Strike. The current Python live runners on FTMO and IC remain production truth.
Nothing here should touch live configs, VPS runtime folders, state files,
journals, Telegram channels, scheduled tasks, or broker orders.

## Current Stage

- Target: native MQL5 EA, not a Python bridge.
- Stage: Strategy Tester-only v1 scaffold.
- Canonical strategy truth: Python V13 mechanics + V15 risk buckets + V22
  LP/FS separation.
- EA default identity: `MagicNumber=331500`, `CommentPrefix=LPFSEA`.
- Live lock: `InpTesterOnly=true`, `InpAllowLiveTrading=false`.
- Local compile: MetaEditor completed with `0 errors, 0 warnings`.
- MT5 tester load/config smoke: passed. The EA loaded in Strategy Tester,
  printed the risk schedule, printed the internal spread gate, and stayed
  tester-only.
- Full-result smoke: pending. The first EURUSD H4 tester run was stopped
  because the scaffold scans the full 28-symbol x 5-timeframe basket on every
  tick, making the estimate impractical for a first smoke test.

If attached outside Strategy Tester with the default settings, the EA refuses to
initialize.

## Next Continuation Task

Before running more MT5 tests, add a fast smoke mode:

- `InpSmokeTestSingleChartOnly=true` by default for v1 tester smoke.
- When enabled, scan only `_Symbol` and `_Period` from the Strategy Tester
  settings.
- Add new-bar gating so scans run only when a relevant H4/H8/H12/D1/W1 bar
  changes, not on every tick.
- Keep full-basket mode available for later portfolio tests after the smoke
  path is cheap.

Current MT5 observation to preserve: the Strategy Tester settings symbol
controls the main tester clock, but a multi-symbol EA can still request other
symbols through `SymbolSelect` and `CopyRates`. That is why the EURUSD H4 run
started synchronizing AUDCAD and other basket symbols.

## Files

- `Experts/LPFS/LPFS_EA.mq5`: native MQL5 EA source.
- `fixtures/canonical_lpfs_ea_fixture.json`: Python-generated parity fixture.
- `scripts/Compile-LpfsEa.ps1`: local MetaEditor compile helper.
- `tester/lpfs_tester_first_run.ini`: first-run tester notes/template.

## Operator MT5 Steps

1. Use a local MT5 test terminal, not the FTMO or IC live terminals.
2. Compile `Experts/LPFS/LPFS_EA.mq5` in MetaEditor or with:

   ```powershell
   .\mql5\lpfs_ea\scripts\Compile-LpfsEa.ps1
   ```

3. Copy the compiled EA to the test terminal `MQL5\Experts\LPFS\` folder if
   MetaEditor is not already pointed at that terminal.
4. Open MT5 Strategy Tester, choose the LPFS EA, and start with one symbol
   only after `InpSmokeTestSingleChartOnly` exists.
5. Use real ticks or the highest-quality tick mode available.
6. Save tester reports for `Conservative`, `Standard`, and `Growth` only after
   the fast single-chart smoke run completes cleanly.

Do not attach this EA to FTMO or IC live charts during v1.

## Risk Profile Disclosure

The EA exposes named risk profiles, not raw timeframe bucket editing. Every
tester run prints the effective schedule:

- Conservative: H4/H8 `0.10%`, H12/D1 `0.15%`, W1 `0.30%`.
- Standard: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.
- Growth: H4/H8 `0.25%`, H12/D1 `0.30%`, W1 `0.75%`.

The spread gate remains internal and dynamic: spread must be no more than 10%
of setup entry-to-stop risk.

`InpMaxOpenRiskPct`, `InpMaxConcurrentTrades`, and
`InpMaxSameSymbolTrades` default to `0`, which means "use the selected
profile's tested cap." Operators can lower or raise those operational caps in
Strategy Tester without editing the hidden LPFS entry/exit rules.

## Fixture Refresh

After any Python strategy patch, regenerate and review the parity fixture:

```powershell
.\venv\Scripts\python scripts\export_lpfs_ea_fixtures.py
```

Then update `docs/ea_migration.html` if the EA parity status changes.
