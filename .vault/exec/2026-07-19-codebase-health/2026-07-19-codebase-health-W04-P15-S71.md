---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S71'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Split project_checkpoint_tuple into immutable checkpoint extraction and response projection stages

## Scope

- `src/vaultspec_a2a/control/thread_state_service.py, tests/control`

## Description

- Confirm the existing projection tests cover the function before touching it.
- Split the ninety-five-line function into an extraction stage and a
  pending-write fold stage, with the public function orchestrating both.
- Move each branch verbatim so the split is mechanical.
- Add tests exercising each stage on its own, which the combined function did not
  permit.

## Outcome

The function did two jobs in one body: it extracted the checkpoint's own immutable fields -
identifiers, timestamps, source, step, updated channels - and then folded the pending-write
and interrupt view onto them. It is now two functions with a thin public orchestrator, and
each stage reads and tests apart.

The existing eight projection tests pass unchanged, so the observable result of the public
function is identical. Six new tests exercise the stages independently: extraction produces
the immutable description with an empty pending view, stamps the checkpoint id into the
resumable config, and the fold adds pending writes, interrupts, the pause cause, and the
degraded reasons for an unknown history or a malformed interrupt payload. One asserts the
public function equals the two stages run in order, which pins the orchestration itself.

Gates: `ruff check` clean, `ty check` clean, and the thread, projection, and control suites
report three hundred forty-two passed.

## Notes

The fold stage mutates the projection in place rather than returning a new one. That was a
deliberate choice over a functional split: the base fields the extraction produced are
already final, and only the pending-work view is being layered on, so a copy would add
allocation and a second object to reason about for no gain. The docstring records the
reasoning so the in-place mutation reads as intended rather than as an oversight.

The scope names ``thread_state_service`` but the function lives in ``thread/snapshots`` and
is imported by the state service. The split was made where the function is defined, which is
the only place it can be, and the state service consumes it unchanged.
