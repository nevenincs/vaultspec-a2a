"""Shared ACP subprocess lifecycle utilities.

Provides platform-aware process spawning and tree killing for ACP agent
subprocesses.  Used by both ``acp_chat_model`` (production) and
``probes/_protocol`` (manual verification).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from contextlib import suppress
from typing import Any


__all__ = ["kill_process_tree", "spawn_acp_process"]

logger = logging.getLogger(__name__)


async def spawn_acp_process(
    command: list[str],
    env: dict[str, str],
    cwd: str,
    *,
    use_exec: bool = False,
) -> asyncio.subprocess.Process:
    """Spawn an ACP subprocess with platform-appropriate isolation.

    Windows (default): ``create_subprocess_shell`` with ``CREATE_NEW_PROCESS_GROUP``
    so that ``.cmd`` shims (e.g. ``gemini.cmd``) work AND the full process tree
    (cmd.exe + node.exe + any grandchildren) can be atomically reaped via
    ``taskkill /T /F`` in ``kill_process_tree``.

    Windows (use_exec=True): ``create_subprocess_exec`` -- bypasses the cmd.exe
    shell intermediary for native PE32+ executables (e.g. the precompiled Bun
    binary) that do not need a .cmd shim.

    Unix/Linux/macOS: ``create_subprocess_exec`` -- no shell intermediary;
    POSIX signals (SIGTERM/SIGKILL) deliver directly to the target process.
    ``use_exec`` has no effect on non-Windows platforms.
    """
    kwargs: dict[str, Any] = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "env": env,
        "cwd": cwd,
        "limit": 10 * 1024 * 1024,
    }
    if sys.platform == "win32":
        if use_exec:
            return await asyncio.create_subprocess_exec(
                command[0],
                *command[1:],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                **kwargs,
            )
        return await asyncio.create_subprocess_shell(
            subprocess.list2cmdline(command),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            **kwargs,
        )
    return await asyncio.create_subprocess_exec(command[0], *command[1:], **kwargs)


async def kill_process_tree(
    process: asyncio.subprocess.Process,
) -> None:
    """Terminate an ACP subprocess and its entire process tree.

    Windows: ``taskkill /T /F /PID`` kills the whole tree atomically.
    ``process.terminate()`` alone only kills cmd.exe and leaves node.exe
    as an orphan.

    Unix/Linux/macOS: SIGTERM with a 5-second escalation to SIGKILL.

    The asyncio transport handle is closed last to prevent OS handle leaks
    when the event loop finalizer runs (cpython#114177).
    """
    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/T",
                "/F",
                "/PID",
                str(process.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), timeout=5.0)
        except Exception:
            with suppress(OSError):
                process.kill()
        with suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=5.0)
    else:
        with suppress(OSError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            logger.warning(
                "ACP process %s did not exit after SIGTERM; escalating to SIGKILL",
                process.pid,
            )
            with suppress(OSError):
                process.kill()
            await process.wait()

    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()
