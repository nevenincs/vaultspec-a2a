---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-8` `step-2`

Extracted state projection and terminal event emission into `StateProjector` class.

- Created: `src/vaultspec_a2a/worker/state_projection.py` (297 lines)

## Description

Moved the following methods from `Executor` into a new `StateProjector` class:

- `_pre_flight_checkpoint` -> `pre_flight_checkpoint` (public, takes `thread_known` bool instead of reading `_thread_to_cache_key` directly)
- `_normalize_execution_state` -> `normalize_execution_state` (static method)
- `_emit_execution_state_projection` -> `emit_execution_state_projection`
- `_emit_terminal_status` -> `emit_terminal_status`

The class accepts `checkpointer`, `bridge`, and an optional `log_extra_fn` callable for structured logging. `Executor` creates the projector in `__init__` and passes `self._log_extra` as the log helper. No shared mutable state -- the projector only reads the checkpointer and writes to the bridge.

## Tests

51 worker tests pass. Full suite: 1041 passed, 9 pre-existing failures in `test_factory.py` (unrelated).
