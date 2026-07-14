---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S36'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Execute the owner-authorized LOCAL cleanup of 2026-07-14 (destructive): remove the three merged worktrees and angry-jemison, drop all four pre-restructure stashes, delete feature/control-layer and feature/entry-point-layer locally, and remove the orphaned feature-ui-integration-wire-regen-28 directory

## Scope

- `NO remote deletions (origin/claude/* stay)`
- `and feature/ci-resolve-vaultspec-core-dep-23 stays untouched pending W02.P03`
- `defer feature/ci-resolve-vaultspec-core-dep-23 until W02.P03 lands`
- `git worktrees`
- `git stashes`
- `git branches`

## Description

- Re-verify each target before deleting: the three worktree branches (`claude-test`, `feature/devrunner-smoke-test-13`, `feature/service-orchestration-lifecycle-manageme-18`) and `claude/angry-jemison` are all 0 commits ahead of main; `feature/control-layer` (13 ahead) and `feature/entry-point-layer` (12 ahead) are pre-restructure/superseded and owner-authorized for force-deletion (entry-point-layer additionally cleared by the S35 spot-check).
- Remove the three merged worktrees with `git worktree remove`, then `git worktree prune` to clear the missing `angry-jemison` entry.
- Drop all four pre-restructure stashes.
- Delete the six local branches: four merged (`-d`) and two authorized-but-ahead (`-D`).
- Confirm `feature-ui-integration-wire-regen-28` is NOT a git worktree (no `.git` link; contains only an empty `.vault/research` and stale `vaultspec.db*` files) and remove the scratch directory.

## Outcome

Local git state reconciled. Worktrees reduced to `main` + the preserved `feature-ci-resolve-vaultspec-core-dep-23`; zero stashes remain; the six target branches are gone; the orphan directory is removed. Preserved exactly as instructed: the `ci-resolve-vaultspec-core-dep-23` branch and worktree (deferred to W02.P03), the `feature/ui-integration-wire-regen-28` branch (only its scratch directory was removed), all other local branches, and every remote branch (`origin/claude/*` untouched — NO remote deletions).

## Notes

All operations were local and destructive-but-authorized; no push or remote mutation occurred. Branch ahead-counts were verified live rather than trusted from the audit, and the two force-deleted branches were confirmed superseded (control-layer) or valueless (entry-point-layer, per S35) before removal. This closes the W01.P15 git-state reconciliation phase.
