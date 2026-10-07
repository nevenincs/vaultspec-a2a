"""Platform command-shim behavior for the canonical provider CLI resolver."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ...graph.enums import Provider
from .. import cli_resolution

if TYPE_CHECKING:
    from pathlib import Path


def _install(directory: Path, name: str) -> Path:
    """Place one real executable file in *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / name
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_windows_admits_command_shims_and_unix_does_not() -> None:
    """The per-platform filename policy is stated once and read here directly."""
    assert cli_resolution._cli_candidates("codex", windows=True) == (
        "codex",
        "codex.cmd",
        "codex.exe",
    )
    assert cli_resolution._cli_candidates("codex", windows=False) == ("codex",)


def test_unix_resolution_does_not_admit_windows_shims(tmp_path: Path) -> None:
    """The host admits a command shim only where its platform can run one."""
    shim = _install(tmp_path / "tools", "kimi.cmd")
    resolved = cli_resolution.resolve_provider_cli_executable(
        Provider.KIMI, search_path=str(shim.parent)
    )
    assert (resolved is not None) is (os.name == "nt")
    if resolved is not None:
        assert os.path.normcase(resolved) == os.path.normcase(str(shim))


def test_resolution_ignores_relative_search_entries(tmp_path: Path) -> None:
    """A search entry that resolves against the working directory is not trusted."""
    _install(tmp_path / "tools", "codex")
    relative_entry = os.path.relpath(tmp_path / "tools", tmp_path)

    assert (
        cli_resolution.resolve_provider_cli_executable(
            Provider.CODEX, search_path=relative_entry
        )
        is None
    )


def test_resolved_executable_is_absolute(tmp_path: Path) -> None:
    """What resolution returns can be launched without a second PATH search."""
    executable = _install(
        tmp_path / "tools", "codex.cmd" if os.name == "nt" else "codex"
    )

    resolved = cli_resolution.resolve_provider_cli_executable(
        Provider.CODEX, search_path=str(executable.parent)
    )

    assert resolved is not None
    assert os.path.isabs(resolved)
    assert os.path.normcase(resolved) == os.path.normcase(str(executable))


def test_non_cli_provider_is_rejected() -> None:
    try:
        cli_resolution.resolve_provider_cli_executable(Provider.OPENAI)
    except ValueError as exc:
        assert "openai has no system CLI" in str(exc)
    else:
        raise AssertionError("an API provider was accepted as a system CLI")


def test_zai_shares_the_claude_cli_without_owning_one() -> None:
    """The Z.ai lane resolves no CLI of its own yet proves against Claude's."""
    assert Provider.ZAI not in cli_resolution.SYSTEM_CLI_LANES
    with pytest.raises(ValueError, match="zai has no system CLI"):
        cli_resolution.resolve_provider_cli_executable(Provider.ZAI)
    assert cli_resolution.proof_cli_name(Provider.ZAI) == "claude"


@pytest.mark.parametrize(
    ("provider", "cli"),
    [
        (Provider.CLAUDE, "claude"),
        (Provider.CODEX, "codex"),
        (Provider.KIMI, "kimi"),
        (Provider.OPENAI, "openai"),
    ],
)
def test_a_lane_proves_against_the_cli_its_provider_names(
    provider: Provider, cli: str
) -> None:
    """Every lane other than Z.ai binds its proof to the CLI named by itself."""
    assert cli_resolution.proof_cli_name(provider) == cli
