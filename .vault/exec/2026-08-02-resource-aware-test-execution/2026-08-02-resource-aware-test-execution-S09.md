---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:53c72b1d3d597b6c177db343da7beffa2ab59fd1242c31f9ff2c7a2baae9a687'
step_id: 'S09'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Prove lease serialization and declaration-derived concurrency with real subprocess runs

## Scope

- `src/vaultspec_a2a/testing/tests/`

## Description

- Land the framework's own real-behavior suite in `src/vaultspec_a2a/testing/tests/`: lease exclusion, dead-holder and frozen-heartbeat reclaim, shared/exclusive interplay, cross-process serialization, progress-deadline verdicts against real child processes and records, endpoint resolution against real HTTP listeners, and subprocess pytest evidence runs.

## Outcome

Committed as d7d026f2 (with 2eae4ec5 guarding collection). Evidence from a real `-n 2 --dist=loadgroup` run: contended pair on one worker at 0.000-1.002s then 1.012-2.012s (no overlap); disjoint group on the other worker fully overlapping it; blind `-n` refused; undeclared fixture use refused; 40/40 tests green in 62s.

## Notes

None.
