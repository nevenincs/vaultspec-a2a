"""LLM Provider factory."""

import logging

from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..core.config import settings
from ..core.team_config import AgentConfig
from ..utils.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Model, Provider
from .acp_chat_model import AcpChatModel


__all__ = ["ProviderFactory"]

logger = logging.getLogger(__name__)


class ProviderFactory:
    """Factory for instantiating LangChain chat models for different providers."""

    @classmethod
    def create(
        cls,
        provider: Provider,
        model: "Model | str | None" = None,
        agent_config: AgentConfig | None = None,
        workspace_root: Path | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> BaseChatModel:
        """Create a configured BaseChatModel for the given provider.

        Args:
            provider: The LLM provider (e.g., Provider.CLAUDE, Provider.GEMINI).
            model: Optional explicit model string or Model enum.
            agent_config: Optional agent configuration for provider initialization.
            workspace_root: Optional workspace root for ACP sandbox scoping.
            kwargs: Additional overrides for the specific provider.

        Returns:
            A LangChain BaseChatModel implementation.
        """
        timeout = kwargs.pop("timeout", settings.provider_timeout_seconds)

        # Guard unsupported providers before model resolution to produce a clear error
        # (PROVIDER_DEFAULT_MODELS lookup raises KeyError for unknown providers).
        supported = {Provider.CLAUDE, Provider.GEMINI, Provider.ZHIPU, Provider.OPENAI}
        if provider not in supported:
            logger.error("Failed to instantiate: Unsupported provider %s", provider)
            raise ValueError(f"Unsupported provider: {provider}")

        # Resolve model name
        if model is None:
            model_level = PROVIDER_DEFAULT_MODELS[provider]
            model_name = MODEL_MAP[provider][model_level]
        elif isinstance(model, Model):
            model_name = MODEL_MAP[provider][model]
        else:
            # M21: raw string model_name bypasses the MODEL_MAP validation that would
            # catch typos or unsupported models.  Log a warning so operators can see
            # when a non-canonical model string is in use.
            model_name = model
            logger.warning(
                "ProviderFactory received a raw model string %r for provider=%s. "
                "Prefer passing a Model enum value to ensure the name is valid.",
                model_name,
                provider,
            )

        logger.info(
            "Instantiating ProviderFactory for provider=%s, resolved_model=%s",
            provider,
            model_name,
        )

        if provider == Provider.CLAUDE:
            oauth_token = settings.claude_code_oauth_token
            logger.debug(
                "[%s] Instantiating ACP Wrapper. OAuth Token present: %s",
                provider,
                bool(oauth_token),
            )

            return AcpChatModel(
                command=["claude-agent-acp"],
                env_vars={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token}
                if oauth_token
                else {},
                agent_config=agent_config,
                workspace_root=str(workspace_root) if workspace_root else None,
            )

        if provider == Provider.GEMINI:
            logger.debug(
                "[%s] Instantiating ACP Wrapper with model=%s.", provider, model_name
            )
            # Bare command string — create_subprocess_shell resolves the CMD
            # shim natively via PATH (ADR-006 §5.1 point 1, TOAD reference).
            # Zero credential injection — Gemini CLI manages OAuth from
            # ~/.gemini/oauth_creds.json (ADR-002).
            return AcpChatModel(
                command=["gemini", "--model", model_name, "--experimental-acp"],
                env_vars={},
                agent_config=agent_config,
                workspace_root=str(workspace_root) if workspace_root else None,
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
                    "Failed to authenticate %s: Missing ZHIPU_API_KEY", provider
                )
                raise ValueError(f"Authentication required for {provider}")

            logger.debug(
                "[%s] Resolved authentication via: %s", provider, auth_resolved
            )
            kwargs["api_key"] = api_key
            kwargs["model"] = model_name
            kwargs["base_url"] = "https://open.bigmodel.cn/api/paas/v4/"
            kwargs["timeout"] = timeout
            kwargs["max_retries"] = 2

            return ChatOpenAI(**kwargs)

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
                    "Failed to authenticate %s: Missing OPENAI_API_KEY", provider
                )
                raise ValueError(f"Authentication required for {provider}")

            logger.debug(
                "[%s] Resolved authentication via: %s", provider, auth_resolved
            )
            kwargs["api_key"] = api_key
            kwargs["model"] = model_name
            kwargs["timeout"] = timeout
            kwargs["max_retries"] = 2

            return ChatOpenAI(**kwargs)

        logger.error("Failed to instantiate: Unsupported provider %s", provider)
        raise ValueError(f"Unsupported provider: {provider}")
