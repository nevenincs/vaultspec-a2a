"""Real-file and real-pipe proofs of ACP v1 filesystem reads."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ...control.config import settings
from ...control.infra_config import InfraConfig
from ...team.team_config import AgentConfig
from ...testing import acp_request, read_acp_frame, settings_override
from .._acp_protocol import _dispatch_stdout_line, process_stdout_loop
from .._acp_request import issue_request, jsonrpc_result
from .._acp_rpc_handlers import (
    _read_workspace_text,
    on_fs_read_text_file,
    on_fs_write_text_file,
    on_terminal_create,
    on_terminal_kill,
    on_terminal_output,
    on_terminal_release,
    on_terminal_wait_for_exit,
)
from .._acp_rpc_terminal_handlers import release_owned_terminal
from .._acp_session import initialize_session, setup_session
from .._acp_types import AcpModelConfig, AcpSessionContext

if TYPE_CHECKING:
    from .._json_contract import JsonObject, JsonValue


def _config(root: Path) -> AcpModelConfig:
    return AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=str(root),
        command=["echo"],
        env_vars={},
        mcp_servers=[],
        use_exec=False,
        provider=None,
        provider_command=None,
        auth_mode=None,
    )


async def _read(root: Path, ctx: AcpSessionContext, params: JsonObject) -> JsonObject:
    return await on_fs_read_text_file(
        7,
        {"path": "data.txt", "sessionId": ctx.session_id, **params},
        ctx,
        _config(root),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["line", "limit"])
@pytest.mark.parametrize(
    "value", [-1, "-1", " -2 ", -1.0, -0.5, 0.5, True, False, "", [], {}, "1", 1.0]
)
async def test_invalid_ranges_are_rejected_before_file_io(
    tmp_path: Path, acp_session_context: AcpSessionContext, field: str, value: JsonValue
) -> None:
    response = await _read(tmp_path, acp_session_context, {field: value})
    error = response.get("error")
    assert isinstance(error, dict)
    assert error["code"] == -32603
    assert field in str(error["message"])
    assert "result" not in response


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [-1, "-1", -1.0, -0.5])
async def test_negative_limits_never_return_workspace_content(
    tmp_path: Path, acp_session_context: AcpSessionContext, value: JsonValue
) -> None:
    (tmp_path / "data.txt").write_text("workspace-sentinel", encoding="utf-8")
    response = await _read(tmp_path, acp_session_context, {"limit": value})
    assert "error" in response
    assert "result" not in response
    assert "workspace-sentinel" not in str(response)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ranges", "expected"),
    [
        ({}, "one\ntwo\nthree"),
        ({"line": None, "limit": None}, "one\ntwo\nthree"),
        ({"line": 1}, "one\ntwo\nthree"),
        ({"limit": 0}, ""),
        ({"line": 2, "limit": 1}, "two\n"),
        ({"line": 2, "limit": 2}, "two\nthree"),
        ({"line": 3, "limit": 1}, "three"),
        ({"line": 20, "limit": 1}, ""),
        ({"limit": 2**32 - 1}, "one\ntwo\nthree"),
        ({"_meta": {"offset": 100}}, "one\ntwo\nthree"),
    ],
)
async def test_line_selection_and_optional_ranges(
    tmp_path: Path,
    acp_session_context: AcpSessionContext,
    ranges: JsonObject,
    expected: str,
) -> None:
    (tmp_path / "data.txt").write_text("one\ntwo\nthree", encoding="utf-8")
    assert await _read(tmp_path, acp_session_context, ranges) == jsonrpc_result(
        7, {"content": expected}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("ranges", [{"line": 0}, {"line": 2**32}, {"limit": 2**32}])
async def test_ranges_outside_the_protocol_domain_are_rejected(
    tmp_path: Path, acp_session_context: AcpSessionContext, ranges: JsonObject
) -> None:
    response = await _read(tmp_path, acp_session_context, ranges)
    assert "error" in response
    assert "result" not in response


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [None, 0, 1, -1, "1", False])
async def test_legacy_offsets_are_never_accepted(
    tmp_path: Path, acp_session_context: AcpSessionContext, offset: JsonValue
) -> None:
    (tmp_path / "data.txt").write_text("must-not-leak", encoding="utf-8")
    response = await _read(tmp_path, acp_session_context, {"offset": offset})
    assert "error" in response
    assert "result" not in response
    assert "offset" in str(response["error"])


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [None, "", "other-session", 1, False, "x" * 513])
async def test_foreign_and_invalid_session_ids_are_refused(
    tmp_path: Path, acp_session_context: AcpSessionContext, session: JsonValue
) -> None:
    (tmp_path / "data.txt").write_text("must-not-leak", encoding="utf-8")
    response = await _read(tmp_path, acp_session_context, {"sessionId": session})
    assert "error" in response
    assert "result" not in response
    assert "must-not-leak" not in str(response)


@pytest.mark.asyncio
async def test_reads_require_an_established_session(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    (tmp_path / "data.txt").write_text("must-not-leak", encoding="utf-8")
    acp_session_context.session_id = None
    response = await _read(tmp_path, acp_session_context, {"sessionId": "caller-id"})
    assert "error" in response and "result" not in response
    response = await on_fs_read_text_file(
        8, {"path": "data.txt"}, acp_session_context, _config(tmp_path)
    )
    assert "error" in response and "result" not in response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cap", "expected"),
    [
        (0, ""),
        (1, "A"),
        (4, "A"),
        (5, "A🙂"),
        (6, "A🙂"),
        (7, "A🙂é"),
        (9, "A🙂éB\n"),
    ],
)
async def test_byte_caps_preserve_complete_utf8_characters(
    tmp_path: Path, acp_session_context: AcpSessionContext, cap: int, expected: str
) -> None:
    (tmp_path / "data.txt").write_text("A🙂éB\nsecond", encoding="utf-8")
    with settings_override(acp_fs_read_max_bytes=cap):
        response = await _read(tmp_path, acp_session_context, {})
    assert response["result"] == {"content": expected}
    assert len(expected.encode("utf-8")) <= cap


@pytest.mark.asyncio
async def test_chunks_are_not_counted_as_lines(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    (tmp_path / "data.txt").write_text(
        "x" * 100_000 + "\nsecond\nthird", encoding="utf-8"
    )
    response = await _read(tmp_path, acp_session_context, {"line": 2, "limit": 1})
    assert response["result"] == {"content": "second\n"}
    (tmp_path / "data.txt").write_text("é" * 10_000 + "\nnext", encoding="utf-8")
    with settings_override(acp_fs_read_max_bytes=8193):
        response = await _read(tmp_path, acp_session_context, {"limit": 1})
    assert response["result"] == {"content": "é" * 4096}


@pytest.mark.asyncio
async def test_normalized_newlines_count_as_lines(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    (tmp_path / "data.txt").write_bytes(b"first\r\nsecond\rthird\n")
    response = await _read(tmp_path, acp_session_context, {"line": 2, "limit": 2})
    assert response["result"] == {"content": "second\nthird\n"}


@pytest.mark.asyncio
async def test_large_reads_stop_at_the_configured_byte_cap(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    cap = settings.acp_fs_read_max_bytes
    (tmp_path / "data.txt").write_text("x" * cap + "must-not-leak", encoding="utf-8")
    response = await _read(tmp_path, acp_session_context, {})
    assert response["result"] == {"content": "x" * cap}
    assert (
        _read_workspace_text("data.txt", _config(tmp_path), line=1, limit=1)
        == "x" * cap
    )


@pytest.mark.parametrize("cap", [-1, "-1"])
def test_configuration_rejects_negative_read_caps(cap: int | str) -> None:
    with pytest.raises(ValidationError, match="acp_fs_read_max_bytes"):
        InfraConfig.model_validate({"acp_fs_read_max_bytes": cap})


def test_configuration_allows_a_zero_read_cap() -> None:
    assert InfraConfig(acp_fs_read_max_bytes=0).acp_fs_read_max_bytes == 0


@pytest.mark.asyncio
async def test_runtime_negative_cap_fails_before_io(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    with settings_override(acp_fs_read_max_bytes=-1):
        response = await _read(tmp_path, acp_session_context, {"limit": 0})
    assert "error" in response
    assert "acp_fs_read_max_bytes" in str(response["error"])
    assert "result" not in response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ranges", "expected"),
    [
        ({"line": 2, "limit": 1}, "two\n"),
        ({"limit": -1}, None),
        ({"sessionId": "foreign"}, None),
        ({"offset": 0}, None),
    ],
)
async def test_json_dispatch_returns_exact_responses_through_real_pipes(
    tmp_path: Path,
    echo_context: AcpSessionContext,
    ranges: JsonObject,
    expected: str | None,
) -> None:
    (tmp_path / "data.txt").write_text("one\ntwo\nthree", encoding="utf-8")
    echo_context.session_id = "wire-session"
    agent = AgentConfig.model_validate(
        {
            "id": "reader",
            "display_name": "Reader",
            "role": "reader",
            "description": "ACP file reader",
            "persona": {"system_prompt": "Read"},
            "capabilities": {"filesystem_read": True},
        }
    )
    request = acp_request(
        11,
        "fs/read_text_file",
        {"path": "data.txt", "sessionId": "wire-session", **ranges},
    )
    await _dispatch_stdout_line(
        json.dumps(request).encode("utf-8"),
        echo_context,
        replace(_config(tmp_path), agent_config=agent),
        {"fs/read_text_file": on_fs_read_text_file},
    )
    response = await read_acp_frame(echo_context.stdout, 11, timeout=5)
    if expected is None:
        assert "error" in response and "result" not in response
    else:
        assert response == jsonrpc_result(11, {"content": expected})


@pytest.mark.service
@pytest.mark.asyncio
async def test_installed_sdk_reads_over_a_negotiated_session(tmp_path: Path) -> None:
    """Prove the installed SDK transport, without claiming a native model tool call."""
    node = shutil.which("node")
    assert node is not None, "Install the pinned Node toolchain before service tests"
    repository = Path(__file__).resolve().parents[4]
    (tmp_path / "data.txt").write_text("first\n🙂éZZ\nthird", encoding="utf-8")
    peer = """
import { agent, methods, ndJsonStream } from '@agentclientprotocol/sdk';
import { Readable, Writable } from 'node:stream';
agent({ name: 'read-contract-peer' })
  .onRequest('initialize', ({params}) => {
    if (!params.clientCapabilities.fs.readTextFile) {
      throw new Error('missing capability');
    }
    if (params.clientCapabilities.terminal) {
      throw new Error('unisolated terminal capability advertised');
    }
    return {protocolVersion: 1, agentCapabilities: {}, authMethods: []};
  })
  .onRequest('session/new', () => ({
    sessionId: 'sdk-read-session',
    modes: {
      currentModeId: 'default',
      availableModes: [{id: 'default', name: 'Default'}]
    }
  }))
  .onRequest('session/prompt', async ({params, client}) => {
    const read = ranges => client.request(methods.client.fs.readTextFile, {
      sessionId: params.sessionId, path: 'data.txt', ...ranges
    });
    const first = await read({line: 2, limit: 1});
    const empty = await read({limit: 0});
    let foreignRefused = false;
    try { await read({sessionId: 'foreign-session'}); }
    catch (error) { foreignRefused = error.code === -32603; }
    const write = await client.request(methods.client.fs.writeTextFile, {
      sessionId: params.sessionId, path: 'sdk-written.txt', content: 'owner write'
    });
    let foreignWriteRefused = false;
    try {
      await client.request(methods.client.fs.writeTextFile, {
        sessionId: 'foreign-session', path: 'foreign.txt', content: 'foreign write'
      });
    } catch (error) { foreignWriteRefused = error.code === -32603; }
    let terminalRefused = false;
    try {
      await client.request(methods.client.terminal.create, {
        sessionId: params.sessionId, command: 'python', args: ['--version']
      });
    } catch (error) {
      terminalRefused = error.code === -32603 &&
        error.message.includes('workspace OS isolation');
    }
    return {stopReason: 'end_turn',
      _meta: {first, empty, foreignRefused, write, foreignWriteRefused,
        terminalRefused}};
  })
  .connect(ndJsonStream(Writable.toWeb(process.stdout), Readable.toWeb(process.stdin)));
"""
    agent = AgentConfig.model_validate(
        {
            "id": "sdk-reader",
            "display_name": "SDK reader",
            "role": "reader",
            "description": "ACP SDK contract reader",
            "persona": {"system_prompt": "Read"},
            "capabilities": {
                "filesystem_read": True,
                "filesystem_write": True,
                "terminal": True,
            },
        }
    )
    process = await asyncio.create_subprocess_exec(
        node,
        "--input-type=module",
        "-e",
        peer,
        cwd=repository,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    context = AcpSessionContext(
        process=process,
        stdin=process.stdin,
        stdout=process.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
    )
    config = replace(_config(tmp_path), agent_config=agent)
    reader = asyncio.create_task(
        process_stdout_loop(
            context,
            config,
            {
                "fs/read_text_file": on_fs_read_text_file,
                "fs/write_text_file": on_fs_write_text_file,
                "terminal/create": on_terminal_create,
                "terminal/output": on_terminal_output,
                "terminal/wait_for_exit": on_terminal_wait_for_exit,
                "terminal/kill": on_terminal_kill,
                "terminal/release": on_terminal_release,
            },
        )
    )
    try:
        with settings_override(acp_fs_read_max_bytes=5):
            async with asyncio.timeout(15):
                initialized = await initialize_session(context, config)
                session = await setup_session(context, config, initialized.auth_methods)
                assert context.session_id == session.session_id == "sdk-read-session"
                response = await issue_request(
                    context.response_futures,
                    stdin=context.stdin,
                    stdin_lock=context.stdin_lock,
                    rpc_id=42,
                    method="session/prompt",
                    params={
                        "sessionId": session.session_id,
                        "prompt": [{"type": "text", "text": "Read the selected line"}],
                    },
                )
                assert await response == jsonrpc_result(
                    42,
                    {
                        "stopReason": "end_turn",
                        "_meta": {
                            "first": {"content": "🙂"},
                            "empty": {"content": ""},
                            "foreignRefused": True,
                            "write": {},
                            "foreignWriteRefused": True,
                            "terminalRefused": True,
                        },
                    },
                )
                assert (tmp_path / "sdk-written.txt").read_text() == "owner write"
                assert not (tmp_path / "foreign.txt").exists()
                assert not context.terminals
    finally:
        for terminal_id in tuple(context.terminals):
            await release_owned_terminal(terminal_id, context)
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
        await reader
