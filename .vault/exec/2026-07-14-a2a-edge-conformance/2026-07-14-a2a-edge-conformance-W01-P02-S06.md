---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S06'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Delete the empty orphan top-level packages (core, cli, tests, bin) and their stale caches after confirming zero inbound references via rag and grep

## Scope

- `src/vaultspec_a2a/core/`
- `src/vaultspec_a2a/cli/`
- `src/vaultspec_a2a/tests/`
- `src/vaultspec_a2a/bin/`

## Description

- Confirm zero inbound references to the empty top-level orphan packages (`core`, `cli`, `tests`, `bin`) via rag and grep before removal.
- Remove the four orphan directories and their stale `__pycache__` caches.
- Verify repository health post-removal: clean import and full test collection.

## Outcome

Done — the four orphan directories are gone (`src/vaultspec_a2a/core`, `cli`, `tests`, `bin` all absent). The deletion was performed by scout-sonnet under the team lead's coordination; the directories held only untracked `__pycache__` bytecode, so the removal produced zero git diff. Health was proven (clean `import vaultspec_a2a`, full test collection). This record is authored after the fact to close the step's one-record contract. Note: `cli/` is intentionally rebuilt later in W04.P11 (operator CLI restoration); deleting the empty husk now is still correct.

## Notes

No tracked files changed (caches only), so there is no code commit for this step. Verified live during W01 wrap-up that all four directories are absent.
