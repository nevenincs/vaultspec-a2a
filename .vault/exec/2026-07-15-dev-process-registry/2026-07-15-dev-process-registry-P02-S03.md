---
tags:
  - '#exec'
  - '#dev-process-registry'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S03'
related:
  - "[[2026-07-15-dev-process-registry-plan]]"
---

# Route the gateway/worker serve paths, the engine-serve wrapper script, and the live-test/service-harness fixtures through registry registration and band-allocated ports

## Scope

- `repoint the port-asserting MCP tests at the declared bands`
- `src/vaultspec_a2a/api/app.py`
- `src/vaultspec_a2a/worker/`
- `scripts/`
- `src/vaultspec_a2a/service_tests/`
- `src/vaultspec_a2a/protocols/mcp/tests/`

## Description

- Close the allocate-and-claim race the S01 reviewer carried forward: add
  `reserve_port` to the registry - an atomic `O_EXCL` reservation marker keyed on
  `<role>-<port>` so two concurrent same-band callers can never receive the same
  port. `commit_reservation` writes the real record and clears the marker;
  `release_reservation` frees it; a marker older than the TTL with no live record
  is reclaimable, so a crash between reserve and commit cannot wedge a band port.
  `allocate_port` now also skips live reservations.
- Add the boot verb the registry was missing: `serve_up` reserves a band port,
  spawns the role's serve command on it, waits for a live listener, then commits
  the claiming record - retrying the next band port (failed reservations held) when
  a child dies or a non-registry racer takes the port. Expose it as `procs up
  <role> <name>` plus `procs allocate <role>` (reserve-and-print) on the operator
  CLI.
- Adopt the registry in the serve paths: the gateway (`api/app.py`) and worker
  (`worker/app.py`) self-register on startup and deregister on owned shutdown, and
  the gateway refreshes its record on the existing discovery-heartbeat cadence.
  Registration is band-gated - a resident instance on its fixed out-of-band port
  registers nothing - so production behaviour is unchanged by construction.
- Add the engine-serve wrapper `scripts/engine_serve.py` (the `engine-dev` serve
  command in procs.toml): register the band-port engine, launch the workspace-local
  `vaultspec serve --no-seat` engine (command overridable via
  `VAULTSPEC_ENGINE_SERVE_CMD`), heartbeat the record, and deregister on shutdown -
  wrapper-based adoption that never modifies the engine binary.
- Correct the stale MCP error-path test docstring: the connection-error tests hit
  an unreachable ASGI base, never a hardcoded live-service port, so a resident
  gateway can never accidentally satisfy them.

## Outcome

- 18 new/extended lifecycle tests pass (56 in the lifecycle suite total) against
  real registry files, real reservation markers, real subprocesses, and real
  loopback binds - no mocks. `test_serve_up_boots_registers_and_picks_distinct_ports`
  proves two boots land on distinct band ports; the reservation tests prove
  exclusivity, commit/release, and stale-marker reclamation.
- `ruff check`, `ruff format --check`, and `ty check` are clean across the
  registry, manager, registration, CLI, gateway, worker, and engine wrapper;
  gateway/worker imports verified.
- Created: `src/vaultspec_a2a/lifecycle/registration.py`,
  `scripts/engine_serve.py`, `src/vaultspec_a2a/lifecycle/tests/test_registration.py`.
- Modified: `src/vaultspec_a2a/lifecycle/registry.py`, `manager.py`, `__init__.py`,
  `tests/test_registry.py`, `tests/test_manager.py`, `tests/conftest.py`,
  `src/vaultspec_a2a/cli/main.py`, `src/vaultspec_a2a/api/app.py`,
  `src/vaultspec_a2a/worker/app.py`,
  `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

## Notes

- Registration is inert for resident/out-of-band ports (returns `None`), so the
  production gateway on 8000 and engine on 8767 register nothing - the ADR's
  "resident instances are never managed" rule holds by construction, not a flag.
- The Docker-compose service-harness port helper was left on OS-ephemeral
  allocation: that harness needs Docker, unavailable in this environment (ADR S06
  not-run), so a band-routing change there is unverifiable here; the local
  acceptance path already targets the gateway-dev band (18100). Flagged for the
  driver rather than shipped unverified.
- The engine-serve wrapper is correct-by-construction but not run here: no engine
  binary is present in this worktree, and the exact engine port flag is kept in
  configuration (`VAULTSPEC_ENGINE_SERVE_CMD`) rather than hardcoded.
- Post-review hardening (review-fanout REVIEW 7 MEDIUM + LOW): reservation reclaim
  is now liveness-aware - a marker whose stored reserver pid is dead is reclaimed
  immediately (fast crash recovery), with the mtime-TTL demoted to a generous
  pid-reuse backstop so the reclaim never couples to a caller's reserve-to-commit
  span. `register_serve` is now non-fatal - a registry write fault degrades to
  "unregistered" and logs rather than crashing a serving gateway/worker, matching
  the heartbeat's stance.
