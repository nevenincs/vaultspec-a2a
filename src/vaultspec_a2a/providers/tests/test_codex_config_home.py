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
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from ...authoring import AgentTool, CatalogSnapshot
from ...control.config import Settings
from ...graph.enums import Provider
from ...utils.enums import CodexWebSearchMode
from .._acp_authoring import AuthoringToolBinding, attach_authoring_tools
from .._acp_config_home import sweep_orphan_config_homes
from .._acp_mcp import codex_mcp_server_specs
from .._codex_config_home import (
    SERVED_WEB_SEARCH_MODE,
    build_codex_config_home,
    cleanup_codex_config_home,
    render_codex_config_toml,
    resolve_codex_web_search_mode,
    sweep_orphan_codex_homes,
)
from .._config_home_roots import ORPHAN_HOME_MIN_AGE_SECONDS, temp_home_root
from ..lane_admission import PROVEN_WEB_LANES, is_web_lane_proven

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from ..codex_chat_model import CodexChatModel


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
    toml = render_codex_config_toml(specs, web_search=CodexWebSearchMode.DISABLED)
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
    toml = render_codex_config_toml(
        codex_mcp_server_specs(["vaultspec-rag"]),
        web_search=CodexWebSearchMode.DISABLED,
    )
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
    parsed = tomllib.loads(
        render_codex_config_toml(specs, web_search=CodexWebSearchMode.DISABLED)
    )
    assert parsed["mcp_servers"]["x-srv"]["env"] == {"K": "V"}


def test_render_with_no_specs_still_declares_the_web_posture() -> None:
    # Previously this asserted the empty string. It cannot any more, and the
    # reason is the whole point of the web-posture work: Codex enables web search
    # when the key is absent, so an empty document is not "no capability", it is
    # "whatever the CLI defaults to". A server-less home must still say off.
    parsed = tomllib.loads(
        render_codex_config_toml([], web_search=CodexWebSearchMode.DISABLED)
    )
    assert parsed == {"web_search": "disabled"}


# --- web-grounding posture on the Codex lane -------------------------------


def _built_config(
    specs: Sequence[dict[str, Any]],
    base: Path,
    **kwargs: CodexWebSearchMode,
) -> dict[str, Any]:
    """Return the parsed config.toml the production builder actually wrote.

    Every posture assertion below goes through this rather than through the
    renderer's return value: the acceptance for this capability is the file on
    disk that Codex will read, not a string the test helped build.
    """
    home = build_codex_config_home(specs, base, **kwargs)
    try:
        return tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    finally:
        cleanup_codex_config_home(home)


def test_web_posture_is_top_level_and_never_absorbed_by_a_server_table() -> None:
    # tomllib IS the semantic ordering proof: TOML binds a bare key to the table
    # above it, so had `web_search` been emitted after `[mcp_servers.vaultspec-rag]`
    # it would parse as an option OF that server and the top-level lookup would
    # raise. The two assertions together pin the key to the document, not a server.
    parsed = tomllib.loads(
        render_codex_config_toml(
            codex_mcp_server_specs(["vaultspec-rag"]),
            web_search=CodexWebSearchMode.LIVE,
        )
    )
    assert parsed["web_search"] == "live"
    assert "web_search" not in parsed["mcp_servers"]["vaultspec-rag"]


def test_web_posture_is_emitted_before_the_first_table_header() -> None:
    # The textual companion to the test above, and the one that names the defect
    # directly. Misordering here does not raise or corrupt the file - it produces
    # a document that parses cleanly and means something else entirely, which is
    # the worst available failure mode. Pin the byte order, not just the semantics.
    rendered = render_codex_config_toml(
        codex_mcp_server_specs(["vaultspec-rag"]),
        web_search=CodexWebSearchMode.LIVE,
    )
    assert rendered.index("web_search") < rendered.index("[")
    assert rendered.startswith('web_search = "live"')


def test_proven_lane_serves_live_retrieval(tmp_path: Path) -> None:
    # The served posture: a lane carrying web proof reads the live web, so its
    # findings differ from a sibling lane's by evidence rather than by index age.
    base = tmp_path / "base"
    base.mkdir()
    mode = resolve_codex_web_search_mode(web_proven=True)
    assert mode is SERVED_WEB_SEARCH_MODE
    cfg = _built_config(
        codex_mcp_server_specs(["vaultspec-rag"]), base, web_search=mode
    )
    assert cfg["web_search"] == "live"


def test_unproven_lane_gets_no_reach_even_when_configured_for_it(
    tmp_path: Path,
) -> None:
    # The gate is absolute, and this is the assertion that says so: a deployment
    # explicitly asking for live on a lane with no web proof still gets disabled.
    # Without that precedence a config key would be a way to talk a lane past a
    # proof it never earned.
    base = tmp_path / "base"
    base.mkdir()
    mode = resolve_codex_web_search_mode(
        web_proven=False, configured=CodexWebSearchMode.LIVE
    )
    assert mode is CodexWebSearchMode.DISABLED
    cfg = _built_config(
        codex_mcp_server_specs(["vaultspec-rag"]), base, web_search=mode
    )
    assert cfg["web_search"] == "disabled"
    # The gate closes the web posture only; the declared harness servers are a
    # separate axis and must still be surfaced.
    assert set(cfg["mcp_servers"]) == {"vaultspec-rag"}


def test_cached_posture_stays_selectable_for_a_zero_egress_deployment(
    tmp_path: Path,
) -> None:
    # Cached is genuine search against a provider-maintained index with no
    # outbound request from the agent host. Live is what a proven lane serves by
    # default, but an install that wants zero egress must still be able to take
    # cached without a further decision record, so this asserts the configured
    # preference wins ABOVE the gate.
    base = tmp_path / "base"
    base.mkdir()
    mode = resolve_codex_web_search_mode(
        web_proven=True, configured=CodexWebSearchMode.CACHED
    )
    cfg = _built_config(
        codex_mcp_server_specs(["vaultspec-rag"]), base, web_search=mode
    )
    assert cfg["web_search"] == "cached"


def test_a_caller_that_never_decided_the_posture_cannot_build_a_home(
    tmp_path: Path,
) -> None:
    """Omitting the posture is a TypeError, and that is load-bearing.

    This replaces a weaker test that asserted a safe DEFAULT. The default had to
    go, because while the proven-lane set is empty every resolution yields
    ``disabled`` - so a defaulted argument makes the gate binding invisible, and
    deleting the binding from the production model would leave the whole suite
    green. Requiring the argument converts that from something a test might
    notice into something the interpreter refuses to run.
    """
    base = tmp_path / "base"
    base.mkdir()
    # The suppressions are the point, not a concession: the type checker refusing
    # these calls IS the first half of the guarantee, and the raise proves the
    # second half holds at runtime for a caller the checker never saw.
    with pytest.raises(TypeError):
        build_codex_config_home(  # ty: ignore[missing-argument]
            codex_mcp_server_specs(["vaultspec-rag"]), base
        )
    with pytest.raises(TypeError):
        render_codex_config_toml(  # ty: ignore[missing-argument]
            codex_mcp_server_specs(["vaultspec-rag"])
        )


class TestWebPostureThroughTheProductionModelSeam:
    """The gate as the production path actually applies it.

    Everything above drives the renderer and builder directly. These drive
    ``CodexChatModel._build_codex_config_home`` - the ONLY place production builds
    a Codex home - so the assertions cover the real composition: the lane verdict
    read from the live declaration, the deployment preference read from the real
    settings surface, and the file Codex will actually load.
    """

    def _model(self, base: Path, **kwargs: object) -> CodexChatModel:
        from ..codex_chat_model import CodexChatModel

        return CodexChatModel(
            command=["codex", "app-server"],
            harness_mcp_servers=["vaultspec-rag"],
            codex_home=str(base),
            **kwargs,
        )

    def _emitted(self, model: CodexChatModel) -> dict[str, Any]:
        home = model._build_codex_config_home()
        assert home is not None
        try:
            return tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        finally:
            cleanup_codex_config_home(home)

    def test_the_codex_lane_is_dark_because_it_carries_no_retrieval_proof(
        self, tmp_path: Path
    ) -> None:
        # Both assertions matter, and the first is the one that keeps this test
        # honest. It states the precondition the second depends on, so when a
        # later step records real retrieval proof for codex this test FAILS and
        # forces someone to revisit it, instead of quietly continuing to assert
        # "disabled" about a lane that has since been activated.
        base = tmp_path / "base"
        base.mkdir()
        assert Provider.CODEX not in PROVEN_WEB_LANES
        assert self._emitted(self._model(base))["web_search"] == "disabled"

    def test_the_declared_lane_is_what_gets_asked_about(self, tmp_path: Path) -> None:
        # The verdict is taken for the model's OWN declared lane rather than a
        # constant, so the wiring cannot be right by coincidence.
        base = tmp_path / "base"
        base.mkdir()
        model = self._model(base)
        assert model.provider == Provider.CODEX.value
        assert is_web_lane_proven(model.provider) is False

    def test_configuration_cannot_open_a_lane_the_gate_has_closed(
        self, tmp_path: Path
    ) -> None:
        # A deployment explicitly asking for live retrieval, through the real
        # model API, on a lane with no proof. The gate is applied after the
        # preference is read, so the answer is still disabled. Without this
        # precedence a config key would be a way around the proof requirement.
        base = tmp_path / "base"
        base.mkdir()
        model = self._model(base, web_search_mode=CodexWebSearchMode.LIVE)
        assert model.web_search_mode is CodexWebSearchMode.LIVE
        assert self._emitted(model)["web_search"] == "disabled"

    def test_the_deployment_preference_is_read_from_real_settings(self) -> None:
        # The zero-egress path is a real settings key, parsed by the real
        # pydantic constructor from the real env alias - not a string this test
        # invented. Above the gate this is the value the resolver receives.
        seated = Settings(VAULTSPEC_CODEX_WEB_SEARCH_MODE="cached")
        assert seated.codex_web_search_mode is CodexWebSearchMode.CACHED
        assert (
            resolve_codex_web_search_mode(
                web_proven=True, configured=seated.codex_web_search_mode
            )
            is CodexWebSearchMode.CACHED
        )

    def test_an_unrecognised_configured_mode_is_refused_at_settings_load(self) -> None:
        # Fail at load, where the operator can see it, rather than at a spawn
        # months later. The enum is the CLI's own vocabulary, so a value pydantic
        # rejects here is exactly one Codex would have rejected too.
        with pytest.raises(ValidationError):
            Settings(VAULTSPEC_CODEX_WEB_SEARCH_MODE="live-ish")

    def test_default_settings_leave_the_choice_to_the_served_posture(self) -> None:
        # Unset must not mean disabled: it means "no deployment preference", so a
        # proven lane serves live. Conflating the two would make the served
        # posture unreachable without an explicit opt-in nobody was told to set.
        assert Settings().codex_web_search_mode is None
        assert (
            resolve_codex_web_search_mode(web_proven=True, configured=None)
            is SERVED_WEB_SEARCH_MODE
        )


def test_build_home_writes_config_and_copies_auth(tmp_path: Path) -> None:
    base = tmp_path / "base_codex"
    base.mkdir()
    (base / "auth.json").write_text('{"token": "x"}', encoding="utf-8")

    specs = codex_mcp_server_specs(["vaultspec-rag"])
    home = build_codex_config_home(specs, base, web_search=CodexWebSearchMode.DISABLED)
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
    home = build_codex_config_home(
        codex_mcp_server_specs(["vaultspec-rag"]),
        base,
        web_search=CodexWebSearchMode.DISABLED,
    )
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


def _authoring_binding(
    *, engine_base_url: str = "http://127.0.0.1:8767", run_id: str = "run:codex-test"
) -> AuthoringToolBinding:
    """A real stdio-transport binding, as ``AuthoringBindingProvider`` builds it."""
    snapshot = CatalogSnapshot(
        schema_version="authoring.semantic_tools.v1",
        tools=(
            AgentTool(
                name="read_context",
                description="read",
                input_schema={"type": "object"},
                risk_tier="read_only",
                permission_requirement="auto_permitted",
                idempotency_required=False,
                commands=("read_context",),
            ),
            AgentTool(
                name="propose_changeset",
                description="propose",
                input_schema={"type": "object"},
                risk_tier="mutating",
                permission_requirement="human_approval_required",
                idempotency_required=True,
                commands=("create_proposal",),
            ),
        ),
    )
    return AuthoringToolBinding(
        snapshot=snapshot,
        bearer_token="machine-bearer-xyz",
        actor_token="actor-token-abc",
        engine_base_url=engine_base_url,
        run_id=run_id,
    )


def test_authoring_bridge_composition_seam_threads_into_codex_config_toml(
    tmp_path: Path,
) -> None:
    """KILLS THE authoring-bridge masking gap, the Codex counterpart of
    ``test_composition_seam_threads_harness_into_codex_config_toml``.

    Before the fix, ``attach_authoring_tools`` dispatched ONLY on
    ``with_mcp_servers`` (the ACP lane), so a Codex model - which has no such
    surface - was returned UNCHANGED: the codex agent connected to app-server
    but its config.toml never carried the ``vaultspec-authoring`` block, so the
    engine's propose/read tools silently never reached the model. Build the
    model through the REAL production composition seam
    (``attach_authoring_tools``), not by setting ``authoring_mcp_server``
    directly, then assert the emitted config.toml carries the bridge with EVERY
    catalog tool name (including the mutating ``propose_changeset`` - the
    read-only-tools restriction that applies to the harness registry must NOT
    apply here, since the engine gates mutation on its own approval flow).
    """
    from ..codex_chat_model import CodexChatModel

    base = tmp_path / "base"
    base.mkdir()
    (base / "auth.json").write_text("{}", encoding="utf-8")
    model = CodexChatModel(command=["codex", "app-server"], codex_home=str(base))
    assert model.authoring_mcp_server is None  # not wired yet

    binding = _authoring_binding()
    composed = attach_authoring_tools(model, binding, autonomous=True)
    assert isinstance(composed, CodexChatModel)
    assert composed.authoring_mcp_server is not None
    assert composed.authoring_mcp_server["name"] == "vaultspec-authoring"

    home = composed._build_codex_config_home()
    assert home is not None
    try:
        cfg = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        bridge = cfg["mcp_servers"]["vaultspec-authoring"]
        assert bridge["args"] == ["-m", "vaultspec_a2a.protocols.mcp.authoring_stdio"]
        # ALL catalog tools are enabled, not just reads - unlike the harness
        # registry's read-verb-only allowlist.
        assert set(bridge["enabled_tools"]) == {"read_context", "propose_changeset"}
        assert bridge["default_tools_approval_mode"] == "auto"
        env = bridge["env"]
        assert env["VAULTSPEC_AUTHORING_BASE_URL"] == "http://127.0.0.1:8767"
        assert env["VAULTSPEC_AUTHORING_RUN_ID"] == "run:codex-test"
        assert env["VAULTSPEC_AUTHORING_BEARER"] == "machine-bearer-xyz"
    finally:
        cleanup_codex_config_home(home)


def test_authoring_bridge_unions_with_harness_servers_in_one_config_toml(
    tmp_path: Path,
) -> None:
    """A doc-editor-shaped preset (authoring_bridge=true + mcp_servers=[rag])
    gets BOTH surfaces in the same config.toml, ADD-only - the harness registry
    is never dropped when the bridge is attached, and vice versa."""
    from .._acp_mcp import compose_harness_mcp_servers
    from ..codex_chat_model import CodexChatModel

    base = tmp_path / "base"
    base.mkdir()
    model = CodexChatModel(command=["codex", "app-server"], codex_home=str(base))

    composed = compose_harness_mcp_servers(model, ["vaultspec-rag"])
    composed = attach_authoring_tools(composed, _authoring_binding(), autonomous=True)

    home = composed._build_codex_config_home()
    assert home is not None
    try:
        cfg = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        assert set(cfg["mcp_servers"]) == {"vaultspec-rag", "vaultspec-authoring"}
        # The harness registry keeps its read-only restriction...
        assert cfg["mcp_servers"]["vaultspec-rag"]["enabled_tools"] == [
            "search_vault",
            "search_codebase",
            "get_code_file",
        ]
        # ...while the bridge keeps its full catalog surface.
        assert set(cfg["mcp_servers"]["vaultspec-authoring"]["enabled_tools"]) == {
            "read_context",
            "propose_changeset",
        }
    finally:
        cleanup_codex_config_home(home)


def test_attach_authoring_tools_refuses_a_provider_with_no_attachment_surface() -> None:
    """A model with neither ``with_mcp_servers`` nor ``with_authoring_mcp_server``
    must refuse loud, not silently return unchanged (the S20-class defect this
    campaign closes: a harness-armed run starting an agent with no tools and
    burning its step timeout finding out)."""
    from langchain_core.language_models.fake_chat_models import FakeChatModel

    from ...thread.errors import ConfigError

    model = FakeChatModel(responses=["stub"])
    assert getattr(model, "with_mcp_servers", None) is None
    assert getattr(model, "with_authoring_mcp_server", None) is None
    with pytest.raises(ConfigError, match="no surface to mount the bridge"):
        attach_authoring_tools(model, _authoring_binding(), autonomous=True)


def test_build_home_tolerates_absent_auth(tmp_path: Path) -> None:
    # A base home without auth.json (e.g. env-based auth) still yields a valid
    # config home; nothing is copied and no error is raised.
    base = tmp_path / "empty_base"
    base.mkdir()
    home = build_codex_config_home(
        codex_mcp_server_specs(["vaultspec-rag"]),
        base,
        web_search=CodexWebSearchMode.DISABLED,
    )
    try:
        assert not (home / "auth.json").exists()
        assert (home / "config.toml").exists()
    finally:
        cleanup_codex_config_home(home)


def test_cleanup_is_none_safe_and_idempotent(tmp_path: Path) -> None:
    cleanup_codex_config_home(None)
    home = build_codex_config_home([], tmp_path, web_search=CodexWebSearchMode.DISABLED)
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
        build_codex_config_home(
            codex_mcp_server_specs(["vaultspec-rag"]),
            base,
            web_search=CodexWebSearchMode.DISABLED,
        )
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
        home = build_codex_config_home(
            specs, tmp_path / "base", web_search=CodexWebSearchMode.DISABLED
        )
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

    @pytest.mark.skipif(
        shutil.which("codex") is None, reason="codex CLI is not installed"
    )
    def test_codex_accepts_the_served_live_web_posture(self, tmp_path: Path) -> None:
        """The real CLI accepts the live posture this lane serves.

        ``web_search`` is not a name this project chose; it is the CLI's own
        top-level key, and the house no-pinning rule means nothing stops upstream
        from renaming it or dropping a variant under us. Exit 0 here is the
        detection mechanism, and the control below is what makes it mean
        something.
        """
        codex = shutil.which("codex")
        assert codex is not None
        home = build_codex_config_home(
            codex_mcp_server_specs(["vaultspec-rag"]),
            tmp_path / "base",
            web_search=CodexWebSearchMode.LIVE,
        )
        try:
            written = (home / "config.toml").read_text(encoding="utf-8")
            assert tomllib.loads(written)["web_search"] == "live"
            proc = subprocess.run(
                [codex, "mcp", "list"],
                env={**os.environ, "CODEX_HOME": str(home)},
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            assert proc.returncode == 0, proc.stderr
        finally:
            cleanup_codex_config_home(home)

    @pytest.mark.skipif(
        shutil.which("codex") is None, reason="codex CLI is not installed"
    )
    def test_codex_would_have_rejected_an_unrecognised_mode(
        self, tmp_path: Path
    ) -> None:
        """The control for the test above: the CLI really does validate this key.

        Exit 0 on our generated config proves nothing unless a wrong value fails.
        This takes the SAME production-rendered document and substitutes only the
        mode token with one the enum cannot produce; if the CLI still exited 0,
        the acceptance above would be vacuous - the key inert text Codex ignores
        rather than the web posture it reads.
        """
        codex = shutil.which("codex")
        assert codex is not None
        rendered = render_codex_config_toml(
            codex_mcp_server_specs(["vaultspec-rag"]),
            web_search=CodexWebSearchMode.LIVE,
        )
        home = tmp_path / "tampered-home"
        home.mkdir()
        (home / "config.toml").write_text(
            rendered.replace('web_search = "live"', 'web_search = "no-such-mode"', 1),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [codex, "mcp", "list"],
            env={**os.environ, "CODEX_HOME": str(home)},
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert "web_search" in combined
        # The CLI names the variants it will accept; every value this module can
        # emit must be among them, which is the served-contract assertion.
        for mode in CodexWebSearchMode:
            assert f"`{mode.value}`" in combined


# --- desktop-state escape defect (codex-config-home-escapes-desktop-state) ---


def test_unarmed_profile_creates_home_in_the_system_temp_root(tmp_path: Path) -> None:
    """Without a declared desktop root, the Codex home stays on OS temp."""
    base = tmp_path / "base"
    base.mkdir()

    with _seated_settings(desktop_app_home=None) as unarmed:
        assert unarmed.desktop_temp_homes_dir is None
        home = build_codex_config_home([], base, web_search=CodexWebSearchMode.DISABLED)
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
        home = build_codex_config_home([], base, web_search=CodexWebSearchMode.DISABLED)
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
