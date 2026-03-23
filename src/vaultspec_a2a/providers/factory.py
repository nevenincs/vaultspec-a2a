"""LLM Provider factory."""

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..control.config import settings
from ..team.team_config import AgentConfig
from ..thread.errors import ConfigError
from ..utils.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Model, Provider
from .acp_chat_model import AcpChatModel

__all__ = ["ProviderFactory"]

logger = logging.getLogger(__name__)

# Resolve the claude-agent-acp entry point from the project-level node_modules.
# VAULTSPEC_PROJECT_ROOT controls the base; see Settings.project_root.
_CLAUDE_ACP_JS = (
    settings.project_root
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


def _build_gemini_env(
    gemini_api_key: str | None = None,
    google_api_key: str | None = None,
    google_application_credentials: str | None = None,
    gemini_cli_home: str | None = None,
) -> dict[str, str]:
    """Return explicit Gemini auth env vars for the subprocess."""
    env_vars: dict[str, str] = {}
    has_noninteractive_auth = False
    if gemini_api_key and gemini_api_key.strip():
        env_vars["GEMINI_API_KEY"] = gemini_api_key
        has_noninteractive_auth = True
    if google_api_key and google_api_key.strip():
        env_vars["GOOGLE_API_KEY"] = google_api_key
        has_noninteractive_auth = True
    if google_application_credentials and google_application_credentials.strip():
        env_vars["GOOGLE_APPLICATION_CREDENTIALS"] = google_application_credentials
        has_noninteractive_auth = True
    if gemini_cli_home and gemini_cli_home.strip():
        env_vars["GEMINI_CLI_HOME"] = gemini_cli_home
        env_vars["HOME"] = gemini_cli_home
        if not has_noninteractive_auth:
            # Gemini CLI's ACP path selects personal OAuth non-interactively via
            # GOOGLE_GENAI_USE_GCA=true while reading credentials from the CLI home.
            env_vars["GOOGLE_GENAI_USE_GCA"] = "true"
    return env_vars


def _classify_gemini_command(
    model_name: str,
    *,
    executable: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return the Gemini CLI command plus bounded runtime metadata."""
    if executable is not None:
        return [
            executable,
            "--model",
            model_name,
            "--experimental-acp",
        ], {
            "runtime_authority": "explicit_executable",
            "command_origin": "explicit_executable",
            "command_kind": "gemini_cli",
            "command_executable": Path(executable).name,
            "command_target": executable,
        }

    docker_entry = Path("/usr/local/lib/node_modules/@google/gemini-cli/dist/index.js")
    if docker_entry.exists():
        return [
            "node",
            str(docker_entry),
            "--model",
            model_name,
            "--experimental-acp",
        ], {
            "runtime_authority": "docker_bundled",
            "command_origin": "docker_node_modules_entry",
            "command_kind": "node_entry",
            "command_executable": "node",
            "command_target": str(docker_entry),
        }

    local_entry = (
        settings.project_root
        / "node_modules"
        / "@google"
        / "gemini-cli"
        / "dist"
        / "index.js"
    )
    if local_entry.exists():
        return [
            "node",
            str(local_entry),
            "--model",
            model_name,
            "--experimental-acp",
        ], {
            "runtime_authority": "project_local",
            "command_origin": "project_node_modules_entry",
            "command_kind": "node_entry",
            "command_executable": "node",
            "command_target": str(local_entry),
        }

    system_gemini = shutil.which("gemini")
    if system_gemini:
        return [
            system_gemini,
            "--model",
            model_name,
            "--experimental-acp",
        ], {
            "runtime_authority": "system_cli",
            "command_origin": "system_path_executable",
            "command_kind": "gemini_cli",
            "command_executable": Path(system_gemini).name,
            "command_target": system_gemini,
        }

    local_bin = settings.project_root / "node_modules" / ".bin"
    candidate_name = "gemini.cmd" if os.name == "nt" else "gemini"
    local_gemini = local_bin / candidate_name
    if local_gemini.exists():
        return [
            str(local_gemini),
            "--model",
            model_name,
            "--experimental-acp",
        ], {
            "runtime_authority": "project_local",
            "command_origin": "project_local_bin",
            "command_kind": "gemini_cli",
            "command_executable": local_gemini.name,
            "command_target": str(local_gemini),
        }

    return [
        "gemini",
        "--model",
        model_name,
        "--experimental-acp",
    ], {
        "runtime_authority": "system_cli",
        "command_origin": "fallback_cli_name",
        "command_kind": "gemini_cli",
        "command_executable": "gemini",
        "command_target": "gemini",
    }


def _build_gemini_command(
    model_name: str,
    *,
    executable: str | None = None,
) -> list[str]:
    """Return the Gemini CLI ACP subprocess command."""
    command, _ = _classify_gemini_command(model_name, executable=executable)
    return command


def _classify_acp_command(backend: str) -> tuple[list[str], dict[str, str]]:
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
        return [str(_BIN_PATH)], {
            "runtime_authority": "package_bin",
            "command_origin": "package_bin",
            "command_kind": "bun_binary",
            "command_executable": _BIN_PATH.name,
            "command_target": str(_BIN_PATH),
            "acp_backend": "binary",
        }
    # default: "node"
    if not _CLAUDE_ACP_JS.exists():
        raise ConfigError(
            f"Claude ACP entry point not found: {_CLAUDE_ACP_JS}. "
            "Run 'npm install' to install @zed-industries/claude-agent-acp."
        )
    return ["node", str(_CLAUDE_ACP_JS)], {
        "runtime_authority": "project_local",
        "command_origin": "project_node_modules_entry",
        "command_kind": "node_entry",
        "command_executable": "node",
        "command_target": str(_CLAUDE_ACP_JS),
        "acp_backend": "node",
    }


def _build_acp_command(backend: str) -> list[str]:
    """Return the ACP gateway subprocess command for the given backend."""
    command, _ = _classify_acp_command(backend)
    return command


class ProviderFactory:
    """Factory for instantiating LangChain chat models for different providers."""

    @classmethod
    def create(
        cls,
        provider: Provider,
        model: "Model | str | None" = None,
        agent_config: AgentConfig | None = None,
        workspace_root: Path | None = None,
        backend: "str | None" = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Create a configured BaseChatModel for the given provider.

        Args:
            provider: The LLM provider (e.g., Provider.CLAUDE, Provider.GEMINI).
            model: Optional explicit model string or Model enum.
            agent_config: Optional agent configuration for provider initialization.
            workspace_root: Optional workspace root for ACP sandbox scoping.
            backend: ACP backend override (``"node"`` or ``"binary"``). When
                ``None`` the value from ``settings.acp_backend`` is used. Pass
                an explicit value to select a backend without mutating global
                settings (useful in tests and factory call sites that need
                non-default behaviour).
            kwargs: Additional overrides for the specific provider.

        Returns:
            A LangChain BaseChatModel implementation.
        """
        timeout = kwargs.pop("timeout", settings.provider_timeout_seconds)

        # Guard unsupported providers before model resolution to produce a clear error
        # (PROVIDER_DEFAULT_MODELS lookup raises KeyError for unknown providers).
        supported = {
            Provider.CLAUDE,
            Provider.GEMINI,
            Provider.MOCK,
            Provider.ZHIPU,
            Provider.OPENAI,
        }
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
            from .mock_chat_model import MockChatModel

            return MockChatModel(agent_config=agent_config)

        if provider == Provider.CLAUDE:
            oauth_token = settings.claude_code_oauth_token
            backend = backend if backend is not None else settings.acp_backend
            logger.debug(
                "[%s] Instantiating ACP Wrapper. OAuth Token present: %s, backend=%s",
                provider,
                bool(oauth_token),
                backend,
            )

            command, command_meta = _classify_acp_command(backend)

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
                provider=str(provider.value),
                runtime_authority=command_meta["runtime_authority"],
                command_origin=command_meta["command_origin"],
                command_kind=command_meta["command_kind"],
                command_executable=command_meta["command_executable"],
                command_target=command_meta["command_target"],
                acp_backend=command_meta["acp_backend"],
                auth_mode="oauth_token" if env_vars else "none_detected",
            )

        if provider == Provider.GEMINI:
            logger.debug(
                "[%s] Instantiating ACP Wrapper with model=%s.", provider, model_name
            )
            # Official Gemini CLI docs support non-interactive env auth
            # (`GEMINI_API_KEY`, `GOOGLE_API_KEY`) in addition to local OAuth.
            # The workspace env scrub removes secret keys by design, so the
            # provider layer must re-inject only the auth vars it intentionally
            # supports for the child subprocess.
            command, command_meta = _classify_gemini_command(model_name)
            env_vars = _build_gemini_env(
                gemini_api_key=settings.gemini_api_key,
                google_api_key=settings.google_api_key,
                google_application_credentials=settings.google_application_credentials,
                gemini_cli_home=settings.gemini_cli_home,
            )
            has_env_credentials = any(
                key in env_vars
                for key in (
                    "GEMINI_API_KEY",
                    "GOOGLE_API_KEY",
                    "GOOGLE_APPLICATION_CREDENTIALS",
                )
            )
            return AcpChatModel(
                command=command,
                env_vars=env_vars,
                agent_config=agent_config,
                workspace_root=str(workspace_root) if workspace_root else None,
                provider=str(provider.value),
                runtime_authority=command_meta["runtime_authority"],
                command_origin=command_meta["command_origin"],
                command_kind=command_meta["command_kind"],
                command_executable=command_meta["command_executable"],
                command_target=command_meta["command_target"],
                acp_backend="gemini-cli",
                auth_mode=(
                    "env_credentials"
                    if has_env_credentials
                    else "local_oauth_mount"
                    if "GEMINI_CLI_HOME" in env_vars
                    else "local_oauth_refresh"
                ),
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
