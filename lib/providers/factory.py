import os
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from ..core.config import settings
from ..utils.enums import Provider


class ProviderFactory:
    """Factory for instantiating LangChain chat models for different providers."""

    @classmethod
    def create(
        cls, provider: Provider, model_name: str | None = None, **kwargs: Any
    ) -> BaseChatModel:
        """Create a configured BaseChatModel for the given provider.

        Args:
            provider: The LLM provider (e.g., Provider.CLAUDE, Provider.GEMINI).
            model_name: Optional explicit model string.
            kwargs: Additional overrides for the specific provider.

        Returns:
            A LangChain BaseChatModel implementation.
        """
        timeout = kwargs.pop("timeout", settings.provider_timeout_seconds)

        if provider == Provider.CLAUDE:
            # Requires ANTHROPIC_API_KEY.
            default_model = "claude-3-7-sonnet-20250219"
            return ChatAnthropic(
                model=model_name or default_model,
                timeout=timeout,
                max_retries=2,
                **kwargs,
            )
        elif provider == Provider.GEMINI:
            # Requires GEMINI_API_KEY.
            default_model = "gemini-2.5-pro"
            return ChatGoogleGenerativeAI(
                model=model_name or default_model,
                timeout=timeout,
                max_retries=2,
                **kwargs,
            )
        elif provider == Provider.GLM5:
            # Requires ZHIPU_API_KEY. Maps through OpenAI compatibility.
            default_model = "glm-4-plus"
            # GLM-5 isn't technically out for general API yet, we map to 4 or "glm-5".
            return ChatOpenAI(
                model=model_name or default_model,
                base_url="https://open.bigmodel.cn/api/paas/v4/",
                api_key=os.environ.get("ZHIPU_API_KEY"),
                timeout=timeout,
                max_retries=2,
                **kwargs,
            )
        elif provider == Provider.CODEX:
            # Requires OPENAI_API_KEY.
            default_model = "gpt-4o"
            return ChatOpenAI(
                model=model_name or default_model,
                timeout=timeout,
                max_retries=2,
                **kwargs,
            )
        else:
            msg = f"Unsupported provider: {provider}"
            raise ValueError(msg)
