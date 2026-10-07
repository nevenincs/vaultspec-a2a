"""Shared subprocess lifecycle and diagnostic utilities.

Provides platform-aware process spawning and tree killing for ACP agent
subprocesses.  Used by ``acp_chat_model`` (production).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

from ..desktop.native_isolation import NativeLaunchAuthority
from ..utils import kill_pid_tree_async, redact_text
from ..utils.async_cleanup import complete_cleanup
from ..utils.process import ProcessContainment, ProcessContainmentError
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


def _retained_popen(
    process: asyncio.subprocess.Process,
) -> subprocess.Popen[bytes]:
    """Return the exact ``Popen`` retained by asyncio's subprocess transport."""
    transport = getattr(process, "_transport", None)
    popen = (
        transport.get_extra_info("subprocess")
        if transport is not None and hasattr(transport, "get_extra_info")
        else None
    )
    if not isinstance(popen, subprocess.Popen):
        raise ProcessContainmentError(
            f"Provider process {process.pid} has no retained subprocess handle"
        )
    return cast("subprocess.Popen[bytes]", popen)


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

    Windows (default): ``create_subprocess_shell`` with ``CREATE_NEW_PROCESS_GROUP``
    so that ``.cmd`` shims (for example ``kimi.cmd``) work; the whole tree (cmd.exe +
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
    containment = options.get("containment") or ProcessContainment.create()
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
    # The containment is allocated above, before anything it contains exists, so
    # a spawn that never produces a process must release it - on Windows it is a
    # job handle, and a provider that fails to start is retried, so a leak here
    # is per-attempt rather than one-off. One guard covers all three spawn
    # branches: releasing in each branch's own handler is the split duty that let
    # the equivalent leak survive elsewhere in this codebase.
    try:
        env = _confined_search_env(env)
        if sys.platform == "win32":
            if use_exec:
                process = await asyncio.create_subprocess_exec(
                    command[0],
                    *command[1:],
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        | containment.suspended_creation_flag()
                    ),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=cwd,
                    limit=_STREAM_LIMIT_BYTES,
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    subprocess.list2cmdline(command),
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        | containment.suspended_creation_flag()
                    ),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=cwd,
                    limit=_STREAM_LIMIT_BYTES,
                )
        else:
            process = await asyncio.create_subprocess_exec(
                command[0],
                *command[1:],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
                limit=_STREAM_LIMIT_BYTES,
                start_new_session=True,
            )
    except BaseException as exc:
        containment.close()
        logger.error("ACP subprocess spawn failed: %s", exc, extra=log_extra)
        raise
    # Windows creates the provider suspended, binds its retained process handle
    # to the Job, then resumes its one initial thread. No provider instruction or
    # descendant launch can precede containment. POSIX start_new_session performs
    # the equivalent seating as part of exec.
    await _admit_provider_process(process, containment, log_extra=log_extra)
    attach_process_containment(process, containment)
    if native_authority is not None:
        setattr(process, _NATIVE_AUTHORITY_ATTR, native_authority)
    logger.info(
        "ACP subprocess spawned",
        extra={**log_extra, "process_pid": process.pid},
    )
    return process


async def _admit_provider_process(
    process: asyncio.subprocess.Process,
    containment: ProcessContainment,
    *,
    log_extra: Mapping[str, object] | None = None,
) -> None:
    """Seat a retained provider root, failing only after its exact tree is gone."""
    try:
        containment.assign_suspended_process(_retained_popen(process))
    except BaseException as admission_error:
        cleanup_error: BaseException | None = None
        try:
            await _reap_provider_admission_failure(process, containment)
        except BaseException as exc:
            cleanup_error = exc
            logger.error(
                "ACP subprocess containment admission cleanup failed: %s",
                exc,
                extra={**_metadata_extra(log_extra), "process_pid": process.pid},
                exc_info=True,
            )
        if cleanup_error is not None:
            raise admission_error from cleanup_error
        raise


async def _reap_provider_admission_failure(
    process: asyncio.subprocess.Process,
    containment: ProcessContainment,
) -> None:
    """Reap a provider whose containment handoff failed before returning it."""
    try:
        if containment.assigned:
            stopped = await containment.terminate(term_timeout=5.0, kill_timeout=5.0)
        else:
            # Windows provider roots are created suspended and reach this branch
            # only when Job assignment failed. The provider has executed zero
            # instructions, so the exact retained root is the complete tree.
            popen = _retained_popen(process)
            popen.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                stopped = False
            else:
                stopped = process.returncode is not None
        if not stopped:
            raise ProcessContainmentError(
                f"Provider process tree {process.pid} could not be reaped after "
                "containment admission failed"
            )
    finally:
        containment.close()
        with suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=0.1)
        transport = getattr(process, "_transport", None)
        if transport is not None:
            transport.close()


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

    A provider spawned by :func:`spawn_acp_process` carries an assigned OS
    containment, so its whole tree (Windows: the Job Object; POSIX: the process
    group) is reaped at once with no parent-pid discovery. A directly created
    process uses the explicit per-pid tree cleanup contract; failed provider
    admission never reaches that path.

    The asyncio transport handle is closed last to prevent OS handle leaks
    when the event loop finalizer runs (cpython#114177).
    """
    containment = process_containment(process)
    has_containment = containment is not None and containment.assigned
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
    # Returned providers use the authority acquired before admission. Direct
    # subprocess owners use the explicit per-pid cleanup contract.
    try:
        if containment is not None and containment.assigned:
            stopped = await containment.terminate(term_timeout=5.0, kill_timeout=5.0)
        else:
            stopped = await kill_pid_tree_async(
                process.pid, term_timeout=5.0, kill_timeout=5.0
            )
        if not stopped:
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
