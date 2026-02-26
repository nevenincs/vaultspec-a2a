import logging
import os
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from ..core.config import settings
from ..utils.enums import PROVIDER_DEFAULT_MODELS, Model, Provider

logger = logging.getLogger(__name__)


class ProviderFactory:
    """Factory for instantiating LangChain chat models for different providers."""

    @classmethod
    def create(
        cls, provider: Provider, model: "Model | str | None" = None, **kwargs: Any
    ) -> BaseChatModel:
        """Create a configured BaseChatModel for the given provider.

        Args:
            provider: The LLM provider (e.g., Provider.CLAUDE, Provider.GEMINI).
            model: Optional explicit model string or Model enum.
            kwargs: Additional overrides for the specific provider.

        Returns:
            A LangChain BaseChatModel implementation.
        """
        timeout = kwargs.pop("timeout", settings.provider_timeout_seconds)

        # Resolve model name
        if model is None:
            model_name = PROVIDER_DEFAULT_MODELS[provider].value
        elif isinstance(model, Model):
            model_name = model.value
        else:
            model_name = model

        logger.info(
            f"Instantiating ProviderFactory for provider={provider}, resolved_model={model_name}"
        )

        if provider == Provider.CLAUDE:
            api_key = (
                kwargs.pop("api_key", None)
                or os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
            )
            if api_key:
                kwargs["api_key"] = api_key
            return ChatAnthropic(
                model=model_name, timeout=timeout, max_retries=2, **kwargs
            )

        elif provider == Provider.GEMINI:
            api_key = (
                kwargs.pop("api_key", None)
                or os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
            )
            if api_key:
                kwargs["api_key"] = api_key
            return ChatGoogleGenerativeAI(
                model=model_name, timeout=timeout, max_retries=2, **kwargs
            )

        elif provider == Provider.ZHIPU:
            api_key = kwargs.pop("api_key", None) or os.environ.get("ZHIPU_API_KEY")
            if api_key:
                kwargs["api_key"] = api_key
            return ChatOpenAI(
                model=model_name,
                base_url="https://open.bigmodel.cn/api/paas/v4/",
                timeout=timeout,
                max_retries=2,
                **kwargs,
            )

        elif provider == Provider.OPENAI:
            api_key = kwargs.pop("api_key", None) or os.environ.get("OPENAI_API_KEY")
            if api_key:
                kwargs["api_key"] = api_key
            return ChatOpenAI(
                model=model_name, timeout=timeout, max_retries=2, **kwargs
            )

        else:
            logger.error(f"Failed to instantiate: Unsupported provider {provider}")
            raise ValueError(f"Unsupported provider: {provider}")
