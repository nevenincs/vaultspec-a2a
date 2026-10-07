"""Tests for the provider factory."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ...control.config import settings
from ...graph._compiler_models import resolve_model_for_worker
from ...graph.enums import Provider
from ...team.team_config import load_agent_config, load_team_config
from ...testing import settings_override
from ...thread.errors import ConfigError
from .._factory_commands import (
    _BIN_PATH,
    CLAUDE_OAUTH_TOKEN,
    ProviderCommand,
    _build_kimi_env,
    _classify_acp_command,
    classify_provider_command,
    claude_acp_entry,
    kimi_temporary_model_configuration_reason,
)
from ..acp_chat_model import AcpChatModel
from ..cli_resolution import (
    SYSTEM_CLI_LANES,
    ProviderRuntimeUnavailableError,
    ProviderRuntimeUnavailableReason,
    resolve_service_executable,
)
from ..codex_chat_model import CodexChatModel
from ..execution_modes import BINARY_BACKEND, NODE_BACKEND
from ..factory import (
    ProviderFactory,
    _acp_catalog_auth_overlay,
    _zai_auth_env,
    kimi_binary_proof_reason,
)
from ..provider_catalog import (
    SELECTION_SCHEMA_VERSION,
    AuthenticationState,
    CatalogStatus,
    HealthState,
    ProviderCatalogKey,
)
from ..team_selection import FrozenLaneAssignment

# The exact model values a run freezes into its role assignment for each external
# lane. Literals rather than lookups: an external provider's models are named by
# the catalog that provider serves, so the repository holds no map to read them
# from and the factory admits only the frozen value it is handed. What these
# tests pin is that the value SURVIVES construction unaltered, which is a
# property of the plumbing and not of the particular string.
_FROZEN_CLAUDE_MODEL = "claude-frozen-entry"
_FROZEN_KIMI_MODEL = "kimi-frozen-entry"
_FROZEN_ZAI_MODEL = "zai-frozen-entry"
_FROZEN_ZHIPU_MODEL = "zhipu-frozen-entry"


def get_model_attr(model_obj: BaseChatModel) -> str | None:
    """Helper to get model name from different LangChain model classes."""
    return getattr(model_obj, "model", getattr(model_obj, "model_name", None))


def test_catalog_registrations_are_execution_mode_specific() -> None:
    registrations = ProviderFactory().catalog_registrations(
        Path.cwd(), serve_in_process_lanes=False
    )
    assert tuple(registration.key for registration in registrations) == (
        ProviderCatalogKey("antigravity", "antigravity-cli"),
        ProviderCatalogKey("claude", f"claude-agent-acp:{settings.acp_backend}"),
        ProviderCatalogKey("codex", "codex-app-server"),
        ProviderCatalogKey("kimi", "kimi-code-acp"),
        ProviderCatalogKey("openai", "openai-api"),
        ProviderCatalogKey("zai", f"zai-claude-agent-acp:{settings.acp_backend}"),
        ProviderCatalogKey("zhipu", "zhipu-openai-compatible-api"),
    )
    with pytest.raises(ValueError, match="no catalog registration"):
        ProviderFactory().catalog_registration(
            ProviderCatalogKey("openai", "api"), Path.cwd()
        )


@pytest.mark.asyncio
async def test_a_lane_with_no_enumeration_surface_says_so() -> None:
    """Zhipu has no prompt-free enumeration at all, and reports that.

    The Z.ai lane is deliberately NOT in this population any more: it runs the
    claude-agent-acp adapter, which does enumerate, so its answer now depends on
    its credential rather than on a blanket refusal.
    """
    key = ProviderCatalogKey("zhipu", "zhipu-openai-compatible-api")
    discovery = await ProviderFactory().catalog_registration(key, Path.cwd()).discover()
    assert discovery.catalog.key == key
    assert discovery.catalog.state.status is CatalogStatus.UNAVAILABLE
    assert discovery.catalog.models == ()
    assert discovery.catalog.state.reason == (
        "provider lane has no verified prompt-free model enumeration"
    )
    assert discovery.authentication is AuthenticationState.UNKNOWN


def _assert_binary_backend_unavailable(action: Callable[[], object]) -> None:
    """Assert the real binary-backend failure contract when no binary exists."""
    with pytest.raises(ConfigError, match="no executable found in"):
        action()


# ---------------------------------------------------------------------------
# _classify_acp_command: node and binary variants
# ---------------------------------------------------------------------------


def test_classify_acp_command_binary_returns_bin_path() -> None:
    """binary backend returns a single-element list pointing to the binary."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(lambda: _classify_acp_command("binary"))
        return
    command = _classify_acp_command("binary")
    assert len(command.argv) == 1
    assert "claude-agent-acp" in command.argv[0]


def test_classify_acp_command_binary_path_matches_bin_path() -> None:
    """binary backend command path matches the resolved _BIN_PATH."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(lambda: _classify_acp_command("binary"))
        return
    command = _classify_acp_command("binary")
    assert Path(command.argv[0]) == _BIN_PATH


def test_provider_factory_claude_binary_backend_injects_bun_flag() -> None:
    """binary backend injects CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN=1 into env_vars."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(
            lambda: ProviderFactory().create(
                Provider.CLAUDE, model="catalog-model", backend="binary"
            )
        )
        return
    model = ProviderFactory().create(
        Provider.CLAUDE, model="catalog-model", backend="binary"
    )
    assert isinstance(model, AcpChatModel)
    assert model.env_vars.get("CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN") == "1"
    assert model.command == [str(_BIN_PATH)]
    launch = model.provider_command
    assert launch is not None
    assert launch.runtime_authority == "package_bin"
    assert launch.command_origin == "package_bin"
    assert launch.command_kind == "bun_binary"
    assert launch.acp_backend == BINARY_BACKEND


def test_provider_factory_claude_default_never_injects_a_setting_token() -> None:
    """The default channel leaves a configured token out of the child overlay."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(
            lambda: ProviderFactory().create(
                Provider.CLAUDE, model="catalog-model", backend="binary"
            )
        )
        return
    from pydantic import SecretStr

    with settings_override(
        claude_auth_channel="subscription_login",
        claude_code_oauth_token=SecretStr("configured-test-token"),
    ):
        model = ProviderFactory().create(
            Provider.CLAUDE, model="catalog-model", backend="binary"
        )
    assert isinstance(model, AcpChatModel)
    assert model.env_vars.get("CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN") == "1"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in model.env_vars
    assert "ANTHROPIC_API_KEY" not in model.env_vars
    assert model.auth_mode == "subscription_login"


def test_provider_factory_claude_binary_sets_use_exec() -> None:
    """binary backend sets use_exec=True on AcpChatModel (no cmd.exe shim needed)."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(
            lambda: ProviderFactory().create(
                Provider.CLAUDE, model="catalog-model", backend="binary"
            )
        )
        return
    model = ProviderFactory().create(
        Provider.CLAUDE, model="catalog-model", backend="binary"
    )
    assert isinstance(model, AcpChatModel)
    assert model.use_exec is True


def test_provider_factory_claude_retains_requested_model_for_acp_selection() -> None:
    """A frozen Claude catalog value must survive factory construction."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(
            lambda: ProviderFactory().create(
                Provider.CLAUDE, model=_FROZEN_CLAUDE_MODEL, backend="binary"
            )
        )
        return
    model = ProviderFactory().create(
        Provider.CLAUDE, model=_FROZEN_CLAUDE_MODEL, backend="binary"
    )
    assert isinstance(model, AcpChatModel)
    assert model.desired_model == _FROZEN_CLAUDE_MODEL
    assert model._config.desired_model == _FROZEN_CLAUDE_MODEL


# ---------------------------------------------------------------------------
# Z.ai: config variant of the Claude ACP path
# ---------------------------------------------------------------------------


def test_zai_auth_env_injects_base_url_and_token() -> None:
    """Z.ai env selection maps configured settings to the Anthropic gateway vars."""
    with settings_override(
        zai_base_url="https://api.z.ai/api/anthropic", zai_auth_token="zai-secret"
    ):
        env, auth_mode = _zai_auth_env()
    assert env == {
        "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "zai-secret",
    }
    assert auth_mode == "zai_auth_token"


def test_zai_auth_env_without_token_returns_empty() -> None:
    """No token means no auth env — the base URL alone is not injected."""
    with settings_override(
        zai_base_url="https://api.z.ai/api/anthropic", zai_auth_token=None
    ):
        assert _zai_auth_env() == ({}, "none_detected")


def test_zai_auth_env_ignores_blank_token() -> None:
    """A whitespace-only token must not produce an ANTHROPIC_AUTH_TOKEN var."""
    with settings_override(
        zai_base_url="https://api.z.ai/api/anthropic", zai_auth_token="  "
    ):
        assert _zai_auth_env() == ({}, "none_detected")


def test_zai_auth_env_omits_blank_base_url() -> None:
    """A blank base URL is dropped while a real token still authenticates."""
    with settings_override(zai_base_url=" ", zai_auth_token="zai-secret"):
        env, auth_mode = _zai_auth_env()
    assert env == {"ANTHROPIC_AUTH_TOKEN": "zai-secret"}
    assert auth_mode == "zai_auth_token"


_ZAI_CATALOG_KEY = ProviderCatalogKey(
    Provider.ZAI.value, f"zai-claude-agent-acp:{settings.acp_backend}"
)


@pytest.mark.asyncio
async def test_zai_catalog_discovery_is_the_shared_acp_lifecycle(
    tmp_path: Path,
) -> None:
    """The Z.ai lane enumerates through the adapter it runs, not a stub.

    Without a token the shared lifecycle refuses at the lane's own credential
    overlay, so the served reason is the Z.ai one. The lane previously answered
    with a blanket "no verified prompt-free model enumeration" whatever was
    configured, which is what made its live proof unpassable: no credential
    could change the answer.
    """
    with settings_override(
        zai_base_url="https://api.z.ai/api/anthropic", zai_auth_token=None
    ):
        resolved = (
            await ProviderFactory()
            .catalog_registration(_ZAI_CATALOG_KEY, tmp_path)
            .discover()
        )
    assert resolved.catalog.state.status is CatalogStatus.UNAVAILABLE
    assert resolved.catalog.state.reason == "no Z.ai auth token configured"
    assert resolved.configured is HealthState.UNAVAILABLE
    assert resolved.authentication is AuthenticationState.UNKNOWN


@pytest.mark.asyncio
async def test_the_zai_overlay_reaches_the_probe_the_lane_launches(
    tmp_path: Path,
) -> None:
    """The probe's child is handed the Z.ai credential, never Claude's.

    The overlay the discovery lifecycle applies is the same one a served turn
    applies, so a catalog built here describes the gateway a run would reach.
    """
    del tmp_path
    with settings_override(
        zai_base_url="https://api.z.ai/api/anthropic", zai_auth_token="zai-secret"
    ):
        overlay = _acp_catalog_auth_overlay(Provider.ZAI)
    assert overlay.mode == "zai_auth_token"
    assert overlay.env == {
        "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "zai-secret",
    }
    # Claude's own channel is never what this lane's child authenticates with.
    assert CLAUDE_OAUTH_TOKEN.env_name not in overlay.env


@pytest.mark.asyncio
async def test_the_zai_overlay_refuses_before_resolving_any_launcher() -> None:
    """A lane with no credential is refused on its own configuration first.

    Readiness already refuses a missing configuration before it resolves a
    command; discovery now reports the same order, so an absent token is never
    reported as a missing adapter or an unpinnable CLI.
    """
    with (
        settings_override(zai_auth_token=None),
        pytest.raises(ProviderRuntimeUnavailableError, match=r"Z\.ai auth token"),
    ):
        _acp_catalog_auth_overlay(Provider.ZAI)


def test_provider_factory_zai_refuses_without_current_turn_proof(
    installed_acp_adapter: Path,
) -> None:
    """A frozen Z.ai model cannot bypass the withdrawn served proof."""
    del installed_acp_adapter
    with pytest.raises(ProviderRuntimeUnavailableError) as refusal:
        ProviderFactory().create(Provider.ZAI, model=_FROZEN_ZAI_MODEL)
    assert refusal.value.reason is ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING


def test_provider_factory_kimi_refuses_without_an_admitted_binary() -> None:
    """An unenrolled Kimi lane is refused before any launcher is constructed.

    Kimi carries handshake coverage only, so it holds no completed-turn proof
    and therefore no admitted binary identity. The refusal is the lane's own,
    independent of whether the CLI happens to be installed on this host: a lane
    with no proof has no version range a resolved binary could fall inside.
    """
    with pytest.raises(ProviderRuntimeUnavailableError) as refusal:
        ProviderFactory().create(Provider.KIMI, model=_FROZEN_KIMI_MODEL)
    assert refusal.value.reason is ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING
    assert kimi_binary_proof_reason() is (
        ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING
    )


def test_complete_kimi_temporary_definition_uses_current_names() -> None:
    assert _build_kimi_env(
        kimi_api_key="temporary-key",
        kimi_base_url="https://kimi.example.invalid/v1",
        kimi_temporary_model_name="configured-alias",
        kimi_temporary_model_max_context_size=131072,
        kimi_temporary_model_capabilities="thinking,image_in",
    ) == {
        "KIMI_MODEL_API_KEY": "temporary-key",
        "KIMI_MODEL_BASE_URL": "https://kimi.example.invalid/v1",
        "KIMI_MODEL_NAME": "configured-alias",
        "KIMI_MODEL_MAX_CONTEXT_SIZE": "131072",
        "KIMI_MODEL_CAPABILITIES": "thinking,image_in",
    }


@pytest.mark.parametrize(
    ("max_context_size", "capabilities"),
    ((131072, None), (None, "thinking"), (131072, "thinking")),
)
def test_optional_kimi_attributes_require_a_complete_temporary_definition(
    max_context_size: int | None, capabilities: str | None
) -> None:
    with pytest.raises(ValueError, match="incomplete Kimi temporary model"):
        _build_kimi_env(
            kimi_temporary_model_max_context_size=max_context_size,
            kimi_temporary_model_capabilities=capabilities,
        )


@pytest.mark.parametrize(
    ("key", "base_url", "name"),
    (
        ("key", None, None),
        (None, "https://kimi.example.invalid/v1", None),
        (None, None, "alias"),
        ("key", "https://kimi.example.invalid/v1", None),
        ("key", None, "alias"),
        (None, "https://kimi.example.invalid/v1", "alias"),
    ),
)
def test_every_partial_kimi_temporary_definition_fails_closed(
    key: str | None, base_url: str | None, name: str | None
) -> None:
    reason = kimi_temporary_model_configuration_reason(
        kimi_api_key=key,
        kimi_base_url=base_url,
        kimi_temporary_model_name=name,
    )
    assert reason == (
        "incomplete Kimi temporary model definition; set KIMI_MODEL_NAME, "
        "KIMI_MODEL_API_KEY, and KIMI_MODEL_BASE_URL together"
    )
    with pytest.raises(ValueError, match="incomplete Kimi temporary model"):
        _build_kimi_env(key, base_url, name)


def _staged_cli(directory: Path, provider: Provider) -> Path:
    """Install one executable-shaped file the service-path search will find."""
    name = SYSTEM_CLI_LANES[provider]
    staged = directory / (f"{name}.cmd" if os.name == "nt" else name)
    staged.write_text("", encoding="utf-8")
    staged.chmod(0o755)
    return staged


@pytest.mark.parametrize("provider", [Provider.CODEX, Provider.KIMI])
def test_a_system_cli_lane_classifies_to_an_absolute_launcher(
    tmp_path: Path, provider: Provider
) -> None:
    """The classified launcher is the absolute file the search found.

    The search path is stated rather than inherited, so this pins the resolution
    production performs on a host where exactly one answer exists.
    """
    staged = _staged_cli(tmp_path, provider)
    command = classify_provider_command(provider, search_path=str(tmp_path))
    assert command.command_kind == f"{provider.value}_cli"
    assert command.command_origin == "system_path_executable"
    assert Path(command.argv[0]).is_absolute()
    assert os.path.normcase(command.argv[0]) == os.path.normcase(str(staged))


@pytest.mark.parametrize("provider", [Provider.CODEX, Provider.KIMI])
def test_an_unresolved_system_cli_lane_is_refused_not_given_a_bare_name(
    tmp_path: Path, provider: Provider
) -> None:
    """No launcher means no command, rather than a name a child would resolve.

    A bare name is resolved by whoever launches it - Windows ``cmd.exe`` reads
    the working directory first, and that directory is the agent's own
    workspace - so a classification that produced one handed the choice of
    binary to the agent.
    """
    with pytest.raises(ConfigError, match="not installed"):
        classify_provider_command(provider, search_path=str(tmp_path))


def test_a_relative_launcher_cannot_be_classified_at_all(tmp_path: Path) -> None:
    """The absolute-launcher rule is enforced where commands are built.

    Every origin - the system CLIs, the node entry, the packaged binary, the
    capsule - passes through this one constructor, so the invariant is stated
    once here rather than re-checked per lane or at spawn.
    """
    with pytest.raises(ValueError, match="absolute"):
        ProviderCommand(
            argv=("kimi", "acp"),
            runtime_authority="system_cli",
            command_origin="system_path_executable",
            command_kind="kimi_cli",
            command_executable="kimi",
            command_target="kimi",
        )
    with pytest.raises(ValueError, match="at least one argument"):
        ProviderCommand(
            argv=(),
            runtime_authority="system_cli",
            command_origin="system_path_executable",
            command_kind="kimi_cli",
            command_executable="kimi",
            command_target="kimi",
        )
    absolute = str(tmp_path / "kimi")
    assert ProviderCommand(
        argv=(absolute, "acp"),
        runtime_authority="system_cli",
        command_origin="system_path_executable",
        command_kind="kimi_cli",
        command_executable="kimi",
        command_target=absolute,
    ).argv == (absolute, "acp")


def test_classify_provider_command_zai_returns_acp_meta() -> None:
    """Z.ai classifies to the same ACP wrapper command metadata as Claude."""
    if not claude_acp_entry().exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            classify_provider_command(Provider.ZAI)
        return
    command = classify_provider_command(Provider.ZAI)
    assert command.command_kind == "node_entry"
    assert command.acp_backend == NODE_BACKEND
    node = str(resolve_service_executable("node"))
    assert command.command_executable == Path(node).name


def test_provider_factory_explicit_string_model() -> None:
    """Verify that factory accepts string model names for OpenAI."""
    custom_model = "experimental-model-2026"
    model = ProviderFactory().create(
        Provider.OPENAI,
        model=custom_model,
        api_key="static-test-key",
    )
    assert get_model_attr(model) == custom_model
    assert isinstance(model, ChatOpenAI)
    assert str(model.openai_api_base).rstrip("/") == settings.openai_base_url


def test_provider_factory_zhipu_mapping() -> None:
    """Verify Zhipu AI (GLM) mapping to OpenAI-compatible ChatOpenAI."""
    model = ProviderFactory().create(
        Provider.ZHIPU, model=_FROZEN_ZHIPU_MODEL, api_key="static-test-key"
    )
    assert get_model_attr(model) == _FROZEN_ZHIPU_MODEL
    assert isinstance(model, ChatOpenAI)
    assert "bigmodel.cn" in str(model.openai_api_base)


def test_retired_gemini_lane_is_not_a_provider_or_catalog_registration() -> None:
    with pytest.raises(ValueError):
        Provider("gemini")
    assert all(
        registration.key.provider_id != "gemini"
        for registration in ProviderFactory().catalog_registrations(Path.cwd())
    )


def test_factory_applies_exact_codex_model_scoped_controls() -> None:
    model = ProviderFactory().create(
        Provider.CODEX,
        model="catalog-model",
        execution_mode="codex-app-server",
        native_controls={
            "reasoning_effort:entry": "brief",
            "service_tier:entry": "priority",
        },
    )
    assert isinstance(model, CodexChatModel)
    assert model.model_name == "catalog-model"
    assert model.effort == "brief"
    assert model.service_tier == "priority"


def test_the_kimi_model_scoped_effort_rides_the_launch_environment() -> None:
    """The selected native control reaches the CLI's own variable.

    Asserted on the environment builder rather than through a constructed
    model: the lane carries no completed-turn proof, so a served construction
    is refused before any environment is composed - and that refusal is pinned
    by ``test_provider_factory_kimi_refuses_without_an_admitted_binary``.
    """
    env = _build_kimi_env(
        kimi_api_key="temporary-key",
        kimi_base_url="https://kimi.example.invalid/v1",
        kimi_temporary_model_name="configured-alias",
        kimi_thinking_effort="deep",
    )
    assert env["KIMI_MODEL_THINKING_EFFORT"] == "deep"
    assert env["KIMI_MODEL_NAME"] == "configured-alias"
    # The control is independent of the tuple, exactly as the launch path emits it.
    assert _build_kimi_env(kimi_thinking_effort="deep") == {
        "KIMI_MODEL_THINKING_EFFORT": "deep"
    }


def test_factory_refuses_unproven_acp_session_controls(
    installed_acp_adapter: Path,
) -> None:
    del installed_acp_adapter
    with pytest.raises(ProviderRuntimeUnavailableError) as refusal:
        ProviderFactory().create(
            Provider.CLAUDE,
            model="catalog-model",
            execution_mode=f"claude-agent-acp:{settings.acp_backend}",
            native_controls={"thinking-budget": "brief-wire"},
        )
    assert refusal.value.reason is ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING


def test_factory_refuses_frozen_acp_backend_without_current_proof(
    installed_acp_adapter: Path,
) -> None:
    del installed_acp_adapter
    if not claude_acp_entry().exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            ProviderFactory().create(
                Provider.CLAUDE,
                model="catalog-model",
                execution_mode="claude-agent-acp:node",
            )
        return
    with pytest.raises(ProviderRuntimeUnavailableError) as refusal:
        ProviderFactory().create(
            Provider.CLAUDE,
            model="catalog-model",
            execution_mode="claude-agent-acp:node",
        )
    assert refusal.value.reason is ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING


def test_compiler_uses_fallback_only_after_a_valid_lane_is_runtime_unavailable() -> (
    None
):
    team = load_team_config("vaultspec-solo-coder")
    worker_ref = team.workers[0]
    agent = load_agent_config(worker_ref.agent_id)
    assignment = {
        worker_ref.agent_id: FrozenLaneAssignment.model_validate(
            {
                "schema_version": SELECTION_SCHEMA_VERSION,
                "provider_id": "codex",
                "execution_mode": "unavailable-mode",
                "catalog_revision": "rev",
                "entry_id": "primary",
                "model_name": "primary-model",
                "controls": [],
                "defaulted_control_ids": [],
                "provenance": {"selection_source": "team_selection"},
                "fallbacks": [
                    {
                        "schema_version": SELECTION_SCHEMA_VERSION,
                        "provider_id": "codex",
                        "execution_mode": "codex-app-server",
                        "catalog_revision": "rev",
                        "entry_id": "fallback",
                        "model_name": "fallback-model",
                        "controls": [],
                        "defaulted_control_ids": [],
                    }
                ],
            }
        )
    }

    with pytest.raises(ValueError, match="cannot execute mode"):
        resolve_model_for_worker(
            worker_ref,
            agent,
            team,
            provider_factory=ProviderFactory(),
            frozen_assignment=assignment,
        )


def test_production_factory_types_a_missing_acp_runtime() -> None:
    if _BIN_PATH is not None:
        pytest.skip("repository carries the optional binary ACP runtime")
    with pytest.raises(ProviderRuntimeUnavailableError, match="no executable found"):
        ProviderFactory().create(
            Provider.CLAUDE,
            model="exact",
            backend="binary",
        )


class TestProviderAdmission:
    """The admission path, exercised apart from construction after the split.

    ``create`` folded the supported-provider guard and the model-name resolution
    into one method with construction. Separated, admission is a pure decision -
    is this provider allowed, and what model does it resolve to - assertable
    without building a model.
    """

    def test_in_process_fast_path_rejects_native_controls(self) -> None:
        with pytest.raises(ValueError, match="no exact native-control executor"):
            ProviderFactory().create(
                Provider.DETERMINISTIC,
                model="exact",
                execution_mode="in-process-deterministic",
                native_controls={"unsupported": "value"},
            )

    def test_an_in_process_lane_has_no_implicit_default(self) -> None:
        from ..factory import _admit_and_resolve_model_name

        with pytest.raises(ValueError, match="exact model value frozen"):
            _admit_and_resolve_model_name(Provider.DETERMINISTIC, None)

    def test_an_external_lane_has_no_implicit_default(self) -> None:
        """Omitting a model may not silently choose the artifact producer.

        A repository-authored default for an external lane would name a model
        that provider never advertised, so admission refuses instead.
        """
        from ..factory import _admit_and_resolve_model_name

        with pytest.raises(ValueError, match="exact model value frozen"):
            _admit_and_resolve_model_name(Provider.CLAUDE, None)

    def test_the_refusal_is_not_reported_as_an_unsupported_provider(self) -> None:
        """Supported-ness and having a repo-authored default are separate facts.

        Claude remains a supported lane; it simply carries no default any more.
        Reporting the absent selection as an unsupported provider would send an
        operator hunting the wrong defect.
        """
        from ..factory import _admit_and_resolve_model_name

        with pytest.raises(ValueError) as excinfo:
            _admit_and_resolve_model_name(Provider.CLAUDE, None)

        assert "Unsupported provider" not in str(excinfo.value)

    def test_a_raw_string_passes_through_unvalidated(self) -> None:
        """The exact frozen catalog value is how an external lane is selected."""
        from ..factory import _admit_and_resolve_model_name

        resolved = _admit_and_resolve_model_name(Provider.CLAUDE, "some-custom-name")

        assert resolved == "some-custom-name"
