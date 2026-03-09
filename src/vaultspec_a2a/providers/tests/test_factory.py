"""Tests for the provider factory."""

from pathlib import Path

import pytest

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from ...utils.enums import MODEL_MAP, Model, Provider
from ..acp_chat_model import AcpChatModel
from ..factory import _BIN_PATH, ProviderFactory, _build_acp_command


def get_model_attr(model_obj: BaseChatModel) -> str | None:
    """Helper to get model name from different LangChain model classes."""
    return getattr(model_obj, "model", getattr(model_obj, "model_name", None))


def test_provider_factory_claude_creates_acp() -> None:
    """Verify Claude provider creates AcpChatModel with the correct ACP command."""
    model = ProviderFactory.create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)
    assert model.command[0] == "node"
    assert model.command[1].endswith("index.js")


# ---------------------------------------------------------------------------
# _build_acp_command: node and binary variants
# ---------------------------------------------------------------------------


def test_build_acp_command_node_returns_node_command() -> None:
    """node backend returns ['node', '<path>/index.js']."""
    cmd = _build_acp_command("node")
    assert cmd[0] == "node"
    assert cmd[1].endswith("index.js")
    assert len(cmd) == 2


def test_build_acp_command_binary_returns_bin_path() -> None:
    """binary backend returns a single-element list pointing to the binary."""
    if _BIN_PATH is None:
        pytest.skip("No binary present in bin/ — skipping binary command test")
    cmd = _build_acp_command("binary")
    assert len(cmd) == 1
    assert "claude-agent-acp" in cmd[0]


def test_build_acp_command_binary_path_matches_bin_path() -> None:
    """binary backend command path matches the resolved _BIN_PATH."""
    if _BIN_PATH is None:
        pytest.skip("No binary present in bin/ — skipping binary path test")
    cmd = _build_acp_command("binary")
    assert Path(cmd[0]) == _BIN_PATH


def test_provider_factory_claude_binary_backend_injects_bun_flag() -> None:
    """binary backend injects CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN=1 into env_vars."""
    if _BIN_PATH is None:
        pytest.skip("No binary present in bin/ — skipping binary backend test")
    model = ProviderFactory.create(Provider.CLAUDE, backend="binary")
    assert isinstance(model, AcpChatModel)
    assert model.env_vars.get("CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN") == "1"
    assert model.command == [str(_BIN_PATH)]


def test_provider_factory_claude_node_backend_no_bun_flag() -> None:
    """node backend does not inject CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN."""
    model = ProviderFactory.create(Provider.CLAUDE, backend="node")
    assert isinstance(model, AcpChatModel)
    assert "CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN" not in model.env_vars
    assert model.command[0] == "node"


def test_provider_factory_claude_binary_oauth_still_injected() -> None:
    """binary backend still injects CLAUDE_CODE_OAUTH_TOKEN when present."""
    if _BIN_PATH is None:
        pytest.skip("No binary present in bin/")
    # We can only assert this when the environment actually has an OAuth token.
    # The factory reads it from settings; we pass backend explicitly and let
    # the real settings supply the token if one is configured.
    model = ProviderFactory.create(Provider.CLAUDE, backend="binary")
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
        pytest.skip("No binary present in bin/")
    model = ProviderFactory.create(Provider.CLAUDE, backend="binary")
    assert isinstance(model, AcpChatModel)
    assert model.use_exec is True


def test_provider_factory_claude_node_use_exec_false() -> None:
    """node backend leaves use_exec=False (shell mode for .cmd shim)."""
    model = ProviderFactory.create(Provider.CLAUDE, backend="node")
    assert isinstance(model, AcpChatModel)
    assert model.use_exec is False


def test_provider_factory_gemini_creates_acp() -> None:
    """Verify Gemini provider creates AcpChatModel with the correct ACP command."""
    model = ProviderFactory.create(Provider.GEMINI)
    assert isinstance(model, AcpChatModel)
    expected_model = MODEL_MAP[Provider.GEMINI][Model.MID]
    assert model.command == ["gemini", "--model", expected_model, "--experimental-acp"]


def test_provider_factory_gemini_no_credential_injection() -> None:
    """Verify Gemini uses zero credential injection (local OAuth creds)."""
    model = ProviderFactory.create(Provider.GEMINI)
    assert isinstance(model, AcpChatModel)
    assert model.env_vars == {}


def test_provider_factory_explicit_string_model() -> None:
    """Verify that factory accepts string model names for OpenAI."""
    custom_model = "experimental-model-2026"
    model = ProviderFactory.create(
        Provider.OPENAI,
        model=custom_model,
        api_key="static-test-key",
    )
    assert get_model_attr(model) == custom_model
    assert isinstance(model, ChatOpenAI)


def test_provider_factory_zhipu_mapping() -> None:
    """Verify Zhipu AI (GLM) mapping to OpenAI-compatible ChatOpenAI."""
    model = ProviderFactory.create(Provider.ZHIPU, api_key="static-test-key")
    expected_model = MODEL_MAP[Provider.ZHIPU][Model.HIGH]
    assert get_model_attr(model) == expected_model
    assert isinstance(model, ChatOpenAI)
    assert "bigmodel.cn" in str(model.openai_api_base)


def test_provider_factory_claude_with_workspace_root() -> None:
    """Verify that workspace_root kwarg is forwarded to AcpChatModel."""
    ws = Path("Y:/code/test")
    model = ProviderFactory.create(Provider.CLAUDE, workspace_root=ws)
    assert isinstance(model, AcpChatModel)
    assert model.workspace_root == str(ws)


def test_provider_factory_gemini_with_workspace_root() -> None:
    """Verify that workspace_root kwarg is forwarded to AcpChatModel for Gemini."""
    ws = Path("Y:/code/test")
    model = ProviderFactory.create(Provider.GEMINI, workspace_root=ws)
    assert isinstance(model, AcpChatModel)
    assert model.workspace_root == str(ws)


def test_provider_factory_workspace_root_none_default() -> None:
    """Verify that workspace_root defaults to None when not provided."""
    model = ProviderFactory.create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)
    assert model.workspace_root is None


def test_provider_factory_claude_never_injects_anthropic_api_key() -> None:
    """ADR-002 §2: Factory must NOT inject ANTHROPIC_API_KEY for Claude.

    The factory reads the real settings. Regardless of what ANTHROPIC_API_KEY
    is set to in the environment, the factory must not place it in env_vars.
    ANTHROPIC_API_KEY is stripped at subprocess spawn time in _astream().
    """
    model = ProviderFactory.create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)
    assert "ANTHROPIC_API_KEY" not in model.env_vars


def test_provider_factory_claude_oauth_only() -> None:
    """When OAuth token is set, only CLAUDE_CODE_OAUTH_TOKEN is in env_vars."""
    model = ProviderFactory.create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)
    if model.env_vars.get("CLAUDE_CODE_OAUTH_TOKEN"):
        assert model.env_vars["CLAUDE_CODE_OAUTH_TOKEN"].strip()
    assert "ANTHROPIC_API_KEY" not in model.env_vars


def test_provider_factory_unsupported_provider() -> None:
    """Verify that nonsense providers raise ValueError with useful message."""
    with pytest.raises(ValueError, match="Unsupported provider: unknown"):
        ProviderFactory.create("unknown")  # type: ignore[arg-type]


@pytest.mark.live
@pytest.mark.asyncio
async def test_factory_claude_live() -> None:
    """Test Claude end-to-end via the ACP subprocess wrapper."""
    model = ProviderFactory.create(Provider.CLAUDE)
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
    model = ProviderFactory.create(Provider.GEMINI)
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
    model = ProviderFactory.create(Provider.OPENAI)
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
    model = ProviderFactory.create(Provider.ZHIPU)
    assert isinstance(model, ChatOpenAI)

    response = await model.ainvoke(
        [HumanMessage(content="Return the exact word 'Hello'.")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()
