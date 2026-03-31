"""control — infrastructure services and dev-tooling.

Pure domain logic (enums, state machine, snapshot dataclasses) has been
extracted to ``thread/enums``, ``thread/transitions``, and
``thread/snapshots`` respectively.  This package retains only
infrastructure concerns: process supervision, health, dispatch, and
dev-tooling.

Production runtime modules:

    config              — application settings (pydantic-settings)
    circuit_breaker     — WorkerCircuitBreaker
    diagnostics         — missing-thread classification, mark_thread_failed
    dispatch            — dispatch_to_worker consolidated dispatch function
    health              — assemble_health_status, SQLite fallback diagnostics
    permission_service  — permission response orchestration (extracted from route)
    team_service        — team status assembly (extracted from route)
    worker_management   — LazyWorkerSpawner, WorkerWatchdog, WorkerState
    event_handlers      — relay_event, terminal/permission/progress/execution
                          state event handlers
    projection          — checkpoint and execution-state projection helpers
    snapshot            — snapshot enrichment from LangGraph state

Dev-tooling modules invoked via ``python -m``:

    python -m vaultspec_a2a.control.db      migrate [--fix]
    python -m vaultspec_a2a.control.db      snapshot [list]
    python -m vaultspec_a2a.control.db      restore --name FILE
    python -m vaultspec_a2a.control.db      clear --yes
    python -m vaultspec_a2a.control.hooks   install
"""

from __future__ import annotations

__all__ = [
    "circuit_breaker",
    "config",
    "db",
    "diagnostics",
    "dispatch",
    "event_handlers",
    "health",
    "hooks",
    "permission_service",
    "projection",
    "repair_transitions",
    "snapshot",
    "team_service",
    "thread_service",
    "thread_state_service",
    "worker_management",
]
