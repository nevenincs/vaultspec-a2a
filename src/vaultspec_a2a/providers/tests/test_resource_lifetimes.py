"""Real subprocess proofs for provider ownership across cancellation and teardown."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

import psutil
import pytest

from ...utils._process_tree import kill_pid_tree_async, pid_is_live
from .._acp_protocol import process_stdout_loop
from .._acp_rpc_handlers import on_terminal_create, on_terminal_release
from .._acp_types import AcpSessionContext
from .._cleanup import cancel_owned_tasks, run_independent_cleanups
from .._codex_config_home import cleanup_codex_config_home
from .._subprocess import kill_process_tree, spawn_acp_process
from ..acp_chat_model import AcpChatModel
from ..codex_chat_model import _CodexAppServerClient
from .conftest import _AcpChildStreams, _fresh_acp_session_context

if TYPE_CHECKING:
    from pathlib import Path


async def _spawn(workspace: Path, script: str) -> asyncio.subprocess.Process:
    return await spawn_acp_process(
        [sys.executable, "-c", script], dict(os.environ), str(workspace), use_exec=True
    )


def _context(process: asyncio.subprocess.Process) -> AcpSessionContext:
    assert process.stdin is not None
    assert process.stdout is not None
    return AcpSessionContext(
        process=process,
        stdin=process.stdin,
        stdout=process.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
    )


@pytest.mark.asyncio
async def test_shared_fixture_child_keeps_session_state_function_scoped(
    acp_session_context: AcpSessionContext,
) -> None:
    """Sharing idle streams must not share any mutable ACP session authority."""

    sibling = _fresh_acp_session_context(
        _AcpChildStreams(
            process=acp_session_context.process,
            stdin=acp_session_context.stdin,
            stdout=acp_session_context.stdout,
        )
    )
    future = asyncio.get_running_loop().create_future()
    future.set_result({})
    acp_session_context.response_futures[1] = future
    acp_session_context.prompt_done.set()
    acp_session_context.prompt_id_ref.append(7)
    acp_session_context.interrupt_exc.append(RuntimeError("first context only"))
    acp_session_context.tool_calls["call"] = {"name": "Read"}
    acp_session_context.config_options.append({"id": "first"})

    assert sibling.process is acp_session_context.process
    assert sibling.stdin is acp_session_context.stdin
    assert sibling.stdout is acp_session_context.stdout
    assert sibling.response_futures == {}
    assert sibling.chunk_queue is not acp_session_context.chunk_queue
    assert not sibling.prompt_done.is_set()
    assert sibling.prompt_id_ref == []
    assert sibling.interrupt_exc == []
    assert sibling.background_tasks == set()
    assert sibling.terminals == {}
    assert sibling.tool_calls == {}
    assert sibling.native_command_catalogs == {}
    assert sibling.config_options == []
    assert sibling.stdin_lock is not acp_session_context.stdin_lock


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_first", [False, True])
async def test_concurrent_codex_close_callers_join_one_completed_release(
    tmp_path: Path, cancel_first: bool
) -> None:
    process = await _spawn(tmp_path, "import time; time.sleep(120)")
    client = _CodexAppServerClient(process)
    first = asyncio.create_task(client.aclose())
    await asyncio.sleep(0)
    second = asyncio.create_task(client.aclose())
    try:
        await asyncio.sleep(0)
        assert not first.done()
        assert not second.done(), "closed admission must not imply completed release"
        if cancel_first:
            first.cancel()
        results = await asyncio.wait_for(
            asyncio.gather(first, second, return_exceptions=True), timeout=20.0
        )
        if cancel_first:
            assert isinstance(results[0], asyncio.CancelledError)
        else:
            assert results[0] is None
        assert results[1] is None
        assert not pid_is_live(process.pid)
        assert client._reader_task.done()
        assert client._stderr_task is not None and client._stderr_task.done()
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellations", [1, 3])
async def test_cancelled_cleanup_joins_process_and_credential_releases(
    tmp_path: Path, cancellations: int
) -> None:
    process = await _spawn(tmp_path, "import time; time.sleep(120)")
    credential = tmp_path / "credential"
    credential.write_text("test credential", encoding="utf-8")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _reap() -> None:
        entered.set()
        await release.wait()
        await kill_process_tree(process)

    cleanup = asyncio.create_task(
        run_independent_cleanups(("process", _reap), ("credential", credential.unlink))
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=10.0)
        for _ in range(cancellations):
            cleanup.cancel()
            await asyncio.sleep(0)
            assert not cleanup.done(), "cancellation detached the resource owner"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(cleanup, timeout=20.0)
        assert process.returncode is not None
        assert not pid_is_live(process.pid)
        assert not credential.exists()
        transport = getattr(process, "_transport", None)
        assert isinstance(transport, asyncio.SubprocessTransport)
        assert transport.is_closing()
    finally:
        release.set()
        await kill_process_tree(process)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellations", [1, 3])
async def test_cancelled_terminal_release_finishes_before_removing_ownership(
    tmp_path: Path, acp_session_context: AcpSessionContext, cancellations: int
) -> None:
    process = await _spawn(tmp_path, "import time; time.sleep(120)")
    model = AcpChatModel(command=[sys.executable], workspace_root=str(tmp_path))
    acp_session_context.terminals["owned"] = process
    release = asyncio.create_task(
        on_terminal_release(
            1, {"terminalId": "owned"}, acp_session_context, model._config
        )
    )
    try:
        await asyncio.sleep(0)
        for _ in range(cancellations):
            assert acp_session_context.terminals.get("owned") is process
            release.cancel()
            await asyncio.sleep(0)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(release, timeout=20.0)
        assert "owned" not in acp_session_context.terminals
        assert not pid_is_live(process.pid)
        transport = getattr(process, "_transport", None)
        assert isinstance(transport, asyncio.SubprocessTransport)
        assert transport.is_closing()
    finally:
        await asyncio.gather(release, return_exceptions=True)
        await kill_process_tree(process)


@pytest.mark.asyncio
async def test_cancelled_spawn_reaps_the_process_before_returning(
    tmp_path: Path,
) -> None:
    owner = psutil.Process()
    existing = {child.pid for child in owner.children()}
    spawn = asyncio.create_task(_spawn(tmp_path, "import time; time.sleep(120)"))
    # Let the acquisition reach create_subprocess_exec, whose transport setup
    # yields after the OS process exists but before its handle reaches the caller.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    created = [child for child in owner.children() if child.pid not in existing]
    try:
        assert created, "the cancellation must exercise an acquired real process"
        assert not spawn.done()
        spawn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(spawn, timeout=20.0)
        assert all(not pid_is_live(child.pid) for child in created)
    finally:
        if not spawn.done():
            spawn.cancel()
            await asyncio.gather(spawn, return_exceptions=True)
        for child in created:
            if pid_is_live(child.pid):
                await kill_pid_tree_async(child.pid)


@pytest.mark.asyncio
async def test_release_after_root_exit_reaps_descendant_and_preserves_foreign_process(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    script = tmp_path / "orphan.py"
    script.write_text(
        "import subprocess, sys\n"
        "sys.stdin.readline()\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(120)'], stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "print(child.pid, flush=True)\n",
        encoding="utf-8",
    )
    model = AcpChatModel(command=[sys.executable], workspace_root=str(tmp_path))
    foreign = await _spawn(tmp_path, "import time; time.sleep(120)")
    descendant: int | None = None
    terminal: asyncio.subprocess.Process | None = None
    try:
        created = await on_terminal_create(
            1,
            {"command": sys.executable, "args": [str(script)]},
            acp_session_context,
            model._config,
        )
        result = created.get("result")
        assert isinstance(result, dict)
        terminal_id = result.get("terminalId")
        assert isinstance(terminal_id, str)
        terminal = acp_session_context.terminals[terminal_id]
        assert terminal.stdin is not None and terminal.stdout is not None
        terminal.stdin.write(b"start\n")
        await terminal.stdin.drain()
        descendant = int(await asyncio.wait_for(terminal.stdout.readline(), timeout=10))
        await asyncio.wait_for(terminal.wait(), timeout=10)
        assert terminal.returncode == 0
        assert pid_is_live(descendant)
        await on_terminal_release(
            2, {"terminalId": terminal_id}, acp_session_context, model._config
        )
        assert terminal_id not in acp_session_context.terminals
        assert not pid_is_live(descendant)
        assert pid_is_live(foreign.pid)
        transport = getattr(terminal, "_transport", None)
        assert isinstance(transport, asyncio.SubprocessTransport)
        assert transport.is_closing()
    finally:
        if terminal is not None:
            await kill_process_tree(terminal)
        if descendant is not None and pid_is_live(descendant):
            await kill_pid_tree_async(descendant)
        await kill_process_tree(foreign)


@pytest.mark.asyncio
async def test_session_cleanup_reaps_terminal_created_during_cancel(
    tmp_path: Path,
) -> None:
    process = await _spawn(
        tmp_path,
        "import sys,json,time\n"
        "request=json.loads(sys.stdin.readline())\n"
        "time.sleep(.4)\n"
        "print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{}}),flush=True)\n"
        "time.sleep(120)\n",
    )
    model = AcpChatModel(command=[sys.executable], workspace_root=str(tmp_path))
    model._active_session_id = "cleanup-session"
    ctx = _context(process)
    stdout = asyncio.create_task(process_stdout_loop(ctx, model._config, {}))
    stderr = asyncio.create_task(model._read_stderr_loop(ctx))

    async def _create() -> None:
        response = await on_terminal_create(
            2, {"command": sys.executable, "args": ["-q"]}, ctx, model._config
        )
        assert "result" in response

    creation = asyncio.create_task(_create())
    ctx.background_tasks.add(creation)
    creation.add_done_callback(ctx.background_tasks.discard)
    try:
        await asyncio.wait_for(model._cleanup_session(ctx, stdout, stderr), timeout=25)
        assert not ctx.terminals
        assert creation.done()
        assert stdout.done() and stderr.done()
        assert process.returncode is not None
        assert ctx.closing
    finally:
        for terminal in tuple(ctx.terminals.values()):
            await kill_process_tree(terminal)
        await kill_process_tree(process)
        await cancel_owned_tasks((stdout, stderr, creation))


@pytest.mark.asyncio
async def test_cancel_request_deadline_includes_locked_writer(tmp_path: Path) -> None:
    process = await _spawn(tmp_path, "import time; time.sleep(120)")
    model = AcpChatModel(command=[sys.executable], workspace_root=str(tmp_path))
    model._active_session_id = "locked-writer"
    ctx = _context(process)
    await ctx.stdin_lock.acquire()
    try:
        await asyncio.wait_for(model._cleanup_session(ctx, None, None), timeout=12.0)
        assert not pid_is_live(process.pid)
    finally:
        ctx.stdin_lock.release()
        await kill_process_tree(process)


@pytest.mark.asyncio
async def test_resistant_handler_is_reported_without_blocking_process_release(
    tmp_path: Path,
) -> None:
    process = await _spawn(tmp_path, "import time; time.sleep(120)")
    entered = asyncio.Event()
    stop = asyncio.Event()

    async def _resist() -> None:
        entered.set()
        while not stop.is_set():
            try:
                await stop.wait()
            except asyncio.CancelledError:
                continue

    handler = asyncio.create_task(_resist())
    try:
        await entered.wait()
        failures = await asyncio.wait_for(
            run_independent_cleanups(
                ("handler", lambda: cancel_owned_tasks((handler,), timeout=0.05)),
                ("process", lambda: kill_process_tree(process)),
            ),
            timeout=15.0,
        )
        assert [name for name, _ in failures] == ["handler"]
        assert isinstance(failures[0][1], TimeoutError)
        assert not pid_is_live(process.pid)
        assert not handler.done()
    finally:
        stop.set()
        await asyncio.wait_for(handler, timeout=5.0)
        await kill_process_tree(process)


def test_config_home_cleanup_reports_failed_removal_and_allows_absent_home(
    tmp_path: Path,
) -> None:
    invalid_home = tmp_path / "credential"
    invalid_home.write_text(
        "must remain visible after failed cleanup", encoding="utf-8"
    )
    with pytest.raises(OSError):
        cleanup_codex_config_home(invalid_home)
    assert invalid_home.exists()
    cleanup_codex_config_home(tmp_path / "already-removed")
