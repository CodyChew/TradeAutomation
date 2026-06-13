# Codex Worktree Workflow

This repository uses Git branches, Git worktrees, and Codex-created worktrees.
They are related but not interchangeable. Check the active checkout before
making changes.

## Terms

- Git branch: a movable name for a commit, such as `main` or
  `codex/lpfs-c01-live-safety-release`.
- Git worktree: a separate checkout directory attached to the same repository
  object database. A branch can be checked out in only one worktree at a time.
- Codex worktree: a Git worktree created by Codex under a Codex-managed path,
  often for isolated task work.
- Detached HEAD: a checkout pinned to a commit instead of a branch. Changes can
  exist there, but they are easy to lose or miss because no branch name moves
  with them.

## Canonical Branch

Use `main` as the canonical branch for normal Codex sessions unless the user
explicitly names another branch for review, archaeology, or a contained
implementation.

New sessions should prefer a checkout where:

- `git status --short --branch` shows `main...origin/main`.
- `git ls-files AGENTS.md` prints `AGENTS.md`.
- `AGENTS.md` is visible in the active checkout.

Do not assume a file exists in every worktree. A stale branch or detached
worktree can be missing `AGENTS.md`, docs, tests, or recent live-safety code
even when another worktree has them.

## Session-Start Checks

Run these before LPFS work:

```powershell
git rev-parse --show-toplevel
git status --short --branch
git worktree list
git ls-files AGENTS.md
```

If the active checkout is not `main`, verify that the branch or detached commit
is intentional before editing. If `AGENTS.md` is missing, stop and switch to an
up-to-date checkout or explicitly treat the checkout as historical.

## Creating Task Branches

Create a `codex/*` branch when work is exploratory, risky, needs review before
merge, or should not immediately affect `main`.

Use `main` directly only for small approved documentation/reporting updates or
after the owner has approved publication to the canonical branch. For live
trading, runtime, broker, scheduler, VPS, recovery, or journal behavior, use a
contained branch and preserve verification evidence before merge.

## Removing Stale Worktrees

Before removing or discarding a worktree:

1. Inventory all worktrees with `git worktree list --porcelain`.
2. Run `git status --short --branch` inside the target worktree.
3. Inspect `git log --oneline -5 --decorate`.
4. Summarize dirty files and staged changes.
5. Compare unique commits against `main`.
6. Get explicit approval for any discard target that contains uncommitted work,
   staged changes, or commits not contained in `main`.

Do not use destructive cleanup commands such as `git reset --hard`,
`git checkout -- .`, `git clean`, `git worktree remove --force`, branch delete,
or stash drop unless the exact discard target has been listed and approved.

If a stale worktree is clean and no longer needed, prefer normal
`git worktree remove <path>` followed by `git worktree prune`.

## Branch Consolidation

When consolidating back to `main`:

1. Confirm `origin/main` contains the required tracked workflow files,
   especially `AGENTS.md`.
2. Confirm any old `codex/*` branch commits are merged, superseded, or
   intentionally abandoned.
3. Preserve or document any non-obsolete detached worktree changes.
4. Switch the intended active checkout to `main`.
5. Pull with `git pull --ff-only`.
6. Verify `git status --short --branch` is clean.

Keep local Git cleanup separate from live operations. Worktree cleanup must not
access VPS, MT5, Task Scheduler, live runtime state, journals, broker orders,
broker positions, or kill switches.
