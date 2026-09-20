"""Tests for the provider factory."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ...control.config import settings
from ...graph.compiler import resolve_model_for_worker
from ...graph.enums import Provider
from ...team.team_config import load_agent_config, load_team_config
from ...thread.errors import ConfigError
from .._factory_commands import (
    _BIN_PATH,
    _CLAUDE_ACP_JS,
    _build_kimi_env,
    _build_zai_env,
    _classify_acp_command,
    _kimi_home_env,
    classify_provider_command,
    kimi_temporary_model_configuration_reason,
)
from ..acp_chat_model import AcpChatModel
from ..cli_resolution import resolve_provider_cli_executable
from ..codex_chat_model import CodexChatModel
from ..factory import ProviderFactory
from ..provider_catalog import AuthenticationState, CatalogStatus, ProviderCatalogKey

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
    registrations = ProviderFactory().catalog_registrations(Path.cwd())
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
@pytest.mark.parametrize(
    "key",
    (
        ProviderCatalogKey("zai", f"zai-claude-agent-acp:{settings.acp_backend}"),
        ProviderCatalogKey("zhipu", "zhipu-openai-compatible-api"),
    ),
)
async def test_unverified_catalog_lanes_are_truthfully_unavailable(
    key: ProviderCatalogKey,
) -> None:
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
    command, _ = _classify_acp_command("binary")
    assert len(command) == 1
    assert "claude-agent-acp" in command[0]


def test_classify_acp_command_binary_path_matches_bin_path() -> None:
    """binary backend command path matches the resolved _BIN_PATH."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(lambda: _classify_acp_command("binary"))
        return
    command, _ = _classify_acp_command("binary")
    assert Path(command[0]) == _BIN_PATH


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
    assert model.runtime_authority == "package_bin"
    assert model.command_origin == "package_bin"
    assert model.command_kind == "bun_binary"
    assert model.acp_backend == "binary"
    assert model.auth_mode in {"cli_session", "none_detected"}


def test_provider_factory_claude_never_injects_an_env_token() -> None:
    """The Claude lane's identity is the operator's CLI session, never a token.

    A configured ``CLAUDE_CODE_OAUTH_TOKEN`` (settings/.env) is a SEPARATE
    credential window from the account the operator is logged in as; injecting
    it would silently redirect every run onto that other identity. The factory
    must therefore construct the model with no token in ``env_vars`` regardless
    of what settings carry, and stamp the lane from the CLI session credential's
    presence alone.
    """
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
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in model.env_vars
    assert "ANTHROPIC_API_KEY" not in model.env_vars
    assert model.auth_mode in {"cli_session", "none_detected"}


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


def test_build_zai_env_injects_base_url_and_token() -> None:
    """Z.ai env builder maps configured settings to the Anthropic gateway vars."""
    env = _build_zai_env(
        zai_base_url="https://api.z.ai/api/anthropic",
        zai_auth_token="zai-secret",
    )
    assert env == {
        "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "zai-secret",
    }


def test_build_zai_env_without_token_returns_empty() -> None:
    """No token means no auth env — the base URL alone is not injected."""
    assert _build_zai_env("https://api.z.ai/api/anthropic", None) == {}


def test_build_zai_env_ignores_blank_token() -> None:
    """A whitespace-only token must not produce an ANTHROPIC_AUTH_TOKEN var."""
    assert _build_zai_env("https://api.z.ai/api/anthropic", "  ") == {}


def test_build_zai_env_omits_blank_base_url() -> None:
    """A blank base URL is dropped while a real token still authenticates."""
    env = _build_zai_env(" ", "zai-secret")
    assert env == {"ANTHROPIC_AUTH_TOKEN": "zai-secret"}


def test_provider_factory_zai_creates_acp_via_claude_wrapper() -> None:
    """Z.ai rides the claude-agent-acp wrapper: same command as the Claude path."""
    if not _CLAUDE_ACP_JS.exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            ProviderFactory().create(Provider.ZAI, model=_FROZEN_ZAI_MODEL)
        return
    model = ProviderFactory().create(Provider.ZAI, model=_FROZEN_ZAI_MODEL)
    assert isinstance(model, AcpChatModel)
    assert model.command == ["node", str(_CLAUDE_ACP_JS)]
    assert model.provider == Provider.ZAI.value
    assert model.acp_backend == "node"
    assert model.use_exec is False
    assert model.auth_mode in {"zai_auth_token", "none_detected"}


def test_provider_factory_zai_retains_requested_model_for_acp_selection() -> None:
    """A frozen Z.ai catalog value must reach the shared Claude ACP model."""
    if not _CLAUDE_ACP_JS.exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            ProviderFactory().create(Provider.ZAI, model=_FROZEN_ZAI_MODEL)
        return
    model = ProviderFactory().create(Provider.ZAI, model=_FROZEN_ZAI_MODEL)
    assert isinstance(model, AcpChatModel)
    assert model.desired_model == _FROZEN_ZAI_MODEL
    assert model._config.desired_model == _FROZEN_ZAI_MODEL


def test_provider_factory_zai_injects_configured_token() -> None:
    """When a Z.ai token is configured, both Anthropic gateway vars are injected."""
    if not _CLAUDE_ACP_JS.exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            ProviderFactory().create(Provider.ZAI, model=_FROZEN_ZAI_MODEL)
        return
    model = ProviderFactory().create(Provider.ZAI, model=_FROZEN_ZAI_MODEL)
    assert isinstance(model, AcpChatModel)
    if settings.zai_auth_token and settings.zai_auth_token.strip():
        assert model.env_vars["ANTHROPIC_AUTH_TOKEN"] == settings.zai_auth_token
        assert model.env_vars["ANTHROPIC_BASE_URL"] == settings.zai_base_url
        assert model.auth_mode == "zai_auth_token"
    else:
        assert "ANTHROPIC_AUTH_TOKEN" not in model.env_vars
        assert model.auth_mode == "none_detected"


def test_provider_factory_kimi_creates_acp_on_kimi_agent() -> None:
    """Kimi builds an AcpChatModel on the `kimi acp` command with the kimi family."""
    if resolve_provider_cli_executable(Provider.KIMI) is None:
        with pytest.raises(ValueError, match="Kimi CLI not resolvable"):
            from .._factory_commands import classify_provider_command

            classify_provider_command(Provider.KIMI)
        return
    model = ProviderFactory().create(Provider.KIMI, model=_FROZEN_KIMI_MODEL)
    assert isinstance(model, AcpChatModel)
    # Kimi drives its own agent, NOT the claude-agent-acp wrapper.
    assert model.command[-1] == "acp"
    assert "kimi" in model.command[0].lower()
    assert model.command[1:] == ["-m", _FROZEN_KIMI_MODEL, "acp"]
    assert model.provider == Provider.KIMI.value
    # The backend family discriminator: kimi omits the Claude allowedTools _meta.
    assert model.acp_family == "kimi"
    assert model._config.acp_family == "kimi"
    # A complete temporary definition is explicit and separate from `-m`.
    if "KIMI_MODEL_API_KEY" in model.env_vars:
        assert settings.kimi_api_key is not None
        assert model.env_vars["KIMI_MODEL_API_KEY"] == (
            settings.kimi_api_key.get_secret_value()
        )
        assert model.auth_mode == "temporary_model"
        assert settings.kimi_api_key.get_secret_value() not in repr(model)
    else:
        assert model.auth_mode == "persisted_config"
    assert "KIMI_API_KEY" not in model.env_vars
    assert "KIMI_BASE_URL" not in model.env_vars
    if settings.kimi_code_home and settings.kimi_code_home.strip():
        assert model.env_vars["KIMI_CODE_HOME"] == settings.kimi_code_home.strip()


def test_kimi_persisted_configuration_injects_no_temporary_definition() -> None:
    assert _kimi_home_env("C:/kimi-home") == {"KIMI_CODE_HOME": "C:/kimi-home"}


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


def test_classify_provider_command_kimi_resolves_or_hints_install() -> None:
    """Kimi classifies to the installed Kimi Code ACP executable."""
    if resolve_provider_cli_executable(Provider.KIMI) is None:
        with pytest.raises(ValueError, match="Kimi Code CLI not resolvable"):
            classify_provider_command(Provider.KIMI)
        return
    meta = classify_provider_command(Provider.KIMI)
    assert meta["command_kind"] == "kimi_cli"
    assert meta["command_origin"] == "system_path_executable"


def test_classify_provider_command_zai_returns_acp_meta() -> None:
    """Z.ai classifies to the same ACP wrapper command metadata as Claude."""
    if not _CLAUDE_ACP_JS.exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            classify_provider_command(Provider.ZAI)
        return
    meta = classify_provider_command(Provider.ZAI)
    assert meta["command_kind"] == "node_entry"
    assert meta["acp_backend"] == "node"
    assert meta["command_executable"] == "node"


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


def test_factory_applies_exact_kimi_model_scoped_effort() -> None:
    model = ProviderFactory().create(
        Provider.KIMI,
        model="configured-alias",
        execution_mode="kimi-code-acp",
        native_controls={"thinking_effort:entry": "deep"},
    )
    assert isinstance(model, AcpChatModel)
    assert model.command[1:3] == ["-m", "configured-alias"]
    assert model.env_vars["KIMI_MODEL_THINKING_EFFORT"] == "deep"


def test_factory_applies_exact_acp_session_controls() -> None:
    model = ProviderFactory().create(
        Provider.CLAUDE,
        model="catalog-model",
        execution_mode=f"claude-agent-acp:{settings.acp_backend}",
        native_controls={"thinking-budget": "brief-wire"},
    )
    assert isinstance(model, AcpChatModel)
    assert model.desired_model == "catalog-model"
    assert model.desired_config_options == {"thinking-budget": "brief-wire"}


def test_factory_restarts_the_frozen_acp_backend_not_the_current_default() -> None:
    if not _CLAUDE_ACP_JS.exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            ProviderFactory().create(
                Provider.CLAUDE,
                model="catalog-model",
                execution_mode="claude-agent-acp:node",
            )
        return
    model = ProviderFactory().create(
        Provider.CLAUDE,
        model="catalog-model",
        execution_mode="claude-agent-acp:node",
    )
    assert isinstance(model, AcpChatModel)
    assert model.acp_backend == "node"
    assert model.command == ["node", str(_CLAUDE_ACP_JS)]


def test_compiler_uses_fallback_only_after_a_valid_lane_is_runtime_unavailable() -> (
    None
):
    team = load_team_config("vaultspec-solo-coder")
    worker_ref = team.workers[0]
    agent = load_agent_config(worker_ref.agent_id)
    assignment: dict[str, dict[str, Any]] = {
        worker_ref.agent_id: {
            "schema_version": 1,
            "provider": "codex",
            "execution_mode": "unavailable-mode",
            "catalog_revision": "rev",
            "entry_id": "primary",
            "model_name": "primary-model",
            "controls": [],
            "provenance": {"selection_source": "team_selection"},
            "fallbacks": [
                {
                    "schema_version": 1,
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
    from ..factory import ProviderRuntimeUnavailableError

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

    @pytest.mark.parametrize("provider", (Provider.DETERMINISTIC, Provider.MOCK))
    def test_in_process_fast_path_rejects_native_controls(
        self, provider: Provider
    ) -> None:
        with pytest.raises(ValueError, match="no exact native-control executor"):
            ProviderFactory().create(
                provider,
                model="exact",
                execution_mode=(
                    "in-process-deterministic"
                    if provider is Provider.DETERMINISTIC
                    else "in-process-mock"
                ),
                native_controls={"unsupported": "value"},
            )

    @pytest.mark.parametrize("provider", (Provider.DETERMINISTIC, Provider.MOCK))
    def test_an_in_process_lane_has_no_implicit_default(
        self, provider: Provider
    ) -> None:
        from ..factory import _admit_and_resolve_model_name

        with pytest.raises(ValueError, match="exact model value frozen"):
            _admit_and_resolve_model_name(provider, None)

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
