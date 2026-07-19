"""LLM Provider factory."""

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..control.config import settings
from ..graph.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Model, Provider
from ..team.team_config import AgentConfig
from ..thread.errors import ConfigError
from .acp_chat_model import AcpChatModel

__all__ = ["ProviderFactory", "classify_provider_command"]

logger = logging.getLogger(__name__)

# Resolve the claude-agent-acp entry point from the project-level node_modules.
# VAULTSPEC_PROJECT_ROOT controls the base; see Settings.project_root.
_CLAUDE_ACP_JS = (
    settings.project_root
    / "node_modules"
    / "@agentclientprotocol"
    / "claude-agent-acp"
    / "dist"
    / "index.js"
)

# Resolve the precompiled Bun binary from the package-local bin/ directory.
# Node backend is the default; binary mode requires an ADR amendment
# — experimental.
_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
_bin_candidates = list(_BIN_DIR.glob("claude-agent-acp*")) if _BIN_DIR.is_dir() else []
_BIN_PATH: Path | None = _bin_candidates[0] if _bin_candidates else None


class _CapsuleAssetsRootOmitted:
    """Marker for callers that delegate capsule-root selection to settings."""

    __slots__ = ()


_CAPSULE_ASSETS_ROOT_OMITTED = _CapsuleAssetsRootOmitted()
_CAPSULE_NODE_RELATIVE_PATH = (
    Path("node") / "node.exe" if os.name == "nt" else Path("node") / "bin" / "node"
)
_CAPSULE_ACP_RELATIVE_PATH = (
    Path("node_modules")
    / "@agentclientprotocol"
    / "claude-agent-acp"
    / "dist"
    / "index.js"
)


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


def _build_zai_env(
    zai_base_url: str | None = None,
    zai_auth_token: str | None = None,
) -> dict[str, str]:
    """Return explicit Z.ai auth env vars for the Claude ACP subprocess.

    Z.ai rides the Claude ACP path: the wrapper's
    Claude Code CLI honours ``ANTHROPIC_BASE_URL``/``ANTHROPIC_AUTH_TOKEN`` to
    retarget the Anthropic Messages API at Z.ai's compatible gateway. The base env
    is scrubbed of ``ANTHROPIC_API_KEY`` (workspace/environment.py) but leaves both
    of these names untouched, so the provider layer supplies them here. The token
    is a secret: it is placed in the returned dict but never logged.
    """
    env_vars: dict[str, str] = {}
    if not (zai_auth_token and zai_auth_token.strip()):
        return env_vars
    if zai_base_url and zai_base_url.strip():
        env_vars["ANTHROPIC_BASE_URL"] = zai_base_url
    env_vars["ANTHROPIC_AUTH_TOKEN"] = zai_auth_token
    return env_vars


def _build_kimi_env(
    kimi_api_key: str | None = None,
    kimi_base_url: str | None = None,
    kimi_model_name: str | None = None,
) -> dict[str, str]:
    """Return explicit Kimi auth/config env vars for the ``kimi acp`` subprocess.

    The Kimi CLI reads its NATIVE unprefixed names directly from the process
    environment (the Z.ai ``ANTHROPIC_*`` passthrough precedent): ``KIMI_API_KEY``
    authenticates, ``KIMI_BASE_URL`` retargets the Moonshot endpoint, and
    ``KIMI_MODEL_NAME`` selects the model. Only names with a value are injected;
    the key is a secret, placed in the returned dict but never logged.
    """
    env_vars: dict[str, str] = {}
    if kimi_api_key and kimi_api_key.strip():
        env_vars["KIMI_API_KEY"] = kimi_api_key
    if kimi_base_url and kimi_base_url.strip():
        env_vars["KIMI_BASE_URL"] = kimi_base_url
    if kimi_model_name and kimi_model_name.strip():
        env_vars["KIMI_MODEL_NAME"] = kimi_model_name
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


def _capsule_node_executable(capsule_assets_root: Path) -> Path:
    """Return the capsule-owned Node.js executable path for this platform.

    Node's official distribution layout places the executable at ``node/node.exe``
    on Windows and ``node/bin/node`` on POSIX. The desktop capsule carries that
    tree verbatim under its assets root.
    """
    return capsule_assets_root / _CAPSULE_NODE_RELATIVE_PATH


def _capsule_acp_entry(capsule_assets_root: Path) -> Path:
    """Return the capsule-owned Claude ACP entry point path.

    Mirrors the checkout ``node_modules`` layout so the same installed adapter
    resolves from capsule assets.
    """
    return capsule_assets_root / _CAPSULE_ACP_RELATIVE_PATH


def _canonical_capsule_assets_root(capsule_assets_root: Path) -> Path:
    """Return the absolute canonical directory that owns capsule assets."""
    try:
        requested_root = capsule_assets_root.expanduser()
        canonical_root = requested_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ConfigError(
            f"Desktop capsule assets root cannot be resolved: {capsule_assets_root}. "
            "Install or repair the desktop capsule before starting the provider."
        ) from exc
    if not canonical_root.is_dir():
        raise ConfigError(
            f"Desktop capsule assets root is not a directory: {canonical_root}. "
            "Install or repair the desktop capsule before starting the provider."
        )
    return canonical_root


def _resolve_capsule_asset(
    capsule_assets_root: Path,
    relative_path: Path,
    *,
    asset_name: str,
    repair_hint: str,
) -> Path:
    """Resolve one required file without allowing it to escape capsule ownership."""
    candidate = capsule_assets_root / relative_path
    try:
        canonical_asset = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Desktop capsule {asset_name} not found: {candidate}. "
            f"The capsule assets root {capsule_assets_root} must carry {repair_hint}."
        ) from exc
    except (OSError, RuntimeError) as exc:
        raise ConfigError(
            f"Desktop capsule {asset_name} cannot be resolved: {candidate}. "
            "Install or repair the desktop capsule before starting the provider."
        ) from exc

    if not canonical_asset.is_relative_to(capsule_assets_root):
        raise ConfigError(
            f"Desktop capsule {asset_name} escapes its assets root: {candidate} "
            f"resolves to {canonical_asset}, outside {capsule_assets_root}. "
            "Install or repair the desktop capsule before starting the provider."
        )
    if not canonical_asset.is_file():
        raise ConfigError(
            f"Desktop capsule {asset_name} is not a file: {canonical_asset}. "
            "Install or repair the desktop capsule before starting the provider."
        )
    return canonical_asset


def _classify_capsule_acp_command(
    capsule_assets_root: Path,
) -> tuple[list[str], dict[str, str]]:
    """Resolve the Node ACP command strictly from capsule-owned assets.

    The desktop capsule owns Node.js and the ACP adapter, so resolution never
    falls back to the checkout or to a PATH ``node``. A missing asset is a fatal
    configuration error naming the exact missing path.

    Raises:
        ConfigError: If the capsule Node executable or ACP entry is absent.
    """
    canonical_root = _canonical_capsule_assets_root(capsule_assets_root)
    node_executable = _resolve_capsule_asset(
        canonical_root,
        _CAPSULE_NODE_RELATIVE_PATH,
        asset_name="Node executable",
        repair_hint="the bundled Node.js runtime",
    )
    acp_entry = _resolve_capsule_asset(
        canonical_root,
        _CAPSULE_ACP_RELATIVE_PATH,
        asset_name="Claude ACP entry point",
        repair_hint="the bundled @agentclientprotocol/claude-agent-acp adapter",
    )
    return [str(node_executable), str(acp_entry)], {
        "runtime_authority": "capsule",
        "command_origin": "capsule",
        "command_kind": "node_entry",
        "command_executable": node_executable.name,
        "command_target": str(acp_entry),
        "acp_backend": "node",
    }


def _classify_acp_command(
    backend: str,
    *,
    capsule_assets_root: Path | None | _CapsuleAssetsRootOmitted = (
        _CAPSULE_ASSETS_ROOT_OMITTED
    ),
) -> tuple[list[str], dict[str, str]]:
    """Return the ACP gateway subprocess command for the given backend.

    Args:
        backend: ``"node"`` for the npm-installed JS entry point (default),
            ``"binary"`` for the precompiled Bun executable in bin/.
        capsule_assets_root: Explicit desktop capsule assets root. When omitted,
            the configured ``settings.capsule_assets_root`` is consulted. Explicit
            ``None`` forces Compose/project-local resolution even when a capsule
            root is configured. When a root is in force, the default Node backend
            resolves its executable and ACP entry ONLY from capsule assets — no
            checkout or PATH fallback. The experimental binary backend is already
            package-owned and is unaffected.

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
    root = (
        settings.capsule_assets_root
        if isinstance(capsule_assets_root, _CapsuleAssetsRootOmitted)
        else capsule_assets_root
    )
    if root is not None:
        return _classify_capsule_acp_command(root)
    if not _CLAUDE_ACP_JS.exists():
        raise ConfigError(
            f"Claude ACP entry point not found: {_CLAUDE_ACP_JS}. "
            "Run 'npm install' to install @agentclientprotocol/claude-agent-acp."
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


def _classify_codex_command() -> tuple[list[str], dict[str, str]]:
    """Return the ``codex app-server`` command plus bounded runtime metadata.

    Codex is a non-ACP JSON-RPC subprocess. Resolution prefers the codex
    executable on PATH; the bare-name ``fallback_cli_name`` origin (no resolved
    path) is what ``classify_provider_command`` treats as unresolvable, matching
    the Gemini classifier's convention.
    """
    system_codex = shutil.which("codex")
    if system_codex:
        return [system_codex, "app-server"], {
            "runtime_authority": "system_cli",
            "command_origin": "system_path_executable",
            "command_kind": "codex_cli",
            "command_executable": Path(system_codex).name,
            "command_target": system_codex,
        }
    return ["codex", "app-server"], {
        "runtime_authority": "system_cli",
        "command_origin": "fallback_cli_name",
        "command_kind": "codex_cli",
        "command_executable": "codex",
        "command_target": "codex",
    }


# Single recorded home for the Kimi CLI pin (a Python `uv tool install` axis,
# distinct from the Node package.json adapter pin). Surfaced in the install hint
# below, mirroring the _classify_acp_command "Run 'npm install' ..." pattern.
_KIMI_CLI_PIN = "1.49.0"
_KIMI_INSTALL_HINT = f"uv tool install kimi-cli=={_KIMI_CLI_PIN}"
# Per-run config isolation: the inline `--config` global flag REPLACES the
# operator's ~/.kimi/config.toml for this launch (kimi --help: "override ... set
# in config file"), so any ambient Kimi MCP the operator has configured is
# suppressed. An explicit empty mcpServers documents the intent. Auth rides the
# KIMI_API_KEY env and the harness rides session-injected mcpServers, both
# independent of this file, so nothing the run needs is lost. Inline text carries
# NO file, so there is no per-run temp file to create or clean up.
_KIMI_ISOLATION_CONFIG = '{"mcpServers": {}}'
# The Kimi CLI's Windows shell backend is Git Bash; it resolves bash.exe via the
# KIMI_CLI_GIT_BASH_PATH env override, then `git` on PATH, then standard install
# paths, and exits at startup if none resolve (kimi-cli 1.49.0 CHANGELOG). NOTE:
# grounding the installed source corrected the env name from the ADR's inferred
# "KIMI_SHELL_PATH" to the actual "KIMI_CLI_GIT_BASH_PATH".
_KIMI_GIT_BASH_ENV = "KIMI_CLI_GIT_BASH_PATH"


def _kimi_git_bash_resolvable() -> bool:
    """Return whether the Kimi CLI's required Git-Bash shell is resolvable.

    Mirrors the CLI's own resolution order so the readiness probe fails for the
    same reason the CLI would exit at startup: the ``KIMI_CLI_GIT_BASH_PATH``
    override (validated to exist), else ``git`` on PATH (Git for Windows ships
    bash.exe beside it), else a standard install path.
    """
    override = os.environ.get(_KIMI_GIT_BASH_ENV)
    if override and Path(override).exists():
        return True
    if shutil.which("git") is not None or shutil.which("bash") is not None:
        return True
    return Path(r"C:\Program Files\Git\bin\bash.exe").exists()


def _classify_kimi_command() -> tuple[list[str], dict[str, str]]:
    """Return the ``kimi acp`` command plus bounded runtime metadata.

    Kimi speaks ACP natively (``kimi acp`` is a stdio ACP server). Resolution
    prefers the ``kimi`` executable on PATH (the ``uv tool install`` shim at
    ``~/.local/bin/kimi``); the bare-name ``fallback_cli_name`` origin (no
    resolved path) is what ``classify_provider_command`` treats as unresolvable,
    matching the Codex/Gemini classifier convention.
    """
    system_kimi = shutil.which("kimi")
    if system_kimi:
        return [system_kimi, "acp"], {
            "runtime_authority": "system_cli",
            "command_origin": "system_path_executable",
            "command_kind": "kimi_cli",
            "command_executable": Path(system_kimi).name,
            "command_target": system_kimi,
        }
    return ["kimi", "acp"], {
        "runtime_authority": "system_cli",
        "command_origin": "fallback_cli_name",
        "command_kind": "kimi_cli",
        "command_executable": "kimi",
        "command_target": "kimi",
    }


def classify_provider_command(
    provider: Provider, *, backend: str | None = None
) -> dict[str, str]:
    """Resolve a subprocess provider's launch command without instantiating it.

    Returns the command metadata for a genuinely resolvable command and raises
    when it cannot be resolved. This is the no-instantiation seam the model-profile
    readiness probe consumes: ``_classify_acp_command`` raises when the Claude ACP
    entry point is missing, and the Gemini classifier's ``fallback_cli_name``
    origin (the only origin that does not correspond to a real resolved path) is
    treated here as unresolvable rather than a silent bare-name fallback.

    Raises:
        ValueError: The provider has no subprocess command, or the Gemini CLI is
            not resolvable on this host.
        ConfigError: The Claude ACP entry point/binary does not exist.
    """
    if provider in (Provider.CLAUDE, Provider.ZAI):
        # Z.ai launches the same claude-agent-acp wrapper as Claude; only the
        # injected auth env differs.
        resolved_backend = backend if backend is not None else settings.acp_backend
        _, meta = _classify_acp_command(resolved_backend)
        return meta
    if provider == Provider.GEMINI:
        default_model = MODEL_MAP[Provider.GEMINI][
            PROVIDER_DEFAULT_MODELS[Provider.GEMINI]
        ]
        _, meta = _classify_gemini_command(default_model)
        if meta.get("command_origin") == "fallback_cli_name":
            raise ValueError(
                "Gemini CLI not resolvable: not found in node_modules, the docker "
                "entry, or on PATH."
            )
        return meta
    if provider == Provider.CODEX:
        _, meta = _classify_codex_command()
        if meta.get("command_origin") == "fallback_cli_name":
            raise ValueError("Codex CLI not resolvable: 'codex' not found on PATH.")
        return meta
    if provider == Provider.KIMI:
        _, meta = _classify_kimi_command()
        if meta.get("command_origin") == "fallback_cli_name":
            raise ValueError(
                f"Kimi CLI not resolvable: 'kimi' not found on PATH. "
                f"Install with '{_KIMI_INSTALL_HINT}'."
            )
        if not _kimi_git_bash_resolvable():
            raise ValueError(
                "Kimi CLI prerequisite missing: Git for Windows (Git Bash) is "
                "required as the CLI's shell. Install Git for Windows, or set "
                f"{_KIMI_GIT_BASH_ENV} to your bash.exe."
            )
        return meta
    raise ValueError(f"provider {provider.value} has no subprocess command to classify")


class ProviderFactory:
    """Factory for instantiating LangChain chat models for different providers."""

    def create(
        self,
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
            Provider.CODEX,
            Provider.DETERMINISTIC,
            Provider.GEMINI,
            Provider.KIMI,
            Provider.MOCK,
            Provider.ZAI,
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

        if provider == Provider.DETERMINISTIC:
            from .deterministic_chat_model import DeterministicResearchAdrChatModel

            # In-process, role-keyed content; no network, no model resolution. Any
            # feature_tag/topic overrides ride in kwargs from the harness.
            det_kwargs = {
                key: kwargs[key] for key in ("feature_tag", "topic") if key in kwargs
            }
            return DeterministicResearchAdrChatModel(
                agent_config=agent_config, **det_kwargs
            )

        if provider == Provider.CODEX:
            from .codex_chat_model import CodexChatModel

            command, command_meta = _classify_codex_command()
            # Codex auth is file-based (persisted local session in the Codex home);
            # no secret env is injected. A raw model string bypasses MODEL_MAP, so
            # pass the resolved name through; None falls back to the account default.
            return CodexChatModel(
                command=command,
                model_name=model_name,
                agent_config=agent_config,
                workspace_root=str(workspace_root) if workspace_root else None,
                codex_home=settings.codex_home,
                timeout=float(timeout),
                provider=str(provider.value),
                runtime_authority=command_meta["runtime_authority"],
                command_origin=command_meta["command_origin"],
                command_kind=command_meta["command_kind"],
                command_executable=command_meta["command_executable"],
                command_target=command_meta["command_target"],
            )

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

            # Only inject CLAUDE_CODE_OAUTH_TOKEN. ANTHROPIC_API_KEY
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

        if provider == Provider.ZAI:
            # Z.ai is a config variant of the Claude ACP path: same wrapper
            # command, Anthropic base URL + auth token injected instead of the
            # Claude OAuth token. ENABLE_TOOL_SEARCH
            # and the other Claude-CLI behaviours in AcpChatModel._astream are
            # inherited unchanged.
            backend = backend if backend is not None else settings.acp_backend
            auth_token = settings.zai_auth_token
            logger.debug(
                "[%s] Instantiating ACP Wrapper. Auth token present: %s, backend=%s",
                provider,
                bool(auth_token and auth_token.strip()),
                backend,
            )

            command, command_meta = _classify_acp_command(backend)

            env_vars = _build_zai_env(
                zai_base_url=settings.zai_base_url,
                zai_auth_token=auth_token,
            )
            if backend == "binary":
                env_vars["CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN"] = "1"

            return AcpChatModel(
                command=command,
                env_vars=env_vars,
                agent_config=agent_config,
                workspace_root=str(workspace_root) if workspace_root else None,
                use_exec=(backend == "binary"),
                provider=str(provider.value),
                runtime_authority=command_meta["runtime_authority"],
                command_origin=command_meta["command_origin"],
                command_kind=command_meta["command_kind"],
                command_executable=command_meta["command_executable"],
                command_target=command_meta["command_target"],
                acp_backend=command_meta["acp_backend"],
                auth_mode=(
                    "zai_auth_token"
                    if "ANTHROPIC_AUTH_TOKEN" in env_vars
                    else "none_detected"
                ),
            )

        if provider == Provider.KIMI:
            # Kimi (Moonshot AI) drives its own `kimi acp` ACP agent, not the
            # claude-agent-acp wrapper. It honors session-injected mcpServers, so
            # its harness composition rides the existing with_mcp_servers ACP
            # branch unchanged; the only conditioning is the backend family
            # discriminator (acp_family="kimi"), which makes _acp_session OMIT the
            # Claude-only allowedTools _meta while the terminal-auth handshake
            # stays unconditional. Read-only discipline is enforced at the
            # permission-RPC handler, not via a config allowlist (Kimi has none).
            #
            # Per-run isolation: inject the inline `--config` global flag before
            # the `acp` subcommand so this launch loads ONLY the run's config,
            # excluding the operator's ~/.kimi/config.toml and thereby suppressing
            # any ambient Kimi MCP (the same per-run-config isolation as the Codex
            # CODEX_HOME and the Claude isolated home).
            base_command, command_meta = _classify_kimi_command()
            command = [
                base_command[0],
                "--config",
                _KIMI_ISOLATION_CONFIG,
                *base_command[1:],
            ]
            api_key = (
                settings.kimi_api_key.get_secret_value()
                if settings.kimi_api_key
                else None
            )
            env_vars = _build_kimi_env(
                kimi_api_key=api_key,
                kimi_base_url=settings.kimi_base_url,
                kimi_model_name=settings.kimi_model_name or model_name,
            )
            logger.debug(
                "[%s] Instantiating Kimi ACP agent. API key present: %s",
                provider,
                "KIMI_API_KEY" in env_vars,
            )

            return AcpChatModel(
                command=command,
                env_vars=env_vars,
                agent_config=agent_config,
                workspace_root=str(workspace_root) if workspace_root else None,
                provider=str(provider.value),
                acp_family="kimi",
                runtime_authority=command_meta["runtime_authority"],
                command_origin=command_meta["command_origin"],
                command_kind=command_meta["command_kind"],
                command_executable=command_meta["command_executable"],
                command_target=command_meta["command_target"],
                acp_backend="kimi_cli",
                auth_mode=(
                    "kimi_api_key" if "KIMI_API_KEY" in env_vars else "none_detected"
                ),
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
