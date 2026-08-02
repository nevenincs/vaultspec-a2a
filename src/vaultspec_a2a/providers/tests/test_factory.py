"""Tests for the provider factory."""

from collections.abc import Callable
from pathlib import Path

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ...control.config import settings
from ...graph.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Model, Provider
from ...thread.errors import ConfigError
from ..acp_chat_model import AcpChatModel
from ..factory import (
    _BIN_PATH,
    _CLAUDE_ACP_JS,
    ProviderFactory,
    _build_gemini_env,
    _build_kimi_env,
    _build_zai_env,
    _classify_acp_command,
    _classify_gemini_command,
    classify_provider_command,
    kimi_temporary_model_configuration_reason,
)
from ..provider_catalog import AuthenticationState, CatalogStatus, ProviderCatalogKey


def get_model_attr(model_obj: BaseChatModel) -> str | None:
    """Helper to get model name from different LangChain model classes."""
    return getattr(model_obj, "model", getattr(model_obj, "model_name", None))


def test_catalog_registrations_are_execution_mode_specific() -> None:
    registrations = ProviderFactory().catalog_registrations()
    assert tuple(registration.key for registration in registrations) == (
        ProviderCatalogKey("claude", f"claude-agent-acp:{settings.acp_backend}"),
        ProviderCatalogKey("codex", "codex-app-server"),
        ProviderCatalogKey("gemini", "gemini-cli-acp"),
        ProviderCatalogKey("kimi", "kimi-code-acp"),
        ProviderCatalogKey("openai", "openai-api"),
        ProviderCatalogKey("zai", f"zai-claude-agent-acp:{settings.acp_backend}"),
        ProviderCatalogKey("zhipu", "zhipu-openai-compatible-api"),
    )
    with pytest.raises(ValueError, match="no catalog registration"):
        ProviderFactory().catalog_registration(ProviderCatalogKey("openai", "api"))


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
    discovery = await ProviderFactory().catalog_registration(key).discover()
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
            lambda: ProviderFactory().create(Provider.CLAUDE, backend="binary")
        )
        return
    model = ProviderFactory().create(Provider.CLAUDE, backend="binary")
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
            lambda: ProviderFactory().create(Provider.CLAUDE, backend="binary")
        )
        return
    model = ProviderFactory().create(Provider.CLAUDE, backend="binary")
    assert isinstance(model, AcpChatModel)
    assert model.env_vars.get("CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN") == "1"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in model.env_vars
    assert "ANTHROPIC_API_KEY" not in model.env_vars
    assert model.auth_mode in {"cli_session", "none_detected"}


def test_provider_factory_claude_binary_sets_use_exec() -> None:
    """binary backend sets use_exec=True on AcpChatModel (no cmd.exe shim needed)."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(
            lambda: ProviderFactory().create(Provider.CLAUDE, backend="binary")
        )
        return
    model = ProviderFactory().create(Provider.CLAUDE, backend="binary")
    assert isinstance(model, AcpChatModel)
    assert model.use_exec is True


def test_provider_factory_claude_retains_requested_model_for_acp_selection() -> None:
    """A profile-resolved Claude tier must survive factory construction."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(
            lambda: ProviderFactory().create(
                Provider.CLAUDE, model=Model.LOW, backend="binary"
            )
        )
        return
    model = ProviderFactory().create(Provider.CLAUDE, model=Model.LOW, backend="binary")
    assert isinstance(model, AcpChatModel)
    expected = MODEL_MAP[Provider.CLAUDE][Model.LOW]
    assert model.desired_model == expected
    assert model._config.desired_model == expected


def test_provider_factory_gemini_creates_acp() -> None:
    """Verify Gemini provider creates AcpChatModel with the correct ACP command."""
    model = ProviderFactory().create(Provider.GEMINI)
    assert isinstance(model, AcpChatModel)
    expected_model = MODEL_MAP[Provider.GEMINI][Model.MID]
    assert model.command[1:] == ["--model", expected_model, "--acp"]


def test_classify_gemini_command_uses_explicit_executable_metadata() -> None:
    """Explicit Gemini executable is recorded as explicit runtime authority."""
    command, meta = _classify_gemini_command(
        "gemini-test-model",
        executable="/usr/local/bin/gemini",
    )
    assert command == [
        "/usr/local/bin/gemini",
        "--model",
        "gemini-test-model",
        "--acp",
    ]
    assert meta["runtime_authority"] == "explicit_executable"
    assert meta["command_origin"] == "explicit_executable"
    assert meta["command_kind"] == "gemini_cli"


def test_gemini_catalog_command_does_not_preselect_a_model() -> None:
    command, _ = _classify_gemini_command(
        None,
        executable="/usr/local/bin/gemini",
    )

    assert command == ["/usr/local/bin/gemini", "--acp"]


def test_build_gemini_env_injects_supported_noninteractive_auth() -> None:
    """Gemini env builder re-injects only documented subprocess auth vars."""
    env = _build_gemini_env(
        "gem-key",
        "google-key",
        "/run/secrets/google-application-credentials.json",
        "/gemini-cli-home",
    )
    assert env == {
        "GEMINI_API_KEY": "gem-key",
        "GOOGLE_API_KEY": "google-key",
        "GOOGLE_APPLICATION_CREDENTIALS": (
            "/run/secrets/google-application-credentials.json"
        ),
        "GEMINI_CLI_HOME": "/gemini-cli-home",
        "HOME": "/gemini-cli-home",
    }


def test_build_gemini_env_marks_local_oauth_mount_for_noninteractive_cli() -> None:
    """Mounted Gemini CLI OAuth state should force the official OAuth auth selector."""
    env = _build_gemini_env(None, None, None, "/gemini-cli-home")
    assert env == {
        "GEMINI_CLI_HOME": "/gemini-cli-home",
        "HOME": "/gemini-cli-home",
        "GOOGLE_GENAI_USE_GCA": "true",
    }


def test_build_gemini_env_ignores_blank_values() -> None:
    """Blank Gemini auth settings must not produce empty subprocess env vars."""
    env = _build_gemini_env(" ", "", " ", "")
    assert env == {}


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
            ProviderFactory().create(Provider.ZAI)
        return
    model = ProviderFactory().create(Provider.ZAI)
    assert isinstance(model, AcpChatModel)
    assert model.command == ["node", str(_CLAUDE_ACP_JS)]
    assert model.provider == Provider.ZAI.value
    assert model.acp_backend == "node"
    assert model.use_exec is False
    assert model.auth_mode in {"zai_auth_token", "none_detected"}


def test_provider_factory_zai_retains_requested_model_for_acp_selection() -> None:
    """A profile-resolved Z.ai tier must reach the shared Claude ACP model."""
    if not _CLAUDE_ACP_JS.exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            ProviderFactory().create(Provider.ZAI, model=Model.LOW)
        return
    model = ProviderFactory().create(Provider.ZAI, model=Model.LOW)
    assert isinstance(model, AcpChatModel)
    expected = MODEL_MAP[Provider.ZAI][Model.LOW]
    assert model.desired_model == expected
    assert model._config.desired_model == expected


def test_provider_factory_zai_injects_configured_token() -> None:
    """When a Z.ai token is configured, both Anthropic gateway vars are injected."""
    if not _CLAUDE_ACP_JS.exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            ProviderFactory().create(Provider.ZAI)
        return
    model = ProviderFactory().create(Provider.ZAI)
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
    import shutil

    if shutil.which("kimi") is None:
        with pytest.raises(ValueError, match="Kimi CLI not resolvable"):
            from ..factory import classify_provider_command

            classify_provider_command(Provider.KIMI)
        return
    model = ProviderFactory().create(Provider.KIMI)
    assert isinstance(model, AcpChatModel)
    # Kimi drives its own agent, NOT the claude-agent-acp wrapper.
    assert model.command[-1] == "acp"
    assert "kimi" in model.command[0].lower()
    expected_model = MODEL_MAP[Provider.KIMI][Model.MID]
    assert model.command[1:] == ["-m", expected_model, "acp"]
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


def test_kimi_persisted_configuration_injects_no_temporary_definition() -> None:
    assert _build_kimi_env(kimi_code_home="C:/kimi-home") == {
        "KIMI_CODE_HOME": "C:/kimi-home"
    }


def test_complete_kimi_temporary_definition_uses_current_names() -> None:
    assert _build_kimi_env(
        kimi_api_key="temporary-key",
        kimi_base_url="https://kimi.example.invalid/v1",
        kimi_temporary_model_name="configured-alias",
    ) == {
        "KIMI_MODEL_API_KEY": "temporary-key",
        "KIMI_MODEL_BASE_URL": "https://kimi.example.invalid/v1",
        "KIMI_MODEL_NAME": "configured-alias",
    }


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
    import shutil

    if shutil.which("kimi") is None:
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
    model = ProviderFactory().create(Provider.ZHIPU, api_key="static-test-key")
    expected_model = MODEL_MAP[Provider.ZHIPU][Model.HIGH]
    assert get_model_attr(model) == expected_model
    assert isinstance(model, ChatOpenAI)
    assert "bigmodel.cn" in str(model.openai_api_base)


def test_provider_factory_gemini_with_workspace_root() -> None:
    """Verify that workspace_root kwarg is forwarded to AcpChatModel for Gemini."""
    ws = Path("Y:/code/test")
    model = ProviderFactory().create(Provider.GEMINI, workspace_root=ws)
    assert isinstance(model, AcpChatModel)
    assert model.workspace_root == str(ws)


class TestProviderAdmission:
    """The admission path, exercised apart from construction after the split.

    ``create`` folded the supported-provider guard and the model-name resolution
    into one method with construction. Separated, admission is a pure decision -
    is this provider allowed, and what model does it resolve to - assertable
    without building a model.
    """

    def test_a_default_resolves_to_the_mapped_model(self) -> None:
        from ..factory import _admit_and_resolve_model_name

        resolved = _admit_and_resolve_model_name(Provider.CLAUDE, None)

        assert (
            resolved
            == MODEL_MAP[Provider.CLAUDE][PROVIDER_DEFAULT_MODELS[Provider.CLAUDE]]
        )

    def test_a_model_enum_resolves_through_the_map(self) -> None:
        from ..factory import _admit_and_resolve_model_name

        level = PROVIDER_DEFAULT_MODELS[Provider.CLAUDE]
        resolved = _admit_and_resolve_model_name(Provider.CLAUDE, level)

        assert resolved == MODEL_MAP[Provider.CLAUDE][level]

    def test_a_raw_string_passes_through_unvalidated(self) -> None:
        from ..factory import _admit_and_resolve_model_name

        resolved = _admit_and_resolve_model_name(Provider.CLAUDE, "some-custom-name")

        assert resolved == "some-custom-name"
