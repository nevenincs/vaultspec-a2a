"""Unit tests for the per-run Codex CODEX_HOME config.toml emission (P04.S18).

Real filesystem + stdlib tomllib, no mocks. The live proof that Codex surfaces
and invokes the servers under the read-only sandbox is executor-service's later
step; these pin the config.toml content, the auth copy, and the home lifecycle.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

from .._acp_mcp import codex_mcp_server_specs
from .._codex_config_home import (
    build_codex_config_home,
    cleanup_codex_config_home,
    render_codex_config_toml,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_render_emits_parseable_mcp_server_block_for_rag() -> None:
    specs = codex_mcp_server_specs(["vaultspec-rag"])
    toml = render_codex_config_toml(specs)
    parsed = tomllib.loads(toml)
    rag = parsed["mcp_servers"]["vaultspec-rag"]
    assert rag["command"] == "uvx"
    assert rag["args"] == ["--from", "vaultspec-rag", "vaultspec-search-mcp"]


def test_render_constrains_to_read_tools_auto_approved() -> None:
    # P04.S19: enabled_tools names EXACTLY the registry's read tools (no write
    # verb the server also exposes), auto-approved so reads run headless.
    toml = render_codex_config_toml(codex_mcp_server_specs(["vaultspec-rag"]))
    rag = tomllib.loads(toml)["mcp_servers"]["vaultspec-rag"]
    assert rag["enabled_tools"] == [
        "search_vault",
        "search_codebase",
        "get_code_file",
    ]
    assert not any("reindex" in t for t in rag["enabled_tools"])
    assert rag["default_tools_approval_mode"] == "auto"


def test_codex_model_defaults_keep_read_only_sandbox_defense_in_depth() -> None:
    # The enabled_tools allowlist composes WITH the headless sandbox, not instead
    # of it: the model keeps approval_policy=never + sandbox=read-only.
    from ..codex_chat_model import CodexChatModel

    model = CodexChatModel(harness_mcp_servers=["vaultspec-rag"])
    assert model.approval_policy == "never"
    assert model.sandbox == "read-only"


def test_render_emits_env_subtable_when_present() -> None:
    specs = [{"name": "x-srv", "command": "c", "args": ["a"], "env": {"K": "V"}}]
    parsed = tomllib.loads(render_codex_config_toml(specs))
    assert parsed["mcp_servers"]["x-srv"]["env"] == {"K": "V"}


def test_render_empty_specs_is_empty() -> None:
    assert render_codex_config_toml([]) == ""


def test_build_home_writes_config_and_copies_auth(tmp_path: Path) -> None:
    base = tmp_path / "base_codex"
    base.mkdir()
    (base / "auth.json").write_text('{"token": "x"}', encoding="utf-8")

    specs = codex_mcp_server_specs(["vaultspec-rag"])
    home = build_codex_config_home(specs, base)
    try:
        # Auth preserved for Codex's file-based auth.
        assert (home / "auth.json").exists()
        assert (home / "auth.json").read_text(encoding="utf-8") == '{"token": "x"}'
        # config.toml carries exactly the declared server.
        cfg = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        assert set(cfg["mcp_servers"]) == {"vaultspec-rag"}
    finally:
        cleanup_codex_config_home(home)
        assert not home.exists()


def test_build_home_tolerates_absent_auth(tmp_path: Path) -> None:
    # A base home without auth.json (e.g. env-based auth) still yields a valid
    # config home; nothing is copied and no error is raised.
    base = tmp_path / "empty_base"
    base.mkdir()
    home = build_codex_config_home(codex_mcp_server_specs(["vaultspec-rag"]), base)
    try:
        assert not (home / "auth.json").exists()
        assert (home / "config.toml").exists()
    finally:
        cleanup_codex_config_home(home)


def test_cleanup_is_none_safe_and_idempotent(tmp_path: Path) -> None:
    cleanup_codex_config_home(None)
    home = build_codex_config_home([], tmp_path)
    cleanup_codex_config_home(home)
    assert not home.exists()
    cleanup_codex_config_home(home)
