"""Shared ACP subprocess lifecycle utilities.

Provides platform-aware process spawning and tree killing for ACP agent
subprocesses.  Used by ``acp_chat_model`` (production).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, Any, cast

from ..utils import kill_pid_tree_async
from ..utils.process import ProcessContainment, ProcessContainmentError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["kill_process_tree", "spawn_acp_process"]

logger = logging.getLogger(__name__)

# Attribute the run-owned provider's OS containment is stashed on so the shared
# reaper can reach it from a bare ``Process`` handle without changing the
# spawn/kill signatures the chat models already call.
_CONTAINMENT_ATTR = "_vaultspec_containment"


def _metadata_extra(metadata: Mapping[str, object] | None) -> dict[str, object]:
    """Return bounded subprocess metadata for structured logging."""
    if not metadata:
        return {}
    return {key: value for key, value in metadata.items() if value is not None}


async def spawn_acp_process(
    command: list[str],
    env: dict[str, str],
    cwd: str,
    *,
    use_exec: bool = False,
    metadata: Mapping[str, object] | None = None,
) -> asyncio.subprocess.Process:
    """Spawn an ACP subprocess with platform-appropriate isolation.

    Windows (default): ``create_subprocess_shell`` with ``CREATE_NEW_PROCESS_GROUP``
    so that ``.cmd`` shims (e.g. ``gemini.cmd``) work; the whole tree (cmd.exe +
    node.exe + any grandchildren) is reaped as one via the Job Object the process
    is assigned to below, terminated in ``kill_process_tree``.

    Windows (use_exec=True): ``create_subprocess_exec`` -- bypasses the cmd.exe
    shell intermediary for native PE32+ executables (e.g. the precompiled Bun
    binary) that do not need a .cmd shim.

    Unix/Linux/macOS: ``create_subprocess_exec`` -- no shell intermediary;
    POSIX signals (SIGTERM/SIGKILL) deliver directly to the target process.
    ``use_exec`` has no effect on non-Windows platforms.
    """
    # Every run-owned provider root is spawned inside its own OS containment (a
    # POSIX new session/process group or a Windows Job Object) so its whole tree -
    # the CLI, its node/grandchildren, and the MCP bridges it launches - is reaped
    # as one on run terminal, without a parent-pid walk. The containment rides on
    # the returned Process for the shared reaper to reach.
    containment = ProcessContainment.create()
    kwargs: dict[str, Any] = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "env": env,
        "cwd": cwd,
        "limit": 10 * 1024 * 1024,
        **containment.spawn_kwargs(),
    }
    spawn_mode = "exec" if sys.platform != "win32" or use_exec else "shell"
    log_extra = _metadata_extra(metadata)
    log_extra.update(
        {
            "cwd": cwd,
            "use_exec": use_exec,
            "spawn_mode": spawn_mode,
        }
    )
    logger.info("ACP subprocess spawn starting", extra=log_extra)
    process: asyncio.subprocess.Process
    if sys.platform == "win32":
        if use_exec:
            try:
                process = await asyncio.create_subprocess_exec(
                    command[0],
                    *command[1:],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    **kwargs,
                )
            except Exception as exc:
                logger.error("ACP subprocess spawn failed: %s", exc, extra=log_extra)
                raise
        else:
            try:
                process = await asyncio.create_subprocess_shell(
                    subprocess.list2cmdline(command),
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    **kwargs,
                )
            except Exception as exc:
                logger.error("ACP subprocess spawn failed: %s", exc, extra=log_extra)
                raise
    else:
        try:
            process = await asyncio.create_subprocess_exec(
                command[0],
                *command[1:],
                **kwargs,
            )
        except Exception as exc:
            logger.error("ACP subprocess spawn failed: %s", exc, extra=log_extra)
            raise
    # Seat the provider root in its containment before it launches any MCP bridge
    # or grandchild. A Windows assignment failure downgrades to the per-pid tree
    # kill rather than failing the spawn.
    try:
        containment.assign(process.pid)
    except ProcessContainmentError:
        logger.warning(
            "Could not seat ACP provider PID %d in its OS containment; termination"
            " will fall back to a per-pid tree kill",
            process.pid,
            extra=log_extra,
            exc_info=True,
        )
    cast("Any", process)._vaultspec_containment = containment
    logger.info(
        "ACP subprocess spawned",
        extra={**log_extra, "process_pid": process.pid},
    )
    return process


async def kill_process_tree(
    process: asyncio.subprocess.Process,
    metadata: Mapping[str, object] | None = None,
) -> None:
    """Terminate an ACP subprocess and its entire process tree.

    A provider spawned by :func:`spawn_acp_process` carries an OS containment, so
    its whole tree (Windows: the Job Object; POSIX: the process group) is reaped
    at once with no parent-pid discovery. A process without a containment falls
    back to the shared per-pid tree kill (Windows ``taskkill /T /F``, POSIX
    SIGTERM->SIGKILL).

    The asyncio transport handle is closed last to prevent OS handle leaks
    when the event loop finalizer runs (cpython#114177).
    """
    has_containment = getattr(process, _CONTAINMENT_ATTR, None) is not None
    kill_strategy = "os_containment" if has_containment else "per_pid_tree_kill"
    log_extra = _metadata_extra(metadata)
    log_extra.update(
        {
            "process_pid": process.pid,
            "kill_strategy": kill_strategy,
            "returncode": process.returncode,
        }
    )
    logger.info("ACP subprocess termination starting", extra=log_extra)
    # Reap the whole provider tree through its OS containment - a POSIX process
    # group killpg escalation or a Windows Job Object termination - with no
    # parent-pid walk. A process spawned without a containment (or whose Windows
    # assignment failed) falls back to the shared per-pid tree kill. The asyncio
    # Process is then waited/reaped here, and its transport closed below to avoid
    # an OS handle leak when the loop finalizer runs (cpython#114177).
    containment: ProcessContainment | None = getattr(process, _CONTAINMENT_ATTR, None)
    if containment is not None:
        await containment.terminate(term_timeout=5.0, kill_timeout=5.0)
    else:
        await kill_pid_tree_async(process.pid, term_timeout=5.0, kill_timeout=5.0)
    with suppress(Exception):
        await asyncio.wait_for(process.wait(), timeout=5.0)

    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()
    logger.info(
        "ACP subprocess terminated",
        extra={
            **log_extra,
            "exit_code": process.returncode,
            "returncode": process.returncode,
        },
    )
