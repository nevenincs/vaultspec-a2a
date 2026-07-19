Operator reference
==================

Use ``vaultspec-a2a`` for gateway and local-development operations. Use
``vaultspec-mcp`` for the lazy Model Context Protocol bridge.

Subcommands
-----------

The ``vaultspec-a2a`` command provides these subcommands:

* ``serve`` starts the API server.
* ``doctor`` checks the local environment.
* ``presets`` works with team presets.
* ``run`` starts an execution.
* ``workspace`` provisions and verifies a run workspace's agent harness.
* ``procs`` manages development processes.

Before you automate this command, run ``vaultspec-a2a --help`` to confirm the
installed options.

.. _process-registry:

Process registry
----------------

:mod:`vaultspec_a2a.lifecycle` owns machine-global development-process
configuration, registration, reconciliation, and lifecycle operations.

The process registry isn't :mod:`vaultspec_a2a.thread` lifecycle state. Use the
``procs`` subcommand to inspect and manage registered development processes.

Worker startup
--------------

Uvicorn starts :mod:`vaultspec_a2a.worker` as a separate FastAPI process. No
``vaultspec-worker`` console command exists.

Gateway-worker messages follow :mod:`vaultspec_a2a.ipc`. Runtime events flow
through :mod:`vaultspec_a2a.streaming`.

Related references
------------------

See :doc:`architecture` for package ownership and :doc:`edge-conformance` for
edge verb mappings.
