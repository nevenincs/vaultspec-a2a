"""Tests for the authoring tool-catalog MCP bridge.

No mocks: the tool advertisement is proven over the REAL MCP protocol using the
in-memory connected client/server helper — the same list_tools/call_tool path a
spawned agent drives. Asserts the agent sees exactly the catalog's propose/read
tools and NO filesystem-write tool.
"""

import json

import pytest
from mcp.types import TextContent

from ....authoring.catalog import CATALOG_SCHEMA_VERSION, parse_catalog
from ..tools.authoring_bridge import (
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


def test_tool_specs_carry_no_write_tool() -> None:
    specs = build_tool_specs(parse_catalog(_LIVE_CATALOG))
    names = {spec["name"] for spec in specs}
    assert names == _EXPECTED_NAMES
    assert not any(
        "write" in name or "fs" in name or name == "edit_file" for name in names
    )


@pytest.mark.asyncio
async def test_agent_sees_authoring_tools_over_real_mcp() -> None:
    from mcp.client import Client

    snapshot = parse_catalog(_LIVE_CATALOG)

    async def _dispatch(name: str, arguments: dict) -> dict:
        return {"tool": name, "arguments": arguments, "disposition": "dispatched"}

    server = build_authoring_mcp_server(snapshot, _dispatch)

    async with Client(server) as client:
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
    from mcp.client import Client

    snapshot = parse_catalog(_LIVE_CATALOG)
    calls: list[tuple[str, dict]] = []

    async def _dispatch(name: str, arguments: dict) -> dict:
        calls.append((name, arguments))
        return {"tool": name, "disposition": "dispatched"}

    server = build_authoring_mcp_server(snapshot, _dispatch)

    async with Client(server) as client:
        result = await client.call_tool("search_graph", {"query": "edge contract"})
        assert calls == [("search_graph", {"query": "edge contract"})]
        text = result.content[0]
        assert text.type == "text"
        payload = json.loads(text.text)
        assert payload["tool"] == "search_graph"
        assert payload["disposition"] == "dispatched"


@pytest.mark.asyncio
async def test_unknown_tool_returns_agent_visible_error_over_real_mcp() -> None:
    """An unknown name is an error-flagged RESULT, not a JSON-RPC protocol error.

    The distinction is what the agent can see. A raised handler exception is
    answered as a top-level protocol error that the client raises on, so the
    model never receives the text and cannot self-correct. Asserting the call
    returns is what keeps the message inside the model's turn.
    """
    from mcp.client import Client

    snapshot = parse_catalog(_LIVE_CATALOG)
    dispatched: list[str] = []

    async def _dispatch(name: str, arguments: dict) -> dict:
        dispatched.append(name)
        return {"tool": name}

    server = build_authoring_mcp_server(snapshot, _dispatch)

    async with Client(server) as client:
        result = await client.call_tool("edit_file", {"path": "x"})

    assert result.is_error is True
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert "unknown authoring tool" in block.text
    # The unknown name never reached the engine dispatcher.
    assert dispatched == []


@pytest.mark.asyncio
async def test_dispatch_failure_returns_agent_visible_error_over_real_mcp() -> None:
    """A failing engine dispatch stays an error-flagged result, as in the v1 bridge."""
    from mcp.client import Client

    snapshot = parse_catalog(_LIVE_CATALOG)

    async def _dispatch(name: str, arguments: dict) -> dict:
        raise RuntimeError("engine refused the call")

    server = build_authoring_mcp_server(snapshot, _dispatch)

    async with Client(server) as client:
        result = await client.call_tool("search_graph", {"query": "q"})

    assert result.is_error is True
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert "engine refused the call" in block.text


@pytest.mark.asyncio
async def test_tool_annotations_reach_the_client_over_real_mcp() -> None:
    """The catalog's risk vocabulary is advertised, not kept private.

    Before MCP 2.0 this information lived only in the spec's private ``_engine``
    key, which no client can read - so a client deciding whether to auto-approve
    a call had nothing to go on but the tool name. Asserting it over a real
    session is what proves the annotations survive serialization rather than
    merely being set on the object.
    """
    from mcp.client import Client

    snapshot = parse_catalog(_LIVE_CATALOG)

    async def _dispatch(name: str, arguments: dict) -> dict:
        return {"tool": name}

    server = build_authoring_mcp_server(snapshot, _dispatch)

    async with Client(server) as client:
        listed = await client.list_tools()

    by_name = {tool.name: tool for tool in listed.tools}
    catalog_by_name = {tool.name: tool for tool in snapshot.tools}
    assert by_name, "the bridge advertised no tools"

    for name, tool in by_name.items():
        source = catalog_by_name[name]
        assert tool.annotations is not None, f"{name} lost its annotations"
        # read_only_hint is the exact inverse of the catalog's own mutation
        # decision, so a tier change moves both together or neither.
        assert tool.annotations.read_only_hint is (not source.is_mutating)
        assert tool.annotations.idempotent_hint is source.idempotency_required
        assert tool.annotations.destructive_hint is (source.risk_tier == "dangerous")

    # The bridge's safety story is that it carries no write tool; that must be
    # visible in the protocol, not only in the construction.
    read_only = [
        name
        for name, tool in by_name.items()
        if tool.annotations is not None and tool.annotations.read_only_hint
    ]
    assert read_only, "no read-only tool was advertised as read-only"


def test_non_conforming_engine_tool_name_is_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A catalog name the spec forbids is surfaced rather than served silently.

    Tool names come from the engine, so the bridge cannot assume they are
    well-formed. A space is illegal under SEP-986, and a client that rejects the
    name drops the tool the same silent way a bad input schema would - the very
    failure mode this module exists to prevent.
    """
    catalog = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "tools": [
            {
                "name": "read context",  # illegal: contains a space
                "description": "Read bounded authoring context.",
                "permission_requirement": "auto_permitted",
                "risk_tier": "read_only",
                "idempotency_required": False,
                "commands": ["read_context"],
                "input_schema": {"type": "object"},
            }
        ],
    }

    async def _dispatch(name: str, arguments: dict) -> dict:
        return {"tool": name}

    with caplog.at_level("WARNING"):
        build_authoring_mcp_server(parse_catalog(catalog), _dispatch)

    assert any(
        "read context" in record.message and "SEP-986" in record.message
        for record in caplog.records
    ), f"no SEP-986 warning was logged; saw {[r.message for r in caplog.records]}"


def test_conforming_engine_tool_names_are_not_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The live catalog's names are legal, so the check must stay quiet.

    Without this, a validator that warned unconditionally would still satisfy
    the test above.
    """

    async def _dispatch(name: str, arguments: dict) -> dict:
        return {"tool": name}

    with caplog.at_level("WARNING"):
        build_authoring_mcp_server(parse_catalog(_LIVE_CATALOG), _dispatch)

    assert not [r for r in caplog.records if "SEP-986" in r.message]
