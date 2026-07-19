"""Group application and infrastructure services for runtime control.

Services supervise workers, monitor health, dispatch work, handle events,
maintain projections, and orchestrate threads, messages, cancellation,
permissions, teams, and repair. Run-start policy and authoring verdict
subscription also live in this layer.

Import implementations from direct child modules, including
:mod:`vaultspec_a2a.control.cancel_service`,
:mod:`vaultspec_a2a.control.message_service`,
:mod:`vaultspec_a2a.control.run_start_policy`, and
:mod:`vaultspec_a2a.control.verdict_subscriber`.

Control services coordinate :mod:`vaultspec_a2a.thread`,
:mod:`vaultspec_a2a.database`, :mod:`vaultspec_a2a.streaming`,
:mod:`vaultspec_a2a.authoring`, and :mod:`vaultspec_a2a.worker`.
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
    "verdict_subscriber",
    "worker_management",
]
