"""Unit tests for catalog parsing and the MCP tool-spec bridge.

No mocks: parsing and spec generation are pure functions exercised against the
verified catalog shape. Live catalog fetch and run-scoped execute are covered
by the live integration tests.
"""

import pytest

from ...protocols.mcp.tools.authoring_bridge import build_tool_specs
from ..catalog import (
    CATALOG_SCHEMA_VERSION,
    AgentTool,
    CatalogSnapshot,
    parse_catalog,
    resolve_tool_command,
)


def _tool(name: str, commands: tuple[str, ...]) -> AgentTool:
    return AgentTool(
        name=name,
        description="",
        input_schema={},
        risk_tier="mutating",
        permission_requirement="human_approval_required",
        idempotency_required=True,
        commands=commands,
    )


class TestResolveToolCommand:
    def test_single_command_maps_directly(self) -> None:
        tool = _tool("read_context", ("read_context",))
        assert resolve_tool_command(tool, {}) == "read_context"

    def test_propose_operation_selects_command(self) -> None:
        tool = _tool(
            "propose_changeset",
            ("create_proposal", "append_draft", "replace_draft"),
        )
        assert resolve_tool_command(tool, {"operation": "create"}) == "create_proposal"
        assert resolve_tool_command(tool, {"operation": "append"}) == "append_draft"
        assert resolve_tool_command(tool, {"operation": "replace"}) == "replace_draft"

    def test_cancel_target_selects_command(self) -> None:
        tool = _tool("cancel", ("cancel_proposal", "cancel_run"))
        assert resolve_tool_command(tool, {"target": "proposal"}) == "cancel_proposal"
        assert resolve_tool_command(tool, {"target": "run"}) == "cancel_run"

    def test_missing_discriminator_falls_back_to_first(self) -> None:
        tool = _tool("cancel", ("cancel_proposal", "cancel_run"))
        assert resolve_tool_command(tool, {}) == "cancel_proposal"


_SAMPLE_CATALOG = {
    "schema_version": CATALOG_SCHEMA_VERSION,
    "tools": [
        {
            "name": "read_context",
            "description": "Read bounded authoring context.",
            "permission_requirement": "auto_permitted",
            "risk_tier": "read_only",
            "idempotency_required": False,
            "input_schema": {"additionalProperties": False},
        },
        {
            "name": "propose_changeset",
            "description": "Create a proposal changeset.",
            "permission_requirement": "human_approval_required",
            "risk_tier": "mutating",
            "idempotency_required": True,
            "input_schema": {"additionalProperties": False},
        },
    ],
}


class TestParseCatalog:
    def test_parses_tools(self) -> None:
        snapshot = parse_catalog(_SAMPLE_CATALOG)
        assert snapshot.schema_version == CATALOG_SCHEMA_VERSION
        assert snapshot.tool_names() == ("read_context", "propose_changeset")

    def test_tool_properties(self) -> None:
        snapshot = parse_catalog(_SAMPLE_CATALOG)
        read = snapshot.get("read_context")
        propose = snapshot.get("propose_changeset")
        assert read is not None
        assert propose is not None
        assert not read.is_mutating
        assert not read.requires_human_approval
        assert propose.is_mutating
        assert propose.requires_human_approval
        assert propose.idempotency_required

    def test_get_unknown_returns_none(self) -> None:
        assert parse_catalog(_SAMPLE_CATALOG).get("nope") is None

    def test_schema_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="schema_version"):
            parse_catalog({"schema_version": "other.v9", "tools": []})

    def test_missing_tools_list_raises(self) -> None:
        with pytest.raises(ValueError, match="tools"):
            parse_catalog({"schema_version": CATALOG_SCHEMA_VERSION})

    def test_tool_without_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            parse_catalog(
                {
                    "schema_version": CATALOG_SCHEMA_VERSION,
                    "tools": [{"description": "no name"}],
                }
            )


class TestBuildToolSpecs:
    def test_maps_snapshot_to_mcp_specs(self) -> None:
        snapshot = parse_catalog(_SAMPLE_CATALOG)
        specs = build_tool_specs(snapshot)
        assert [spec["name"] for spec in specs] == ["read_context", "propose_changeset"]
        read_spec = specs[0]
        assert read_spec["description"] == "Read bounded authoring context."
        # The catalog schema is normalized to a valid JSON Schema object at the
        # serving seam (a bare {"additionalProperties": false} becomes a proper
        # object schema the CLI keeps rather than silently drops).
        assert read_spec["inputSchema"] == {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        assert read_spec["_engine"]["risk_tier"] == "read_only"
        assert read_spec["_engine"]["permission_requirement"] == "auto_permitted"

    def test_empty_snapshot_yields_no_specs(self) -> None:
        assert build_tool_specs(CatalogSnapshot(CATALOG_SCHEMA_VERSION, ())) == []
