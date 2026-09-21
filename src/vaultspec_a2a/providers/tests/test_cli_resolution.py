"""Platform command-shim behavior for the canonical provider CLI resolver."""

from __future__ import annotations

import shutil
import sys
from typing import TYPE_CHECKING

from ...graph.enums import Provider
from .. import cli_resolution

if TYPE_CHECKING:
    import pytest


def test_windows_resolution_accepts_cmd_shim_without_pathext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def _which(candidate: str) -> str | None:
        attempts.append(candidate)
        return "C:/tools/codex.cmd" if candidate == "codex.cmd" else None

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", _which)

    assert (
        cli_resolution.resolve_provider_cli_executable(Provider.CODEX)
        == "C:/tools/codex.cmd"
    )
    assert attempts == ["codex", "codex.cmd"]


def test_unix_resolution_does_not_admit_windows_shims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def _which(candidate: str) -> None:
        attempts.append(candidate)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", _which)

    assert cli_resolution.resolve_provider_cli_executable(Provider.KIMI) is None
    assert attempts == ["kimi"]


def test_non_cli_provider_is_rejected() -> None:
    try:
        cli_resolution.resolve_provider_cli_executable(Provider.OPENAI)
    except ValueError as exc:
        assert "openai has no system CLI" in str(exc)
    else:
        raise AssertionError("an API provider was accepted as a system CLI")
