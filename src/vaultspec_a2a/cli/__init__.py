"""Provide the ``vaultspec-a2a`` command-line interface.

:func:`vaultspec_a2a.cli.main.main` dispatches subcommands for serving,
diagnostics, presets, runs, workspaces, and development processes.

The ``serve`` subcommand routes to :mod:`vaultspec_a2a.api.app`. The ``procs``
subcommand uses :mod:`vaultspec_a2a.lifecycle`. The ``workspace`` subcommand
delegates provisioning to :mod:`vaultspec_a2a.cli.provision`, which verifies
the agent harness through :mod:`vaultspec_a2a.context.harness`.

See :doc:`/operations` for operator-facing command and process guidance.
"""

from .main import main as main

__all__ = ["main"]
