---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S04'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Remove obsolete broad framework ignores and prove Core-managed policy convergence

## Scope

- `.gitignore`

## Description

- Remove only the obsolete broad ignores for canonical Vaultspec and provider framework paths.
- Invoke project-locked Core 0.1.48 to reconcile its marker-bounded managed block.
- Verify one marker pair, trackability of canonical/provider paths, ignored managed runtime state, and a converged second sync preview.
- Preserve unrelated repository ignores and concurrent work outside the S04 hunks.

## Outcome

Core added `.vaultspec/mcp-ownership.json` to its managed block and reported every provider projection current on the second dry-run. Real `git check-ignore` checks proved canonical `.vaultspec`, provider rules, synthesized instructions, and `.mcp.json` are trackable, while Core-managed vault caches, snapshots, provider manifests, ownership state, and lock files remain ignored. Formal review passed with one medium contract-drift finding queued in the rolling audit. The `.gitignore` implementation was captured by concurrent commit `63e2c33`; S03 commit `813a88b` preserved the shared S04 audit, plan closure, and refreshed feature index.

## Notes

A concurrent `*.bak-*` ignore addition was preserved and excluded from the S04 staged hunk. The broad-ignore removal exposed pre-existing `.vaultspec/runtime/` evidence and provider-local lock files that Core 0.1.48 does not currently ignore; they remain unstaged and are queued for S05/upstream ownership review.
