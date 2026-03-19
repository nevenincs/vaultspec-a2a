"""Tests for the `vaultspec mcp` CLI group."""

from __future__ import annotations

from click.testing import CliRunner

from .._mcp import _tool_rows, mcp_group


def test_tool_rows_match_registered_mcp_tools() -> None:
    """CLI tool rows should be derived from the registered MCP server tools."""
    tool_rows = dict(_tool_rows())

    assert tool_rows
    expected = (
        "Start a new multi-agent coding workflow and return a thread ID for tracking."
    )
    assert tool_rows["start_thread"] == expected
    assert tool_rows["cancel_thread"].startswith("Cancel a running thread")


def test_tools_command_renders_registered_tool_names() -> None:
    """`vaultspec mcp tools` should render the live registered tool surface."""
    runner = CliRunner()

    result = runner.invoke(mcp_group, ["tools"])

    assert result.exit_code == 0
    assert "start_thread" in result.output
    assert "respond_to_permission" in result.output
    assert "cancel_thread" in result.output


def test_status_command_reports_registered_tool_count() -> None:
    """`vaultspec mcp status` should report the live tool count."""
    runner = CliRunner()

    result = runner.invoke(mcp_group, ["status"])

    assert result.exit_code == 0
    assert f"Tools: {len(_tool_rows())}" in result.output
