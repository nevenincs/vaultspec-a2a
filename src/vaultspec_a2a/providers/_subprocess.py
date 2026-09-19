"""Shared subprocess lifecycle and diagnostic utilities.

Provides platform-aware process spawning and tree killing for ACP agent
subprocesses.  Used by ``acp_chat_model`` (production).

Also home to :func:`redact_secrets`, the single masking rule for text a failed
child wrote about itself. Every provider surface that retains a subprocess
diagnostic shares one threat - a child reports its configuration when it fails,
and configuration is where credentials live - so it shares one redactor rather
than each deciding for itself. A per-module copy is how one such surface came to
retain credentials verbatim while its neighbour masked them.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, cast

from ..utils import kill_pid_tree_async
from ..utils.async_cleanup import complete_cleanup
from ..utils.process import ProcessContainment, ProcessContainmentError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "kill_process_tree",
    "process_containment",
    "redact_secrets",
    "spawn_acp_process",
]

logger = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(
    r"(?i)((?:[A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL)[A-Z0-9_]*)"
    r"[\"']?\s*[=:]\s*"
    r"|bearer\s+)"
    r"(\"[^\"]*\"|'[^']*'|\S+)"
)


def redact_secrets(text: str) -> str:
    """Mask credential-shaped values in diagnostic text.

    Provider subprocesses report their configuration when they fail, and
    configuration is where credentials live, so a retained diagnostic tail is a
    plausible place for a token to surface. Matches on the NAME rather than the
    value shape: a token has no reliable shape, but the thing introducing it -
    an assignment to something called a token, secret, key, password or
    credential, or a bearer prefix - does.

    JSON is covered as well as ``NAME=value``. A provider that dumps its config
    as JSON writes ``"apiKey": "sk-..."``, where a quote sits between the name
    and its separator - and the earlier pattern, which expected only whitespace
    there, passed the credential through untouched. That is the shape the Kimi
    provider listing actually emits, so it was a live hole rather than a
    hypothetical one. A quoted value keeps its quotes so the surrounding
    structure still reads as JSON after masking.

    Accepts a single line or a whole multi-line block. The separator between an
    introducing name and its value spans newlines deliberately, so a value the
    child wrote on the line after its name is masked too; an unquoted value is
    non-whitespace and therefore never runs past its own line, and a quoted one
    is bounded by its closing quote.
    """

    def _mask(match: re.Match[str]) -> str:
        value = match.group(2)
        quoted = len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]
        replacement = f"{value[0]}<redacted>{value[0]}" if quoted else "<redacted>"
        return f"{match.group(1)}{replacement}"

    return _SECRET_PATTERN.sub(_mask, text)


# Attribute the run-owned provider's OS containment is stashed on so the shared
# reaper can reach it from a bare ``Process`` handle without changing the
# spawn/kill signatures the chat models already call.
_CONTAINMENT_ATTR = "_vaultspec_containment"


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


async def spawn_acp_process(
    command: list[str],
    env: dict[str, str],
    cwd: str,
    *,
    use_exec: bool = False,
    metadata: Mapping[str, object] | None = None,
) -> asyncio.subprocess.Process:
    """Acquire a contained subprocess, reaping it if the caller is cancelled."""
    spawn_task = asyncio.create_task(
        _spawn_acp_process(command, env, cwd, use_exec=use_exec, metadata=metadata)
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
    *,
    use_exec: bool,
    metadata: Mapping[str, object] | None,
    containment: ProcessContainment | None = None,
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
    containment = containment or ProcessContainment.create()
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
                    limit=10 * 1024 * 1024,
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
                    limit=10 * 1024 * 1024,
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
                limit=10 * 1024 * 1024,
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
