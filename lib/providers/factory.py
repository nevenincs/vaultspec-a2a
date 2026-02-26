"""LLM Provider factory"""

import logging

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..core.config import settings
from ..utils.enums import PROVIDER_DEFAULT_MODELS, Model, Provider
from .acp_chat_model import AcpChatModel


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

        # Guard unsupported providers before model resolution to produce a clear error
        # (PROVIDER_DEFAULT_MODELS lookup raises KeyError for unknown providers).
        supported = {Provider.CLAUDE, Provider.GEMINI, Provider.ZHIPU, Provider.OPENAI}
        if provider not in supported:
            logger.error(f"Failed to instantiate: Unsupported provider {provider}")
            raise ValueError(f"Unsupported provider: {provider}")

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
            oauth_token = settings.claude_code_oauth_token
            logger.debug(
                f"[{provider}] Instantiating ACP Wrapper. OAuth Token present: {bool(oauth_token)}"
            )

            return AcpChatModel(
                command=["claude-agent-acp"],
                env_vars={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token}
                if oauth_token
                else {},
            )

        if provider == Provider.GEMINI:
            logger.debug(f"[{provider}] Instantiating ACP Wrapper with model={model_name}.")
            # Bare command string — create_subprocess_shell resolves the CMD
            # shim natively via PATH (ADR-006 §5.1 point 1, TOAD reference).
            # Zero credential injection — Gemini CLI manages OAuth from
            # ~/.gemini/oauth_creds.json (ADR-002).
            return AcpChatModel(
                command=["gemini", "--model", model_name, "--experimental-acp"],
                env_vars={},
            )

        if provider == Provider.ZHIPU:
            auth_resolved = (
                "kwargs"
                if "api_key" in kwargs
                else "ZHIPU_API_KEY"
                if settings.zhipu_api_key
                else None
            )
            api_key = kwargs.pop("api_key", None) or settings.zhipu_api_key

            if not api_key:
                logger.error(
                    f"Failed to authenticate {provider}: Missing ZHIPU_API_KEY"
                )
                raise ValueError(f"Authentication required for {provider}")

            logger.debug(f"[{provider}] Resolved authentication via: {auth_resolved}")
            kwargs["api_key"] = api_key

            return ChatOpenAI(
                model=model_name,
                base_url="https://open.bigmodel.cn/api/paas/v4/",
                timeout=timeout,
                max_retries=2,
                **kwargs,
            )

        if provider == Provider.OPENAI:
            auth_resolved = (
                "kwargs"
                if "api_key" in kwargs
                else "OPENAI_API_KEY"
                if settings.openai_api_key
                else None
            )
            api_key = kwargs.pop("api_key", None) or settings.openai_api_key

            if not api_key:
                logger.error(
                    f"Failed to authenticate {provider}: Missing OPENAI_API_KEY"
                )
                raise ValueError(f"Authentication required for {provider}")

            logger.debug(f"[{provider}] Resolved authentication via: {auth_resolved}")
            kwargs["api_key"] = api_key

            return ChatOpenAI(
                model=model_name, timeout=timeout, max_retries=2, **kwargs
            )

        logger.error(f"Failed to instantiate: Unsupported provider {provider}")
        raise ValueError(f"Unsupported provider: {provider}")
