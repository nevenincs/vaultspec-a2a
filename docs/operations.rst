Operator reference
==================

Use the project-locked Just facade to route product operations, named host
processes, and Compose stacks to their owning implementation.

Command discovery
-----------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Command
     - Scope
   * - ``just help``
     - List top-level repository commands.
   * - ``just dev help``
     - List development modules.
   * - ``just dev <module> help``
     - List commands in one development module.
   * - ``just dev product help``
     - List product passthrough recipes.
   * - ``just dev product cli --help``
     - Display the native product CLI reference.

Just selects frozen project dependencies and routes arguments. It owns no
product behavior.

Product command-line interface (CLI)
------------------------------------

``just dev product cli`` exposes the native :mod:`vaultspec_a2a.cli` command
surface, including ``serve``, ``doctor``, ``presets``, ``run``, ``workspace``,
and ``procs``. The table lists shorter Just wrapper routes. ``product mcp``
targets a separate MCP console command rather than the native product CLI.

.. list-table::
   :header-rows: 1
   :widths: 44 56

   * - Route
     - Destination
   * - ``just dev product cli serve``
     - Start the caller-owned :mod:`vaultspec_a2a.api` gateway.
   * - ``just dev product doctor``
     - Report gateway health.
   * - ``just dev product presets``
     - List available team presets.
   * - ``just dev product run``
     - Run start, status, or cancellation operations.
   * - ``just dev product workspace``
     - Provision or verify a run workspace through
       :mod:`vaultspec_a2a.cli.provision` and
       :mod:`vaultspec_a2a.context.harness`.
   * - ``just dev product mcp``
     - Run the separate Model Context Protocol (MCP) console bridge from
       :mod:`vaultspec_a2a.protocols.mcp`.

``just doctor`` diagnoses repository prerequisites. It is distinct from
``just dev product doctor``, which checks gateway health. A foreground gateway
is attached to its invoking terminal; the caller owns its lifetime.

.. _process-registry:

Named host-process registry
---------------------------

The :mod:`vaultspec_a2a.lifecycle` machine-global registry exclusively owns
named development-process allocation, registration, liveness, restart state,
and process-tree termination. The ``just dev service`` recipes pass through to
``vaultspec-a2a procs``.

Square brackets mark optional arguments; don't type the brackets.

.. list-table::
   :header-rows: 1
   :widths: 54 46

   * - Route
     - Operation
   * - ``just dev service gateway-up [NAME]``
     - Start a gateway under an optional registry name.
   * - ``just dev service worker-up [NAME]``
     - Start a :mod:`vaultspec_a2a.worker` process under an optional registry
       name.
   * - ``just dev service engine-up NAME REPO BUILD_REPO WORKSPACE``
     - Start an explicitly named engine seat.
   * - ``just dev service list``
     - List registrations, liveness, and endpoints.
   * - ``just dev service attach NAME``
     - Verify that a named process is live and print its endpoint.
   * - ``just dev service kill NAME``
     - Terminate its process tree and remove its registration.
   * - ``just dev service allocate ROLE``
     - Reserve the next available role port.
   * - ``just dev service rebuild NAME``
     - Run the registered build command.
   * - ``just dev service rerun NAME``
     - Kill, rebuild, and restart on the same port.
   * - ``just dev service resume NAME``
     - Restart a dead registration on its original port.
   * - ``just dev service reap``
     - Terminate and clear stale or dead registrations.

The registry is distinct from :mod:`vaultspec_a2a.thread` application
lifecycle, caller-owned foreground execution, and Compose-owned stacks.

Compose-owned stacks
--------------------

Docker Compose exclusively owns multi-service stack lifecycle.

#. Run ``just doctor`` to verify Docker support.
#. Inspect the development configuration, then start its isolated Compose
   project:

   .. code-block:: console

      just dev stack dev-config
      just dev stack dev-up

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

See :doc:`architecture` for ownership, :doc:`glossary` for terminology, and
:doc:`edge-conformance` for Hypertext Transfer Protocol (HTTP) edge mappings.
