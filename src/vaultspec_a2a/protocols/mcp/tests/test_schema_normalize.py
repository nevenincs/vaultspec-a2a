"""Tests for catalog input-schema normalization at the bridge boundary.

The fixture ``catalog.json`` carries the REAL engine catalog schemas (the custom
DSL from ``engine/.../authoring/tools.rs`` - the same shapes es-3's live catalog
dump captured), not invented shapes. The pinned CLI validates a tool's
``inputSchema`` as JSON Schema and silently drops non-conforming tools, so every
served schema must be a valid JSON Schema object.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ....authoring.catalog import parse_catalog
from ..tools.authoring_bridge import build_authoring_mcp_server, build_tool_specs
from ..tools.schema_normalize import normalize_tool_input_schema

_CATALOG = json.loads((Path(__file__).parent / "catalog.json").read_text("utf-8"))


def _schema_for(name: str) -> dict:
    for tool in _CATALOG["tools"]:
        if tool["name"] == name:
            return tool["input_schema"]
    raise KeyError(name)


def test_every_real_catalog_tool_normalizes_to_json_schema_object() -> None:
    # The whole real catalog (all DSL shapes) becomes valid JSON Schema objects
    # through the single serving seam - none would be dropped by the CLI.
    specs = build_tool_specs(parse_catalog(_CATALOG))
    assert specs, "fixture catalog is non-empty"
    for spec in specs:
        schema = spec["inputSchema"]
        # The load-bearing invariant: a JSON Schema object the CLI keeps rather
        # than silently drops. (additionalProperties is closed for fully-enumerated
        # tools and open for payload-carrying ones - asserted per tool below.)
        assert schema["type"] == "object", spec["name"]
        assert isinstance(schema["properties"], dict), spec["name"]
        assert schema.get("additionalProperties", False) in (False, True), spec["name"]


def test_read_context_translates_to_documented_shape() -> None:
    schema, guidance = normalize_tool_input_schema(_schema_for("read_context"))
    assert schema == {
        "type": "object",
        "properties": {
            "document": {"type": "string"},
            "revision": {"type": "string"},
            "max_bytes": {"type": "string"},
            "changeset_id": {"type": "string"},
            "session_id": {"type": "string"},
            "cursor": {"type": "string"},
            "cap": {"type": "string"},
            "target": {
                "type": "string",
                "enum": ["document", "proposal", "session", "document_list"],
            },
        },
        "additionalProperties": False,
        # Per-branch required sets are disjoint, so the intersection is empty and
        # no top-level required is emitted; the requirements ride the guidance.
    }
    assert "target='document' requires document" in guidance


def test_propose_changeset_passes_through_valid_engine_schema() -> None:
    # The newer engine serves propose_changeset as a valid JSON Schema; the
    # normalizer detects that and passes the model-owned content through VERBATIM
    # (nested operations preserved), stripping only the dispatcher-injected ids.
    raw = _schema_for("propose_changeset")
    injected = frozenset({"session_id", "changeset_id"})
    schema, guidance = normalize_tool_input_schema(raw, injected)
    props = schema["properties"]
    assert props["operation"] == {
        "type": "string",
        "enum": ["create", "append", "replace"],
    }
    ops = props["operations"]
    assert ops["type"] == "array"
    item = ops["items"]["properties"]
    assert "child_key" in item
    assert "create_document" in item["operation"]["enum"]
    document = item["target"]["properties"]["document"]["properties"]
    # Both DocumentRef variants ride through: ProvisionalCreate + Existing.
    assert "collision_status" in document
    assert "provisional_doc_id" in document
    assert "node_id" in document
    assert "body" in item["draft"]["properties"]
    # Verbatim: the nested operations shape is byte-identical to what the engine
    # served (the engine advertises no injected ids there, so nothing changes).
    assert ops == raw["properties"]["operations"]
    # The engine's scoped-follow-up description rides through untouched.
    assert schema["description"] == raw["description"]
    # Dispatcher-injected ids are absent; guidance names them as withheld.
    assert "session_id" not in props
    assert "changeset_id" not in props
    assert "session_id" in guidance
    assert "changeset_id" in guidance


def test_deep_strips_injected_ids_wherever_they_appear() -> None:
    # A valid schema that (wrongly) advertises an injected id at the top level AND
    # nested must have it removed from every properties map and required list -
    # the model must never see a dispatcher-owned id. A non-injected sibling and
    # the source schema both survive intact.
    raw = {
        "type": "object",
        "properties": {
            "changeset_id": {"type": "string"},
            "summary": {"type": "string"},
            "nested": {
                "type": "object",
                "properties": {
                    "changeset_id": {"type": "string"},
                    "keep": {"type": "string"},
                },
                "required": ["changeset_id", "keep"],
            },
        },
        "required": ["changeset_id", "summary"],
    }
    schema, _guidance = normalize_tool_input_schema(raw, frozenset({"changeset_id"}))
    assert "changeset_id" not in schema["properties"]
    assert "summary" in schema["properties"]
    assert schema["required"] == ["summary"]
    nested = schema["properties"]["nested"]
    assert "changeset_id" not in nested["properties"]
    assert "keep" in nested["properties"]
    assert nested["required"] == ["keep"]
    # Source untouched: normalization happens on a copy at serving time only.
    assert "changeset_id" in raw["properties"]
    assert raw["required"] == ["changeset_id", "summary"]


def test_dsl_fallback_translates_older_engine_propose_schema() -> None:
    # Version skew: an older engine serves propose_changeset as the custom DSL
    # (oneOf branches, no top-level type/properties), some carrying inlined
    # properties. The fallback path still yields a valid JSON Schema object - the
    # operation discriminator enumerated, the inlined operations content merged
    # verbatim, injected ids stripped, aliases named in guidance.
    dsl = {
        "oneOf": [
            {
                "operation": "create",
                "properties": {
                    "summary": {"type": "string"},
                    "operations": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["summary", "operations"],
            },
            {"operation": "append", "alias_of": "append_draft"},
        ],
        "additionalProperties": False,
    }
    schema, guidance = normalize_tool_input_schema(
        dsl, frozenset({"session_id", "changeset_id"})
    )
    assert schema["type"] == "object"
    props = schema["properties"]
    assert props["operation"] == {"type": "string", "enum": ["create", "append"]}
    # Inlined DSL-branch content is preserved verbatim by the fallback path too.
    assert props["operations"] == {"type": "array", "items": {"type": "object"}}
    assert "session_id" not in props
    assert "append_draft" in guidance


def test_mixed_catalog_routes_each_tool_through_the_right_path() -> None:
    # A catalog with one valid-schema tool (propose, pass-through) and one DSL
    # tool (read_context, translated) - the normalizer handles both in one sweep.
    mixed = {
        "schema_version": _CATALOG["schema_version"],
        "tools": [
            next(t for t in _CATALOG["tools"] if t["name"] == "propose_changeset"),
            next(t for t in _CATALOG["tools"] if t["name"] == "read_context"),
        ],
    }
    by_name = {s["name"]: s for s in build_tool_specs(parse_catalog(mixed))}
    # propose was passed through verbatim: its rich nested operations shape stays.
    propose = by_name["propose_changeset"]["inputSchema"]
    assert "child_key" in propose["properties"]["operations"]["items"]["properties"]
    # read_context was DSL-translated: its oneOf branches collapsed to a target
    # discriminator enum with permissive fields (a shape the DSL never had).
    read = by_name["read_context"]["inputSchema"]
    assert read["properties"]["target"]["enum"] == [
        "document",
        "proposal",
        "session",
        "document_list",
    ]
    assert read["properties"]["document"] == {"type": "string"}


def test_served_propose_changeset_surfaces_operations_shape() -> None:
    # Contract check: through the real serving seam (build_tool_specs applies the
    # per-tool injected map), the model sees the nested operations schema it must
    # build - proving a2a consumes what the engine now serves.
    by_name = {s["name"]: s for s in build_tool_specs(parse_catalog(_CATALOG))}
    ops = by_name["propose_changeset"]["inputSchema"]["properties"]["operations"]
    assert ops["type"] == "array"
    assert "child_key" in ops["items"]["properties"]


def test_request_apply_payload_is_sendable_and_named() -> None:
    schema, guidance = normalize_tool_input_schema(_schema_for("request_apply"))
    assert schema["type"] == "object"
    # Open so the model can send the opaque ApplyRequest payload; named in guidance.
    assert "additionalProperties" not in schema
    assert "ApplyRequest" in guidance


def test_search_graph_bounds_go_to_guidance_not_schema() -> None:
    schema, guidance = normalize_tool_input_schema(_schema_for("search_graph"))
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"query", "scope", "type", "max_results"}
    assert schema["required"] == ["query"]
    assert "bounds" not in schema
    assert "query_chars_max=512" in guidance


def test_unknown_dsl_keywords_are_dropped_and_summarized() -> None:
    # validate_proposal carries alias_of + backend_derived: neither is JSON Schema,
    # so both are dropped from the schema and summarized into guidance instead.
    # (No injection here - the raw keyword-dropping behavior.)
    schema, guidance = normalize_tool_input_schema(_schema_for("validate_proposal"))
    assert schema["type"] == "object"
    assert "alias_of" not in schema
    assert "backend_derived" not in schema
    assert set(schema["properties"]) == {"changeset_id", "expected_revision", "summary"}
    assert schema["required"] == ["changeset_id", "expected_revision", "summary"]
    assert "alias_of" in guidance
    assert "backend_derived" in guidance


def test_injected_fields_hidden_from_schema_and_guidance() -> None:
    # The dispatcher owns changeset_id + expected_revision for validate; they must
    # vanish from the model's contract, leaving only the model-owned summary.
    injected = frozenset({"changeset_id", "expected_revision"})
    schema, _guidance = normalize_tool_input_schema(
        _schema_for("validate_proposal"), injected
    )
    assert set(schema["properties"]) == {"summary"}
    assert schema["required"] == ["summary"]
    assert "changeset_id" not in schema["properties"]
    assert "expected_revision" not in schema["properties"]


def test_served_injected_tools_hide_owned_ids() -> None:
    # Through the real serving seam (map applied), the proposal-lifecycle tools do
    # not expose the dispatcher-owned ids; read_context keeps its model-owned ones.
    by_name = {s["name"]: s for s in build_tool_specs(parse_catalog(_CATALOG))}
    validate_props = by_name["validate_proposal"]["inputSchema"]["properties"]
    assert "changeset_id" not in validate_props
    assert "expected_revision" not in validate_props
    assert "summary" in validate_props
    # read_context is a read tool: its target ids stay model-owned.
    read_props = by_name["read_context"]["inputSchema"]["properties"]
    assert "changeset_id" in read_props
    assert "session_id" in read_props


def test_non_dict_schema_yields_bare_object() -> None:
    schema, guidance = normalize_tool_input_schema(None)
    assert schema == {"type": "object"}
    assert guidance == ""


@pytest.mark.asyncio
async def test_served_tools_carry_json_schema_object_over_real_mcp() -> None:
    # Real seam: through the live MCP server the spawned CLI connects to, every
    # advertised tool's inputSchema is a JSON Schema object (type:object), so the
    # CLI keeps them instead of silently dropping the DSL shapes.
    from mcp.shared.memory import create_connected_server_and_client_session

    snapshot = parse_catalog(_CATALOG)

    async def _dispatch(name: str, arguments: dict) -> dict:
        return {"tool": name, "arguments": arguments, "disposition": "dispatched"}

    server = build_authoring_mcp_server(snapshot, _dispatch)
    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_tools()
        assert listed.tools, "the bridge advertises tools"
        for tool in listed.tools:
            assert tool.inputSchema.get("type") == "object", tool.name
