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

Scratchpad convention
----------------------

Probe scripts, one-off log captures, ad hoc databases, and other exploratory
artifacts a development session produces belong under a session-scoped
scratchpad directory, never the repository root. A stray file at the repo
root is untracked clutter that survives across sessions and pollutes ``git
status``; a scratchpad directory is disposable by construction and git-ignored.

When working through an agent harness that provisions one, use the
harness-assigned scratchpad path. Otherwise, create a ``scratchpad/``
directory at the repository root (already git-ignored) and write artifacts
there. Never write probe output, temporary databases, or log captures
directly into ``src/``, the repository root, or any tracked directory.

Related references
------------------

See :doc:`architecture` for package ownership and :doc:`edge-conformance` for
edge verb mappings.
