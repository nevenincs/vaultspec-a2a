import os

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from vaultspec_a2a.lib.providers.factory import ProviderFactory
from vaultspec_a2a.lib.utils.enums import Provider


@pytest.mark.asyncio
async def test_factory_invalid_provider():
    """Test factory raises ValueError on invalid provider."""
    with pytest.raises(ValueError, match="Unsupported provider"):
        ProviderFactory.create("invalid-provider")  # type: ignore


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
async def test_factory_claude_live():
    """Test Claude live integration."""
    model = ProviderFactory.create(Provider.CLAUDE)
    assert isinstance(model, BaseChatModel)

    # Live network call
    response = await model.ainvoke(
        [HumanMessage(content="Say exclusively the word 'Hello'")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set"
)
async def test_factory_gemini_live():
    """Test Gemini live integration."""
    model = ProviderFactory.create(Provider.GEMINI)
    assert isinstance(model, BaseChatModel)

    # Live network call
    response = await model.ainvoke(
        [HumanMessage(content="Say exclusively the word 'Hello'")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"
)
async def test_factory_codex_live():
    """Test Codex/OpenAI live integration."""
    model = ProviderFactory.create(Provider.CODEX)
    assert isinstance(model, BaseChatModel)

    # Live network call
    response = await model.ainvoke(
        [HumanMessage(content="Say exclusively the word 'Hello'")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("ZHIPU_API_KEY"), reason="ZHIPU_API_KEY not set")
async def test_factory_glm5_live():
    """Test GLM-5 live integration."""
    model = ProviderFactory.create(Provider.GLM5)
    assert isinstance(model, BaseChatModel)

    # Live network call
    response = await model.ainvoke(
        [HumanMessage(content="Say exclusively the word 'Hello'")]
    )
    assert response.content
    assert "hello" in str(response.content).lower()
