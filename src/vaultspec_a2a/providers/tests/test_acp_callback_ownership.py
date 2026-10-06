"""Real filesystem and subprocess proofs of ACP callback session authority."""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from typing import TYPE_CHECKING

import pytest

from ...workspace.concurrency import git_workspace_mutex
from .._acp_rpc_handlers import (
    on_fs_write_text_file,
    on_request_permission,
    on_terminal_create,
    on_terminal_kill,
    on_terminal_output,
    on_terminal_release,
    on_terminal_wait_for_exit,
)
from .._acp_rpc_terminal_handlers import release_owned_terminal
from .._acp_types import AcpModelConfig, AcpSessionContext
from ._terminal_process import retain_terminal_process

if TYPE_CHECKING:
    from pathlib import Path

    from .._json_contract import JsonObject, JsonValue

_PERMISSION_OPTIONS: list[JsonValue] = [
    {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
    {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
]


def _config(root: Path) -> AcpModelConfig:
    return AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=str(root),
        command=[],
        env_vars={},
        mcp_servers=[],
        use_exec=False,
        provider=None,
        runtime_authority=None,
        acp_backend=None,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [None, "", "foreign", False, 0, [], {}, "x" * 513])
async def test_invalid_write_session_cannot_replace_or_create_files(
    tmp_path: Path, acp_session_context: AcpSessionContext, session: JsonValue
) -> None:
    existing = tmp_path / "existing.txt"
    existing.write_text("owner content", encoding="utf-8")
    for path in ("existing.txt", "new/created.txt"):
        response = await on_fs_write_text_file(
            1,
            {"sessionId": session, "path": path, "content": "foreign content"},
            acp_session_context,
            _config(tmp_path),
        )
        assert "error" in response and "result" not in response
        assert "session" in str(response["error"]).lower()
    assert existing.read_text(encoding="utf-8") == "owner content"
    assert not (tmp_path / "new").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", [True, False])
async def test_write_requires_a_bound_and_supplied_session(
    tmp_path: Path, acp_session_context: AcpSessionContext, bound: bool
) -> None:
    params: JsonObject = {"path": "created.txt", "content": "unauthorized"}
    if not bound:
        params["sessionId"] = acp_session_context.session_id
        acp_session_context.session_id = None
    response = await on_fs_write_text_file(
        1, params, acp_session_context, _config(tmp_path)
    )
    assert "error" in response and "result" not in response
    assert not (tmp_path / "created.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [None, "", "foreign", False, 0, [], {}, "x" * 513])
async def test_invalid_session_cannot_create_a_terminal(
    tmp_path: Path, acp_session_context: AcpSessionContext, session: JsonValue
) -> None:
    script = tmp_path / "create_marker.py"
    script.write_text(
        "from pathlib import Path\nPath('started.txt').write_text('started')\n",
        encoding="utf-8",
    )
    response = await on_terminal_create(
        1,
        {"sessionId": session, "command": sys.executable, "args": [str(script)]},
        acp_session_context,
        _config(tmp_path),
    )
    assert "error" in response and "result" not in response
    assert acp_session_context.terminals == {}
    assert not (tmp_path / "started.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "unbound", "closed"])
async def test_terminal_creation_requires_an_open_negotiated_session(
    tmp_path: Path, acp_session_context: AcpSessionContext, mode: str
) -> None:
    params: JsonObject = {"command": sys.executable, "args": ["--version"]}
    if mode != "missing":
        params["sessionId"] = acp_session_context.session_id
    if mode == "unbound":
        acp_session_context.session_id = None
    elif mode == "closed":
        acp_session_context.closing = True
    response = await on_terminal_create(
        1, params, acp_session_context, _config(tmp_path)
    )
    assert "error" in response and "result" not in response
    assert acp_session_context.terminals == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_id", [None, "", False, 0, [], {}])
async def test_terminal_addressing_requires_a_nonempty_string_id(
    tmp_path: Path, acp_session_context: AcpSessionContext, terminal_id: JsonValue
) -> None:
    for handler in (
        on_terminal_output,
        on_terminal_wait_for_exit,
        on_terminal_kill,
        on_terminal_release,
    ):
        response = await handler(
            1,
            {"sessionId": acp_session_context.session_id, "terminalId": terminal_id},
            acp_session_context,
            _config(tmp_path),
        )
        assert "error" in response and "result" not in response


async def _create_owned_terminal(root: Path, ctx: AcpSessionContext) -> str:
    script = root / "owned_terminal.py"
    script.write_text(
        "import sys, time\n"
        "sys.stdout.buffer.write(b'owned-output\\n')\n"
        "sys.stdout.buffer.flush()\ntime.sleep(120)\n",
        encoding="utf-8",
    )
    return await retain_terminal_process(ctx, root, [str(script)])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "foreign",
        "null",
        "boolean",
        "number",
        "oversized",
        "unbound",
        "closed",
    ],
)
async def test_every_terminal_callback_refuses_unowned_session_without_side_effects(
    tmp_path: Path, acp_session_context: AcpSessionContext, mode: str
) -> None:
    terminal_id = await _create_owned_terminal(tmp_path, acp_session_context)
    process = acp_session_context.terminals[terminal_id]
    owner_session = acp_session_context.session_id
    params: JsonObject = {"terminalId": terminal_id}
    if mode != "missing":
        sessions: dict[str, JsonValue] = {
            "foreign": "foreign-session",
            "null": None,
            "boolean": False,
            "number": 1,
            "oversized": "x" * 513,
            "unbound": owner_session,
            "closed": owner_session,
        }
        params["sessionId"] = sessions[mode]
    if mode == "unbound":
        acp_session_context.session_id = None
    elif mode == "closed":
        acp_session_context.closing = True
    try:
        async with asyncio.timeout(2):
            for handler in (
                on_terminal_output,
                on_terminal_wait_for_exit,
                on_terminal_kill,
                on_terminal_release,
            ):
                response = await handler(
                    2, params, acp_session_context, _config(tmp_path)
                )
                assert "error" in response and "result" not in response
                assert acp_session_context.terminals.get(terminal_id) is process
                assert process.returncode is None
        async with asyncio.timeout(5):
            while not acp_session_context.terminal_outputs[terminal_id].output:
                await asyncio.sleep(0.01)
        assert acp_session_context.terminal_outputs[terminal_id].output == (
            "owned-output\n"
        )
    finally:
        # Local cleanup owes no protocol authority, including partial setup.
        await release_owned_terminal(terminal_id, acp_session_context)
    assert process.returncode is not None
    assert terminal_id not in acp_session_context.terminals


@pytest.mark.asyncio
async def test_release_uses_the_receiving_contexts_registry(
    tmp_path: Path,
    acp_session_context: AcpSessionContext,
    echo_context: AcpSessionContext,
) -> None:
    echo_context.session_id = "sibling-session"
    first_id = await _create_owned_terminal(tmp_path, acp_session_context)
    sibling_id = await _create_owned_terminal(tmp_path, echo_context)
    first = acp_session_context.terminals.pop(first_id)
    sibling = echo_context.terminals.pop(sibling_id)
    acp_session_context.terminals["same-id"] = first
    echo_context.terminals["same-id"] = sibling
    first_output = acp_session_context.terminal_outputs.pop(first_id)
    sibling_output = echo_context.terminal_outputs.pop(sibling_id)
    acp_session_context.terminal_outputs["same-id"] = first_output
    echo_context.terminal_outputs["same-id"] = sibling_output
    try:
        refused = await on_terminal_release(
            2,
            {"sessionId": echo_context.session_id, "terminalId": "same-id"},
            acp_session_context,
            _config(tmp_path),
        )
        assert "error" in refused
        assert first.returncode is None and sibling.returncode is None
        released = await on_terminal_release(
            3,
            {"sessionId": acp_session_context.session_id, "terminalId": "same-id"},
            acp_session_context,
            _config(tmp_path),
        )
        assert released["result"] == {}
        assert first.returncode is not None and sibling.returncode is None
        assert echo_context.terminals["same-id"] is sibling
        assert not acp_session_context.terminal_outputs
        assert echo_context.terminal_outputs["same-id"] is sibling_output
        assert all(task.done() for task in first_output._tasks)
    finally:
        await release_owned_terminal("same-id", acp_session_context)
        await release_owned_terminal("same-id", echo_context)
    assert not echo_context.terminal_outputs
    assert all(task.done() for task in sibling_output._tasks)


@pytest.mark.asyncio
async def test_owner_write_remains_permitted(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    response = await on_fs_write_text_file(
        1,
        {
            "sessionId": acp_session_context.session_id,
            "path": "nested/created.txt",
            "content": "owner content",
        },
        acp_session_context,
        _config(tmp_path),
    )
    assert response == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert (tmp_path / "nested/created.txt").read_text(
        encoding="utf-8"
    ) == "owner content"


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("change", ["replace", "close"])
async def test_write_rechecks_session_after_waiting_for_workspace_mutex(
    tmp_path: Path, acp_session_context: AcpSessionContext, change: str
) -> None:
    async with git_workspace_mutex:
        pending = asyncio.create_task(
            on_fs_write_text_file(
                1,
                {
                    "sessionId": acp_session_context.session_id,
                    "path": "created.txt",
                    "content": "old session",
                },
                acp_session_context,
                _config(tmp_path),
            )
        )
        await asyncio.sleep(0)
        assert not pending.done()
        if change == "close":
            acp_session_context.closing = True
        else:
            acp_session_context.session_id = "replacement-session"
    response = await asyncio.wait_for(pending, timeout=5)
    assert "error" in response and "result" not in response
    assert not (tmp_path / "created.txt").exists()


def _permission_params(session: JsonValue) -> JsonObject:
    return {
        "sessionId": session,
        "toolCall": {"title": "Edit", "rawInput": {}},
        "options": list(_PERMISSION_OPTIONS),
    }


def _recording_config(root: Path, asked: list[str]) -> AcpModelConfig:
    """A supervised config whose human rung records each question it is asked."""

    async def callback(name: str, _args: JsonObject, _options: list[JsonObject]) -> str:
        asked.append(name)
        return "allow"

    return dataclasses.replace(_config(root), permission_callback=callback)


_REFUSED = {"outcome": {"optionId": "reject", "outcome": "selected"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [None, "", "foreign", False, 0, [], {}, "x" * 513])
async def test_permission_outside_the_session_is_refused_before_any_rung(
    tmp_path: Path, acp_session_context: AcpSessionContext, session: JsonValue
) -> None:
    """A foreign or malformed session never reaches the person or the allowlist."""
    asked: list[str] = []
    response = await on_request_permission(
        1,
        _permission_params(session),
        acp_session_context,
        _recording_config(tmp_path, asked),
    )
    assert response["result"] == _REFUSED
    assert asked == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "unbound", "closed"])
async def test_permission_requires_an_open_negotiated_session(
    tmp_path: Path, acp_session_context: AcpSessionContext, mode: str
) -> None:
    asked: list[str] = []
    params = _permission_params(acp_session_context.session_id)
    if mode == "missing":
        params.pop("sessionId")
    elif mode == "unbound":
        acp_session_context.session_id = None
    else:
        acp_session_context.closing = True
    response = await on_request_permission(
        1, params, acp_session_context, _recording_config(tmp_path, asked)
    )
    assert response["result"] == _REFUSED
    assert asked == []


@pytest.mark.asyncio
async def test_owner_permission_request_reaches_the_human_rung(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    asked: list[str] = []
    response = await on_request_permission(
        1,
        _permission_params(acp_session_context.session_id),
        acp_session_context,
        _recording_config(tmp_path, asked),
    )
    assert response["result"] == {
        "outcome": {"optionId": "allow", "outcome": "selected"}
    }
    assert asked == ["Edit"]
