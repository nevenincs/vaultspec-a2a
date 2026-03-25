"""control — infrastructure services and dev-tooling.

Production runtime modules:

    config              — application settings (pydantic-settings)
    circuit_breaker     — WorkerCircuitBreaker
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
    python -m vaultspec_a2a.control.verify  prodlike_docker
    python -m vaultspec_a2a.control.verify  provider <name>
    python -m vaultspec_a2a.control.doctor  [all|ports|config|services]
"""

from __future__ import annotations

__all__ = [
    "circuit_breaker",
    "config",
    "db",
    "doctor",
    "event_handlers",
    "projection",
    "snapshot",
    "verify",
    "worker_management",
]
