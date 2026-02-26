import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from ...utils.enums import PROVIDER_DEFAULT_MODELS, Model, Provider
from ..factory import ProviderFactory


def get_model_attr(model_obj):
    """Helper to get model name from different LangChain model classes."""
    return getattr(model_obj, "model", getattr(model_obj, "model_name", None))


def test_provider_factory_default_resolution():
    """Verify that factory resolves to centralized defaults when no model is provided."""
    model = ProviderFactory.create(Provider.CLAUDE)
    expected = PROVIDER_DEFAULT_MODELS[Provider.CLAUDE].value
    assert get_model_attr(model) == expected
    assert isinstance(model, ChatAnthropic)


def test_provider_factory_explicit_enum_model():
    """Verify that factory accepts Model enum members correctly."""
    model = ProviderFactory.create(Provider.GEMINI, model=Model.GEMINI_3_PRO)
    assert get_model_attr(model) == Model.GEMINI_3_PRO.value
    assert isinstance(model, ChatGoogleGenerativeAI)


def test_provider_factory_explicit_string_model():
    """Verify that factory still accepts string model names for flexibility."""
    custom_model = "experimental-model-2026"
    model = ProviderFactory.create(Provider.OPENAI, model=custom_model)
    assert get_model_attr(model) == custom_model
    assert isinstance(model, ChatOpenAI)


def test_provider_factory_zhipu_mapping():
    """Verify Zhipu AI (GLM) mapping to OpenAI-compatible ChatOpenAI."""
    model = ProviderFactory.create(Provider.ZHIPU)
    assert get_model_attr(model) == Model.GLM_5.value
    assert isinstance(model, ChatOpenAI)
    # Check OpenAI client configuration within the model
    assert "bigmodel.cn" in str(model.openai_api_base)


def test_provider_factory_unsupported_provider():
    """Verify that nonsense providers raise ValueError with useful message."""
    with pytest.raises(ValueError, match="Unsupported provider: unknown"):
        ProviderFactory.create("unknown")


# Live Integration Tests
# MOCKS ARE FORBIDDEN per project rules (GEMINI.md).
# Skipping logic has been removed. These tests mandate functional authentication
# fallbacks using environment variables like CLAUDE_CODE_OAUTH_TOKEN, etc.


@pytest.mark.asyncio
async def test_factory_claude_live():
    """Test Claude live integration with fallback auth mechanisms."""
    # Instantiation will throw error immediately if API keys or fallbacks
    # aren't populated.
    model = ProviderFactory.create(Provider.CLAUDE)
    assert isinstance(model, BaseChatModel)

    # Test network connectivity and response structure
    response = await model.ainvoke(
        [HumanMessage(content="Return the exact word 'Hello'.")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()


@pytest.mark.asyncio
async def test_factory_gemini_live():
    """Test Gemini live integration with fallback auth mechanisms."""
    model = ProviderFactory.create(Provider.GEMINI)
    assert isinstance(model, BaseChatModel)

    # Test network connectivity and response structure
    response = await model.ainvoke(
        [HumanMessage(content="Return the exact word 'Hello'.")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()


@pytest.mark.asyncio
async def test_factory_openai_live():
    """Test OpenAI live integration with fallback auth mechanisms."""
    model = ProviderFactory.create(Provider.OPENAI)
    assert isinstance(model, BaseChatModel)

    # Test network connectivity and response structure
    response = await model.ainvoke(
        [HumanMessage(content="Return the exact word 'Hello'.")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()


@pytest.mark.asyncio
async def test_factory_zhipu_live():
    """Test Zhipu GLM live integration via OpenAI compatibility."""
    model = ProviderFactory.create(Provider.ZHIPU)
    assert isinstance(model, BaseChatModel)

    # Test network connectivity and response structure
    response = await model.ainvoke(
        [HumanMessage(content="Return the exact word 'Hello'.")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()
