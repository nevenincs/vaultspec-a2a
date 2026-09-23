Operator reference
==================

Use the project-locked Just facade to route product operations, named host
processes, and Docker Compose (Compose) stacks to their owning implementation.

Command discovery
-----------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Command
     - Scope
   * - ``just``
     - List every recipe, grouped by consequence.
   * - ``just --list --unsorted``
     - The same list in declaration order.
   * - ``just product-cli --help``
     - Display the native product CLI reference.

Just selects frozen project dependencies and routes arguments. It owns no
product behavior.

Configuration and state
-----------------------

Every setting is read by one settings authority,
:mod:`vaultspec_a2a.control.config`, under the ``VAULTSPEC_A2A_`` prefix. A
variable that names another tool's configuration (``OPENAI_API_KEY``,
``CODEX_HOME``, ``CI``, the ``OTEL_*`` names) is also read under that tool's own
spelling, with the ``VAULTSPEC_A2A_`` name winning when both are set. The
repository's ``.env.example`` lists every setting, and a test holds the example
and the settings to each other in both directions.

**Project root.** ``VAULTSPEC_A2A_PROJECT_ROOT`` names the project a2a serves;
unset, it is the nearest ancestor of the working directory holding
``.vaultspec/`` or ``.vault/``, then one holding ``.git``, else the working
directory. The project's ``.env`` is read from that root, so a process started
anywhere inside the project reads the same file. The root itself is read from
the process environment only.

**State home.** ``VAULTSPEC_A2A_HOME`` defaults to ``.vault/data/agents`` in the
project root - the runtime subtree vaultspec ignores and never walks. a2a
writes nothing to the user profile or the system temporary directory, and it
seals the home with a self-ignoring ``.gitignore`` so a project without
vaultspec's ignore rules cannot commit it. One layout,
:func:`vaultspec_a2a.control.state_layout.state_layout`, places everything
beneath the home:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Path
     - Contents
   * - ``state/vaultspec.db``, ``state/checkpoints.db``
     - Application database and LangGraph checkpoints, unless
       ``VAULTSPEC_A2A_DATABASE_URL`` or ``VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL``
       names another store.
   * - ``runtime/``
     - Gateway, worker and MCP logs and the gateway singleton lock.
   * - ``service.json``, ``service.token``
     - The discovery record the engine attaches through, and its
       owner-restricted handoff credential.
   * - ``procs/``
     - The named host-process registry, its port reservations and test leases,
       unless ``VAULTSPEC_A2A_PROCS_HOME`` names another directory.
   * - ``tmp/homes/``
     - Per-run provider configuration homes.

**Relative paths.** Every path setting accepts an absolute path or one relative
to the project root - never to the working directory, so two processes of one
project open the same files wherever each was launched. The armed desktop
profile (``VAULTSPEC_A2A_DESKTOP_APP_HOME``, set by the dashboard) derives the
same layout from its application home instead.

Product command-line interface (CLI)
------------------------------------

``just product-cli`` exposes the native :mod:`vaultspec_a2a.cli` command
surface, including ``serve``, ``doctor``, ``presets``, ``run``, ``workspace``,
and ``procs``. The table lists shorter Just wrapper routes. ``product mcp``
targets a separate MCP console command rather than the native product CLI.

.. list-table::
   :header-rows: 1
   :widths: 44 56

   * - Route
     - Destination
   * - ``just product-cli serve``
     - Start the caller-owned :mod:`vaultspec_a2a.api` gateway.
   * - ``just product-doctor``
     - Report gateway health.
   * - ``just product-presets``
     - List available team presets.
   * - ``just product-run``
     - Run start, status, or cancellation operations.
   * - ``just product-workspace``
     - Provision or verify a run workspace through
       :mod:`vaultspec_a2a.cli.provision` and
       :mod:`vaultspec_a2a.context.harness`.

``just doctor-check`` diagnoses repository prerequisites. It is distinct from
``just product-doctor``, which checks gateway health. A foreground gateway
is attached to its invoking terminal; the caller owns its lifetime.

Gateway bearer authentication
-----------------------------

The engine-facing ``/v1`` routes require a gateway bearer token. The gateway
uses its configured service token or generates a fresh token when none is
configured. It publishes the credential in the adjacent, owner-restricted
``service.token`` handoff file. The ``service.json`` discovery record in the
state home is secret-free: its ``handoff_reference`` names that file but never
embeds the token.

Product CLI calls use :func:`vaultspec_a2a.lifecycle.discovery.read_resident_service`
to follow a validated handoff reference automatically, but only for a fresh
record whose port matches the requested loopback endpoint. Direct clients with
authority to read the handoff credential must send
``Authorization: Bearer <token>``; an absent or invalid bearer returns ``401``.
The top-level ``/health`` liveness route remains public so local supervisors can
probe the process. Discovery publication and credential-file validation are
implemented by :mod:`vaultspec_a2a.lifecycle.discovery`.

Authentication is implemented by
:func:`vaultspec_a2a.api.auth.authenticate_request` and wired by
:func:`vaultspec_a2a.api.app.create_app`. The
``allow_unauthenticated_v1_for_testing`` application option is test-only and
must never be enabled by an operator deployment.

Desktop store migration
-----------------------

``vaultspec-a2a migrate`` is the dashboard-spawnable migrate step of the
dashboard's own update transaction, not an interactive run-control command. The
dashboard owns ordering (drain, snapshot, migrate, activate) and rollback via
its own snapshot; after quiescing the old gateway it spawns ``migrate``, which
executes a2a's schema work through
:func:`vaultspec_a2a.desktop.migration.migrate_stores`, prints a bounded JSON
:class:`vaultspec_a2a.desktop.migration.MigrationResult`, and exits nonzero when
store locking, schema migration, checkpointer setup, or the state backfill
fails. The ``setup`` verb initialises fresh stores for a new install through the
same authority via
:func:`vaultspec_a2a.desktop.migration.initialize_fresh_stores`.

Active-run discovery
--------------------

``GET /v1/runs?state=active`` returns a bounded, newest-first identity
projection for viewer rebinding. Optional absolute ``workspace_root`` and
``feature_tag`` selectors narrow the indexed query, and ``limit`` is capped at
100. The result from
:func:`vaultspec_a2a.control.run_discovery_service.discover_active_runs` is not
an authoritative recovery snapshot: after selecting a run id, read that run's
status surface to obtain its current recovery state. The route uses the same
``/v1`` bearer authentication described above.

.. _process-registry:

Named host-process registry
---------------------------

The :mod:`vaultspec_a2a.lifecycle` project registry exclusively owns
named development-process allocation, registration, liveness, restart state,
and process-tree termination. The ``service-*`` recipes pass through to
``vaultspec-a2a procs``.

Square brackets mark optional arguments; don't type the brackets.

.. list-table::
   :header-rows: 1
   :widths: 54 46

   * - Route
     - Operation
   * - ``just service-gateway-up [NAME]``
     - Start a gateway under an optional registry name.
   * - ``just service-worker-up [NAME]``
     - Start a :mod:`vaultspec_a2a.worker` process under an optional registry
       name.
   * - ``just service-engine-up NAME REPO BUILD_REPO WORKSPACE``
     - Start an explicitly named engine seat.
   * - ``just service-list``
     - List registrations, liveness, and endpoints.
   * - ``just service-attach NAME``
     - Verify that a named process is live and print its endpoint.
   * - ``just service-kill NAME``
     - Terminate its process tree and remove its registration.
   * - ``just service-allocate ROLE``
     - Reserve the next available role port.
   * - ``just service-rebuild NAME``
     - Run the registered build command.
   * - ``just service-rerun NAME``
     - Kill, rebuild, and restart on the same port.
   * - ``just service-resume NAME``
     - Restart a dead registration on its original port.
   * - ``just service-reap``
     - Terminate and clear stale or dead registrations.

The registry is distinct from :mod:`vaultspec_a2a.thread` application
lifecycle, caller-owned foreground execution, and Compose-owned stacks.

Compose-owned stacks
--------------------

Docker Compose exclusively owns multi-service stack lifecycle.

#. Run ``just doctor-check`` to verify Docker support.
#. Inspect the development configuration, then start its isolated Compose
   project:

   .. code-block:: console

      just stack-dev-config
      just stack-dev-up

.. list-table::
   :header-rows: 1
   :widths: 18 22 18 20 22

   * - Family
     - Inspect
     - Start
     - Status
     - Stop
   * - Development
     - ``dev-config``
     - ``dev-up``
     - ``dev-status``
     - ``dev-down``
   * - Integration
     - ``integration-config``
     - ``integration-up``
     - ``integration-status``
     - ``integration-down``
   * - Database
     - ``database-config``
     - ``database-up``
     - ``database-status``
     - ``database-down``
   * - Production
     - ``prod-config``
     - ``prod-up``
     - ``prod-status``
     - ``prod-down``
   * - Infrastructure
     - ``infrastructure-config``
     - ``infrastructure-up``
     - ``infrastructure-status``
     - ``infrastructure-down``

The database family starts PostgreSQL from the production configuration plus
its database overlay. The infrastructure family starts Jaeger. Don't register
Compose services as named host processes.

Scratchpad convention
---------------------

Put probe scripts, logs, ad hoc databases, and other disposable session output
in the harness-assigned scratchpad. Without a harness path, use the ignored
repository-root ``scratchpad/`` directory. Don't put exploratory output in the
repository root, ``src/``, or another tracked directory.

See :doc:`architecture` for ownership and :doc:`glossary` for terminology.
