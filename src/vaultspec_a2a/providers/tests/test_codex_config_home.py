"""Unit tests for the per-run Codex CODEX_HOME config.toml emission (P04.S18).

Real filesystem + stdlib tomllib, no mocks. The live proof that Codex surfaces
and invokes the servers under the read-only sandbox is executor-service's later
step; these pin the config.toml content, the auth copy, and the home lifecycle.
"""

from __future__ import annotations

import glob
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...control.config import Settings
from .._acp_config_home import sweep_orphan_config_homes
from .._acp_mcp import codex_mcp_server_specs
from .._codex_config_home import (
    build_codex_config_home,
    cleanup_codex_config_home,
    render_codex_config_toml,
    sweep_orphan_codex_homes,
)
from .._config_home_roots import ORPHAN_HOME_MIN_AGE_SECONDS, temp_home_root

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def _seated_settings(*, desktop_app_home: Path | None) -> Iterator[Settings]:
    """Swap the shared settings singleton for a second real instance.

    ``temp_home_root`` (the Claude side's root resolver, moved verbatim into
    the shared ``_config_home_roots`` core) resolves the armed desktop root
    through a deliberately lazy ``from ..control.config import settings``
    import, re-read on every call - by design, there is no injectable
    parameter (see ``_config_home_roots.temp_home_root``). The module exposes
    no settings-reset API, so the only way to drive its armed and unarmed
    branches through the REAL constructor - never a fake, stub, or mock - is to
    point the module's own public ``settings`` name at a second real, fully
    pydantic-validated ``Settings(...)`` instance for the duration of the test,
    restoring the original immediately after. Both instances are built through
    the exact constructor call ``test_acp_temp_home_root.py`` and
    ``test_desktop_credential_references.py`` already use to arm/unarm this
    same field; only the target of the public module name changes.
    """
    from ...control import config as config_module

    seated = Settings(VAULTSPEC_DESKTOP_APP_HOME=desktop_app_home)
    original = config_module.settings
    config_module.settings = seated
    try:
        yield seated
    finally:
        config_module.settings = original


def _active_codex_leak_root() -> Path:
    """Return the root ``build_codex_config_home`` actually creates homes in.

    The pre-fix version of this test file hardcoded ``tempfile.gettempdir()``
    to search for leaked homes. That hardcoding silently encoded the defect as
    an expectation: had the home ever landed somewhere else (an armed desktop
    root), the glob would find nothing there either, and the "no leak"
    assertion would pass vacuously without ever having looked in the right
    place. Resolving the root the same way the production code does keeps the
    leak check honest under both the armed and unarmed profile.
    """
    return temp_home_root() or Path(tempfile.gettempdir())


def test_render_emits_parseable_mcp_server_block_for_rag() -> None:
    specs = codex_mcp_server_specs(["vaultspec-rag"])
    toml = render_codex_config_toml(specs)
    parsed = tomllib.loads(toml)
    rag = parsed["mcp_servers"]["vaultspec-rag"]
    assert rag["command"] == "uvx"
    assert rag["args"] == [
        "--from",
        "vaultspec-rag[mcp]",
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
    base = tmp_path / "base"
    base.mkdir()
    # auth.json is a DIRECTORY, so shutil.copy2 raises inside build.
    (base / "auth.json").mkdir()
    pattern = os.path.join(str(_active_codex_leak_root()), "vaultspec-codex-home-*")
    before = set(glob.glob(pattern))
    with pytest.raises(OSError):
        build_codex_config_home(codex_mcp_server_specs(["vaultspec-rag"]), base)
    assert set(glob.glob(pattern)) <= before  # no new home leaked


@pytest.mark.asyncio
async def test_spawn_failure_cleans_credential_home(tmp_path: Path) -> None:
    # The exact HIGH-1 scenario: the credential home is built, then the subprocess
    # SPAWN itself raises (here an invalid cwd) before a client exists. The home
    # must still be cleaned - exercising the `client is None` finally branch.
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
    pattern = os.path.join(str(_active_codex_leak_root()), "vaultspec-codex-home-*")
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
    pattern = os.path.join(str(_active_codex_leak_root()), "vaultspec-codex-home-*")
    before = set(glob.glob(pattern))
    # The codex handshake against an immediately-exited subprocess raises
    # _CodexProtocolError (a RuntimeError).
    with pytest.raises(RuntimeError):
        async for _ in model.astream([HumanMessage(content="hi")]):
            pass
    assert set(glob.glob(pattern)) <= before  # credential home cleaned


class TestCodexEntrypointAcceptsEmittedMcpConfig:
    """The emitted CODEX_HOME config is valid to the real Codex entrypoint (S114).

    The unit tests above pin the config.toml content; this drives the REAL
    ``codex mcp list`` entrypoint against a per-run CODEX_HOME built by
    production ``build_codex_config_home`` and confirms Codex parses the config
    and surfaces our declared MCP server. Skips only when the ``codex`` binary is
    genuinely absent - an honest environment prerequisite, not a green shortcut.
    """

    @pytest.mark.skipif(
        shutil.which("codex") is None, reason="codex CLI is not installed"
    )
    def test_codex_mcp_list_accepts_the_built_config_home(self, tmp_path: Path) -> None:
        codex = shutil.which("codex")
        assert codex is not None
        specs = codex_mcp_server_specs(["vaultspec-rag"])
        home = build_codex_config_home(specs, tmp_path / "base")
        try:
            proc = subprocess.run(
                [codex, "mcp", "list"],
                env={**os.environ, "CODEX_HOME": str(home)},
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            # Exit 0 proves Codex parsed the config without rejecting it.
            assert proc.returncode == 0, proc.stderr
            # The declared server surfaces with its production launch command,
            # so the emitted mcp_servers block is not merely parseable but the
            # server Codex would actually launch.
            assert "vaultspec-rag" in proc.stdout
            assert "uvx" in proc.stdout
            assert "vaultspec-search-mcp" in proc.stdout
        finally:
            cleanup_codex_config_home(home)


# --- desktop-state escape defect (codex-config-home-escapes-desktop-state) ---


def test_unarmed_profile_creates_home_in_the_system_temp_root(tmp_path: Path) -> None:
    """Without a declared desktop root, the Codex home stays on OS temp."""
    base = tmp_path / "base"
    base.mkdir()

    with _seated_settings(desktop_app_home=None) as unarmed:
        assert unarmed.desktop_temp_homes_dir is None
        home = build_codex_config_home([], base)
    try:
        assert home.parent == Path(tempfile.gettempdir())
    finally:
        cleanup_codex_config_home(home)


def test_armed_desktop_profile_seats_the_home_inside_the_declared_root(
    tmp_path: Path,
) -> None:
    """On an armed desktop install the Codex home is seated under the app home.

    This is the direct proof for the escapes-desktop-state defect: before the
    fix, ``mkdtemp`` carried no ``dir=`` at all, so the home always landed in
    system temp regardless of the desktop profile - a disk leak and an
    uninstall-completeness gap. Swapping the shared settings singleton to a
    real, fully-validated armed instance (see ``_seated_settings``) drives
    ``temp_home_root`` - the Claude side's own root resolver, now shared - to
    resolve the declared root through its real, unmodified lazy import.
    """
    base = tmp_path / "base"
    base.mkdir()
    app_home = tmp_path / "app-home"
    app_home.mkdir()

    with _seated_settings(desktop_app_home=app_home) as armed:
        declared_root = armed.desktop_temp_homes_dir
        assert declared_root is not None
        # The declared root is itself carved out under the app home, never the
        # bare OS temp directory - the contrast the unarmed test exercises.
        assert declared_root != Path(tempfile.gettempdir())
        home = build_codex_config_home([], base)
    try:
        assert home.parent == declared_root
        assert app_home in home.parents
    finally:
        cleanup_codex_config_home(home)


def _codex_home(root: Path, name: str, *, age_seconds: float) -> Path:
    """Create a Codex config home whose modification time is in the past."""
    home = root / name
    home.mkdir(parents=True)
    (home / "config.toml").write_text("", encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(home, (stamp, stamp))
    return home


def test_codex_sweep_reclaims_stale_orphan_and_spares_fresh_and_keep(
    tmp_path: Path,
) -> None:
    stale = _codex_home(
        tmp_path,
        "vaultspec-codex-home-stale",
        age_seconds=ORPHAN_HOME_MIN_AGE_SECONDS + 3600,
    )
    fresh = _codex_home(tmp_path, "vaultspec-codex-home-fresh", age_seconds=60)
    mine = _codex_home(
        tmp_path,
        "vaultspec-codex-home-mine",
        age_seconds=ORPHAN_HOME_MIN_AGE_SECONDS * 10,
    )

    removed = sweep_orphan_codex_homes(keep=mine, root=tmp_path)

    assert removed == [stale]
    assert not stale.exists()
    assert fresh.exists()
    assert mine.exists()


def test_codex_and_claude_sweeps_never_cross_collect(tmp_path: Path) -> None:
    """A Codex sweep must never collect a Claude home, and vice versa."""
    aged = ORPHAN_HOME_MIN_AGE_SECONDS + 3600
    stale_codex = _codex_home(tmp_path, "vaultspec-codex-home-stale", age_seconds=aged)
    stale_claude = tmp_path / "vaultspec-acp-home-stale"
    stale_claude.mkdir()
    (stale_claude / ".claude.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - aged
    os.utime(stale_claude, (stamp, stamp))

    codex_removed = sweep_orphan_codex_homes(root=tmp_path)
    assert codex_removed == [stale_codex]
    assert stale_claude.exists()  # untouched by the Codex-prefixed sweep

    claude_removed = sweep_orphan_config_homes(root=tmp_path)
    assert claude_removed == [stale_claude]
