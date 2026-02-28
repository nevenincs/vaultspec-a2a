"""Tests for the provider factory."""

import pytest

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from ...utils.enums import MODEL_MAP, Model, Provider
from ..acp_chat_model import AcpChatModel
from ..factory import ProviderFactory


def get_model_attr(model_obj: BaseChatModel) -> str | None:
    """Helper to get model name from different LangChain model classes."""
    return getattr(model_obj, "model", getattr(model_obj, "model_name", None))


def test_provider_factory_claude_creates_acp() -> None:
    """Verify Claude provider creates AcpChatModel with the correct ACP command."""
    model = ProviderFactory.create(Provider.CLAUDE)
    assert isinstance(model, AcpChatModel)
    assert model.command == ["claude-agent-acp"]


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
