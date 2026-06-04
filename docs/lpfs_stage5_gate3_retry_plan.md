# LPFS Stage 5 FTMO Gate 3 Retry Plan

Last updated: 2026-06-04 ICT after the accepted FTMO Gate 3 `STOPPED` result.

## Current Gate

Do not retry FTMO Gate 3. Do not access either VPS or MT5 until the offline
structured-verifier change is reviewed and a fresh dual-lane Gate 1 read-only
packet is separately approved.

The accepted FTMO Gate 3 stopped packet is:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\ftmo_gate3_20260604_100840
```

Its `manifest.json` SHA-256 is:

```text
85df11692de17e3d35b986dafee1ce729a15b822b8ce0f3c3ccea367eb27318e
```

The packet proves final FTMO containment: `KILL_SWITCH` active, `LPFS_Live`
disabled, runner/watchdog process count `0`, broker pending orders `0`, strict
MT5 reads successful, correct FTMO identity, and the same three positions with
unchanged symbol, magic, comment, volume, SL, and TP.

Fallback containment refreshed the FTMO `KILL_SWITCH` content and invoked
`Disable-ScheduledTask` while `LPFS_Live` was already disabled. It did not
enable or start the task, clear the kill switch, access IC, run
reconciliation, run a canary, pull code, or mutate broker exposure.

## Malformed Verification Incident

The ad hoc verification probe was not written into the authoritative Gate 3
packet before execution. Its exact command, stdout, stderr, and exit code are
therefore unavailable from durable packet evidence and cannot be
independently verified. Do not reconstruct or treat a remembered command as
authoritative.

The session observed ambiguous output from that probe. Because the command
bundle was not preserved, the durable root-cause classification is:

```text
unverified malformed local verification command
```

This evidence gap is the reason the Gate 3 result remains `STOPPED`.

## Structured Verifier

Use `scripts/verify_lpfs_structured_command.py` for every future pre-mutation
verification step. It is offline-only and does not access SSH, VPS, MT5,
runtime files, journals, or broker APIs.

For each step, it requires these files before returning `PASS`:

```text
<step>.command.txt
<step>.stdout.txt
<step>.stderr.txt
<step>.exit_code.txt
```

The verifier fails closed when:

- any artifact is missing or unreadable;
- the command is empty;
- stderr is nonempty;
- the exit code is missing, malformed, or nonzero;
- stdout does not contain exactly one nonempty structured marker line;
- the structured marker is missing, duplicated, ambiguous, or invalid JSON;
- the packet manifest, payload hash, byte count, or expected packet result
  does not match.

It writes an atomic JSON receipt when `--output` is provided. A future
operator must preserve the verifier receipt before advancing to any mutation.

Example offline verification:

```powershell
.\venv\Scripts\python scripts\verify_lpfs_structured_command.py `
  --packet "<packet-root>" `
  --expected-packet-result PASS `
  --step "precheck=LPFS_GATE3_PRECHECK_JSON=" `
  --output "<separate-local-verifier-receipt.json>"
```

The verifier receipt records `PASS` or `STOPPED`, an explicit reason, artifact
paths, byte counts, SHA-256 values, parsed structured output, manifest
validation, and expected packet-result validation.

## Offline Verification Performed

The offline follow-up did not access either VPS or MT5.

- verifier unit tests: `8` passed, covering valid, missing, malformed exit
  code, malformed JSON, ambiguous output, nonempty stderr, manifest pass, and
  manifest tamper cases;
- full LPFS suite: `403` passed with `2` intentional skips;
- strict core coverage: `6401` statements and `2192` branches at `100.00%`;
- archived Gate 1 packet `20260604_095237`: manifest, expected `PASS`, and four
  FTMO/IC containment and strict-MT5 command bundles verified `PASS`;
- archived Gate 3 packet `ftmo_gate3_20260604_100840`: manifest, expected
  `STOPPED`, preserved precheck, pre-strict-MT5, and final-strict-MT5 bundles
  verified `PASS`;
- archived Gate 3 fallback bundle: correctly verified `STOPPED` because
  `fallback_containment.command.txt` is missing.

Offline verifier receipts are ignored local evidence:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate1_offline_verification_20260604.json
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate3_offline_verification_20260604.json
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate3_fallback_bundle_verification_20260604.json
```

## Review-Only Retry Plan

This plan is not approved for execution.

1. Review the offline verifier code, tests, archived-packet results, and this
   plan.
2. Collect a fresh dual-lane Gate 1 read-only packet and stop for review. The
   previous Gate 1 packet `20260604_095237` is stale.
3. Require separate explicit approval for another FTMO-only Gate 3 attempt.
4. Before any FTMO mutation, capture the task-contract command with command,
   stdout, stderr, and exit-code sidecars.
5. Run the structured verifier against that command bundle. Stop unless its
   atomic receipt is `PASS`.
6. Reconfirm fresh Gate 1 age is less than 30 minutes and revalidate FTMO
   containment, strict identity, strict broker reads, pending orders `0`, and
   the approved three-position inventory.
7. Enable only `LPFS_Live`, verify it is enabled but `Ready` and not running,
   then capture and verify a new structured command bundle.
8. Clear only the FTMO kill switch and start only `LPFS_Live`.
9. Immediately collect bounded FTMO status and strict MT5 evidence. Require
   one logical watchdog/runner path, fresh running heartbeat and lifecycle
   rows, recovery disabled, unchanged existing positions, and full evidence
   for any new exposure.
10. On any failure or ambiguity, restore the FTMO kill switch, disable
    `LPFS_Live`, leave broker exposure untouched, preserve evidence, and stop.
11. Do not access IC during the FTMO-only retry. Do not run reconciliation,
    run a canary, or pull code.

Every operational step must preserve its command bundle before the next step.
No ad hoc inline verification command is allowed.
