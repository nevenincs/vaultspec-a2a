Architecture navigation
=======================

Use package boundaries to locate behavior. This page describes ownership, not
a fixed count of files or components.

External boundaries
-------------------

:mod:`vaultspec_a2a.api` exposes application programming interface (API)
schemas and Hypertext Transfer Protocol (HTTP) and WebSocket entry points.
:mod:`vaultspec_a2a.protocols` adapts Model Context Protocol (MCP) traffic.
:mod:`vaultspec_a2a.cli` exposes command-line interface (CLI) operator commands.

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
:mod:`vaultspec_a2a.desktop` defines the stable desktop capsule contract and
manifest emission boundary. Workflow-internal
:mod:`vaultspec_a2a.desktop.artifacts`, :mod:`vaultspec_a2a.desktop.capsule`,
and :mod:`vaultspec_a2a.desktop.capsule_evidence` verify exact inputs, project
bounded archive content, and publish installed-tree evidence.
:mod:`vaultspec_a2a.lifecycle` manages machine-global development processes.
:mod:`vaultspec_a2a.workspace` manages Git worktrees and environments.

:mod:`vaultspec_a2a.telemetry` instruments API and worker execution.
:mod:`vaultspec_a2a.utils` contains narrow shared helpers.
:mod:`vaultspec_a2a.domain_config` initializes domain configuration.

Repository control-surface ownership
------------------------------------

Each control surface has one owner so local development, automation, and
continuous integration (CI) don't make conflicting lifecycle or configuration
decisions. Docker Compose (Compose) owns coordinated multi-service stacks.

.. list-table::
   :header-rows: 1
   :widths: 29 29 42

   * - Control surface
     - Owner
     - Boundary
   * - Task entry points
     - Just
     - Provides the facade without product or lifecycle logic.
   * - Product behavior
     - ``vaultspec-a2a``
     - Implements product operations and defines their behavior.
   * - Foreground execution
     - Caller
     - Retains process lifetime and interruption.
   * - Named host processes
     - Process registry
     - Owns identity, allocation, liveness, and lifecycle.
   * - Multi-service stacks
     - Compose
     - Owns coordinated stack state and teardown.
   * - Dependencies and tools
     - ``uv.lock``
     - Selects resolved dependency and tool versions.
   * - Framework-managed files
     - Vaultspec Core
     - Reconciles its managed Git-ignore block and provider projections.
   * - Validation
     - CI gates
     - Report drift without intentional source mutation.
   * - Drift correction
     - Explicit maintenance verbs
     - Repair, sync, and upgrade managed state intentionally.

Bypassing an owner creates conflicting process, stack, dependency, or
generated-file state. Core derives projections from canonical inputs; CI
reports mismatches; explicit maintenance verbs apply mutations.

Continue with :doc:`api/modules` for Python symbols, :doc:`development` for
contributor entry points, :doc:`operations` for lifecycle guidance, and
:doc:`glossary` for the terms used here.
