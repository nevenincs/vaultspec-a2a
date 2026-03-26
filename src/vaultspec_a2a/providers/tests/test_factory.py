"""Tests for the provider factory."""

from pathlib import Path

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from ...graph.enums import MODEL_MAP, Model, Provider
from ...thread.errors import ConfigError
from ..acp_chat_model import AcpChatModel
from ..factory import (
    _BIN_PATH,
    ProviderFactory,
    _build_acp_command,
    _build_gemini_command,
    _build_gemini_env,
    _classify_acp_command,
    _classify_gemini_command,
)


def get_model_attr(model_obj: BaseChatModel) -> str | None:
    """Helper to get model name from different LangChain model classes."""
    return getattr(model_obj, "model", getattr(model_obj, "model_name", None))


def _assert_binary_backend_unavailable(action) -> None:
    """Assert the real binary-backend failure contract when no binary exists."""
    with pytest.raises(ConfigError, match="no executable found in"):
        action()


@pytest.mark.requires_acp
def test_provider_factory_claude_creates_acp() -> None:
    """Verify Claude provider creates AcpChatModel with the correct ACP command."""
    model = ProviderFactory().create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)
    assert model.command[0] == "node"
    assert model.command[1].endswith("index.js")
    assert model.provider == Provider.CLAUDE.value
    assert model.runtime_authority == "project_local"
    assert model.command_origin == "project_node_modules_entry"
    assert model.command_kind == "node_entry"
    assert model.acp_backend == "node"


# ---------------------------------------------------------------------------
# _build_acp_command: node and binary variants
# ---------------------------------------------------------------------------


@pytest.mark.requires_acp
def test_build_acp_command_node_returns_node_command() -> None:
    """node backend returns ['node', '<path>/index.js']."""
    cmd = _build_acp_command("node")
    assert cmd[0] == "node"
    assert cmd[1].endswith("index.js")
    assert len(cmd) == 2


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


@pytest.mark.requires_acp
def test_classify_acp_command_node_returns_runtime_metadata() -> None:
    """Claude node backend exposes bounded runtime-authority metadata."""
    command, meta = _classify_acp_command("node")
    assert command[0] == "node"
    assert meta["runtime_authority"] == "project_local"
    assert meta["command_origin"] == "project_node_modules_entry"
    assert meta["command_kind"] == "node_entry"
    assert meta["acp_backend"] == "node"


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


@pytest.mark.requires_acp
def test_provider_factory_claude_node_backend_no_bun_flag() -> None:
    """node backend does not inject CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN."""
    model = ProviderFactory().create(Provider.CLAUDE, backend="node")
    assert isinstance(model, AcpChatModel)
    assert "CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN" not in model.env_vars
    assert model.command[0] == "node"


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


@pytest.mark.requires_acp
def test_provider_factory_claude_node_use_exec_false() -> None:
    """node backend leaves use_exec=False (shell mode for .cmd shim)."""
    model = ProviderFactory().create(Provider.CLAUDE, backend="node")
    assert isinstance(model, AcpChatModel)
    assert model.use_exec is False


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


@pytest.mark.requires_acp
def test_provider_factory_claude_with_workspace_root() -> None:
    """Verify that workspace_root kwarg is forwarded to AcpChatModel."""
    ws = Path("Y:/code/test")
    model = ProviderFactory().create(Provider.CLAUDE, workspace_root=ws)
    assert isinstance(model, AcpChatModel)
    assert model.workspace_root == str(ws)


def test_provider_factory_gemini_with_workspace_root() -> None:
    """Verify that workspace_root kwarg is forwarded to AcpChatModel for Gemini."""
    ws = Path("Y:/code/test")
    model = ProviderFactory().create(Provider.GEMINI, workspace_root=ws)
    assert isinstance(model, AcpChatModel)
    assert model.workspace_root == str(ws)


@pytest.mark.requires_acp
def test_provider_factory_workspace_root_none_default() -> None:
    """Verify that workspace_root defaults to None when not provided."""
    model = ProviderFactory().create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)
    assert model.workspace_root is None


@pytest.mark.requires_acp
def test_provider_factory_claude_never_injects_anthropic_api_key() -> None:
    """ADR-002 §2: Factory must NOT inject ANTHROPIC_API_KEY for Claude.

    The factory reads the real settings. Regardless of what ANTHROPIC_API_KEY
    is set to in the environment, the factory must not place it in env_vars.
    ANTHROPIC_API_KEY is stripped at subprocess spawn time in _astream().
    """
    model = ProviderFactory().create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)
    assert "ANTHROPIC_API_KEY" not in model.env_vars


@pytest.mark.requires_acp
def test_provider_factory_claude_oauth_only() -> None:
    """When OAuth token is set, only CLAUDE_CODE_OAUTH_TOKEN is in env_vars."""
    model = ProviderFactory().create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)
    if model.env_vars.get("CLAUDE_CODE_OAUTH_TOKEN"):
        assert model.env_vars["CLAUDE_CODE_OAUTH_TOKEN"].strip()
    assert "ANTHROPIC_API_KEY" not in model.env_vars


def test_provider_factory_unsupported_provider() -> None:
    """Verify that nonsense providers raise ValueError with useful message."""
    with pytest.raises(ValueError, match="Unsupported provider: unknown"):
        ProviderFactory().create("unknown")  # type: ignore[arg-type]


@pytest.mark.live
@pytest.mark.asyncio
async def test_factory_claude_live() -> None:
    """Test Claude end-to-end via the ACP subprocess wrapper."""
    model = ProviderFactory().create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)

    response = await model.ainvoke(
        [HumanMessage(content="Return the exact word 'Hello'.")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()


@pytest.mark.live
@pytest.mark.asyncio
async def test_factory_gemini_live() -> None:
    """Test Gemini end-to-end via the ACP subprocess wrapper."""
    model = ProviderFactory().create(Provider.GEMINI)
    assert isinstance(model, AcpChatModel)

    response = await model.ainvoke(
        [HumanMessage(content="Return the exact word 'Hello'.")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()


@pytest.mark.live
@pytest.mark.asyncio
async def test_factory_openai_live() -> None:
    """Test OpenAI end-to-end via the ChatOpenAI SDK wrapper."""
    model = ProviderFactory().create(Provider.OPENAI)
    assert isinstance(model, ChatOpenAI)

    response = await model.ainvoke(
        [HumanMessage(content="Return the exact word 'Hello'.")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()


@pytest.mark.live
@pytest.mark.asyncio
async def test_factory_zhipu_live() -> None:
    """Test Zhipu GLM end-to-end via the OpenAI-compatible ChatOpenAI wrapper."""
    model = ProviderFactory().create(Provider.ZHIPU)
    assert isinstance(model, ChatOpenAI)

    response = await model.ainvoke(
        [HumanMessage(content="Return the exact word 'Hello'.")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()
