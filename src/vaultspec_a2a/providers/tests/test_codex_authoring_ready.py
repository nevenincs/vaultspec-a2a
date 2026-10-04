"""The actual turn driver must verify its thread's MCP surface before work."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ...authoring.catalog import parse_catalog
from ...authoring.tests.test_dispatch_injection import _BEARER, _CATALOG
from ...testing import settings_override
from .._acp_authoring import AuthoringToolBinding, codex_authoring_mcp_server_spec
from .._codex_protocol import _CodexProtocolError
from ..codex_chat_model import CodexChatModel

if TYPE_CHECKING:
    from pathlib import Path

# A real subprocess speaks the installed app-server's public JSON-RPC schema.
# It controls inventory responses, not the code under test or its tool checks.
_PEER = r"""
import json, sys
from pathlib import Path
scenario, events = sys.argv[1], Path(sys.argv[2])
names = json.loads(Path(sys.argv[3]).read_text())
checks = 0
def emit(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method, params = request['method'], request.get('params', {})
    with events.open('a') as stream:
        stream.write(json.dumps({'method': method, 'params': params})+'\n')
    if method == 'initialize':
        result = {}
    elif method == 'thread/start':
        result = {'thread': {'id': 'inventory-thread'}}
    elif method == 'mcpServerStatus/list':
        assert params['threadId'] == 'inventory-thread'
        checks += 1
        tools = {name: {'name': name, 'inputSchema': {}} for name in names}
        status = 'connected'
        pending = checks == 1 or scenario == 'never-ready'
        if scenario in ('starting', 'never-ready') and pending:
            tools, status = {}, 'starting'
        if scenario == 'missing-tool':
            tools.pop(names[0])
        if scenario == 'malformed-tool':
            tools[names[0]] = {'name': [names[0]], 'inputSchema': {}}
        if scenario == 'failed':
            status = 'failed'
        server = {'name': 'vaultspec-authoring', 'runtimeStatus': status,
                  'tools': tools, 'toolsError': None, 'authStatus': 'unsupported'}
        result = {'data': [server], 'nextCursor': None}
        if scenario == 'duplicate':
            result['data'].append(server)
        if scenario == 'absent':
            result['data'] = []
        if scenario == 'page' and params['cursor'] is None:
            result = {'data': [{'name': 'foreign', 'tools': {}}], 'nextCursor': 'next'}
        if scenario == 'cursor-cycle':
            result = {'data': [], 'nextCursor': 'repeated'}
    elif method == 'turn/start':
        result = {'turn': {'id': 'inventory-turn'}}
    else:
        raise AssertionError(method)
    emit({'id': request['id'], 'result': result})
    if method == 'turn/start':
        assert checks > 0, 'model work started before MCP inventory'
        emit({'method': 'item/agentMessage/delta', 'params': {
            'threadId': 'inventory-thread', 'delta': 'done'}})
        emit({'method': 'turn/completed', 'params': {
            'threadId': 'inventory-thread', 'turn': {
                'id': 'inventory-turn', 'status': 'completed', 'error': None}}})
"""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario, failure",
    [
        ("connected", None),
        ("starting", None),
        ("page", None),
        ("missing-tool", "inventory is incomplete"),
        ("malformed-tool", "inventory is incomplete"),
        ("duplicate", "repeated the authoring server"),
        ("failed", "failed startup"),
        ("absent", "did not load"),
        ("cursor-cycle", "invalid MCP cursor"),
        ("never-ready", "timeout"),
    ],
)
async def test_turn_requires_its_actual_authoring_surface(
    tmp_path: Path, scenario: str, failure: str | None
) -> None:
    events = tmp_path / "requests.jsonl"
    peer = tmp_path / "app_server_peer.py"
    peer.write_text(_PEER)
    snapshot = parse_catalog(_CATALOG)
    names = tmp_path / "tool_names.json"
    names.write_text(json.dumps(snapshot.tool_names()))
    with settings_override(codex_home=str(tmp_path / "empty-login")):
        binding = AuthoringToolBinding(
            snapshot=snapshot,
            bearer_token=_BEARER,
            actor_token="test-actor",
            engine_base_url="http://127.0.0.1:65534",
            run_id=f"inventory:{scenario}",
            call_scope="writer",
        )
        model = CodexChatModel(
            command=[
                sys.executable,
                str(peer),
                scenario,
                str(events),
                str(names),
            ],
            workspace_root=str(tmp_path),
            # The timeout case must reach the inventory loop, rather than time
            # out while a real interpreter is still completing initialization.
            timeout=5,
        ).with_authoring_mcp_server(codex_authoring_mcp_server_spec(binding))
        if failure == "timeout":
            with pytest.raises(TimeoutError):
                await model.ainvoke([HumanMessage(content="start")])
        elif failure:
            with pytest.raises(_CodexProtocolError, match=failure):
                await model.ainvoke([HumanMessage(content="start")])
        else:
            answer = await model.ainvoke([HumanMessage(content="start")])
            assert answer.content == "done"
    requests = [json.loads(line) for line in events.read_text().splitlines()]
    methods = [request["method"] for request in requests]
    assert ("turn/start" in methods) is (failure is None)
    if scenario in {"starting", "page", "cursor-cycle", "never-ready"}:
        assert methods.count("mcpServerStatus/list") >= 2
