"""LLM Provider factory."""

import logging

from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..core.config import settings
from ..core.exceptions import ConfigError
from ..core.team_config import AgentConfig
from ..utils.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Model, Provider
from .acp_chat_model import AcpChatModel


__all__ = ["ProviderFactory"]

logger = logging.getLogger(__name__)

# PROV-01: cache created model clients to avoid repeated instantiation.
_client_cache: dict[tuple, "BaseChatModel"] = {}

# Resolve the claude-agent-acp entry point from the project-level node_modules.
# src/vaultspec_a2a/providers/factory.py -> providers -> vaultspec_a2a -> src -> project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CLAUDE_ACP_JS = (
    _PROJECT_ROOT
    / "node_modules"
    / "@zed-industries"
    / "claude-agent-acp"
    / "dist"
    / "index.js"
)

# Resolve the precompiled Bun binary from the package-local bin/ directory.
# ADR-002 §5.1 mandates node backend as default; binary mode requires ADR amendment
# — experimental.
_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
_bin_candidates = list(_BIN_DIR.glob("claude-agent-acp*")) if _BIN_DIR.is_dir() else []
_BIN_PATH: Path | None = _bin_candidates[0] if _bin_candidates else None


def _build_acp_command(backend: str) -> list[str]:
    """Return the ACP gateway subprocess command for the given backend.

    Args:
        backend: ``"node"`` for the npm-installed JS entry point (default),
            ``"binary"`` for the precompiled Bun executable in bin/.

    Raises:
        ConfigError: If the resolved entry point does not exist.
    """
    if backend == "binary":
        if _BIN_PATH is None:
            raise ConfigError(
                f"ACP binary backend requested but no executable found in {_BIN_DIR}. "
                "Place a claude-agent-acp binary in src/vaultspec_a2a/bin/."
            )
        if not _BIN_PATH.exists():
            raise ConfigError(
                f"ACP binary not found at {_BIN_PATH}. "
                "Place a claude-agent-acp binary in src/vaultspec_a2a/bin/."
            )
        return [str(_BIN_PATH)]
    # default: "node"
    if not _CLAUDE_ACP_JS.exists():
        raise ConfigError(
            f"Claude ACP entry point not found: {_CLAUDE_ACP_JS}. "
            "Run 'npm install' to install @zed-industries/claude-agent-acp."
        )
    return ["node", str(_CLAUDE_ACP_JS)]


class ProviderFactory:
    """Factory for instantiating LangChain chat models for different providers."""

    @classmethod
    def create(
        cls,
        provider: Provider,
        model: "Model | str | None" = None,
        agent_config: AgentConfig | None = None,
        workspace_root: Path | None = None,
        **kwargs: Any,
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
        supported = {Provider.CLAUDE, Provider.GEMINI, Provider.MOCK, Provider.ZHIPU, Provider.OPENAI}
        if provider not in supported:
            logger.error("Failed to instantiate: Unsupported provider %s", provider)
            raise ValueError(f"Unsupported provider: {provider}")

        # Resolve model name
        if model is None:
            model_level = PROVIDER_DEFAULT_MODELS[provider]
            try:
                model_name = MODEL_MAP[provider][model_level]
            except KeyError:
                raise ValueError(
                    f"Unsupported model level {model_level!r} for provider {provider!r}"
                ) from None
        elif isinstance(model, Model):
            try:
                model_name = MODEL_MAP[provider][model]
            except KeyError:
                raise ValueError(
                    f"Unsupported model level {model!r} for provider {provider!r}"
                ) from None
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

        if provider == Provider.MOCK:
            from .mock_chat_model import MockChatModel  # noqa: PLC0415
            return MockChatModel(agent_config=agent_config)

        if provider == Provider.CLAUDE:
            oauth_token = settings.claude_code_oauth_token
            backend = settings.acp_backend
            logger.debug(
                "[%s] Instantiating ACP Wrapper. OAuth Token present: %s, backend=%s",
                provider,
                bool(oauth_token),
                backend,
            )

            command = _build_acp_command(backend)

            # ADR-002 §2: Only inject CLAUDE_CODE_OAUTH_TOKEN. ANTHROPIC_API_KEY
            # is explicitly stripped in _astream() to prevent pay-as-you-go billing
            # from overriding the OAuth subscription.
            env_vars: dict[str, str] = (
                {"CLAUDE_CODE_OAUTH_TOKEN": oauth_token}
                if oauth_token and oauth_token.strip()
                else {}
            )
            # Binary Bun executable requires this flag so acp-agent.ts can detect
            # it is running as a single-file Bun bundle (not via node + index.js).
            if backend == "binary":
                env_vars["CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN"] = "1"

            return AcpChatModel(
                command=command,
                env_vars=env_vars,
                agent_config=agent_config,
                workspace_root=str(workspace_root) if workspace_root else None,
                # Native PE32+ binary bypasses cmd.exe shim — use exec directly.
                use_exec=(backend == "binary"),
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

            cache_key = (provider, model_name)
            if cache_key in _client_cache:
                return _client_cache[cache_key]
            client = ChatOpenAI(**kwargs)
            _client_cache[cache_key] = client
            return client

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

            cache_key = (provider, model_name)
            if cache_key in _client_cache:
                return _client_cache[cache_key]
            client = ChatOpenAI(**kwargs)
            _client_cache[cache_key] = client
            return client

        logger.error("Failed to instantiate: Unsupported provider %s", provider)
        raise ValueError(f"Unsupported provider: {provider}")
