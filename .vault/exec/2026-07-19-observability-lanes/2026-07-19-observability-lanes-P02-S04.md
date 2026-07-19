---
tags:
  - '#exec'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S04'
related:
  - "[[2026-07-19-observability-lanes-plan]]"
---

# Close loop-hygiene residuals and test-output noise: dedup the dispatch reconciling-redispatch failure log (state change plus every Nth repeat), give the websocket client-heartbeat failure the worker heartbeat's escalation ladder, remove log_cli from default pytest config documenting the opt-in, and document the scratchpad artifact convention. Live tests for both loop-hygiene changes

## Scope

- `src/vaultspec_a2a/control/dispatch.py`
- `src/vaultspec_a2a/api/websocket.py`
- `pyproject.toml`
- `docs/`

## Description

- Add `_log_redispatch_failure_ladder` and `_REDISPATCH_LOG_EVERY_N` to `control/dispatch.py`; `redispatch_reconciling_threads` now logs a circuit-open or redispatch-error failure in full only on its 1st occurrence and every Nth repeat within the batch (mirroring the worker heartbeat ladder in `worker/ipc.py`), tracked per failure category so switching categories mid-batch always logs at its own occurrence 1. A batch-end INFO summary reports the total count for any category that was suppressed.
- Add `_consecutive_heartbeat_failures`, `_log_heartbeat_failure`, and `_record_heartbeat_success` to `ConnectionManager` in `api/websocket.py`; the idle-heartbeat send-failure path now escalates the same way (1st + every Nth full WARNING, INFO on recovery), scoped across all clients since a single client's writer loop already breaks on its own first failure (there is no per-connection "consecutive" to track).
- Removed `log_cli`/`log_cli_level` from the default `[tool.pytest.ini_options]` in `pyproject.toml` (kept `log_cli_format`/`log_cli_date_format` so the opt-in still gets a readable format); documented the `-o log_cli=true` opt-in inline. Verified `pyproject.toml` was clean of the contending parallel session's edits before touching it.
- Documented the scratchpad artifact convention in `docs/operations.rst` and added `scratchpad/` to `.gitignore` (it was previously untracked, not actually ignored, contradicting the convention being documented). Verified `docs/` was clean of the contending parallel session's untracked scaffold before touching it, and confirmed a Sphinx build (`sphinx-build -b html docs docs/_build/html`) still succeeds with the new section.
- Live tests (real DB, real threads, a real forced-open circuit breaker, real logging - no mocks): `control/tests/test_redispatch_failure_ladder.py` drives 12 real RECONCILING threads through a real circuit-open failure and asserts exactly 3 WARNING lines (occurrence 1, 5, 10) plus 1 summary, and a lone-failure case asserts 1 WARNING with no summary. `api/tests/test_websocket.py::TestHeartbeatFailureLadder` exercises the production ladder/recovery methods directly on a real `ConnectionManager` instance with a real logger (a graceful WebSocket disconnect drains and cancels the writer task before any heartbeat timeout could fire, so a live-socket failure cannot reach this branch through the wire in this harness - noted as the reason for testing at the method level rather than over a real connection).

## Outcome

The reconciling-redispatch and websocket-heartbeat failure logs both now follow the same escalation-ladder idiom as the existing worker heartbeat loop instead of re-logging identically per occurrence. Default `pytest` runs are quiet (no live log streaming) with a documented, discoverable opt-in. The scratchpad convention is documented and now actually enforced by `.gitignore`. All touched modules pass ruff, ty, and their live test suites (see S03 record for the venv-repair note that also covers this step's verification).

## Notes

No incidents beyond the shared-venv repair already recorded in the S03 record (same session, same root cause). `pyproject.toml` and `docs/` were both confirmed clean of contention (per the team-lead's hold instruction) immediately before editing - `pyproject.toml`'s last touching commit was unrelated desktop-wheel work, and `docs/` had already landed via `exec-s37`'s P01.S02 commit.
