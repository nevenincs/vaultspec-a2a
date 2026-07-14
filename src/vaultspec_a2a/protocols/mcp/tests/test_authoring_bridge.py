"""Tests for the authoring tool-catalog MCP bridge (ADR R4, S19).

No mocks: the tool advertisement is proven over the REAL MCP protocol using the
in-memory connected client/server helper — the same list_tools/call_tool path a
spawned agent drives. Asserts the agent sees exactly the catalog's propose/read
tools and NO filesystem-write tool.
"""

import json

import pytest

from ....authoring.catalog import CATALOG_SCHEMA_VERSION, parse_catalog
from ..tools.authoring_bridge import (
    authoring_mcp_server_config,
    build_authoring_mcp_server,
    build_tool_specs,
)

# The live catalog shape (authoring.semantic_tools.v1): the 7 semantic tools.
_LIVE_CATALOG = {
    "schema_version": CATALOG_SCHEMA_VERSION,
    "tools": [
        {
            "name": "read_context",
            "description": "Read bounded authoring context.",
            "permission_requirement": "auto_permitted",
            "risk_tier": "read_only",
            "idempotency_required": False,
            "commands": ["read_context"],
            "input_schema": {"type": "object"},
        },
        {
            "name": "search_graph",
            "description": "Search the bounded project graph.",
            "permission_requirement": "auto_permitted",
            "risk_tier": "read_only",
            "idempotency_required": False,
            "commands": ["search_graph"],
            "input_schema": {"type": "object", "required": ["query"]},
        },
        {
            "name": "propose_changeset",
            "description": "Create a proposal changeset.",
            "permission_requirement": "human_approval_required",
            "risk_tier": "mutating",
            "idempotency_required": True,
            "commands": ["create_proposal", "append_draft", "replace_draft"],
            "input_schema": {"type": "object"},
        },
        {
            "name": "validate_proposal",
            "description": "Request backend validation.",
            "permission_requirement": "human_approval_required",
            "risk_tier": "mutating",
            "idempotency_required": True,
            "commands": ["validate_proposal"],
            "input_schema": {"type": "object"},
        },
        {
            "name": "request_approval",
            "description": "Submit a validated proposal into review.",
            "permission_requirement": "human_approval_required",
            "risk_tier": "mutating",
            "idempotency_required": True,
            "commands": ["submit_for_review"],
            "input_schema": {"type": "object"},
        },
        {
            "name": "cancel",
            "description": "Cancel a proposal or run.",
            "permission_requirement": "human_approval_required",
            "risk_tier": "mutating",
            "idempotency_required": True,
            "commands": ["cancel_proposal", "cancel_run"],
            "input_schema": {"type": "object"},
        },
        {
            "name": "request_apply",
            "description": "Request application of an approved proposal.",
            "permission_requirement": "human_approval_required",
            "risk_tier": "dangerous",
            "idempotency_required": True,
            "commands": ["request_apply"],
            "input_schema": {"type": "object"},
        },
    ],
}

_EXPECTED_NAMES = {
    "read_context",
    "search_graph",
    "propose_changeset",
    "validate_proposal",
    "request_approval",
    "cancel",
    "request_apply",
}


def test_server_config_is_http_entry() -> None:
    entry = authoring_mcp_server_config("authoring", "http://127.0.0.1:9/mcp")
    assert entry == {
        "type": "http",
        "name": "authoring",
        "url": "http://127.0.0.1:9/mcp",
    }


def test_tool_specs_carry_no_write_tool() -> None:
    specs = build_tool_specs(parse_catalog(_LIVE_CATALOG))
    names = {spec["name"] for spec in specs}
    assert names == _EXPECTED_NAMES
    assert not any(
        "write" in name or "fs" in name or name == "edit_file" for name in names
    )


@pytest.mark.asyncio
async def test_agent_sees_authoring_tools_over_real_mcp() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    snapshot = parse_catalog(_LIVE_CATALOG)

    async def _dispatch(name: str, arguments: dict) -> dict:
        return {"tool": name, "arguments": arguments, "disposition": "dispatched"}

    server = build_authoring_mcp_server(snapshot, _dispatch)

    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_tools()
        names = {tool.name for tool in listed.tools}
        # The agent sees exactly the catalog's tools...
        assert names == _EXPECTED_NAMES
        # ...including the propose and read tools...
        assert "propose_changeset" in names
        assert "read_context" in names
        # ...and NO filesystem-write / vault-write tool of any kind.
        assert not any(
            "write" in n or "fs" in n or n in {"edit_file", "create_file"}
            for n in names
        )


@pytest.mark.asyncio
async def test_call_tool_routes_to_dispatch_over_real_mcp() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    snapshot = parse_catalog(_LIVE_CATALOG)
    calls: list[tuple[str, dict]] = []

    async def _dispatch(name: str, arguments: dict) -> dict:
        calls.append((name, arguments))
        return {"tool": name, "disposition": "dispatched"}

    server = build_authoring_mcp_server(snapshot, _dispatch)

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("search_graph", {"query": "edge contract"})
        assert calls == [("search_graph", {"query": "edge contract"})]
        text = result.content[0]
        assert text.type == "text"
        payload = json.loads(text.text)
        assert payload["tool"] == "search_graph"
        assert payload["disposition"] == "dispatched"
