"""Provider command resolution and explicit subprocess environment builders."""

import functools
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from vaultspec_core.config import ConfigVariable

from ..control.config import settings
from ..control.env_prefix import ENV_PREFIX
from ..control.env_registry import CREDENTIAL_VARIABLES
from ..control.infra_config import AcpBackend
from ..graph.enums import Provider
from ..thread.errors import ConfigError
from .cli_resolution import resolve_provider_cli_executable, resolve_service_executable
from .execution_modes import ACP_BACKEND_LANES, BINARY_BACKEND, NODE_BACKEND

__all__ = [
    "ANTHROPIC_AUTH_TOKEN_ENV",
    "CLAUDE_CONFIG_DIR_ENV",
    "CLAUDE_OAUTH_TOKEN",
    "CODEX_HOME_ENV",
    "COMMAND_LANES",
    "KIMI_API_KEY_ENV",
    "_BIN_PATH",
    "ProviderCommand",
    "_build_kimi_env",
    "_classify_acp_command",
    "_kimi_home_env",
    "acp_launch_options",
    "capsule_acp_entry",
    "capsule_claude_executable",
    "capsule_node_executable",
    "classify_provider_command",
    "claude_acp_entry",
    "foreign_credential",
    "kimi_temporary_model_configuration_reason",
]


_FALLBACK_CLI_NAME = "fallback_cli_name"


@dataclass(frozen=True, slots=True)
class ProviderCommand:
    """One provider launch command and the runtime facts its resolution found.

    The command is resolved once and every consumer reads these facts rather
    than re-testing the argv. ``resolved`` is false only for the bare-name
    fallback that no trusted search path answered; every other origin carries
    an absolute launcher.

    The chat models hold one as a pydantic field, so this module keeps its
    annotations evaluated rather than deferred.
    """

    argv: tuple[str, ...]
    runtime_authority: str
    command_origin: str
    command_kind: str
    command_executable: str
    command_target: str
    acp_backend: AcpBackend | None = None

    @property
    def resolved(self) -> bool:
        return self.command_origin != _FALLBACK_CLI_NAME

    def metadata(self) -> dict[str, str]:
        """Return the bounded runtime metadata attached to launches and probes."""
        fields = {
            "runtime_authority": self.runtime_authority,
            "command_origin": self.command_origin,
            "command_kind": self.command_kind,
            "command_executable": self.command_executable,
            "command_target": self.command_target,
        }
        if self.acp_backend is not None:
            fields["acp_backend"] = self.acp_backend
        return fields


# Resolve the claude-agent-acp entry point from the checkout's node_modules.
# install_root names THIS SERVICE's own shipped assets, never a place to put
# data and never a directory an agent runs in; see Settings.install_root.
#
# Resolved at the first call rather than at import: this module is reached by
# importing the provider factory, and reading a setting there would hand a
# refused configuration to the import machinery instead of to the entry point
# that can name it. Cached, so the answer is still one per process.
@functools.cache
def claude_acp_entry() -> Path:
    """Return the project-local claude-agent-acp entry point."""
    return (
        settings.install_root
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


def foreign_credential(field: str) -> ConfigVariable:
    """Return the registry entry for the name a lane's own tool reads ``field`` by.

    A credential is registered under its canonical a2a name and the owning
    tool's own spelling. A child process reads the latter, so the provider layer
    takes it from the registry instead of spelling it again.

    Raises:
        ValueError: ``field`` is not registered under exactly one foreign name.
    """
    (variable,) = (
        entry
        for entry in CREDENTIAL_VARIABLES[field]
        if not entry.env_name.startswith(ENV_PREFIX)
    )
    return variable


CLAUDE_OAUTH_TOKEN: Final = foreign_credential("claude_code_oauth_token")
KIMI_API_KEY_ENV: Final = foreign_credential("kimi_model_api_key").env_name

# Names the provider tools read that no credential entry declares. The registry
# lists ANTHROPIC_AUTH_TOKEN only as a name a child never inherits, so the Z.ai
# lane is the sole writer of it.
ANTHROPIC_AUTH_TOKEN_ENV: Final = "ANTHROPIC_AUTH_TOKEN"
CLAUDE_CONFIG_DIR_ENV: Final = "CLAUDE_CONFIG_DIR"
CODEX_HOME_ENV: Final = "CODEX_HOME"
_BUN_SINGLE_FILE_ENV: Final = "CLAUDE_AGENT_ACP_IS_SINGLE_FILE_BUN"


def acp_launch_options(backend: AcpBackend | None) -> tuple[bool, dict[str, str]]:
    """Return ``use_exec`` and the adapter environment ``backend`` launches with.

    The precompiled Bun executable is a native binary that needs no ``.cmd``
    shim, and it must be told it is the single-file build. A command with no
    selectable backend launches with neither.
    """
    if backend == BINARY_BACKEND:
        return True, {_BUN_SINGLE_FILE_ENV: "1"}
    return False, {}


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
        env_vars[KIMI_API_KEY_ENV] = kimi_api_key.strip()
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


def capsule_claude_executable(capsule_assets_root: Path) -> Path:
    """Return the CLI path selected by the bundled ACP adapter on this host.

    The adapter prefers the Linux package matching the host libc and tries the
    other variant only when the preferred package is absent. The capsule uses
    the same verbatim npm layout, so no checkout or PATH lookup is involved.
    """
    node_platform = {
        "win32": "win32",
        "darwin": "darwin",
        "linux": "linux",
    }.get(sys.platform)
    node_arch = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(platform.machine().lower())
    if node_platform is None or node_arch is None:
        raise ConfigError(
            f"No capsule Claude CLI variant for {sys.platform}/{platform.machine()}"
        )
    variants = [f"@anthropic-ai/claude-agent-sdk-{node_platform}-{node_arch}"]
    if node_platform == "linux":
        musl_variant = f"{variants[0]}-musl"
        variants = (
            [musl_variant, variants[0]]
            if platform.libc_ver()[0] != "glibc"
            else [variants[0], musl_variant]
        )
    binary_name = "claude.exe" if node_platform == "win32" else "claude"
    candidates = [
        capsule_assets_root / "node_modules" / variant / binary_name
        for variant in variants
    ]
    return next(
        (candidate for candidate in candidates if candidate.is_file()), candidates[0]
    )


def _canonical_capsule_assets_root(capsule_assets_root: Path) -> Path:
    """Return the absolute canonical directory that owns capsule assets."""
    try:
        canonical_root = capsule_assets_root.resolve(strict=True)
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


def _classify_capsule_acp_command(capsule_assets_root: Path) -> ProviderCommand:
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
    return ProviderCommand(
        argv=(str(node_executable), str(acp_entry)),
        runtime_authority="capsule",
        command_origin="capsule",
        command_kind="node_entry",
        command_executable=node_executable.name,
        command_target=str(acp_entry),
        acp_backend=NODE_BACKEND,
    )


def _classify_acp_command(
    backend: AcpBackend,
    *,
    capsule_assets_root: Path | _CapsuleAssetsRootOmitted | None = (
        _CAPSULE_ASSETS_ROOT_OMITTED
    ),
) -> ProviderCommand:
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
    if backend == BINARY_BACKEND:
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
        return ProviderCommand(
            argv=(str(_BIN_PATH),),
            runtime_authority="package_bin",
            command_origin="package_bin",
            command_kind="bun_binary",
            command_executable=_BIN_PATH.name,
            command_target=str(_BIN_PATH),
            acp_backend=BINARY_BACKEND,
        )
    # default: "node"
    root = (
        settings.capsule_assets_root
        if isinstance(capsule_assets_root, _CapsuleAssetsRootOmitted)
        else capsule_assets_root
    )
    if root is not None:
        return _classify_capsule_acp_command(root)
    entry = claude_acp_entry()
    if not entry.exists():
        raise ConfigError(
            f"Claude ACP entry point not found: {entry}. "
            "Run 'npm install' to install @agentclientprotocol/claude-agent-acp."
        )
    # The adapter is a Node entry point, so the Node runtime is part of the
    # launch and is resolved from the service's own environment here, once, to an
    # absolute path. Resolving it at spawn time instead would resolve it from the
    # child's environment, which leads with the agent workspace.
    node_executable = resolve_service_executable("node")
    if node_executable is None:
        raise ConfigError(
            "Node.js runtime not found on this service's PATH, so the Claude ACP "
            f"entry point {entry} cannot be launched. Install the Node "
            "version named by .node-version and make it reachable from the "
            "service environment."
        )
    return ProviderCommand(
        argv=(node_executable, str(entry)),
        runtime_authority="project_local",
        command_origin="project_node_modules_entry",
        command_kind="node_entry",
        command_executable=Path(node_executable).name,
        command_target=str(entry),
        acp_backend=NODE_BACKEND,
    )


# The system-CLI lanes and the subcommand that serves each: Codex is a non-ACP
# JSON-RPC ``app-server``; Kimi speaks ACP natively through ``kimi acp``.
_SYSTEM_CLI_SUBCOMMANDS: dict[Provider, str] = {
    Provider.CODEX: "app-server",
    Provider.KIMI: "acp",
}

#: Every lane launched as a native subprocess: exactly the lanes
#: :func:`classify_provider_command` classifies.
COMMAND_LANES: frozenset[Provider] = ACP_BACKEND_LANES | frozenset(
    _SYSTEM_CLI_SUBCOMMANDS
)


def _classify_system_cli_command(provider: Provider) -> ProviderCommand:
    """Return a system-CLI lane's command, resolved from this service's PATH.

    An unresolved CLI keeps its bare name under the ``fallback_cli_name``
    origin, which :attr:`ProviderCommand.resolved` reports as unresolved.
    """
    subcommand = _SYSTEM_CLI_SUBCOMMANDS[provider]
    kind = f"{provider.value}_cli"
    executable = resolve_provider_cli_executable(provider)
    if executable:
        return ProviderCommand(
            argv=(executable, subcommand),
            runtime_authority="system_cli",
            command_origin="system_path_executable",
            command_kind=kind,
            command_executable=Path(executable).name,
            command_target=executable,
        )
    return ProviderCommand(
        argv=(provider.value, subcommand),
        runtime_authority="system_cli",
        command_origin=_FALLBACK_CLI_NAME,
        command_kind=kind,
        command_executable=provider.value,
        command_target=provider.value,
    )


def classify_provider_command(
    provider: Provider, *, backend: AcpBackend | None = None
) -> ProviderCommand:
    """Resolve a subprocess provider's launch command without instantiating it.

    The one classification of a lane's launch: the returned command carries
    what resolution established, including whether a system CLI resolved at
    all, so no caller looks the binary up a second time.

    Raises:
        ValueError: The provider has no subprocess command.
        ConfigError: The Claude ACP entry point/binary does not exist.
    """
    if provider in ACP_BACKEND_LANES:
        # Z.ai launches the same claude-agent-acp wrapper as Claude; only the
        # injected auth env differs.
        return _classify_acp_command(
            backend if backend is not None else settings.acp_backend
        )
    if provider in _SYSTEM_CLI_SUBCOMMANDS:
        return _classify_system_cli_command(provider)
    raise ValueError(f"provider {provider.value} has no subprocess command to classify")
