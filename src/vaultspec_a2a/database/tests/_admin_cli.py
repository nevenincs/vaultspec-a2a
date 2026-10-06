"""Run the real administrative CLI in a subprocess.

Shared by the suites that drive :mod:`vaultspec_a2a.database.admin` end to end.
A subprocess rather than an in-process call because every verb reads the
process-wide settings singleton: configuring a child through its environment
exercises the real configuration path, where reaching into the singleton would
only prove that the singleton can be overwritten.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ["run_admin"]


def run_admin(
    database: Path, *args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m vaultspec_a2a.database.admin *args`` against *database*.

    *env* overlays the child's environment after the database URL is seated, so
    a caller can point the configured service ports somewhere specific.
    """
    child_env = dict(os.environ)
    child_env["VAULTSPEC_A2A_DATABASE_URL"] = (
        f"sqlite+aiosqlite:///{database.as_posix()}"
    )
    # The blocked-checkpoint proof needs a nonzero wait, not the production
    # default's five seconds of idle time. The administrative connection must
    # honor the same setting as every other SQLite connection authority.
    child_env["VAULTSPEC_A2A_SQLITE_BUSY_TIMEOUT_MS"] = "50"
    if env is not None:
        child_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "vaultspec_a2a.database.admin", *args],
        capture_output=True,
        text=True,
        env=child_env,
        timeout=300,
        check=False,
    )
