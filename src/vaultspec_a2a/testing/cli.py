"""Run the real ``vaultspec-a2a`` operator CLI in a child process.

The one runner for suites that drive a CLI verb end to end. A child process
rather than an in-process call because every verb reads the process-wide
settings singleton: configuring a child through its environment exercises the
real configuration path, where reaching into the singleton would only prove that
the singleton can be overwritten. The argv comes from the runtime's own
self-execution authority, so the child is the CLI an installed runtime runs.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ..utils.runtime_exec import self_command
from .children import run_child

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Mapping

__all__ = ["run_cli"]


def run_cli(
    *argv: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``vaultspec-a2a *argv`` to completion, capturing its text output.

    *env* overlays the inherited environment, so a caller can point the
    configured ports, stores or timeouts somewhere specific without having to
    restate everything else the child needs to start. The wait is progress-based:
    a child that stops making progress fails the call, a merely slow one does not.
    """
    child_env = dict(os.environ)
    if env is not None:
        child_env.update(env)
    return run_child(
        self_command(*argv),
        what=f"vaultspec-a2a {' '.join(argv)}",
        env=child_env,
    )
