Architecture navigation
=======================

Use package boundaries to locate behavior. This page describes ownership, not
a fixed count of files or components.

External boundaries
-------------------

:mod:`vaultspec_a2a.api` exposes HTTP and WebSocket schemas and entry points.
:mod:`vaultspec_a2a.protocols` adapts Model Context Protocol traffic.
:mod:`vaultspec_a2a.cli` exposes operator commands.

:mod:`vaultspec_a2a.ipc` defines the neutral contract between the gateway and
worker processes.

Runtime coordination
--------------------

:mod:`vaultspec_a2a.control` coordinates application and infrastructure
services. :mod:`vaultspec_a2a.thread` owns thread-domain state and projections.

:mod:`vaultspec_a2a.context` prepares execution context.
:mod:`vaultspec_a2a.team` defines team topology.
:mod:`vaultspec_a2a.graph` compiles executable graphs.

Execution and events
--------------------

:mod:`vaultspec_a2a.worker` runs graph execution in a separate FastAPI process.
:mod:`vaultspec_a2a.providers` supplies model implementations.

:mod:`vaultspec_a2a.streaming` orders and emits runtime events.
:mod:`vaultspec_a2a.authoring` connects execution to the engine authoring
plane.

Persistence and operations
--------------------------

:mod:`vaultspec_a2a.database` persists runtime state.
:mod:`vaultspec_a2a.lifecycle` manages machine-global development processes.
:mod:`vaultspec_a2a.workspace` manages Git worktrees and environments.

:mod:`vaultspec_a2a.telemetry` instruments API and worker execution.
:mod:`vaultspec_a2a.utils` contains narrow shared helpers.
:mod:`vaultspec_a2a.domain_config` initializes domain configuration.

Continue with :doc:`api/modules` for Python symbols. See :doc:`operations` for
process and command guidance.
