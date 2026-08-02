---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:c315a6b32dd7d00ba28f037f3f9af0aefd7f51db227a3b9eb406e212fc23c737'
step_id: 'S21'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Add the parallel toolchain lane for declaration-derived distribution

## Scope

- `dev/toolchain.py`

## Description

- Add the parallel toolchain lane: the unit gate under -n auto
--dist=loadgroup, workers admitted by the plugin against live peers and
machine capacity.

## Outcome

Committed as 235dc399. The wall-clock delta against the 39m29s serial baseline is deliberately deferred: the box is saturated (sampled load 100 percent) and any figure taken now is noise; owed when quiet. Note: this commit also carried the toolchain owner's uncommitted taplo pin bump (0.9 to 0.9.3) - a pathspec commit takes worktree state, and the hunks could not be split; disclosed to the owner.

## Notes

None.
