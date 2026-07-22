"""Tests for the provider factory."""

from pathlib import Path
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ...graph.enums import MODEL_MAP, Model, Provider
from ...thread.errors import ConfigError
from ..acp_chat_model import AcpChatModel
from ..factory import (
    _BIN_PATH,
    _CLAUDE_ACP_JS,
    ProviderFactory,
    _build_acp_command,
    _build_gemini_command,
    _build_gemini_env,
    _build_zai_env,
    _classify_gemini_command,
    classify_provider_command,
)
from ..model_profiles import PROVIDER_DEFAULT_MODELS


def get_model_attr(model_obj: BaseChatModel) -> str | None:
    """Helper to get model name from different LangChain model classes."""
    return getattr(model_obj, "model", getattr(model_obj, "model_name", None))


def _assert_binary_backend_unavailable(action) -> None:
    """Assert the real binary-backend failure contract when no binary exists."""
    with pytest.raises(ConfigError, match="no executable found in"):
        action()


# ---------------------------------------------------------------------------
# _build_acp_command: node and binary variants
# ---------------------------------------------------------------------------


def test_build_acp_command_binary_returns_bin_path() -> None:
    """binary backend returns a single-element list pointing to the binary."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(lambda: _build_acp_command("binary"))
        return
    cmd = _build_acp_command("binary")
    assert len(cmd) == 1
    assert "claude-agent-acp" in cmd[0]


def test_build_acp_command_binary_path_matches_bin_path() -> None:
    """binary backend command path matches the resolved _BIN_PATH."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(lambda: _build_acp_command("binary"))
        return
    cmd = _build_acp_command("binary")
    assert Path(cmd[0]) == _BIN_PATH


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
    assert model.auth_mode in {"oauth_token", "none_detected"}


def test_provider_factory_claude_binary_oauth_still_injected() -> None:
    """binary backend still injects CLAUDE_CODE_OAUTH_TOKEN when present."""
    if _BIN_PATH is None:
        _assert_binary_backend_unavailable(
            lambda: ProviderFactory().create(Provider.CLAUDE, backend="binary")
        )
        return
    # We can only assert this when the environment actually has an OAuth token.
    # The factory reads it from settings; we pass backend explicitly and let
    # the real settings supply the token if one is configured.
    model = ProviderFactory().create(Provider.CLAUDE, backend="binary")
    assert isinstance(model, AcpChatModel)
    assert model.env_vars.get("CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN") == "1"
    # If an OAuth token is configured in the environment, it must appear.
    from ..factory import settings as factory_settings

    if factory_settings.claude_code_oauth_token:
        assert (
            model.env_vars.get("CLAUDE_CODE_OAUTH_TOKEN")
            == factory_settings.claude_code_oauth_token
        )


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


def test_provider_factory_gemini_creates_acp() -> None:
    """Verify Gemini provider creates AcpChatModel with the correct ACP command."""
    model = ProviderFactory().create(Provider.GEMINI)
    assert isinstance(model, AcpChatModel)
    expected_model = MODEL_MAP[Provider.GEMINI][Model.MID]
    assert model.command[1:] == ["--model", expected_model, "--experimental-acp"]


def test_build_gemini_command_uses_explicit_executable() -> None:
    """Gemini command builder preserves an already-resolved executable path."""
    command = _build_gemini_command(
        "gemini-test-model", executable="/usr/local/bin/gemini"
    )
    assert command == [
        "/usr/local/bin/gemini",
        "--model",
        "gemini-test-model",
        "--experimental-acp",
    ]


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
        "--experimental-acp",
    ]
    assert meta["runtime_authority"] == "explicit_executable"
    assert meta["command_origin"] == "explicit_executable"
    assert meta["command_kind"] == "gemini_cli"


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


def test_provider_factory_zai_injects_configured_token() -> None:
    """When a Z.ai token is configured, both Anthropic gateway vars are injected."""
    from ..factory import settings as factory_settings

    if not _CLAUDE_ACP_JS.exists():
        with pytest.raises(ConfigError, match="Claude ACP entry point not found"):
            ProviderFactory().create(Provider.ZAI)
        return
    model = ProviderFactory().create(Provider.ZAI)
    assert isinstance(model, AcpChatModel)
    if factory_settings.zai_auth_token and factory_settings.zai_auth_token.strip():
        assert model.env_vars["ANTHROPIC_AUTH_TOKEN"] == factory_settings.zai_auth_token
        assert model.env_vars["ANTHROPIC_BASE_URL"] == factory_settings.zai_base_url
        assert model.auth_mode == "zai_auth_token"
    else:
        assert "ANTHROPIC_AUTH_TOKEN" not in model.env_vars
        assert model.auth_mode == "none_detected"


def test_provider_factory_kimi_creates_acp_on_kimi_agent() -> None:
    """Kimi builds an AcpChatModel on the `kimi acp` command with the kimi family."""
    import shutil

    from ..factory import settings as factory_settings

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
    # Per-run isolation (P03.S12): the inline --config global flag replaces the
    # ambient ~/.kimi/config.toml, suppressing any ambient Kimi MCP.
    assert "--config" in model.command
    cfg_idx = model.command.index("--config")
    assert "mcpServers" in model.command[cfg_idx + 1]
    assert cfg_idx < model.command.index("acp")  # global flag before subcommand
    assert model.provider == Provider.KIMI.value
    # The backend family discriminator: kimi omits the Claude allowedTools _meta.
    assert model.acp_family == "kimi"
    assert model._config.acp_family == "kimi"
    # Env passthrough uses the CLI's native unprefixed names; the key is a secret.
    if factory_settings.kimi_api_key:
        assert model.env_vars["KIMI_API_KEY"] == (
            factory_settings.kimi_api_key.get_secret_value()
        )
        assert model.auth_mode == "kimi_api_key"
        assert factory_settings.kimi_api_key.get_secret_value() not in repr(model)
    else:
        assert "KIMI_API_KEY" not in model.env_vars
        assert model.auth_mode == "none_detected"


def test_kimi_pin_and_install_hint_are_colocated() -> None:
    """The kimi-cli pin lives as one named constant and rides the install hint."""
    from ..factory import _KIMI_CLI_PIN, _KIMI_INSTALL_HINT

    assert _KIMI_CLI_PIN == "1.49.0"
    assert f"kimi-cli=={_KIMI_CLI_PIN}" in _KIMI_INSTALL_HINT
    assert _KIMI_INSTALL_HINT.startswith("uv tool install")


def test_classify_provider_command_kimi_resolves_or_hints_install() -> None:
    """KIMI classifies to the kimi acp agent meta, or raises the pinned hint."""
    import shutil

    from ..factory import _KIMI_CLI_PIN, classify_provider_command

    if shutil.which("kimi") is None:
        with pytest.raises(ValueError, match=f"kimi-cli=={_KIMI_CLI_PIN}"):
            classify_provider_command(Provider.KIMI)
        return
    meta = classify_provider_command(Provider.KIMI)
    assert meta["command_kind"] == "kimi_cli"
    assert meta["command_origin"] == "system_path_executable"


def test_kimi_git_bash_prerequisite_helper() -> None:
    """The Git-Bash prerequisite helper honors the CLI's own env override name."""
    from ..factory import _KIMI_GIT_BASH_ENV, _kimi_git_bash_resolvable

    # The override name matches the installed CLI source, not the ADR's inferred
    # KIMI_SHELL_PATH (grounding correction).
    assert _KIMI_GIT_BASH_ENV == "KIMI_CLI_GIT_BASH_PATH"
    # Git for Windows is a host prerequisite here, so this resolves True.
    assert _kimi_git_bash_resolvable() is True


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


def test_provider_factory_unsupported_provider() -> None:
    """Verify that nonsense providers raise ValueError with useful message."""
    with pytest.raises(ValueError, match="Unsupported provider: unknown"):
        ProviderFactory().create(cast("Provider", "unknown"))


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

        assert resolved == MODEL_MAP[Provider.CLAUDE][
            PROVIDER_DEFAULT_MODELS[Provider.CLAUDE]
        ]

    def test_a_model_enum_resolves_through_the_map(self) -> None:
        from ..factory import _admit_and_resolve_model_name

        level = PROVIDER_DEFAULT_MODELS[Provider.CLAUDE]
        resolved = _admit_and_resolve_model_name(Provider.CLAUDE, level)

        assert resolved == MODEL_MAP[Provider.CLAUDE][level]

    def test_a_raw_string_passes_through_unvalidated(self) -> None:
        from ..factory import _admit_and_resolve_model_name

        resolved = _admit_and_resolve_model_name(Provider.CLAUDE, "some-custom-name")

        assert resolved == "some-custom-name"

    def test_an_unsupported_provider_is_refused(self) -> None:
        from ..factory import _admit_and_resolve_model_name

        class _Bogus:
            value = "bogus"

        with pytest.raises(ValueError, match="Unsupported provider"):
            _admit_and_resolve_model_name(cast("Provider", _Bogus()), None)
