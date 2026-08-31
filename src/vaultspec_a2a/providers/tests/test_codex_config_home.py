"""Unit tests for the per-run Codex CODEX_HOME config.toml emission (P04.S18).

Real filesystem + stdlib tomllib, no mocks. The live proof that Codex surfaces
and invokes the servers under the read-only sandbox is executor-service's later
step; these pin the config.toml content, the auth copy, and the home lifecycle.
"""

from __future__ import annotations

import glob
import inspect
import os
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr

from ...authoring import AgentTool, CatalogSnapshot
from ...control.config import Settings
from ...graph.enums import Provider
from ...testing import armed_desktop_app_home
from ...utils.enums import CodexWebSearchMode
from .._acp_authoring import AuthoringToolBinding, attach_authoring_tools
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

    from .._json_contract import JsonObject
    from ..codex_chat_model import CodexChatModel


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


@pytest.fixture
def private_home_root(tmp_path: Path) -> Iterator[Path]:
    """Point per-run home creation at a root no other process writes to.

    The leak assertions below compare a glob of that root before and after a
    failure. By default the root is the machine-wide temporary directory, shared
    with every other lane on the machine, so a concurrent run creating its own
    Codex home made the comparison fail for a reason that had nothing to do with
    cleanup. Declaring the root through the settings surface - the same field an
    armed desktop install sets - makes the comparison private without teaching
    the tests a second way to find homes.

    The steering is ASSERTED rather than assumed. If the declared root stopped
    being what the production resolver returns, the glob would search a
    directory nothing ever writes to and every leak assertion below would pass
    VACUOUSLY - which is the exact failure :func:`_active_codex_leak_root`
    exists to prevent, arriving through the fix for a different problem.

    It arms the profile because ``desktop_temp_homes_dir`` is DERIVED from the
    application home and has no setter; arming through the sanctioned helper
    sets the field the property reads. That does move these three onto the armed
    placement, and that costs no coverage: placement under each profile has its
    own dedicated test below, while what these three assert is the cleanup
    branch, which does not vary by root.
    """
    with armed_desktop_app_home(tmp_path / "app-home"):
        root = _active_codex_leak_root()
        assert root != Path(tempfile.gettempdir()), (
            "the armed profile did not move the home root off the shared "
            "temporary directory, so these assertions would still be exposed "
            "to every other process on this machine"
        )
        yield root


def _settings_from_child(web_search_mode: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["VAULTSPEC_CODEX_WEB_SEARCH_MODE"] = web_search_mode
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from vaultspec_a2a.control.config import Settings; "
                "print(Settings().codex_web_search_mode)"
            ),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _config_home_parent_from_child(base: Path, app_home: Path | None) -> Path:
    environment = dict(os.environ)
    if app_home is None:
        environment.pop("VAULTSPEC_DESKTOP_APP_HOME", None)
    else:
        environment["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys; "
                "from vaultspec_a2a.providers._codex_config_home import "
                "build_codex_config_home, cleanup_codex_config_home; "
                "from vaultspec_a2a.utils.enums import CodexWebSearchMode; "
                "home = build_codex_config_home([], Path(sys.argv[1]), "
                "web_search=CodexWebSearchMode.DISABLED); "
                "print(home.parent); cleanup_codex_config_home(home)"
            ),
            str(base),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return Path(proc.stdout.strip())


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
    specs: list[JsonObject] = [
        {"name": "x-srv", "command": "c", "args": ["a"], "env": {"K": "V"}}
    ]
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
    specs: Sequence[JsonObject],
    base: Path,
    **kwargs: CodexWebSearchMode,
):
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
    # The callable signatures are runtime contracts as well as static ones. Bind
    # without the required parameter, so the interpreter's ordinary argument
    # check remains the second half of the invariant without a checker escape.
    with pytest.raises(TypeError):
        inspect.signature(build_codex_config_home).bind(
            codex_mcp_server_specs(["vaultspec-rag"]), base
        )
    with pytest.raises(TypeError):
        inspect.signature(render_codex_config_toml).bind(
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

    def _model(
        self,
        base: Path,
        *,
        web_search_mode: CodexWebSearchMode | None = None,
    ) -> CodexChatModel:
        from ..codex_chat_model import CodexChatModel

        return CodexChatModel(
            command=["codex", "app-server"],
            harness_mcp_servers=["vaultspec-rag"],
            codex_home=str(base),
            web_search_mode=web_search_mode,
        )

    def _emitted(self, model: CodexChatModel) -> dict[str, object]:
        home = model._build_codex_config_home()
        assert home is not None
        try:
            return tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        finally:
            cleanup_codex_config_home(home)

    def test_the_codex_lane_emits_live_because_it_carries_retrieval_proof(
        self, tmp_path: Path
    ) -> None:
        # This test previously asserted the mirror image - dark, because the lane
        # carried no proof - and was written to FAIL the day that proof was
        # recorded rather than quietly go on describing a lane that had since
        # been activated. That day came: the declaration now carries a live
        # retrieval proof for this lane, so both halves are restated against the
        # state that replaced it, and the first still states the precondition the
        # second depends on.
        base = tmp_path / "base"
        base.mkdir()
        assert Provider.CODEX in PROVEN_WEB_LANES
        assert self._emitted(self._model(base))["web_search"] == "live"

    def test_the_declared_lane_is_what_gets_asked_about(self, tmp_path: Path) -> None:
        # The verdict is taken for the model's OWN declared lane rather than a
        # constant, so the wiring cannot be right by coincidence. A lane with no
        # recorded proof is asked the same question and answers the other way,
        # which is what keeps the predicate from being constant-true now that the
        # model's own lane is proven.
        base = tmp_path / "base"
        base.mkdir()
        model = self._model(base)
        assert model.provider == Provider.CODEX.value
        assert is_web_lane_proven(model.provider) is True
        assert is_web_lane_proven(Provider.KIMI.value) is False

    def test_configuration_cannot_open_a_lane_the_gate_has_closed(self) -> None:
        # A deployment explicitly asking for live retrieval on a lane with no
        # proof. The gate is applied after the preference is read, so the answer
        # is still disabled. Without this precedence a config key would be a way
        # around the proof requirement.
        #
        # The subject is a lane that is genuinely unproven rather than this
        # module's own, because the model seam can only ask about the lane it
        # declares and that lane now carries proof. The verdict is still the real
        # predicate over the real declaration - nothing here is asserted about a
        # hypothetical.
        assert is_web_lane_proven(Provider.KIMI) is False
        assert (
            resolve_codex_web_search_mode(
                web_proven=is_web_lane_proven(Provider.KIMI),
                configured=CodexWebSearchMode.LIVE,
            )
            is CodexWebSearchMode.DISABLED
        )

    def test_configuration_narrows_a_lane_the_gate_has_opened(
        self, tmp_path: Path
    ) -> None:
        # The other half of the precedence, and the one the model seam can still
        # express: above the gate the deployment's preference governs, so an
        # install that wants search with zero egress takes the cached posture
        # through the real model API on a lane the gate has opened.
        base = tmp_path / "base"
        base.mkdir()
        model = self._model(base, web_search_mode=CodexWebSearchMode.CACHED)
        assert model.web_search_mode is CodexWebSearchMode.CACHED
        assert self._emitted(model)["web_search"] == "cached"

    def test_the_deployment_preference_is_read_from_real_settings(self) -> None:
        # The zero-egress path is a real settings key, parsed by the real
        # pydantic constructor from the real env alias - not a string this test
        # invented. Above the gate this is the value the resolver receives.
        result = _settings_from_child("cached")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == CodexWebSearchMode.CACHED.value
        assert (
            resolve_codex_web_search_mode(
                web_proven=True, configured=CodexWebSearchMode.CACHED
            )
            is CodexWebSearchMode.CACHED
        )

    def test_an_unrecognised_configured_mode_is_refused_at_settings_load(self) -> None:
        # Fail at load, where the operator can see it, rather than at a spawn
        # months later. The enum is the CLI's own vocabulary, so a value pydantic
        # rejects here is exactly one Codex would have rejected too.
        result = _settings_from_child("live-ish")
        assert result.returncode != 0
        assert "codex_web_search_mode" in result.stderr

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


def test_unarmed_codex_model_still_uses_an_isolated_home(tmp_path: Path) -> None:
    """An MCP-free turn cannot inherit the operator's ambient MCP servers."""
    from ..codex_chat_model import CodexChatModel

    base = tmp_path / "operator-codex-home"
    base.mkdir()
    (base / "auth.json").write_text('{"token": "x"}', encoding="utf-8")
    (base / "config.toml").write_text(
        '[mcp_servers.operator-owned]\ncommand = "never-inherit"\n',
        encoding="utf-8",
    )
    model = CodexChatModel(
        command=["codex", "app-server"],
        codex_home=str(base),
        web_search_mode=CodexWebSearchMode.CACHED,
    )

    home = model._build_codex_config_home()
    try:
        assert home != base
        assert (home / "auth.json").read_text(encoding="utf-8") == '{"token": "x"}'
        config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        assert config == {"web_search": CodexWebSearchMode.CACHED.value}
    finally:
        cleanup_codex_config_home(home)


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

    harnessed = compose_harness_mcp_servers(model, ["vaultspec-rag"])
    composed = attach_authoring_tools(harnessed, _authoring_binding(), autonomous=True)
    # Both composition seams declare the base type; asserting the Codex type
    # survives BOTH is the precondition for reading the config home at all.
    assert isinstance(composed, CodexChatModel)

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
    from langchain_openai import ChatOpenAI

    from ...thread.errors import ConfigError

    model = ChatOpenAI(api_key=SecretStr("unused-test-key"), model="gpt-4o-mini")
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


def test_cleanup_removes_home_by_default(tmp_path: Path) -> None:
    """Verify that cleanup_codex_config_home removes the home by default."""
    # Ensure the env var is unset (preservation: cleanup still happens)
    environment = dict(os.environ)
    environment.pop("VAULTSPEC_CODEX_CONFIG_HOME_RETAIN", None)

    home = build_codex_config_home([], tmp_path, web_search=CodexWebSearchMode.DISABLED)
    assert home.exists()
    # Run cleanup in a context where the env var is not set
    saved_env = os.environ.pop("VAULTSPEC_CODEX_CONFIG_HOME_RETAIN", None)
    try:
        cleanup_codex_config_home(home)
        assert not home.exists()
    finally:
        if saved_env is not None:
            os.environ["VAULTSPEC_CODEX_CONFIG_HOME_RETAIN"] = saved_env


def test_cleanup_retains_home_when_env_var_set(tmp_path: Path) -> None:
    """Verify that cleanup_codex_config_home retains the home when env var is set."""
    home = build_codex_config_home([], tmp_path, web_search=CodexWebSearchMode.DISABLED)
    assert home.exists()
    # Save the original env var and set the retention flag
    saved_env = os.environ.get("VAULTSPEC_CODEX_CONFIG_HOME_RETAIN")
    try:
        os.environ["VAULTSPEC_CODEX_CONFIG_HOME_RETAIN"] = "1"
        cleanup_codex_config_home(home)
        # Home should still exist (fix: home retention when flag is set)
        assert home.exists()
    finally:
        if saved_env is not None:
            os.environ["VAULTSPEC_CODEX_CONFIG_HOME_RETAIN"] = saved_env
        else:
            os.environ.pop("VAULTSPEC_CODEX_CONFIG_HOME_RETAIN", None)


def test_build_self_cleans_on_copy_failure(
    tmp_path: Path, private_home_root: Path
) -> None:
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
async def test_spawn_failure_cleans_credential_home(
    tmp_path: Path, private_home_root: Path
) -> None:
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
    tmp_path: Path, private_home_root: Path
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
        workspace_root=str(tmp_path),
    )
    pattern = os.path.join(str(_active_codex_leak_root()), "vaultspec-codex-home-*")
    before = set(glob.glob(pattern))
    # The codex handshake against an immediately-exited subprocess raises
    # _CodexProtocolError (a RuntimeError).
    with pytest.raises(RuntimeError):
        async for _ in model.astream([HumanMessage(content="hi")]):
            pass
    assert set(glob.glob(pattern)) <= before  # credential home cleaned


# --- desktop-state escape defect (codex-config-home-escapes-desktop-state) ---


def test_unarmed_profile_creates_home_in_the_system_temp_root(tmp_path: Path) -> None:
    """Without a declared desktop root, the Codex home stays on OS temp."""
    base = tmp_path / "base"
    base.mkdir()

    assert _config_home_parent_from_child(base, None) == Path(tempfile.gettempdir())


def test_armed_desktop_profile_seats_the_home_inside_the_declared_root(
    tmp_path: Path,
) -> None:
    """On an armed desktop install the Codex home is seated under the app home.

    This is the direct proof for the escapes-desktop-state defect: before the
    fix, ``mkdtemp`` carried no ``dir=`` at all, so the home always landed in
    system temp regardless of the desktop profile - a disk leak and an
    uninstall-completeness gap. Swapping the shared settings singleton to a
    real, fully-validated armed child environment drives
    ``temp_home_root`` - the Claude side's own root resolver, now shared - to
    resolve the declared root through its real, unmodified lazy import.
    """
    base = tmp_path / "base"
    base.mkdir()
    app_home = tmp_path / "app-home"
    app_home.mkdir()

    home_parent = _config_home_parent_from_child(base, app_home)
    assert home_parent != Path(tempfile.gettempdir())
    assert app_home in home_parent.parents


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


def test_codex_sweep_is_prefix_bound_and_never_collects_foreign_homes(
    tmp_path: Path,
) -> None:
    """The Codex sweep collects only its own prefix, never a foreign directory.

    A stale directory under another product's prefix (here the retired Claude
    ACP home prefix, which real hosts may still carry as residue) must survive a
    Codex sweep untouched - the sweep's scope is its prefix, not its age gate.
    """
    aged = ORPHAN_HOME_MIN_AGE_SECONDS + 3600
    stale_codex = _codex_home(tmp_path, "vaultspec-codex-home-stale", age_seconds=aged)
    foreign = tmp_path / "vaultspec-acp-home-stale"
    foreign.mkdir()
    (foreign / ".claude.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - aged
    os.utime(foreign, (stamp, stamp))

    codex_removed = sweep_orphan_codex_homes(root=tmp_path)
    assert codex_removed == [stale_codex]
    assert foreign.exists()  # untouched by the Codex-prefixed sweep


# --- endpoint redirect on the Codex lane -----------------------------------


def test_render_omits_any_provider_table_when_no_override_is_given() -> None:
    # The served shape. A config home that named a provider table by default
    # would silently move every run's traffic, so absence is the assertion that
    # matters most here - not the presence case below.
    parsed = tomllib.loads(
        render_codex_config_toml(
            codex_mcp_server_specs(["vaultspec-rag"]),
            web_search=CodexWebSearchMode.DISABLED,
        )
    )
    assert "model_providers" not in parsed
    assert "model_provider" not in parsed


def test_render_selects_the_provider_table_it_declares() -> None:
    # Declaring [model_providers.X] without also setting model_provider = "X"
    # renders an inert table: Codex would keep its own endpoint and the run
    # would silently reach the real provider. Both halves, or neither.
    parsed = tomllib.loads(
        render_codex_config_toml(
            codex_mcp_server_specs(["vaultspec-rag"]),
            web_search=CodexWebSearchMode.DISABLED,
            base_url_override="http://127.0.0.1:19999/v1",
        )
    )
    selected = parsed["model_provider"]
    provider = parsed["model_providers"][selected]
    assert provider["base_url"] == "http://127.0.0.1:19999/v1"
    # Not cosmetic: the installed app-server rejects the older "chat" value at
    # config load, so a redirect declaring it fails before reaching any endpoint.
    assert provider["wire_api"] == "responses"
    # The MCP surface must survive the redirect; the override moves the endpoint,
    # not the harness.
    assert "vaultspec-rag" in parsed["mcp_servers"]


def _override_config_from_child(base: Path, base_url: str | None) -> dict[str, Any]:
    """Return the config.toml the model writes under a given environment.

    Drives the REAL seam - environment -> Settings -> CodexChatModel ->
    build_codex_config_home - in a child process, because Settings is read once
    at import. Setting the field on the model instead would prove only that the
    renderer works, which the tests above already cover; what is in question
    here is whether a deployment's variable reaches the file Codex reads.
    """
    environment = dict(os.environ)
    if base_url is None:
        environment.pop("VAULTSPEC_CODEX_BASE_URL", None)
    else:
        environment["VAULTSPEC_CODEX_BASE_URL"] = base_url
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys; "
                "from vaultspec_a2a.providers.codex_chat_model import CodexChatModel; "
                "from vaultspec_a2a.providers._codex_config_home import "
                "cleanup_codex_config_home; "
                "m = CodexChatModel(codex_home=sys.argv[1]); "
                "h = m._build_codex_config_home(); "
                "sys.stdout.write((h / 'config.toml').read_text(encoding='utf-8')); "
                "cleanup_codex_config_home(h)"
            ),
            str(base),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return tomllib.loads(proc.stdout)


def test_deployment_variable_reaches_the_file_codex_reads(tmp_path: Path) -> None:
    parsed = _override_config_from_child(tmp_path, "http://127.0.0.1:19998/v1")
    selected = parsed["model_provider"]
    assert parsed["model_providers"][selected]["base_url"] == (
        "http://127.0.0.1:19998/v1"
    )


def test_unset_deployment_variable_leaves_the_provider_endpoint_alone(
    tmp_path: Path,
) -> None:
    assert "model_providers" not in _override_config_from_child(tmp_path, None)
