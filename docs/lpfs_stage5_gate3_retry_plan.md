# LPFS Stage 5 FTMO Gate 3 Retry Plan

Last updated: 2026-06-04 ICT after the accepted FTMO Gate 3 `STOPPED` result.

## Current Gate

Do not retry FTMO Gate 3. Do not access either VPS or MT5 until the offline
structured-verifier change is reviewed and a fresh dual-lane Gate 1 read-only
packet is separately approved.

The current verifier-hardening diff is local and review-only in the isolated
worktree. It has not been committed, pushed, pulled to a VPS, or used for a
fresh Gate 1 or Gate 3 operation.

The future-operation safety profiles and the complete six-step Gate 1 v2
pre-execution producer/contract are now defined, but they are review
candidates only. Fresh Gate 1 remains blocked until this offline diff is
reviewed and the operator separately approves read-only collection. No
restart approval is possible until the complete structured Gate 3
precheck/postcheck probe commands that satisfy the lane-specific resumption
profiles are also separately hash-reviewed. The new producer,
bounded-status collector, contracts, and profiles have not been executed
against either VPS.

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

Review-candidate profile IDs:

- `stage5_gate1_dual_lane_contained_v2`
- `stage5_ftmo_gate3_resumption_v1`
- `stage5_ic_gate3_resumption_v1`

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
runtime file declared by the Gate 1 v2 safety profile. The complete Gate 1 v2
pre-execution contract ID is:

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

The command, exact status implementation, execution metadata, stdout, stderr,
exit code, and timeout sidecar must all be manifest-bound. The verifier
requires the profile-pinned command hash and implementation hash, the remote
hash-verification marker, nonempty status output, empty stderr, exit code `0`,
and `timeout=false`. It rejects commands that name the VPS-resident
`Get-LpfsLiveStatus.ps1`.

Every checked artifact must be declared by `manifest.json` with the same byte
count and SHA-256. The expected packet result, required steps, and complete
expectation sets come only from the mandatory profile. The verifier compares
expected values against structured payloads using exact JSON types and exact
arrays/objects.

The verifier fails closed when:

- any artifact is missing or unreadable;
- any checked artifact or `validation_summary.json` is not manifest-declared;
- the command is empty;
- stderr is nonempty;
- the exit code is missing, malformed, or nonzero;
- a bounded-status timeout sidecar is missing, malformed, or true;
- bounded-status stdout is missing or empty;
- the bounded-status command or status implementation differs from the
  profile-pinned SHA-256;
- the bounded-status command attempts to execute a VPS-resident status script;
- bounded-status execution metadata or the remote implementation-hash marker
  is missing or inconsistent;
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

- focused structured-verifier, collector, producer, and contract module: `40`
  tests passed;
- current full LPFS suite: `435` tests total (`433` passed, `2` intentional
  skips) with `228` subtests;
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
- staged Gate 3 reviewed read-only hash-contract rehearsal: `PASS`;
- all pre-execution rehearsals state `authorizes_execution=false`.

Current pinned review-candidate contract hashes:

```text
lpfs_stage5_safety_contract_profiles_v1.json
1666fe6bbfe73c4d85746c8bb49d413a0e2011b0979d9ca49308709ff3f2e1a5

lpfs_stage5_read_only_command_contracts_v1.json
947105e7a50c46b582f7f0ed336b6a602c38d7a931b9cbc4d1f5d7f4ed72ba10

lpfs_stage5_resumption_safety_contract_profiles_v2.json
61ba3084457e6466cfdd484d568a5c6f2c2f3f44c2103dde204a1e10b0a71f43

lpfs_stage5_read_only_command_contracts_v2.json
1a1bbd812fd36ad8627abba1f9591166b27d64cc3b222794ad5ff356f9cfb435

collect_lpfs_bounded_status_bundle.py
0d6f1be193d51b4dfdeb12f16d4963f6d1b5e131cc01cfc7db9b5974d0163919

build_lpfs_stage5_gate1_v2_pre_execution.py
1aeb47069d629653a483552d647e8c39ea9491f17cf81c0ccd0596fa01c89303
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

## Review-Only Retry Plan

This plan is not approved for execution.

1. Review the offline verifier code, tests, archived-packet results, and this
   plan.
2. Fresh Gate 1 remains blocked until the complete six-step v2 producer,
   command-hash barrier, contract, tests, and this documentation pass review.
   After that review and separate operator approval, generate and verify the
   exact local command bundle under
   `stage5_gate1_v2_complete_read_only_v1`, collect a fresh dual-lane Gate 1
   packet using `stage5_gate1_dual_lane_contained_v2`, and stop for review.
   The previous Gate 1 packet `20260604_095237` is stale. Gate 1 v1 is
   historical only.
3. Require separate explicit approval for another FTMO-only Gate 3 attempt.
4. Before executing any read-only command, stage the exact planned command and
   script files locally. Run the pre-execution hash-contract verifier and stop
   unless its reviewed-contract receipt is `PASS`. A `PASS` does not authorize
   execution; obtain explicit operator approval separately.
5. After execution, publish every checked artifact in the packet manifest and
   run the mandatory-profile post-execution verifier. Stop unless its atomic
   receipt is `PASS` and proves the command bundle, bounded-status timeout and
   output checks, exact hash-approved status implementation, runtime-integrity
   evidence, manifest binding, expected packet result, complete safety
   profile, and exact position inventory.
6. Reconfirm fresh Gate 1 age is less than 30 minutes and revalidate FTMO
   containment, strict identity, strict broker reads, pending orders `0`, and
   the approved three-position inventory.
7. Do not approve restart execution until the complete structured precheck and
   postcheck command producers are separately hash-reviewed and can satisfy
   `stage5_ftmo_gate3_resumption_v1`. Then enable only `LPFS_Live`, verify it
   is enabled but `Ready` and not running, and capture the required structured
   command bundle.
8. Clear only the FTMO kill switch and start only `LPFS_Live`.
9. Immediately collect bounded FTMO status and strict MT5 evidence. Require
   one logical watchdog/runner path, fresh running heartbeat and lifecycle
   rows, recovery disabled, unchanged existing positions, and full evidence
   for any new exposure.
10. On any failure or ambiguity, restore the FTMO kill switch, disable
    `LPFS_Live`, leave broker exposure untouched, preserve evidence, and stop.
11. Do not access IC during the FTMO-only retry. Do not run reconciliation,
    run a canary, or pull code.

Every operational step must use a reviewed versioned profile and preserve its
command bundle before the next step. Pre-execution hash approval and
post-execution evidence validation are separate required checks. Neither one
authorizes execution. Zero-step verification, partial expectation sets,
undeclared artifacts, unapproved scripts, and ad hoc inline verification
commands are prohibited.
