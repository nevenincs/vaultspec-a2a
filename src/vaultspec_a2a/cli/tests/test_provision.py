"""Tests for workspace provisioning (agent-harness-provisioning P02.S03).

Pure-logic helpers (version-skew composition, version parsing) are exercised with
real string inputs - no mocks. Provisioning itself is proven the honest way: a
REAL ``vaultspec-core install`` subprocess into a ``tmp_path`` workspace, then the
real harness verifier over the result. No doubles: an integration test that does
not shell the real installer would prove nothing about provisioning.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from ..provision import (
    _compute_skew,
    _parse_version,
    provision_workspace,
)

if TYPE_CHECKING:
    from pathlib import Path

_CORE_ON_PATH = (
    shutil.which("vaultspec-core") is not None or shutil.which("uvx") is not None
)


class TestVersionSkew:
    def test_no_skew_when_versions_agree(self) -> None:
        assert _compute_skew("0.1.43", "0.1.43") is None

    def test_skew_message_names_both_versions(self) -> None:
        msg = _compute_skew("0.1.43", "0.1.42")
        assert msg is not None
        assert "0.1.43" in msg
        assert "0.1.42" in msg

    def test_unknown_pinned_is_not_a_skew(self) -> None:
        assert _compute_skew(None, "0.1.43") is None

    def test_unknown_resolved_is_not_a_skew(self) -> None:
        assert _compute_skew("0.1.43", None) is None


class TestParseVersion:
    def test_parses_bare_semver(self) -> None:
        assert _parse_version("0.1.43\n") == "0.1.43"

    def test_parses_click_style_version_line(self) -> None:
        assert _parse_version("vaultspec-core, version 0.1.43") == "0.1.43"

    def test_no_version_returns_none(self) -> None:
        assert _parse_version("no version here") is None


class TestVerifyOnly:
    def test_bare_workspace_is_not_harness_ready(self, tmp_path: Path) -> None:
        """verify-only over an unprovisioned dir yields an incomplete harness."""
        result = provision_workspace(tmp_path, install=False)
        assert result.installed is False
        assert result.ok is False
        assert any("rules corpus" in r for r in result.harness.reasons)


@pytest.mark.skipif(
    not _CORE_ON_PATH, reason="vaultspec-core CLI not resolvable in this environment"
)
class TestRealInstall:
    def test_install_makes_a_bare_workspace_harness_ready(self, tmp_path: Path) -> None:
        """A REAL vaultspec-core install turns a bare dir into a ready harness."""
        ws = tmp_path / "ws"
        result = provision_workspace(ws, install=True)
        assert result.installed is True
        # install scaffolded the flat corpus...
        assert (ws / ".vaultspec" / "rules").is_dir()
        assert (ws / ".vaultspec" / "templates").is_dir()
        # ...and the verifier reads the provisioned tree as complete.
        assert result.ok is True, result.harness.reasons
        assert result.harness.reasons == []
