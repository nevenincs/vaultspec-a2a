---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `a2a-edge-conformance` audit: `worktree and branch reconciliation`

## Scope

Reconciliation audit of all unmerged git state around this repository before
conformance execution begins (owner-flagged, scout-audited 2026-07-14): 4
local branches unmerged into main, 3 registered sibling worktrees, 1
orphaned on-disk directory, 4 stashes, and 3 `origin/claude/*` remote
branches. The question per item: does it contain work that must merge, be
consciously superseded, or be discarded - under the governing ADR's
fluidity qualifier (nothing is authoritative until verified) and before
wave W02 touches overlapping files.

## Findings

### branch-17-live-overlap | high | the only live item; overlaps W02 write-seam and streaming files

`feature/integration-testing-smoke-tests-api-veri-17` is 9 commits ahead
(main is 33 ahead of it): 28 files, +739/-49, touching CURRENT architecture
files - `control/thread_service.py`, `database/artifact_repository.py`,
`graph/compiler.py`, `graph/enums.py`, `graph/nodes/supervisor.py`,
`graph/nodes/vault_reader.py`, `graph/tools/task_queue.py`,
`providers/_acp_rpc_handlers.py`, and six `streaming/*.py` modules. Commit
subjects: audit closeouts 8-10, an SSE close-after-terminal fix, a
PipelinePhase enum for typed phase routing, artifact safety / input bounds
/ subprocess caps, delete-boundary hardening with artifact path redaction,
and PR review fixes. Direct collision with this plan: `task_queue.py` and
`_acp_rpc_handlers.py` are W02.P05's write-seam files, and the streaming
modules are W02.P04 sweep and W04.P10 targets. Merge or conscious
supersession MUST precede W02.

### everything-else-dead | medium | all other items verified merged, stale, or empty

Worktrees `claude-test`, `feature-devrunner-smoke-test-13`,
`feature-service-orchestration-lifecycle-manageme-18`, and branch
`angry-jemison` have tips 0 commits ahead of main - fully merged, clean
checkouts (the lifecycle-18 worktree, initially suspected of overlapping
the R8 discovery work, contains nothing unmerged). The orphaned directory
`feature-ui-integration-wire-regen-28` is not a registered worktree and
holds only an empty vault research directory and transient SQLite files.
All 4 stashes predate the `src/` restructure, the Svelte-to-React rewrite,
or the docs-to-vault migration - unrestorable against the current tree.
The 3 `origin/claude/*` remote branches are Figma/Svelte-era artifacts.

### branch-control-layer-dead | low | 219 behind, touches deleted paths

`feature/control-layer` is 219 commits behind main and its diffs touch
paths deleted by the landed decomposition; nothing salvageable.

### branch-entry-point-possible-residue | low | duplicate lineage; only test diffs possibly novel

`feature/entry-point-layer` duplicates the lineage of the already-landed
entry-point decomposition; the only possibly-novel content is conftest and
vowel-counter test diffs, worth a spot-check before deletion.

### branch-ci-23-moot | low | UI wire-types regen mooted by the UI deletion

`feature/ci-resolve-vaultspec-core-dep-23` is mostly UI wire-type
regeneration (moot: W02.P03 deletes the UI) plus unrelated CI housekeeping.
Defer; discard once W02.P03 lands unless the CI housekeeping proves wanted.

## Recommendations

- Branch -17: the owner decides merge versus conscious supersession before
  W02 starts (merge commits only; squash/rebase disabled repo-wide). If
  superseded, record what each of its six themes is superseded BY in the
  step record executing the decision.
- Spot-check `feature/entry-point-layer` conftest and vowel-counter test
  diffs for novel coverage before deletion; harvest into a step record if
  any.
- Bulk-discard everything else (worktree remove, stash drops, local and
  remote branch deletes, orphan directory removal) under explicit owner
  authorization - destructive, irreversible once remotes are pruned.
- Defer `feature/ci-resolve-vaultspec-core-dep-23` until W02.P03 lands,
  then re-triage its CI housekeeping only.

Owner dispositions (decided 2026-07-14, interactive sign-off; executed by
plan steps S34/S36): branch -17 is review-merged in full - merge commit,
full test baseline before and after. Local cleanup is authorized: merged
worktrees, all four stashes, stale local branches, and the orphan directory
go; remote branches are NOT deleted (`origin/claude/*` remain), and
`feature/ci-resolve-vaultspec-core-dep-23` stays untouched pending W02.P03.
