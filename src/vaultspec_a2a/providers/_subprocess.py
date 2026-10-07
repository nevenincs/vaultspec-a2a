"""Shared subprocess lifecycle and diagnostic utilities.

Provides platform-aware process spawning and tree killing for ACP agent
subprocesses.  Used by ``acp_chat_model`` (production).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, TypedDict, Unpack

from ..desktop.native_isolation import NativeLaunchAuthority
from ..utils import (
    ProcessContainment,
    ProcessContainmentError,
    redact_text,
    spawn_contained_async,
)
from ..utils.async_cleanup import complete_cleanup
from ._provider_execution import provider_execution_launch

if TYPE_CHECKING:
    from collections import deque
    from collections.abc import Mapping

__all__ = [
    "STDERR_TAIL_LINES",
    "drain_stderr_into",
    "kill_process_tree",
    "process_containment",
    "process_native_authority",
    "spawn_acp_process",
]

STDERR_TAIL_LINES = 200
"""How many redacted stderr lines any provider lane retains for diagnosis.

One bound for every lane, beside the one redactor, because the thing being bounded
is the same on all of them: what a failing child said about itself, kept long
enough to explain the failure and no longer.
"""

logger = logging.getLogger(__name__)

# The reader buffer bound for a provider's pipes, the same on every spawn path.
# One JSON-RPC line from a provider can carry a whole tool result, far past
# asyncio's 64 KiB default, and a line over the bound fails the read outright.
_STREAM_LIMIT_BYTES = 10 * 1024 * 1024


class _SpawnRequired(TypedDict):
    use_exec: bool
    metadata: Mapping[str, object] | None


class _SpawnOptions(_SpawnRequired, total=False):
    containment: ProcessContainment | None
    native_authority: NativeLaunchAuthority | None


async def drain_stderr_into(
    stream: asyncio.StreamReader | None, tail: deque[str]
) -> None:
    """Read *stream* to end, appending each redacted non-empty line to *tail*.

    Module-level rather than a method so the behaviour can be driven directly
    against a real stream, without reaching into a half-built client.

    Never raises: a diagnostic channel must not be able to fail a turn. Each line
    is redacted before retention because provider subprocesses report their
    configuration when they fail, and configuration is where credentials live.
    """
    if stream is None:
        return
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                tail.append(redact_text(text))
    except (OSError, ValueError, asyncio.CancelledError):
        return


# Attribute the run-owned provider's OS containment is stashed on so the shared
# reaper can reach it from a bare ``Process`` handle without changing the
# spawn/kill signatures the chat models already call.
_CONTAINMENT_ATTR = "_vaultspec_containment"
_NATIVE_AUTHORITY_ATTR = "_vaultspec_native_authority"


def attach_process_containment(
    process: asyncio.subprocess.Process,
    containment: ProcessContainment,
) -> None:
    """Attach run-owned containment to one spawned process."""
    setattr(process, _CONTAINMENT_ATTR, containment)


def process_containment(
    process: asyncio.subprocess.Process,
) -> ProcessContainment | None:
    """Return the containment attached by :func:`attach_process_containment`."""
    attached = getattr(process, _CONTAINMENT_ATTR, None)
    return attached if isinstance(attached, ProcessContainment) else None


def _metadata_extra(metadata: Mapping[str, object] | None) -> dict[str, object]:
    """Return bounded subprocess metadata for structured logging."""
    if not metadata:
        return {}
    return {key: value for key, value in metadata.items() if value is not None}


def process_native_authority(
    process: asyncio.subprocess.Process,
) -> NativeLaunchAuthority | None:
    """Read trusted authority retained on the admitted session process."""
    authority = getattr(process, _NATIVE_AUTHORITY_ATTR, None)
    if authority is not None and not isinstance(authority, NativeLaunchAuthority):
        raise ProcessContainmentError("provider process has invalid native authority")
    return authority


def _confined_search_env(env: dict[str, str]) -> dict[str, str]:
    """Return the child environment with Windows working-directory search off.

    Windows resolves a bare program name against the working directory before
    PATH, both in ``CreateProcess`` and in the ``cmd.exe`` shim path this module
    takes for ``.cmd`` launchers, and the working directory of every provider
    child is the agent's own workspace. ``NoDefaultCurrentDirectoryInExePath``
    is the documented way to turn that lookup off, and it is inherited, so it
    also covers the tools the child launches. Provider launchers are already
    resolved to absolute paths before they reach here; this closes the same hole
    for the names a child resolves for itself.
    """
    if sys.platform != "win32":
        return env
    return {**env, "NoDefaultCurrentDirectoryInExePath": "1"}


async def spawn_acp_process(
    command: list[str],
    env: dict[str, str],
    cwd: str,
    *,
    use_exec: bool = False,
    metadata: Mapping[str, object] | None = None,
    native_authority: NativeLaunchAuthority | None = None,
) -> asyncio.subprocess.Process:
    """Acquire a contained subprocess, reaping it if the caller is cancelled."""
    spawn_task = asyncio.create_task(
        _spawn_acp_process(
            command,
            env,
            cwd,
            use_exec=use_exec,
            metadata=metadata,
            native_authority=native_authority,
        )
    )
    try:
        return await asyncio.shield(spawn_task)
    except asyncio.CancelledError as cancellation:
        # Subprocess creation may have acquired an OS process before its await
        # returns. Join the acquisition so that handle always reaches a reaper.
        async def _reap_cancelled_spawn() -> None:
            process = await spawn_task
            await kill_process_tree(process, metadata)

        try:
            await complete_cleanup(_reap_cancelled_spawn())
        except Exception as exc:
            raise cancellation from exc
        raise


async def _spawn_acp_process(
    command: list[str],
    env: dict[str, str],
    cwd: str,
    **options: Unpack[_SpawnOptions],
) -> asyncio.subprocess.Process:
    """Spawn an ACP subprocess with platform-appropriate isolation.

    Windows (default): through the shell, in a new console process group, so
    that ``.cmd`` shims (for example ``kimi.cmd``) work; the whole tree (cmd.exe +
    node.exe + any grandchildren) is reaped as one through its Job Object in
    ``kill_process_tree``.

    Windows (use_exec=True): exec -- bypasses the cmd.exe shell intermediary for
    native PE32+ executables (e.g. the precompiled Bun binary) that do not need a
    .cmd shim.

    Unix/Linux/macOS: exec -- no shell intermediary; POSIX signals
    (SIGTERM/SIGKILL) deliver directly to the target process group. ``use_exec``
    has no effect on non-Windows platforms.
    """
    # Every run-owned provider root is spawned inside its own OS containment (a
    # POSIX new session/process group or a Windows Job Object) before its first
    # instruction, so its whole tree - the CLI, its node/grandchildren, and the
    # MCP bridges it launches - is reaped as one on run terminal, without a
    # parent-pid walk. The containment rides on the returned Process for the
    # shared reaper to reach.
    use_exec = options["use_exec"]
    metadata = options["metadata"]
    # Refuse native execution before acquiring even a lifetime containment.
    native_authority = options.get("native_authority")
    launch = provider_execution_launch(
        command, environment=env, cwd=cwd, native_authority=native_authority
    )
    command = list(launch.command)
    assert launch.environment is not None
    env = dict(launch.environment)
    assert launch.cwd is not None
    cwd = launch.cwd
    env = _confined_search_env(env)
    shell = sys.platform == "win32" and not use_exec
    log_extra = _metadata_extra(metadata)
    log_extra.update(
        {
            "cwd": cwd,
            "use_exec": use_exec,
            "spawn_mode": "shell" if shell else "exec",
        }
    )
    logger.info("ACP subprocess spawn starting", extra=log_extra)
    try:
        # Allocated last, so the contained spawn is its only owner on failure.
        containment = options.get("containment") or ProcessContainment.create()
        process = await spawn_contained_async(
            command,
            containment,
            shell=shell,
            new_process_group=True,
            limit=_STREAM_LIMIT_BYTES,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
    except BaseException as exc:
        logger.error("ACP subprocess spawn failed: %s", exc, extra=log_extra)
        raise
    attach_process_containment(process, containment)
    if native_authority is not None:
        setattr(process, _NATIVE_AUTHORITY_ATTR, native_authority)
    logger.info(
        "ACP subprocess spawned",
        extra={**log_extra, "process_pid": process.pid},
    )
    return process


async def kill_process_tree(
    process: asyncio.subprocess.Process,
    metadata: Mapping[str, object] | None = None,
) -> None:
    """Join complete process, containment and transport release before cancellation."""
    await complete_cleanup(_kill_process_tree(process, metadata))


async def _kill_process_tree(
    process: asyncio.subprocess.Process,
    metadata: Mapping[str, object] | None,
) -> None:
    """Terminate an ACP subprocess and its entire process tree.

    Every provider spawned by :func:`spawn_acp_process` carries its OS
    containment, so its whole tree (Windows: the Job Object; POSIX: the process
    group) is reaped at once with no parent-pid discovery. The containment, not
    its current assignment, is the authority: a repeat call after a completed
    reap is a no-op rather than a kill aimed at a numeric pid.

    The asyncio transport handle is closed last to prevent OS handle leaks
    when the event loop finalizer runs (cpython#114177).
    """
    containment = process_containment(process)
    log_extra = _metadata_extra(metadata)
    log_extra.update(
        {
            "process_pid": process.pid,
            "returncode": process.returncode,
        }
    )
    logger.info("ACP subprocess termination starting", extra=log_extra)
    try:
        if containment is None:
            raise ProcessContainmentError(
                f"Provider process {process.pid} carries no containment"
            )
        if not await containment.terminate(term_timeout=5.0, kill_timeout=5.0):
            raise ProcessContainmentError(
                f"Provider process tree {process.pid} could not be fully reaped"
            )
    finally:
        try:
            with suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=5.0)
        finally:
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
