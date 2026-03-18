"""Tests for the `vaultspec test` CLI group."""

from __future__ import annotations

from click.testing import CliRunner

from .._test import test


def test_test_help_lists_prodlike_verification_commands() -> None:
    """The test CLI should expose the prod-like Docker verification commands."""
    runner = CliRunner()

    result = runner.invoke(test, ["--help"])

    assert result.exit_code == 0
    assert "prodlike-docker" in result.output
    assert "prodlike-provider" in result.output
    assert "claude-docker" in result.output
    assert "gemini-docker" in result.output
