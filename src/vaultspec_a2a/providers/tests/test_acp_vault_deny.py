"""Adversarial tests for the ADR R2 ``.vault/**`` write-deny policy.

These drive the REAL ``on_fs_write_text_file`` / ``on_fs_read_text_file`` RPC
handlers against a real temp-dir workspace — no mocks, no monkeypatching. They
assert that every route to a vault write (direct, nested, ``..`` traversal,
relative, case-variant, symlink/junction) returns the value-typed
``forbidden_actor`` denial and writes nothing, while non-vault writes and vault
READS remain permitted.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING, cast

import pytest

from .._acp_rpc_handlers import on_fs_read_text_file, on_fs_write_text_file
from .._acp_types import _AcpModelConfig, _AcpSessionContext

if TYPE_CHECKING:
    from pathlib import Path


def _make_config(workspace_root: str) -> _AcpModelConfig:
    return _AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=workspace_root,
        cwd=None,
        command=["echo"],
        env_vars={},
        session_id=None,
        mcp_servers=[],
        use_exec=False,
        provider=None,
        runtime_authority=None,
        acp_backend=None,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
    )


# The write handler never touches ctx (it is the ``_ctx`` throwaway param).
_NO_CTX = cast("_AcpSessionContext", None)


async def _write(config: _AcpModelConfig, path: str) -> dict:
    return await on_fs_write_text_file(
        1, {"path": path, "content": "SHOULD NOT LAND"}, _NO_CTX, config
    )


def _assert_denied(result: dict) -> None:
    payload = cast("dict", result["result"])
    assert payload["status"] == "denied"
    assert payload["denial_kind"] == "forbidden_actor"
    eligibility = cast("dict", payload["eligibility"])
    assert eligibility["allowed"] is False
    # The reason must steer the agent to the authoring tools.
    assert "propose" in str(eligibility["reason"]).lower()
    # A denial is a value, never a JSON-RPC transport error.
    assert "error" not in result


class TestVaultWriteDeny:
    """Every write path into .vault/ is denied and lands nothing."""

    @pytest.mark.asyncio
    async def test_denies_direct_vault_write(self, tmp_path: Path) -> None:
        config = _make_config(str(tmp_path))
        result = await _write(config, ".vault/plan/x.md")
        _assert_denied(result)
        assert not (tmp_path / ".vault" / "plan" / "x.md").exists()

    @pytest.mark.asyncio
    async def test_denies_deeply_nested_vault_write(self, tmp_path: Path) -> None:
        config = _make_config(str(tmp_path))
        result = await _write(config, ".vault/adr/deep/nested/y.md")
        _assert_denied(result)

    @pytest.mark.asyncio
    async def test_denies_traversal_back_into_vault(self, tmp_path: Path) -> None:
        config = _make_config(str(tmp_path))
        # Resolves to <ws>/.vault/x.md — inside the sandbox, still a vault write.
        result = await _write(config, "sub/dir/../../.vault/x.md")
        _assert_denied(result)

    @pytest.mark.asyncio
    async def test_denies_relative_dot_prefixed_vault(self, tmp_path: Path) -> None:
        config = _make_config(str(tmp_path))
        result = await _write(config, "./.vault/./notes.md")
        _assert_denied(result)

    @pytest.mark.parametrize("variant", [".VAULT", ".Vault", ".vAuLt"])
    @pytest.mark.asyncio
    async def test_denies_case_variant_vault(
        self, tmp_path: Path, variant: str
    ) -> None:
        config = _make_config(str(tmp_path))
        result = await _write(config, f"{variant}/x.md")
        _assert_denied(result)

    @pytest.mark.asyncio
    async def test_denies_write_through_symlink_or_junction(
        self, tmp_path: Path
    ) -> None:
        """A link that resolves to .vault is denied — .resolve() collapses it."""
        real_vault = tmp_path / ".vault"
        real_vault.mkdir()
        link = tmp_path / "sneaky-link"
        _link_dir(link, real_vault)

        config = _make_config(str(tmp_path))
        result = await _write(config, "sneaky-link/x.md")
        _assert_denied(result)
        assert not (real_vault / "x.md").exists()


class TestNonVaultAndReadsPermitted:
    """The policy is surgical: non-vault writes and vault reads still work."""

    @pytest.mark.asyncio
    async def test_permits_non_vault_write(self, tmp_path: Path) -> None:
        config = _make_config(str(tmp_path))
        result = await on_fs_write_text_file(
            1, {"path": "notes/ok.md", "content": "landed"}, _NO_CTX, config
        )
        assert result["result"] == {}
        assert (tmp_path / "notes" / "ok.md").read_text(encoding="utf-8") == "landed"

    @pytest.mark.asyncio
    async def test_permits_vault_read(self, tmp_path: Path) -> None:
        """Reads through the ACP fs surface stay permitted (dashboard D4)."""
        vault_doc = tmp_path / ".vault" / "research" / "doc.md"
        vault_doc.parent.mkdir(parents=True)
        vault_doc.write_text("corpus context", encoding="utf-8")

        config = _make_config(str(tmp_path))
        result = await on_fs_read_text_file(
            1, {"path": ".vault/research/doc.md"}, _NO_CTX, config
        )
        assert cast("dict", result["result"])["content"] == "corpus context"
        assert "error" not in result


def _link_dir(link: Path, target: Path) -> None:
    """Create a directory link, preferring a symlink and falling back to a
    Windows junction (which needs no elevation) so the test runs everywhere."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        if sys.platform == "win32":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
            )
            return
        raise
