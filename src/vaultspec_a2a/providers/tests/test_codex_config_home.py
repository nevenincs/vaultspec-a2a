"""Unit tests for the per-run Codex CODEX_HOME config.toml emission (P04.S18).

Real filesystem + stdlib tomllib, no mocks. The live proof that Codex surfaces
and invokes the servers under the read-only sandbox is executor-service's later
step; these pin the config.toml content, the auth copy, and the home lifecycle.
"""

from __future__ import annotations

import os
import stat
import sys
import tomllib
from typing import TYPE_CHECKING

import pytest

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
    assert rag["args"] == [
        "--from",
        "vaultspec-rag[mcp]==0.3.2",
        "vaultspec-search-mcp",
    ]


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
    # NOTE: this sets harness_mcp_servers directly ON PURPOSE - it asserts only the
    # sandbox/approval defaults, NOT the production wiring. The wiring (that the
    # preset's harness actually REACHES the model through composition) is covered
    # by test_composition_seam_threads_harness_into_codex_config_toml; do not read
    # this direct-field construction as evidence the live path works.
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


def test_copied_credential_is_owner_only_on_posix(tmp_path: Path) -> None:
    # The credential copy must not widen access. On POSIX the file is pinned to
    # 0o600 and the home to 0o700; on Windows chmod is a no-op and the per-user
    # temp tree is ACL-scoped, so we only assert the copy exists there.
    base = tmp_path / "base"
    base.mkdir()
    (base / "auth.json").write_text("{}", encoding="utf-8")
    home = build_codex_config_home(codex_mcp_server_specs(["vaultspec-rag"]), base)
    try:
        auth = home / "auth.json"
        assert auth.exists()
        if os.name == "posix":
            assert stat.S_IMODE(auth.stat().st_mode) == 0o600
            assert stat.S_IMODE(home.stat().st_mode) == 0o700
    finally:
        cleanup_codex_config_home(home)


def test_composition_seam_threads_harness_into_codex_config_toml(
    tmp_path: Path,
) -> None:
    # KILLS THE MASKING GAP: build the model through the REAL production
    # composition seam (compose_harness_mcp_servers), NOT by setting
    # harness_mcp_servers directly, then assert the emitted config.toml carries
    # vaultspec-rag. Before the fix, compose silently no-oped for Codex (no
    # with_mcp_servers) and the config.toml was always emitted from an empty list.
    import tomllib

    from .._acp_mcp import compose_harness_mcp_servers
    from ..codex_chat_model import CodexChatModel

    base = tmp_path / "base"
    base.mkdir()
    (base / "auth.json").write_text("{}", encoding="utf-8")
    model = CodexChatModel(command=["codex", "app-server"], codex_home=str(base))
    assert model.harness_mcp_servers == []  # not wired yet

    composed = compose_harness_mcp_servers(model, ["vaultspec-rag"])
    assert isinstance(composed, CodexChatModel)
    assert composed.harness_mcp_servers == ["vaultspec-rag"]

    home = composed._build_codex_config_home()
    assert home is not None
    try:
        cfg = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        assert set(cfg["mcp_servers"]) == {"vaultspec-rag"}
        assert cfg["mcp_servers"]["vaultspec-rag"]["enabled_tools"] == [
            "search_vault",
            "search_codebase",
            "get_code_file",
        ]
    finally:
        cleanup_codex_config_home(home)


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


def test_build_self_cleans_on_copy_failure(tmp_path: Path) -> None:
    # If the credential copy fails mid-build, the partially-built home (which may
    # already hold a credential) must not leak: the builder removes its own dir.
    import glob
    import tempfile

    base = tmp_path / "base"
    base.mkdir()
    # auth.json is a DIRECTORY, so shutil.copy2 raises inside build.
    (base / "auth.json").mkdir()
    pattern = os.path.join(tempfile.gettempdir(), "vaultspec-codex-home-*")
    before = set(glob.glob(pattern))
    with pytest.raises(OSError):
        build_codex_config_home(codex_mcp_server_specs(["vaultspec-rag"]), base)
    assert set(glob.glob(pattern)) <= before  # no new home leaked


@pytest.mark.asyncio
async def test_spawn_failure_cleans_credential_home(tmp_path: Path) -> None:
    # The exact HIGH-1 scenario: the credential home is built, then the subprocess
    # SPAWN itself raises (here an invalid cwd) before a client exists. The home
    # must still be cleaned - exercising the `client is None` finally branch.
    import glob
    import tempfile

    from langchain_core.messages import HumanMessage

    from ..codex_chat_model import CodexChatModel

    base = tmp_path / "base"
    base.mkdir()
    (base / "auth.json").write_text("{}", encoding="utf-8")
    model = CodexChatModel(
        command=[sys.executable, "-c", "pass"],
        harness_mcp_servers=["vaultspec-rag"],
        codex_home=str(base),
        workspace_root=str(tmp_path / "no-such-workspace-dir"),
    )
    pattern = os.path.join(tempfile.gettempdir(), "vaultspec-codex-home-*")
    before = set(glob.glob(pattern))
    with pytest.raises(OSError):
        async for _ in model.astream([HumanMessage(content="hi")]):
            pass
    assert set(glob.glob(pattern)) <= before  # credential home cleaned


@pytest.mark.asyncio
async def test_turn_failure_after_build_cleans_credential_home(
    tmp_path: Path,
) -> None:
    # A failure AFTER the credential home is built (here the codex subprocess
    # exits immediately, so the handshake fails) must still clean the home - the
    # credential copy cannot outlive the failed turn.
    import glob
    import tempfile

    from langchain_core.messages import HumanMessage

    from ..codex_chat_model import CodexChatModel

    base = tmp_path / "base"
    base.mkdir()
    (base / "auth.json").write_text("{}", encoding="utf-8")
    model = CodexChatModel(
        command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        harness_mcp_servers=["vaultspec-rag"],
        codex_home=str(base),
        timeout=10.0,
    )
    pattern = os.path.join(tempfile.gettempdir(), "vaultspec-codex-home-*")
    before = set(glob.glob(pattern))
    # The codex handshake against an immediately-exited subprocess raises
    # _CodexProtocolError (a RuntimeError).
    with pytest.raises(RuntimeError):
        async for _ in model.astream([HumanMessage(content="hi")]):
            pass
    assert set(glob.glob(pattern)) <= before  # credential home cleaned
