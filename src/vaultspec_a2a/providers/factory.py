"""LLM Provider factory.

The LangChain model classes are imported lazily, not at module scope. Importing
``langchain_openai`` costs roughly twenty-five seconds in this environment, and
this module's classification and readiness helpers - which several callers reach
for WITHOUT ever constructing a model - had to pay that before answering. The
chat-model classes are now imported where a model is actually built, so probing
which provider a command resolves to no longer loads a model stack to answer.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain_core.language_models import BaseChatModel

    from ..team.team_config import AgentConfig

from ..artifacts import ArtifactDeclaration, RetentionDisposition
from ..control.config import settings
from ..graph.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Model, Provider
from ..thread.errors import ConfigError
from ..workspace.environment import resolve_env_vars
from .acp_catalog import discover_acp_catalog
from .antigravity_catalog import discover_antigravity_catalog
from .antigravity_cli import resolve_antigravity_command
from .codex_catalog import discover_codex_catalog
from .in_process_catalog import (
    IN_PROCESS_EXECUTION_MODES,
    discover_in_process_catalog,
    in_process_lane_serving_armed,
    served_in_process_lanes,
)
from .kimi_catalog import discover_kimi_catalog
from .openai_catalog import discover_openai_compatible_catalog
from .provider_catalog import (
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    HealthState,
    ProviderCatalog,
    ProviderCatalogKey,
)

__all__ = [
    "ANTIGRAVITY_CLI_STATE_DECLARATION",
    "ARTIFACT_DECLARATIONS",
    "GEMINI_SESSION_STORE_DECLARATION",
    "KIMI_SESSION_STORE_DECLARATION",
    "ProviderCatalogDiscovery",
    "ProviderCatalogRegistration",
    "ProviderFactory",
    "classify_provider_command",
    "kimi_temporary_model_configuration_reason",
]

logger = logging.getLogger(__name__)


# Gemini and Kimi keep their own project-partitioned session stores, in homes
# THIS module decides (``_build_gemini_env`` seats GEMINI_CLI_HOME,
# ``_build_kimi_env`` seats KIMI_CODE_HOME) and reached by CLIs THIS module
# spawns. Neither store sits under the sweep root in ``_config_home_roots`` nor
# matches its prefixes, so no reaper here has ever seen them.
#
# The dominant producer is not a run - it is ``catalog_registrations`` below.
# Every external lane gets a registration whose discovery spawns the real CLI
# rooted at the caller's workspace, so ONE catalog read spawns Gemini and Kimi
# against that directory even when the caller wants neither. Each family's store
# then keys the directory its own way, which is why one declaration cannot cover
# them and why reclamation is unavailable on both (see each mechanism).
GEMINI_SESSION_STORE_DECLARATION = ArtifactDeclaration(
    name="gemini-cli-session-store",
    root="<GEMINI_CLI_HOME, else operator ~/.gemini>/<project-partitioned tree>/",
    owner="providers.factory",
    disposition=RetentionDisposition.PERMANENT,
    reason=(
        "permanence is what this project can honestly promise rather than what "
        "it would choose: the store belongs to the operator's Gemini CLI and "
        "holds their own interactive sessions alongside anything a spawn here "
        "produced. The key is the workspace directory's BASENAME with "
        "underscores sanitized, which is far more collision-prone than a full "
        "path - an operator's own directory sharing a basename with a discarded "
        "temporary one is not merely hard to tell apart, it is the SAME entry. "
        "No reclaim predicate can be built on a key that ambiguous"
    ),
    mechanism=(
        "NOTHING bounds it. No sweep here reaches the home, no age gate applies, "
        "and no equivalent of the Claude CLI's cleanupPeriodDays has been "
        "verified for this lane, so growth is one entry per distinct workspace "
        "basename ever discovered against, retained until an operator deletes it "
        "by hand. Suppression, not reclamation, is the lever: spawning fewer "
        "lanes at discovery would stop most entries being minted at all"
    ),
)

ANTIGRAVITY_CLI_STATE_DECLARATION = ArtifactDeclaration(
    name="antigravity-cli-state",
    root="<ANTIGRAVITY_CLI_HOME, else operator ~/.gemini/antigravity-cli>/",
    owner="providers.factory",
    disposition=RetentionDisposition.PERMANENT,
    reason=(
        "the home belongs to the operator's Antigravity CLI and holds their own "
        "interactive state - a conversation-summary database, an onboarding "
        "cache - beside anything a spawn here produced, so nothing in it can be "
        "reclaimed without deleting work this project never created. What makes "
        "this lane WORSE than the Gemini and Kimi stores is the key: those mint "
        "one entry per distinct workspace, so a repeated discovery against the "
        "same directory reuses an entry, while this CLI writes a fresh "
        "TIMESTAMPED log per INVOCATION. Catalog discovery is an invocation, so "
        "growth here tracks how often the catalog is read rather than how many "
        "projects exist, and nothing in the name identifies the read that "
        "produced it"
    ),
    mechanism=(
        "NOTHING bounds it. Each run appends `log/cli-<timestamp>.log`, and a "
        "failed run additionally leaves `crashes/crash_<pid>_<uuid>.log`; a bare "
        "`agy models` was observed writing both while still exiting zero. "
        "Measured on one developer host: 80 log files totalling 82 MB. No sweep "
        "here reaches the home and no age gate applies, so an operator deletes "
        "it by hand. Suppression is the lever, as on the other CLI lanes: "
        "spawning fewer discoveries mints fewer entries"
    ),
)

KIMI_SESSION_STORE_DECLARATION = ArtifactDeclaration(
    name="kimi-code-session-store",
    root="<KIMI_CODE_HOME, else operator ~/.kimi-code>/<per-workspace partition>/",
    owner="providers.factory",
    disposition=RetentionDisposition.PERMANENT,
    reason=(
        "the store is the operator's, and on this lane orphanhood cannot even be "
        "ESTABLISHED: the partition key is a one-way truncated digest of the "
        "full working-directory path, so a key cannot be decoded back into the "
        "directory it names and no reader here can ask whether that directory "
        "still exists. A reclaim predicate needs a question this key cannot "
        "answer, which is the strongest form of the argument that declaring, "
        "not reaping, is the only mechanism that covers every lane"
    ),
    mechanism=(
        "NOTHING bounds it, and nothing here can: see the reason above. Measured "
        "volume is currently negligible - a single certification window - but "
        "that is a fact about how rarely the lane is exercised, not a bound"
    ),
)

ARTIFACT_DECLARATIONS: tuple[ArtifactDeclaration, ...] = (
    ANTIGRAVITY_CLI_STATE_DECLARATION,
    GEMINI_SESSION_STORE_DECLARATION,
    KIMI_SESSION_STORE_DECLARATION,
)

# Resolve the claude-agent-acp entry point from the project-level node_modules.
# VAULTSPEC_PROJECT_ROOT controls the base; see Settings.project_root.
# project_root resolves THIS SERVICE's own installed assets here, never a place
# to put data and never a directory an agent runs in - the two roles the
# storage-anchor gate exists to separate.
_CLAUDE_ACP_JS = (
    settings.project_root  # storage-anchor-ok
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
    kimi_temporary_model_name: str | None = None,
    kimi_code_home: str | None = None,
    kimi_temporary_model_max_context_size: int | None = None,
    kimi_temporary_model_capabilities: str | None = None,
) -> dict[str, str]:
    """Return the explicit Kimi Code home and temporary-provider definition.

    Kimi Code 0.28.1 treats ``KIMI_MODEL_*`` as one temporary provider, not as
    independent launch overrides. The tuple is injected only when complete;
    exact configured-alias selection is a separate ``-m`` argument.
    """
    reason = kimi_temporary_model_configuration_reason(
        kimi_api_key=kimi_api_key,
        kimi_base_url=kimi_base_url,
        kimi_temporary_model_name=kimi_temporary_model_name,
        kimi_temporary_model_max_context_size=kimi_temporary_model_max_context_size,
        kimi_temporary_model_capabilities=kimi_temporary_model_capabilities,
    )
    if reason is not None:
        raise ValueError(reason)
    env_vars: dict[str, str] = {}
    if kimi_code_home and kimi_code_home.strip():
        env_vars["KIMI_CODE_HOME"] = kimi_code_home.strip()
    if kimi_api_key and kimi_base_url and kimi_temporary_model_name:
        env_vars["KIMI_MODEL_API_KEY"] = kimi_api_key.strip()
        env_vars["KIMI_MODEL_BASE_URL"] = kimi_base_url.strip()
        env_vars["KIMI_MODEL_NAME"] = kimi_temporary_model_name.strip()
        if kimi_temporary_model_max_context_size is not None:
            env_vars["KIMI_MODEL_MAX_CONTEXT_SIZE"] = str(
                kimi_temporary_model_max_context_size
            )
        if kimi_temporary_model_capabilities:
            env_vars["KIMI_MODEL_CAPABILITIES"] = (
                kimi_temporary_model_capabilities.strip()
            )
    return env_vars


def kimi_temporary_model_configuration_reason(
    *,
    kimi_api_key: str | None,
    kimi_base_url: str | None,
    kimi_temporary_model_name: str | None,
    kimi_temporary_model_max_context_size: int | None = None,
    kimi_temporary_model_capabilities: str | None = None,
) -> str | None:
    """Return a static reason when a temporary Kimi definition is partial."""
    values = (kimi_api_key, kimi_base_url, kimi_temporary_model_name)
    present = tuple(bool(value and value.strip()) for value in values)
    optional_present = kimi_temporary_model_max_context_size is not None or bool(
        kimi_temporary_model_capabilities and kimi_temporary_model_capabilities.strip()
    )
    if (not any(present) and not optional_present) or all(present):
        return None
    return (
        "incomplete Kimi temporary model definition; set KIMI_MODEL_NAME, "
        "KIMI_MODEL_API_KEY, and KIMI_MODEL_BASE_URL together"
    )


def _classify_gemini_command(
    model_name: str | None,
    *,
    executable: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return the Gemini CLI command plus bounded runtime metadata."""
    if executable is not None:
        command = [executable]
        if model_name is not None:
            command.extend(("--model", model_name))
        command.append("--acp")
        return command, {
            "runtime_authority": "explicit_executable",
            "command_origin": "explicit_executable",
            "command_kind": "gemini_cli",
            "command_executable": Path(executable).name,
            "command_target": executable,
        }

    docker_entry = Path("/usr/local/lib/node_modules/@google/gemini-cli/dist/index.js")
    if docker_entry.exists():
        command = ["node", str(docker_entry)]
        if model_name is not None:
            command.extend(("--model", model_name))
        command.append("--acp")
        return command, {
            "runtime_authority": "docker_bundled",
            "command_origin": "docker_node_modules_entry",
            "command_kind": "node_entry",
            "command_executable": "node",
            "command_target": str(docker_entry),
        }

    local_entry = (
        settings.project_root  # storage-anchor-ok
        / "node_modules"
        / "@google"
        / "gemini-cli"
        / "dist"
        / "index.js"
    )
    if local_entry.exists():
        command = ["node", str(local_entry)]
        if model_name is not None:
            command.extend(("--model", model_name))
        command.append("--acp")
        return command, {
            "runtime_authority": "project_local",
            "command_origin": "project_node_modules_entry",
            "command_kind": "node_entry",
            "command_executable": "node",
            "command_target": str(local_entry),
        }

    system_gemini = shutil.which("gemini")
    if system_gemini:
        command = [system_gemini]
        if model_name is not None:
            command.extend(("--model", model_name))
        command.append("--acp")
        return command, {
            "runtime_authority": "system_cli",
            "command_origin": "system_path_executable",
            "command_kind": "gemini_cli",
            "command_executable": Path(system_gemini).name,
            "command_target": system_gemini,
        }

    local_bin = settings.project_root / "node_modules" / ".bin"  # storage-anchor-ok
    candidate_name = "gemini.cmd" if os.name == "nt" else "gemini"
    local_gemini = local_bin / candidate_name
    if local_gemini.exists():
        command = [str(local_gemini)]
        if model_name is not None:
            command.extend(("--model", model_name))
        command.append("--acp")
        return command, {
            "runtime_authority": "project_local",
            "command_origin": "project_local_bin",
            "command_kind": "gemini_cli",
            "command_executable": local_gemini.name,
            "command_target": str(local_gemini),
        }

    command = ["gemini"]
    if model_name is not None:
        command.extend(("--model", model_name))
    command.append("--acp")
    return command, {
        "runtime_authority": "system_cli",
        "command_origin": "fallback_cli_name",
        "command_kind": "gemini_cli",
        "command_executable": "gemini",
        "command_target": "gemini",
    }


def capsule_node_executable(capsule_assets_root: Path) -> Path:
    """Return the capsule-owned Node.js executable path for this platform.

    Node's official distribution layout places the executable at ``node/node.exe``
    on Windows and ``node/bin/node`` on POSIX. The desktop capsule carries that
    tree verbatim under its assets root.
    """
    return capsule_assets_root / _CAPSULE_NODE_RELATIVE_PATH


def capsule_acp_entry(capsule_assets_root: Path) -> Path:
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
    capsule_assets_root: Path | _CapsuleAssetsRootOmitted | None = (
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


def _classify_kimi_command() -> tuple[list[str], dict[str, str]]:
    """Return the ``kimi acp`` command plus bounded runtime metadata.

    Kimi speaks ACP natively (``kimi acp`` is a stdio ACP server). Resolution
    prefers the installed Kimi Code executable on PATH. The bare-name
    ``fallback_cli_name`` origin is treated as unresolvable by readiness and
    catalog registration.
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
        # Catalog/readiness classification must not preselect a static model.
        _, meta = _classify_gemini_command(None)
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
            raise ValueError("Kimi Code CLI not resolvable: 'kimi' not found on PATH.")
        return meta
    raise ValueError(f"provider {provider.value} has no subprocess command to classify")


_SUPPORTED_PROVIDERS: frozenset[Provider] = frozenset(
    {
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
)


@dataclass(frozen=True, slots=True)
class ProviderCatalogDiscovery:
    """One adapter result normalized at the factory registration boundary."""

    catalog: ProviderCatalog
    authentication: AuthenticationState
    configured: HealthState = HealthState.UNKNOWN
    transport: HealthState = HealthState.UNKNOWN


@dataclass(frozen=True, slots=True)
class ProviderCatalogRegistration:
    """A single execution-mode-specific catalog discovery callback."""

    key: ProviderCatalogKey
    discover: Callable[[], Awaitable[ProviderCatalogDiscovery]]


def _unavailable_catalog_discovery(
    key: ProviderCatalogKey,
    *,
    reason: str,
    authentication: AuthenticationState = AuthenticationState.UNKNOWN,
    configured: HealthState = HealthState.UNKNOWN,
    transport: HealthState = HealthState.UNKNOWN,
) -> ProviderCatalogDiscovery:
    return ProviderCatalogDiscovery(
        catalog=ProviderCatalog(
            key=key,
            state=CatalogState(
                status=CatalogStatus.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                reason=reason,
            ),
            models=(),
        ),
        authentication=authentication,
        configured=configured,
        transport=transport,
    )


def _transport_evidence(discovery: ProviderCatalogDiscovery) -> HealthState:
    """Return transport evidence only when discovery observed a provider response."""
    if discovery.catalog.state.status in {
        CatalogStatus.AVAILABLE,
        CatalogStatus.STALE,
    } or discovery.authentication in {
        AuthenticationState.AUTHENTICATED,
        AuthenticationState.UNAUTHENTICATED,
    }:
        return HealthState.AVAILABLE
    return HealthState.UNKNOWN


async def _discover_claude_catalog(
    key: ProviderCatalogKey, workspace_root: Path
) -> ProviderCatalogDiscovery:
    try:
        command, metadata = _classify_acp_command(settings.acp_backend)
    except (ConfigError, ValueError):
        return _unavailable_catalog_discovery(
            key,
            reason="provider catalog command is unavailable",
            transport=HealthState.UNAVAILABLE,
        )
    env = resolve_env_vars(workspace_root)
    use_exec = metadata["acp_backend"] == "binary"
    if use_exec:
        env["CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN"] = "1"
    discovered = await discover_acp_catalog(
        tuple(command),
        env=env,
        cwd=str(workspace_root),
        key=key,
        use_exec=use_exec,
        metadata={"provider": Provider.CLAUDE.value, **metadata},
    )
    normalized = ProviderCatalogDiscovery(discovered.catalog, discovered.authentication)
    return replace(normalized, transport=_transport_evidence(normalized))


async def _discover_codex_catalog(
    key: ProviderCatalogKey, workspace_root: Path
) -> ProviderCatalogDiscovery:
    try:
        command, _ = _classify_codex_command()
        if command[0] == "codex":
            raise ValueError("Codex CLI is not resolvable")
    except ValueError:
        return _unavailable_catalog_discovery(
            key,
            reason="provider catalog command is unavailable",
            transport=HealthState.UNAVAILABLE,
        )
    env = resolve_env_vars(workspace_root)
    if settings.codex_home:
        env["CODEX_HOME"] = settings.codex_home
    discovered = await discover_codex_catalog(
        tuple(command),
        env=env,
        cwd=str(workspace_root),
        key=key,
    )
    normalized = ProviderCatalogDiscovery(discovered.catalog, discovered.authentication)
    return replace(normalized, transport=_transport_evidence(normalized))


async def _discover_antigravity_catalog(
    key: ProviderCatalogKey, workspace_root: Path
) -> ProviderCatalogDiscovery:
    """Normalize the Antigravity listing into a registration-boundary result.

    Transport health follows the catalog: this lane's only surface IS the CLI
    invocation, so a listing that came back is a reachable transport and one
    that did not is an unreachable one. There is no separate handshake to
    distinguish the two.
    """
    catalog, authentication = await discover_antigravity_catalog(
        key,
        workspace_root,
        cli_path=settings.antigravity_cli_path,
        home=settings.antigravity_cli_home,
    )
    available = catalog.state.status is CatalogStatus.AVAILABLE
    return ProviderCatalogDiscovery(
        catalog=catalog,
        authentication=authentication,
        configured=(
            HealthState.AVAILABLE
            if resolve_antigravity_command(
                cli_path=settings.antigravity_cli_path,
                home=settings.antigravity_cli_home,
            )
            is not None
            else HealthState.UNAVAILABLE
        ),
        transport=HealthState.AVAILABLE if available else HealthState.UNAVAILABLE,
    )


async def _discover_gemini_catalog(
    key: ProviderCatalogKey, workspace_root: Path
) -> ProviderCatalogDiscovery:
    """Discover the Gemini CLI catalog.

    LEGACY LANE. Still supported and still served - existing configurations keep
    working and nothing here is being removed - but it is no longer where new
    work goes: the Antigravity lane is the forward coding-CLI surface, and it is
    a separate lane rather than a successor because its catalog spans vendors.

    Legacy is a maintenance posture, not a new mechanism: the lane's turn
    admission is unchanged, which is to say it has none. Gemini is absent from
    PROVEN_TURN_LANES and so is already deny-by-default for turns, and this
    module deliberately gains no LEGACY registry to express the status, because
    a marker with no consumer is dead capability of exactly the kind this tree
    treats as a defect.
    """
    try:
        command, metadata = _classify_gemini_command(None)
        if metadata["command_origin"] == "fallback_cli_name":
            raise ValueError("Gemini CLI is not resolvable")
    except ValueError:
        return _unavailable_catalog_discovery(
            key,
            reason="provider catalog command is unavailable",
            configured=(
                HealthState.AVAILABLE
                if any(
                    (
                        settings.gemini_api_key,
                        settings.google_api_key,
                        settings.google_application_credentials,
                        settings.gemini_cli_home,
                    )
                )
                else HealthState.UNKNOWN
            ),
            transport=HealthState.UNAVAILABLE,
        )
    env = resolve_env_vars(workspace_root)
    env.update(
        _build_gemini_env(
            settings.gemini_api_key,
            settings.google_api_key,
            settings.google_application_credentials,
            settings.gemini_cli_home,
        )
    )
    discovered = await discover_acp_catalog(
        tuple(command),
        env=env,
        cwd=str(workspace_root),
        key=key,
        metadata={"provider": Provider.GEMINI.value, **metadata},
    )
    normalized = ProviderCatalogDiscovery(
        discovered.catalog,
        discovered.authentication,
        configured=(
            HealthState.AVAILABLE
            if any(
                (
                    settings.gemini_api_key,
                    settings.google_api_key,
                    settings.google_application_credentials,
                    settings.gemini_cli_home,
                )
            )
            else HealthState.UNKNOWN
        ),
    )
    return replace(normalized, transport=_transport_evidence(normalized))


async def _discover_kimi_catalog(
    key: ProviderCatalogKey, workspace_root: Path
) -> ProviderCatalogDiscovery:
    command: list[str] | None = None
    metadata: dict[str, str] = {}
    try:
        command, metadata = _classify_kimi_command()
        if metadata["command_origin"] == "fallback_cli_name":
            raise ValueError("Kimi Code CLI is not resolvable")
    except ValueError:
        command = None
    api_key = (
        settings.kimi_api_key.get_secret_value() if settings.kimi_api_key else None
    )
    try:
        injected = _build_kimi_env(
            kimi_api_key=api_key,
            kimi_base_url=settings.kimi_base_url,
            kimi_temporary_model_name=settings.kimi_temporary_model_name,
            kimi_code_home=settings.kimi_code_home,
            kimi_temporary_model_max_context_size=(
                settings.kimi_temporary_model_max_context_size
            ),
            kimi_temporary_model_capabilities=(
                settings.kimi_temporary_model_capabilities
            ),
        )
    except ValueError:
        return _unavailable_catalog_discovery(
            key,
            reason="temporary Kimi provider configuration is incomplete",
            configured=HealthState.UNAVAILABLE,
            transport=(
                HealthState.AVAILABLE
                if command is not None
                else HealthState.UNAVAILABLE
            ),
        )
    configured = HealthState.AVAILABLE if injected else HealthState.UNKNOWN
    if command is None:
        return _unavailable_catalog_discovery(
            key,
            reason="provider catalog command is unavailable",
            configured=configured,
            transport=HealthState.UNAVAILABLE,
        )
    env = resolve_env_vars(workspace_root)
    env.update(injected)
    # Discovery is a sibling command, never `kimi acp provider list`.
    discovered = await discover_kimi_catalog(
        (command[0],),
        env=env,
        cwd=str(workspace_root),
        key=key,
        metadata={"provider": Provider.KIMI.value, **metadata},
    )
    normalized = ProviderCatalogDiscovery(
        discovered.catalog,
        discovered.authentication,
        configured=configured,
    )
    return replace(normalized, transport=_transport_evidence(normalized))


async def _discover_openai_catalog(key: ProviderCatalogKey) -> ProviderCatalogDiscovery:
    discovered = await discover_openai_compatible_catalog(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        key=key,
    )
    return ProviderCatalogDiscovery(
        discovered.catalog,
        discovered.authentication,
        configured=(
            HealthState.AVAILABLE
            if settings.openai_api_key
            else HealthState.UNAVAILABLE
        ),
        transport=(
            HealthState.AVAILABLE
            if discovered.catalog.state.status is CatalogStatus.AVAILABLE
            or discovered.authentication is AuthenticationState.UNAUTHENTICATED
            else HealthState.UNKNOWN
        ),
    )


async def _discover_in_process_catalog(
    key: ProviderCatalogKey,
) -> ProviderCatalogDiscovery:
    """Adapt the computed in-process catalog to the registration contract.

    The health evidence is asserted rather than observed, and every value is a
    fact about this build: the provider is compiled into this process, so it is
    configured and its transport is a function call; it holds no credential, so
    authentication is not applicable rather than unknown.
    """
    discovered = discover_in_process_catalog(key)
    return ProviderCatalogDiscovery(
        discovered.catalog,
        discovered.authentication,
        configured=HealthState.AVAILABLE,
        transport=HealthState.AVAILABLE,
    )


async def _discover_unverified_catalog(
    key: ProviderCatalogKey,
) -> ProviderCatalogDiscovery:
    provider = Provider(key.provider_id)
    configured = HealthState.UNKNOWN
    if provider is Provider.ZAI:
        configured = (
            HealthState.AVAILABLE
            if settings.zai_auth_token
            else HealthState.UNAVAILABLE
        )
    elif provider is Provider.ZHIPU:
        configured = (
            HealthState.AVAILABLE if settings.zhipu_api_key else HealthState.UNAVAILABLE
        )
    return _unavailable_catalog_discovery(
        key,
        reason="provider lane has no verified prompt-free model enumeration",
        configured=configured,
    )


def _admit_and_resolve_model_name(provider: Provider, model: Model | str | None) -> str:
    """Admit the provider and resolve its model name, or raise.

    The admission path, separated from construction: it refuses an unsupported
    provider and turns the optional model selector into a concrete model name.

    Only the internal in-process lanes carry a repository-authored default and
    capability map. An external lane is selected from its own served catalog and
    frozen into the run's role assignment, so it admits the exact frozen value
    alone: asked for a default or a capability tier, this refuses rather than
    inventing a model identifier the provider never advertised. Being supported
    and having a repo-authored default are separate facts, so the refusal names
    the missing selection rather than reporting an unsupported provider.

    Raises:
        ValueError: If the provider is unsupported, if an external lane is asked
            for an implicit default or a capability tier, or if the model level
            is not mapped for an internal lane.
    """
    if provider not in _SUPPORTED_PROVIDERS:
        logger.error("Failed to instantiate: Unsupported provider %s", provider)
        raise ValueError(f"Unsupported provider: {provider}")

    if model is None:
        if provider not in PROVIDER_DEFAULT_MODELS:
            raise ValueError(
                f"Provider {provider.value!r} has no implicit default model. An "
                "external lane is chosen from the catalog that lane serves, so "
                "the exact model value frozen into the run's role assignment is "
                "the only admissible selection."
            )
        model_level = PROVIDER_DEFAULT_MODELS[provider]
        try:
            return MODEL_MAP[provider][model_level]
        except KeyError:
            raise ValueError(
                f"Unsupported model level {model_level!r} for provider {provider!r}"
            ) from None
    if isinstance(model, Model):
        if provider not in MODEL_MAP:
            raise ValueError(
                f"Provider {provider.value!r} does not map capability level "
                f"{model.value!r}. Capability tiers carry no equivalent meaning "
                "across providers, so an external lane admits only the exact "
                "model value frozen from its served catalog."
            )
        try:
            return MODEL_MAP[provider][model]
        except KeyError:
            raise ValueError(
                f"Unsupported model level {model!r} for provider {provider!r}"
            ) from None
    # For an external lane the raw string IS the frozen catalog value, which is
    # the admissible selection. Only an internal lane, which has a map to
    # validate against, is worth warning about here.
    if provider in MODEL_MAP:
        logger.warning(
            "ProviderFactory received a raw model string %r for provider=%s. "
            "Prefer passing a Model enum value to ensure the name is valid.",
            model,
            provider,
        )
    return model


class ProviderFactory:
    """Factory for instantiating LangChain chat models for different providers."""

    def catalog_registrations(
        self, workspace_root: Path, *, serve_in_process_lanes: bool | None = None
    ) -> tuple[ProviderCatalogRegistration, ...]:
        """Return each catalog lane with its exact discovery adapter.

        Registrations deliberately contain no model values. A lane without a
        verified enumeration surface remains present but unavailable, rather than
        inheriting an API or ACP catalog from a different execution mode.

        The workspace root is required: discovery spawns real provider
        subprocesses, and a lane discovered against this service's own tree
        describes a different machine state than the one the run will execute in.

        ``serve_in_process_lanes`` arms the in-process lanes, which are hidden by
        default. ``None`` consults the deployment's environment declaration, which
        is what the served gateway path does; an explicit value is the same
        decision made by a caller that already knows its own posture, so the
        policy is exercisable without reaching into the process environment.
        The in-process registrations come last, so arming them cannot reorder the
        external lanes a client already enumerates.
        """
        discovery_root = workspace_root
        armed = (
            in_process_lane_serving_armed()
            if serve_in_process_lanes is None
            else serve_in_process_lanes
        )
        claude = ProviderCatalogKey(
            Provider.CLAUDE.value, f"claude-agent-acp:{settings.acp_backend}"
        )
        codex = ProviderCatalogKey(Provider.CODEX.value, "codex-app-server")
        antigravity = ProviderCatalogKey(Provider.ANTIGRAVITY.value, "antigravity-cli")
        gemini = ProviderCatalogKey(Provider.GEMINI.value, "gemini-cli-acp")
        kimi = ProviderCatalogKey(Provider.KIMI.value, "kimi-code-acp")
        openai = ProviderCatalogKey(Provider.OPENAI.value, "openai-api")
        zai = ProviderCatalogKey(
            Provider.ZAI.value, f"zai-claude-agent-acp:{settings.acp_backend}"
        )
        zhipu = ProviderCatalogKey(Provider.ZHIPU.value, "zhipu-openai-compatible-api")
        in_process = tuple(
            # ``key=key`` binds this iteration's lane into the callback; a bare
            # closure over the loop variable would give every registration the
            # last lane's identity, and the loader fences a mismatched key.
            ProviderCatalogRegistration(
                key, lambda key=key: _discover_in_process_catalog(key)
            )
            for key in served_in_process_lanes(
                armed=armed, mock_api_base=settings.mock_api_base
            )
        )
        return (
            ProviderCatalogRegistration(
                antigravity,
                lambda: _discover_antigravity_catalog(antigravity, discovery_root),
            ),
            ProviderCatalogRegistration(
                claude, lambda: _discover_claude_catalog(claude, discovery_root)
            ),
            ProviderCatalogRegistration(
                codex, lambda: _discover_codex_catalog(codex, discovery_root)
            ),
            ProviderCatalogRegistration(
                gemini, lambda: _discover_gemini_catalog(gemini, discovery_root)
            ),
            ProviderCatalogRegistration(
                kimi, lambda: _discover_kimi_catalog(kimi, discovery_root)
            ),
            ProviderCatalogRegistration(
                openai, lambda: _discover_openai_catalog(openai)
            ),
            ProviderCatalogRegistration(zai, lambda: _discover_unverified_catalog(zai)),
            ProviderCatalogRegistration(
                zhipu, lambda: _discover_unverified_catalog(zhipu)
            ),
            *in_process,
        )

    def catalog_registration(
        self,
        key: ProviderCatalogKey,
        workspace_root: Path,
        *,
        serve_in_process_lanes: bool | None = None,
    ) -> ProviderCatalogRegistration:
        """Resolve a served lane exactly; unknown modes cannot borrow an adapter."""
        for registration in self.catalog_registrations(
            workspace_root, serve_in_process_lanes=serve_in_process_lanes
        ):
            if registration.key == key:
                return registration
        raise ValueError(
            "no catalog registration exists for the requested provider execution lane"
        )

    def create(
        self,
        provider: Provider,
        model: Model | str | None = None,
        agent_config: AgentConfig | None = None,
        workspace_root: Path | None = None,
        backend: str | None = None,
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
        # Imported here rather than at module scope: this is the only place that
        # builds one, and the LangChain model stack costs tens of seconds to load,
        # which every caller of this module's classification helpers used to pay to
        # answer a question that needs no model at all.
        from langchain_openai import ChatOpenAI

        from .acp_chat_model import AcpChatModel

        timeout = kwargs.pop("timeout", settings.provider_timeout_seconds)
        execution_mode = kwargs.pop("execution_mode", None)
        native_controls = kwargs.pop("native_controls", None)
        if execution_mode is not None:
            if not isinstance(execution_mode, str):
                raise ValueError("execution_mode must be a string")
            acp_prefixes = {
                Provider.CLAUDE: "claude-agent-acp:",
                Provider.ZAI: "zai-claude-agent-acp:",
            }
            acp_prefix = acp_prefixes.get(provider)
            if acp_prefix is not None and execution_mode.startswith(acp_prefix):
                frozen_backend = execution_mode.removeprefix(acp_prefix)
                if frozen_backend not in {"node", "binary"}:
                    raise ValueError(
                        f"Provider {provider.value!r} cannot execute mode "
                        f"{execution_mode!r}"
                    )
                if backend is not None and backend != frozen_backend:
                    raise ValueError("backend conflicts with frozen execution_mode")
                backend = frozen_backend
            expected_modes = {
                # The in-process lanes read their modes from the serving
                # declaration, so a frozen selection and the catalog that issued
                # it cannot disagree about what the lane is called.
                Provider.DETERMINISTIC: IN_PROCESS_EXECUTION_MODES[
                    Provider.DETERMINISTIC
                ],
                Provider.MOCK: IN_PROCESS_EXECUTION_MODES[Provider.MOCK],
                Provider.CODEX: "codex-app-server",
                Provider.CLAUDE: f"claude-agent-acp:{backend or settings.acp_backend}",
                Provider.ZAI: f"zai-claude-agent-acp:{backend or settings.acp_backend}",
                Provider.KIMI: "kimi-code-acp",
                Provider.GEMINI: "gemini-cli-acp",
                Provider.OPENAI: "openai-api",
                Provider.ZHIPU: "zhipu-openai-compatible-api",
            }
            if expected_modes.get(provider) != execution_mode:
                raise ValueError(
                    f"Provider {provider.value!r} cannot execute mode "
                    f"{execution_mode!r}"
                )
        if native_controls is None:
            selected_controls: dict[str, str] = {}
        elif isinstance(native_controls, dict):
            raw_controls = cast("dict[object, object]", native_controls)
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in raw_controls.items()
            ):
                raise ValueError(
                    "native_controls must map control ids to provider values"
                )
            selected_controls = cast("dict[str, str]", dict(raw_controls))
        else:
            raise ValueError("native_controls must map control ids to provider values")

        # Admission: refuse an unsupported provider and resolve its model name
        # before any construction begins, so a bad request fails clearly rather
        # than partway through building a model.
        model_name = _admit_and_resolve_model_name(provider, model)

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
            codex_controls: dict[str, str] = {}
            for control_id, value in selected_controls.items():
                field = control_id.partition(":")[0]
                if field not in {"reasoning_effort", "service_tier"}:
                    raise ValueError(f"Unsupported Codex native control {control_id!r}")
                if field in codex_controls:
                    raise ValueError(f"Duplicate Codex native control {field!r}")
                codex_controls[field] = value
            return CodexChatModel(
                command=command,
                model_name=model_name,
                effort=codex_controls.get("reasoning_effort"),
                service_tier=codex_controls.get("service_tier"),
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
            backend = backend if backend is not None else settings.acp_backend
            logger.debug(
                "[%s] Instantiating ACP Wrapper. backend=%s", provider, backend
            )

            command, command_meta = _classify_acp_command(backend)

            # No authentication is implemented for this lane: the spawned CLI
            # inherits the ambient environment and the operator's real config
            # home, and resolves whatever auth the operator ambiently has - a
            # logged-in CLI session, an API key in the environment, either -
            # exactly as an interactive `claude` invocation would. This layer
            # injects nothing, reads no credential, and expresses no preference.
            env_vars: dict[str, str] = {}
            # Binary Bun executable requires this flag so acp-agent.ts can detect
            # it is running as a single-file Bun bundle (not via node + index.js).
            if backend == "binary":
                env_vars["CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN"] = "1"

            return AcpChatModel(
                command=command,
                env_vars=env_vars,
                desired_model=model_name,
                desired_config_options=selected_controls,
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
                auth_mode="ambient",
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
                desired_model=model_name,
                desired_config_options=selected_controls,
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
            # Kimi Code owns its provider aliases. The exact catalog-selected
            # alias is passed through the installed CLI's `-m` option; it is not
            # reinterpreted as a temporary-provider KIMI_MODEL_NAME.
            base_command, command_meta = _classify_kimi_command()
            command = [base_command[0], "-m", model_name, *base_command[1:]]
            api_key = (
                settings.kimi_api_key.get_secret_value()
                if settings.kimi_api_key
                else None
            )
            env_vars = _build_kimi_env(
                kimi_api_key=api_key,
                kimi_base_url=settings.kimi_base_url,
                kimi_temporary_model_name=settings.kimi_temporary_model_name,
                kimi_code_home=settings.kimi_code_home,
                kimi_temporary_model_max_context_size=(
                    settings.kimi_temporary_model_max_context_size
                ),
                kimi_temporary_model_capabilities=(
                    settings.kimi_temporary_model_capabilities
                ),
            )
            kimi_effort: str | None = None
            for control_id, value in selected_controls.items():
                if control_id.partition(":")[0] != "thinking_effort":
                    raise ValueError(f"Unsupported Kimi native control {control_id!r}")
                if kimi_effort is not None:
                    raise ValueError("Duplicate Kimi thinking-effort control")
                kimi_effort = value
            if kimi_effort is not None:
                # Kimi's model-scoped environment binding is the supported
                # per-invocation override; the CLI intentionally has no effort
                # flag. Admission already proved this value belongs to the alias.
                env_vars["KIMI_MODEL_THINKING_EFFORT"] = kimi_effort
            logger.debug(
                "[%s] Instantiating Kimi ACP agent. Temporary definition present: %s",
                provider,
                "KIMI_MODEL_API_KEY" in env_vars,
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
                acp_backend="kimi-code",
                auth_mode=(
                    "temporary_model"
                    if "KIMI_MODEL_API_KEY" in env_vars
                    else "persisted_config"
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
                desired_config_options=selected_controls,
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

        if selected_controls:
            raise ValueError(
                f"Provider {provider.value!r} has no exact native-control executor"
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
            kwargs["base_url"] = settings.openai_base_url
            kwargs["timeout"] = timeout
            kwargs["max_retries"] = 2

            return ChatOpenAI(**kwargs)

        logger.error("Failed to instantiate: Unsupported provider %s", provider)
        raise ValueError(f"Unsupported provider: {provider}")
