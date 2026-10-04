"""Real filesystem and subprocess proofs of ACP callback session authority."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ...workspace.concurrency import git_workspace_mutex
from .._acp_rpc_handlers import on_fs_write_text_file
from .._acp_types import AcpModelConfig, AcpSessionContext

if TYPE_CHECKING:
    from pathlib import Path

    from .._json_contract import JsonObject, JsonValue


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
