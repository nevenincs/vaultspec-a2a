---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:339002d136895f0de78578fcbbc0839388201abefe3a44e4d55bf24b0e4c292e'
step_id: 'S144'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Run the A2A real-process acceptance suites

## Scope

- `tests/acceptance`
- `src/vaultspec_a2a/desktop_tests`
- `src/vaultspec_a2a/service_tests`

## Description

- Ran the acceptance, desktop, and service suites together as real processes.

## Outcome

PASS. 46 passed, 74 deselected, in 9m22s.

## Notes

The Step's command names `tests/acceptance`, which does not exist. The suite
lives beside the code it certifies because the project's test paths point there
and a tree outside them would never be collected. Several sibling Steps carry
the same stale path.

A first attempt reported one failure and was discarded as self-inflicted rather
than investigated as a defect: port-claiming suites were running in the
foreground while this ran in the background, and the failing test took 25s under
that contention against 1.5s in isolation. The clean re-run passed.

That was the third misleading result in this campaign from overlapping
real-process work. These suites claim real ports and spawn real gateways, and
are not safe to overlap with each other or with an edit to the tree beneath
them.
