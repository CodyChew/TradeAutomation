# LPFS Stage 5 FTMO Gate 3 Retry Plan

Last updated: 2026-06-07 ICT after LPFS minimum-safety resumption and Phase 1
live quote telemetry deploy completed for FTMO first and IC second.

## Current Gate

Current objective is complete: LPFS data collection was restored with minimum
necessary live-safety checks, and Phase 1 live quote telemetry separation was
deployed sequentially to FTMO and IC. The old strict six-step Gate 1 V2 path is
historical context, not the current operational blocker.

Both VPS lanes currently run runtime code SHA
`027e0afe932081713067dc24b2bc457cddf1041e`. FTMO `LPFS_Live` was resumed and
then updated/restarted first, proved clean, and then IC `LPFS_IC_Live` was
updated/restarted. A later docs/status/handoff-only closeout commit may
advance `main` without changing live runner behavior.
Both lanes have one logical runner path, fresh running heartbeats, successful MT5
`account_info`, `terminal_info`, `orders_get`, and `positions_get`, pending
strategy orders `0`, unchanged active positions including SL/TP, and no
unexplained broker exposure. Primary lifecycle journals no longer receive new
live `market_snapshot` rows; separated telemetry journals exist/grow; telemetry
write and retention failure counts were `0`.

Final evidence:

- FTMO packet:
  `C:\TradeAutomationEvidence\lpfs_c01_stage5\ftmo_resume_minimal_20260607_102235`,
  current manifest SHA-256 in `manifest.sha256.txt`
- IC packet:
  `C:\TradeAutomationEvidence\lpfs_c01_stage5\ic_resume_minimal_20260607_103929`,
  current manifest SHA-256 in `manifest.sha256.txt`
- Combined validation packet:
  `C:\TradeAutomationEvidence\lpfs_c01_stage5\resume_final_20260607_104948`,
  current manifest SHA-256 in `manifest.sha256.txt`
- FTMO Phase 1 telemetry packet:
  `C:\TradeAutomationEvidence\lpfs_phase1_telemetry\ftmo_task_repair_retry_20260607_201146`,
  manifest SHA-256
  `4ec14b8ad6f4ab0bb3fbe22e86dd20140039c95c8e41ce0ae1f4977e8a1a9461`
- IC Phase 1 telemetry packet:
  `C:\TradeAutomationEvidence\lpfs_phase1_telemetry\ic_deploy_20260607_202435`,
  manifest SHA-256
  `7aba24f3227988473c9d6ab46a877e1c228e20faf29a5626cc11d664b900f23f`

No reconciliation or canary was run. No manual broker order/position
modification, runtime-state edit, or historical journal cleanup was performed.
No strategy, risk, sizing, SL/TP, or broker-send setting was changed. Task
executable path repairs to the full System32 PowerShell path are complete on
both lanes.

The latest Gate 1 v2 packet is:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate1_v2_20260606_020556
```

Its `manifest.json` SHA-256 is:

```text
d33094989b3f2ef1566f2e2e97c9015ebb5bd18f845a6d1d0f2630131590bcf2
```

This historical strict Gate 1 packet remains `STOPPED`. The offline hardening patch fixes two
evidence-tooling blockers against this archived packet: bounded-status stderr
now accepts only safe PowerShell CLIXML host/progress/information records, and
critical runtime hash comparison now accepts only explicit reviewed
line-ending-equivalent SHA-256 variants while preserving raw observed hashes.
The archived strict MT5 steps pass and the bounded-status steps pass under the
new classifier. FTMO compact containment also passes under the reviewed
runtime-hash variants. IC compact containment still timed out with exit `124`,
empty stdout/stderr, and no remote script-hash marker. The local artifacts do
not prove whether the timeout was SSH stdin handling, remote command waiting
behavior, timeout length, or transient VPS behavior. Therefore IC compact
timeout remained a real strict-profile `STOPPED` condition. The current
owner-approved path uses the minimum read-only profile instead.

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

## Mandatory Safety Profiles

Post-execution evidence verification must use the reviewed versioned profiles
in:

```text
configs/operations/lpfs_stage5_safety_contract_profiles_v1.json
```

Historical packet profile IDs:

- `stage5_gate1_dual_lane_contained_v1`
- `stage5_ftmo_gate3_stopped_v1`

These v1 profiles preserve verification of already-captured packets. They are
not approved for a fresh Gate 1 collection or a Gate 3 restart.

Future-operation profiles are in:

```text
configs/operations/lpfs_stage5_resumption_safety_contract_profiles_v2.json
```

Profile IDs:

- `stage5_gate1_dual_lane_contained_v2`
- `stage5_minimum_dual_lane_read_only_v1`
- `stage5_ftmo_gate3_resumption_v1`
- `stage5_ic_gate3_resumption_v1`

Use `stage5_minimum_dual_lane_read_only_v1` for the owner-approved minimum
fresh read-only evidence gate. It intentionally omits bounded-status and MT5
history reads from the pass/fail requirements.

The FTMO and IC resumption profiles are intentionally separate. Approval or a
`PASS` for one lane does not authorize action on the other lane.

The post-execution verifier pins the complete profile-document SHA-256. It
rejects an otherwise valid profile if the document hash differs. A profile or
expectation change therefore requires an explicit reviewed code-and-profile
change; an operator cannot weaken the profile by editing the JSON locally.

Each gate profile declares the exact required step set. Each step has its own
`contract_version`, required expectation-field set, structured marker, and
expected values. The verifier rejects missing or extra steps, missing or extra
expectations, duplicate expectation fields, unknown contract keys, and
unsupported profile versions. Operator-supplied partial `--expect` sets are no
longer accepted.

The Gate 1 profile validates exact approved position inventories, including
ticket, identifier, symbol, magic, comment, volume, SL, and TP. Matching only
the position count is insufficient. Inventory comparison is order-independent
but requires every reviewed row and field to match exactly.

Every future-operation profile declares mandatory runtime-integrity steps.
The schema requires the reviewed `repo_head` plus a clean tracked worktree or
exact critical runtime-file SHA-256 values. The current profiles require both:
`tracked_worktree_clean=true`, an empty tracked-worktree status, and exact
hashes for the watchdog, runner CLI, live executor, dry-run/execution helpers,
diagnostics, and timestamp semantics. A matching commit SHA cannot hide a
modified tracked runtime file.

Future Gate 1 requires a bounded-status bundle for both lanes. Each Gate 3
resumption profile requires bounded-status bundles before and after the
lane-specific restart attempt.

The profiles, manifests, summaries, and structured payloads use strict
standard JSON. Duplicate object keys and non-standard constants such as
`NaN`, `Infinity`, and `-Infinity` are rejected.

## Pre-Execution Read-Only Contract

Before any approved read-only command is executed, stage every planned command
and script locally and verify it against the separately reviewed hashes in:

```text
configs/operations/lpfs_stage5_read_only_command_contracts_v1.json
```

Use:

```powershell
.\venv\Scripts\python scripts\verify_lpfs_pre_execution_contract.py `
  --artifact-root "<local-staged-read-only-files>" `
  --contract-file "configs\operations\lpfs_stage5_read_only_command_contracts_v1.json" `
  --contract-id "stage5_gate1_dual_lane_read_only_v1" `
  --output "<separate-local-pre-execution-receipt.json>"
```

The staged directory must contain the exact reviewed executable-like artifact
set. Missing files, unapproved `.command.txt`, `.ps1`, or `.py` files, hash
changes, byte changes, incomplete contracts, duplicate JSON keys, and
non-standard JSON stop the check.

The pre-execution verifier pins the complete read-only-contract document
SHA-256. Any hash-contract change requires a separately reviewed
code-and-contract change.

A command that invokes a repository script is incomplete unless that invoked
script is also staged and hash-approved. The historical v1 contracts therefore
require the exact `scripts/Get-LpfsLiveStatus.ps1` artifact in addition to the
historical bounded-status command line.

Future hash-approved Gate 1 read-only collection uses:

```text
scripts/build_lpfs_stage5_gate1_v2_pre_execution.py
scripts/collect_lpfs_bounded_status_bundle.py
configs/operations/lpfs_stage5_read_only_command_contracts_v2.json
```

The producer is local-only. It creates the exact reviewed command/script
artifact set for all six mandatory Gate 1 steps without executing any command:

- FTMO compact containment;
- FTMO bounded status;
- FTMO strict MT5;
- IC compact containment;
- IC bounded status;
- IC strict MT5.

The compact-containment scripts emit tracked-worktree status, a
`tracked_worktree_clean` result, and exact SHA-256 values for every critical
runtime file declared by the Gate 1 v2 safety profile. They are no longer
embedded as a full inline command. The reviewed compact command is a short
hash-bound bootstrap under the `4000` character safe threshold; it receives
the reviewed local `compact_containment.remote.ps1` artifact through SSH
stdin, verifies that script SHA-256 remotely, and executes it in memory. The
collector exposes this route through explicit CLI mode
`--mode compact-containment`, and tests prove it dispatches to the reviewed
`collect_compact_containment_bundle` path. Missing compact script/hash inputs
stop before SSH. The
complete Gate 1 v2 pre-execution contract ID is:

The strict MT5 probe must use the same hash-bound stdin transport. The
reviewed local `strict_mt5_probe.py` artifact is sent over SSH stdin as
base64, verified remotely by SHA-256, and piped into the lane Python
interpreter in memory. The strict command must not use inline `python -c`, must
stay below the `4000` character safe threshold, and must not contain the full
strict script body or script base64. The collector exposes this route through
explicit CLI mode `--mode strict-mt5`; wrong command hash, wrong script hash,
SSH-alias drift, Python-path drift, or command length at/above the threshold
writes structured `STOPPED` with `execution_attempted=false`; SSH is not
invoked.

- `stage5_gate1_v2_complete_read_only_v1`

Generate a new local staging directory, then verify it:

```powershell
.\venv\Scripts\python scripts\build_lpfs_stage5_gate1_v2_pre_execution.py `
  --output-root "<new-local-gate1-v2-staging-directory>"

.\venv\Scripts\python scripts\verify_lpfs_pre_execution_contract.py `
  --artifact-root "<new-local-gate1-v2-staging-directory>" `
  --contract-file "configs\operations\lpfs_stage5_read_only_command_contracts_v2.json" `
  --contract-id "stage5_gate1_v2_complete_read_only_v1" `
  --output "<separate-local-pre-execution-receipt.json>"
```

The v2 contract document also retains bounded-status-only review contracts
for Gate 1, FTMO resumption, and IC resumption:

- `stage5_gate1_bounded_status_read_only_v1`
- `stage5_ftmo_gate3_resumption_bounded_status_read_only_v1`
- `stage5_ic_gate3_resumption_bounded_status_read_only_v1`

Each bounded-status contract pins both the collector and
`scripts/Get-LpfsLiveStatus.ps1`. The collector requires the exact reviewed
SSH command SHA-256 in addition to the status-implementation SHA-256. It
computes and compares the generated command hash before `subprocess.run`. Any
alias, runtime-root, filename, log-filter, or line-limit drift writes a
structured `STOPPED` result with `execution_attempted=false`; SSH is not
invoked. When the command matches, the collector sends the reviewed status
implementation over SSH stdin, verifies its SHA-256 remotely, and executes it
in memory. It does not call an unverified VPS-resident
`C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1` and does not write a
remote status-script file.

The same collector module also provides compact-containment execution for Gate
1 v2. It requires both the reviewed compact command SHA-256 and the reviewed
compact script SHA-256 before `subprocess.run`. A wrong command hash, wrong
script hash, alias drift, or command length at/above the safe threshold writes
structured `STOPPED` with `execution_attempted=false`; SSH is not invoked.

A pre-execution `PASS` proves only that the staged files match the separately
reviewed read-only hashes. Its receipt always states
`authorizes_execution=false`; explicit operator approval is still required.
It does not prove the later execution or output was correct.

## Post-Execution Evidence Verifier

Use `scripts/verify_lpfs_structured_command.py` only after command execution
to validate the preserved evidence packet. It is offline-only and does not
access SSH, VPS, MT5, runtime files, journals, or broker APIs.

For each mandatory profile step, it requires these manifest-bound files before
returning `PASS`:

```text
<step>.command.txt
<step>.stdout.txt
<step>.stderr.txt
<step>.exit_code.txt
```

Future bounded-status steps additionally require:

```text
<step>.timeout.txt
<step>.status_implementation.ps1
<step>.execution.json
```

Future compact-containment steps additionally require:

```text
<step>.timeout.txt
<step>.remote.ps1
<step>.execution.json
```

Future strict-MT5 steps additionally require:

```text
<step>.timeout.txt
<step>.py
<step>.execution.json
```

The command, exact status implementation, execution metadata, stdout, stderr,
exit code, and timeout sidecar must all be manifest-bound. The verifier
requires the profile-pinned command hash and implementation hash, the remote
hash-verification marker, nonempty status output, exit code `0`, and
`timeout=false`. Nonempty stderr is accepted only when it is well-formed
PowerShell CLIXML containing only progress, information, or host records. It
fails closed on malformed CLIXML, error records, exception text,
native-command errors, nonzero exit, timeout, missing stdout, or missing
status hash markers. It rejects commands that name the VPS-resident
`Get-LpfsLiveStatus.ps1`.

For compact-containment steps, the compact command, compact script, execution
metadata, stdout, stderr, exit code, and timeout sidecar must all be
manifest-bound. The verifier requires the profile-pinned command hash and
compact script hash, the remote script-hash verification marker, nonempty
containment output, empty stderr, exit code `0`, `timeout=false`, command
length below `4000`, and no full compact script body inside the command
artifact.

For strict-MT5 steps, the strict command, strict Python script, execution
metadata, stdout, stderr, exit code, and timeout sidecar must all be
manifest-bound. The verifier requires the profile-pinned command hash and
strict script hash, the remote script-hash verification marker, exactly one
`LPFS_GATE1_MT5_JSON=` payload, empty stderr, exit code `0`, `timeout=false`,
command length below `4000`, and no inline `python -c`, full strict script
body, or strict script base64 inside the command artifact.

Every checked artifact must be declared by `manifest.json` with the same byte
count and SHA-256. The expected packet result, required steps, and complete
expectation sets come only from the mandatory profile. The verifier compares
expected values against structured payloads using exact JSON types and exact
arrays/objects, except `critical_runtime_file_hashes`, which is compared
against explicit reviewed SHA-256 variant sets for line-ending-equivalent
tracked runtime files. Raw observed runtime hashes remain in the structured
payload and receipt.

The verifier fails closed when:

- any artifact is missing or unreadable;
- any checked artifact or `validation_summary.json` is not manifest-declared;
- the command is empty;
- bounded-status stderr is nonempty and not classified as safe PowerShell
  CLIXML host/progress/information records;
- compact-containment stderr is nonempty;
- strict-MT5 stderr is nonempty;
- the exit code is missing, malformed, or nonzero;
- a bounded-status timeout sidecar is missing, malformed, or true;
- a compact-containment timeout sidecar is missing, malformed, or true;
- a strict-MT5 timeout sidecar is missing, malformed, or true;
- bounded-status stdout is missing or empty;
- compact-containment stdout is missing or empty;
- strict-MT5 stdout is missing or empty;
- the bounded-status command or status implementation differs from the
  profile-pinned SHA-256;
- the compact-containment command or compact script differs from the
  profile-pinned SHA-256;
- the strict-MT5 command or strict Python script differs from the
  profile-pinned SHA-256;
- the compact-containment command is at/above the safe length threshold or
  contains the full compact script body;
- the strict-MT5 command is at/above the safe length threshold, uses inline
  `python -c`, or contains the full strict script body or script base64;
- the bounded-status command attempts to execute a VPS-resident status script;
- bounded-status execution metadata or the remote implementation-hash marker
  is missing or inconsistent;
- compact-containment execution metadata or the remote script-hash marker is
  missing or inconsistent;
- strict-MT5 execution metadata or the remote script-hash marker is missing
  or inconsistent;
- stdout does not contain exactly one nonempty structured marker line;
- the structured marker is missing, duplicated, ambiguous, or invalid JSON;
- the mandatory profile is missing, malformed, incomplete, or unversioned;
- a required gate step is missing or an undeclared step is present;
- a safety expectation is missing from the payload or does not match exactly;
- an exact position inventory differs even when the count is unchanged;
- the packet manifest, payload hash, byte count, or expected packet result
  does not match;
- the manifest is malformed, contains invalid or duplicate declarations, or
  reports an unsupported packet result;
- a manifest, summary, profile, or structured payload contains duplicate keys
  or non-standard JSON.

`--output` is required and must point outside the immutable packet. The
verifier writes an atomic `PASS` or `STOPPED` JSON receipt. If argument parsing
or input construction is malformed, it still writes a structured `STOPPED`
receipt to the parseable `--output` path. If no output path can be parsed, it
writes the `STOPPED` receipt under the local temporary directory and prints
that receipt path. A future operator must preserve the verifier receipt before
advancing to any mutation.

Example offline verification:

```powershell
.\venv\Scripts\python scripts\verify_lpfs_structured_command.py `
  --packet "<packet-root>" `
  --safety-profile "configs\operations\lpfs_stage5_safety_contract_profiles_v1.json" `
  --profile-id "stage5_gate1_dual_lane_contained_v1" `
  --output "<separate-local-verifier-receipt.json>"
```

The verifier receipt records `PASS` or `STOPPED`, an explicit reason, artifact
paths, byte counts, SHA-256 values, parsed structured output, manifest
validation, mandatory profile identity and hash, exact expectation results,
and expected packet-result validation. Every post-execution receipt states:

```text
proof_scope=post_execution_evidence_only
proves_command_was_safe_to_run=false
pre_execution_read_only_contract_required=true
```

A post-execution `PASS` must never be treated as proof that a command was safe
to run.

## Offline Verification Performed

The offline follow-up did not access either VPS or MT5.

- focused Stage 5 structured-verifier module: `65` tests passed;
- current full LPFS suite: `461` tests total (`459` passed, `2` intentional
  skips);
- independently verified pre-hardening full-suite baseline: `430` tests total
  (`428` passed, `2` intentional skips) with `216` subtests; this corrects the
  prior wording that incorrectly called `428` the full-suite count;
- strict core coverage: `6401` statements and `2192` branches at `100.00%`;
- archived Gate 1 packet `20260604_095237`: mandatory profile including exact
  FTMO/IC inventories verified `PASS`;
- archived Gate 3 packet `ftmo_gate3_20260604_100840`: mandatory profile and
  expected packet `STOPPED` result verified `PASS`;
- Gate 1 reviewed read-only hash-contract rehearsal: `PASS`;
- complete six-step Gate 1 v2 reviewed read-only hash-contract rehearsal:
  `PASS`, with `authorizes_execution=false`;
- archived Gate 1 v2 packet `gate1_v2_20260606_020556`: strict MT5 and
  bounded-status steps now verify `PASS`; FTMO compact-containment verifies
  `PASS` under reviewed LF/CRLF-equivalent hash variants; IC
  compact-containment remains `STOPPED` for timeout;
- stale pre-hardening Gate 1 v2 read-only contract hash
  `f4a602aac651220fb599324edd9c284aaa19071737d7472f4468efc2012cc057`
  is rejected by the default verifier allowlist;
- staged Gate 3 reviewed read-only hash-contract rehearsal: `PASS`;
- all pre-execution rehearsals state `authorizes_execution=false`.

Current pinned review-candidate contract hashes:

```text
lpfs_stage5_safety_contract_profiles_v1.json
1666fe6bbfe73c4d85746c8bb49d413a0e2011b0979d9ca49308709ff3f2e1a5

lpfs_stage5_read_only_command_contracts_v1.json
947105e7a50c46b582f7f0ed336b6a602c38d7a931b9cbc4d1f5d7f4ed72ba10

lpfs_stage5_resumption_safety_contract_profiles_v2.json
3e0b385e71f544faafc1029e01bfb740ea6b62e8e179c1032371c43b5c068928

lpfs_stage5_read_only_command_contracts_v2.json
61f2831aa3a3d2ca82a57e83274389a98a2095be0b3cd8a728a9dbcada441c16

collect_lpfs_bounded_status_bundle.py
b9147c8501b5bb7b344eaf375d48f4815de77f5179b1b14c16d7ce2892c3855d

build_lpfs_stage5_gate1_v2_pre_execution.py
d235a50e37dc4b1c945d3e84b31c7529a7015307c65f5d3c9d1103e62b0f1c53
```

These hashes are review candidates only. They become operationally approved
only after a separate review and explicit operator approval. The local
rehearsal receipts do not approve them.

Offline verifier receipts are ignored local evidence:

```text
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate1_profile_verification_review_only_20260604.json
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate3_profile_verification_review_only_20260604.json
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate1_pre_execution_contract_rehearsal_review_only_20260604.json
C:\TradeAutomationEvidence\lpfs_c01_stage5\gate3_pre_execution_contract_rehearsal_review_only_20260604.json
```

## Minimum-Safety Resumption Plan

The sequence below is the historical owner-approved operational path that was
used for the accepted 2026-06-07 minimum-safety resumption. It is retained for
audit context, not as a pending gate.

1. Collect fresh dual-lane minimum read-only evidence with
   `stage5_minimum_dual_lane_read_only_v1`. Before final `main` deployment,
   FTMO must match approved runtime SHA
   `3dd1895ca5300d448e4d100095b294e78679a6b9` and IC must match approved
   runtime SHA `b02a3cb92a05e771782c7a9ca4e4339c9452969a`.
2. Stop if any minimum check fails: wrong VPS/account identity, unexpected
   runtime SHA for the phase, kill switch not active, task not disabled,
   runner/watchdog count not `0`, recovery not disabled, broker pending orders
   nonzero, active positions not exactly matching approved ticket/symbol/magic
   comment/volume/SL/TP, or MT5 `account_info`, `terminal_info`, `orders_get`,
   or `positions_get` unavailable.
3. Merge the reviewed PR to `main` only after review approval and passing
   fresh minimum read-only evidence. Record the final approved `main` SHA.
4. Deploy the final approved `main` SHA under containment, one lane at a time.
   Keep kill switches active, tasks disabled, and runner/watchdog counts `0`.
   After deploying a lane, rerun that lane's minimum read-only checks and
   require the lane repo SHA to equal the final approved `main` SHA.
5. Resume FTMO first: confirm FTMO kill switch active; confirm `LPFS_Live`
   disabled and runner/watchdog counts `0`; enable only `LPFS_Live`; confirm
   enabled/ready but not running; clear only the FTMO kill switch; start only
   `LPFS_Live`; immediately capture status, MT5 inventory, heartbeat, journal
   tail, process count, pending orders, active positions, and any new exposure.
6. Resume IC only if FTMO post-start evidence is clean. Run a fresh IC
   pre-start check, then use the same ordered sequence for `LPFS_IC_Live`.
7. If any task starts unexpectedly while its kill switch is still active,
   disable that task, preserve evidence, and do not clear the kill switch.
8. On any failure or ambiguity, re-contain only the affected lane, leave
   broker exposure untouched, preserve evidence, and stop.
9. Do not run reconciliation or canary. Do not manually close, cancel, or
   modify broker orders or positions without separate approval.

Every operational step must use a reviewed versioned profile and preserve its
command bundle before the next step. Pre-execution hash approval and
post-execution evidence validation are separate required checks. Neither one
authorizes execution. Zero-step verification, partial expectation sets,
undeclared artifacts, unapproved scripts, and ad hoc inline verification
commands are prohibited.
