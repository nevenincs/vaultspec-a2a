"""Provider command resolution and explicit subprocess environment builders."""

from __future__ import annotations

import os
from pathlib import Path

from ..control.config import settings
from ..graph.enums import Provider
from ..thread.errors import ConfigError
from .cli_resolution import resolve_provider_cli_executable

__all__ = [
    "_BIN_PATH",
    "_CLAUDE_ACP_JS",
    "_build_kimi_env",
    "_build_zai_env",
    "_classify_acp_command",
    "_classify_codex_command",
    "_classify_kimi_command",
    "_kimi_home_env",
    "capsule_acp_entry",
    "capsule_node_executable",
    "classify_provider_command",
    "kimi_temporary_model_configuration_reason",
]

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
# Node backend is the default; binary mode is experimental and requires a
# deliberate decision to adopt.
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


def _kimi_home_env(kimi_code_home: str | None) -> dict[str, str]:
    if kimi_code_home and kimi_code_home.strip():
        return {"KIMI_CODE_HOME": kimi_code_home.strip()}
    return {}


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
    path) is what ``classify_provider_command`` treats as unresolvable.
    """
    system_codex = resolve_provider_cli_executable(Provider.CODEX)
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
    system_kimi = resolve_provider_cli_executable(Provider.KIMI)
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
    when it cannot be resolved. ``_classify_acp_command`` raises when the Claude
    ACP entry point is missing, and bare-name command fallbacks are treated as
    unresolvable rather than silently accepted.

    Raises:
        ValueError: The provider has no resolvable subprocess command.
        ConfigError: The Claude ACP entry point/binary does not exist.
    """
    if provider in (Provider.CLAUDE, Provider.ZAI):
        # Z.ai launches the same claude-agent-acp wrapper as Claude; only the
        # injected auth env differs.
        resolved_backend = backend if backend is not None else settings.acp_backend
        _, meta = _classify_acp_command(resolved_backend)
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
