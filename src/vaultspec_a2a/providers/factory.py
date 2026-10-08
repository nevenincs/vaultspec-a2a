"""LLM Provider factory.

The LangChain model classes are imported lazily, not at module scope. Importing
``langchain_openai`` costs roughly twenty-five seconds in this environment, and
this module's classification and readiness helpers - which several callers reach
for WITHOUT ever constructing a model - had to pay that before answering. The
chat-model classes are now imported where a model is actually built, so probing
which provider a command resolves to no longer loads a model stack to answer.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from vaultspec_core.config import env_value

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from langchain_core.language_models import BaseChatModel

    from ..control.infra_config import AcpBackend
    from ..desktop.native_isolation import NativeLaunchAuthority
    from ..team.team_config import AgentConfig

from ..control.config import settings
from ..graph.enums import Provider
from ..thread.errors import ConfigError
from ..utils import ProcessContainmentError
from ..utils.async_cleanup import complete_cleanup
from ..workspace.environment import resolve_env_vars
from ._catalog_discovery import ProviderCatalogDiscovery, unavailable_discovery
from ._claude_tool_policy import claude_bypass_declined_meta
from ._factory_commands import (
    ANTHROPIC_AUTH_TOKEN_ENV,
    CLAUDE_OAUTH_TOKEN,
    CODEX_HOME_ENV,
    KIMI_API_KEY_ENV,
    ProviderCommand,
    _build_kimi_env,
    acp_launch_options,
    classify_provider_command,
    foreign_credential,
)
from ._native_role import (
    capture_native_workspace,
    prepare_acp_role,
    prepare_native_version_probe,
    role_environment,
)
from .acp_catalog import discover_acp_catalog
from .antigravity_catalog import discover_antigravity_catalog
from .binary_version import BinaryVersionProbeError, probe_binary_version
from .cli_resolution import (
    ClaudeCliResolution,
    ProviderRuntimeUnavailableError,
    ProviderRuntimeUnavailableReason,
    pin_claude_executable,
    proof_cli_name,
)
from .codex_catalog import discover_codex_catalog
from .execution_modes import (
    ACP_BACKEND_LANES,
    EXTERNAL_EXECUTION_MODES,
    external_execution_mode,
    is_acp_backend,
)
from .in_process_catalog import (
    discover_in_process_catalog,
    in_process_lane,
    served_in_process_lanes,
)
from .kimi_catalog import discover_kimi_catalog
from .lane_admission import PROVEN_TURN_LANES, lane_proof_accepts_version
from .lane_registry import registered_lanes
from .openai_catalog import discover_openai_compatible_catalog
from .provider_catalog import (
    AuthenticationState,
    CatalogStatus,
    HealthState,
    ProviderCatalogKey,
)
from .provider_readiness import (
    KIMI_NO_TEMPORARY_MODEL_REASON,
    probe_provider_configuration,
)

__all__ = [
    "ProviderCatalogRegistration",
    "ProviderFactory",
    "UnsupportedExecutionLaneError",
    "validate_current_execution_lane",
    "validate_current_native_controls",
]


class UnsupportedExecutionLaneError(ValueError):
    """A frozen provider/mode pair is outside the current execution inventory."""


def validate_current_execution_lane(provider: Provider, execution_mode: str) -> None:
    """Refuse a structurally impossible provider/mode pair without construction."""
    if provider in EXTERNAL_EXECUTION_MODES:
        expected = external_execution_mode(provider, settings.acp_backend)
    else:
        lane = in_process_lane(provider)
        expected = lane.execution_mode if lane is not None else None
    if expected != execution_mode:
        raise UnsupportedExecutionLaneError(
            f"Provider {provider.value!r} cannot execute mode {execution_mode!r}"
        )


def validate_current_native_controls(
    provider: Provider, controls: dict[str, str]
) -> None:
    """Validate provider-specific frozen control structure before construction."""
    no_control_lanes = {Provider.OPENAI, Provider.ZHIPU}
    if controls and (
        provider in no_control_lanes or in_process_lane(provider) is not None
    ):
        raise ValueError(
            f"Provider {provider.value!r} has no exact native-control executor"
        )
    allowed_fields = {
        Provider.CODEX: {"reasoning_effort", "service_tier"},
        Provider.KIMI: {"thinking_effort"},
    }.get(provider)
    if allowed_fields is None:
        return
    seen: set[str] = set()
    for control_id in controls:
        field = control_id.partition(":")[0]
        if field not in allowed_fields:
            raise ValueError(
                f"Unsupported {provider.value} native control {control_id!r}"
            )
        if field in seen:
            raise ValueError(f"Duplicate {provider.value} native control {field!r}")
        seen.add(field)


logger = logging.getLogger(__name__)


# The external lanes this factory constructs; an in-process lane is supported
# exactly when this process holds its registration.
_SUPPORTED_PROVIDERS: frozenset[Provider] = frozenset(
    {
        Provider.CLAUDE,
        Provider.CODEX,
        Provider.KIMI,
        Provider.ZAI,
        Provider.ZHIPU,
        Provider.OPENAI,
    }
)


@dataclass(frozen=True, slots=True)
class ProviderCatalogRegistration:
    """A single execution-mode-specific catalog discovery callback."""

    key: ProviderCatalogKey
    discover: Callable[[], Awaitable[ProviderCatalogDiscovery]]
    version_admission: Callable[[], ProviderRuntimeUnavailableReason | None] | None = (
        None
    )


def binary_proof_reason(
    provider: Provider,
    executable: str,
    authority: str,
    *,
    native_authority: NativeLaunchAuthority | None = None,
    workspace_root: Path | None = None,
) -> ProviderRuntimeUnavailableReason | None:
    """Check the same resolved launcher that this lane would hand to its child."""
    proof = PROVEN_TURN_LANES.get(provider)
    if proof is None:
        return ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING
    if proof.binary != proof_cli_name(provider):
        return ProviderRuntimeUnavailableReason.BINARY_OUT_OF_PROOF_RANGE
    if native_authority is None and settings.desktop_profile_armed:
        try:
            with prepare_native_version_probe(
                capture_native_workspace(workspace_root)
            ) as prepared:
                return binary_proof_reason(
                    provider, executable, authority, native_authority=prepared
                )
        except (OSError, ValueError, ProcessContainmentError):
            return ProviderRuntimeUnavailableReason.BINARY_VERSION_UNAVAILABLE
    try:
        reported = (
            probe_binary_version(executable)
            if native_authority is None
            else probe_binary_version(executable, native_authority=native_authority)
        )
    except BinaryVersionProbeError:
        return ProviderRuntimeUnavailableReason.BINARY_VERSION_UNAVAILABLE
    if not lane_proof_accepts_version(proof, reported, authority):
        return ProviderRuntimeUnavailableReason.BINARY_OUT_OF_PROOF_RANGE
    return None


def _system_cli_binary_proof_reason(
    provider: Provider,
    command: ProviderCommand | None,
    *,
    native_authority: NativeLaunchAuthority | None = None,
    workspace_root: Path | None = None,
) -> ProviderRuntimeUnavailableReason | None:
    """Probe the service-path launcher a system-CLI lane would hand its child.

    ``command`` is the classification a model already holds; without one the
    lane is classified here, once. The lane's own proof is read FIRST, so an
    unenrolled lane is refused without resolving or spawning anything - which
    also makes the refusal independent of whether the CLI is installed here.
    """
    if provider not in PROVEN_TURN_LANES:
        return ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING
    if command is None:
        try:
            command = classify_provider_command(provider)
        except ConfigError:
            return ProviderRuntimeUnavailableReason.BINARY_VERSION_UNAVAILABLE
    return binary_proof_reason(
        provider,
        command.argv[0],
        "service_path",
        native_authority=native_authority,
        workspace_root=workspace_root,
    )


def codex_binary_proof_reason(
    command: ProviderCommand | None = None,
    *,
    native_authority: NativeLaunchAuthority | None = None,
    workspace_root: Path | None = None,
) -> ProviderRuntimeUnavailableReason | None:
    """Probe the service-path Codex launcher selected by the factory."""
    return _system_cli_binary_proof_reason(
        Provider.CODEX,
        command,
        native_authority=native_authority,
        workspace_root=workspace_root,
    )


def kimi_binary_proof_reason(
    command: ProviderCommand | None = None,
    *,
    native_authority: NativeLaunchAuthority | None = None,
    workspace_root: Path | None = None,
) -> ProviderRuntimeUnavailableReason | None:
    """Probe the service-path Kimi launcher selected by the factory.

    Kimi is unenrolled - its live coverage is a handshake, which proves spawn
    and not work - so this answers ``BINARY_PROOF_MISSING`` today for every
    host. It is the same gate the Claude and Codex lanes pass through rather
    than a lane-specific refusal: when a completed turn is recorded against a
    Kimi binary identity, this lane is served exactly within that version
    range and no further.
    """
    return _system_cli_binary_proof_reason(
        Provider.KIMI,
        command,
        native_authority=native_authority,
        workspace_root=workspace_root,
    )


def _claude_binary_proof_reason(
    provider: Provider, workspace_root: Path
) -> ProviderRuntimeUnavailableReason | None:
    """Resolve and probe a Claude-backed catalog lane without child PATH lookup."""
    if provider not in PROVEN_TURN_LANES:
        return ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING
    try:
        resolved = pin_claude_executable(resolve_env_vars(workspace_root))
    except ProviderRuntimeUnavailableError as exc:
        return exc.reason or ProviderRuntimeUnavailableReason.CLAUDE_CLI_UNAVAILABLE
    return binary_proof_reason(
        provider, str(resolved.path), resolved.authority, workspace_root=workspace_root
    )


def require_binary_proof(reason: ProviderRuntimeUnavailableReason | None) -> None:
    if reason is not None:
        raise ProviderRuntimeUnavailableError(
            "resolved provider binary lacks a current completed-turn proof",
            reason=reason,
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


def claude_auth_env() -> tuple[dict[str, str], str]:
    """Select only the declared Claude credential channel for a child."""
    if settings.claude_auth_channel == "subscription_login":
        # Preserve an explicit operator export only at the Claude root seam.
        # The shared environment must never grant this credential to other lanes.
        token = env_value(CLAUDE_OAUTH_TOKEN, environ=os.environ) or ""
        return (
            {CLAUDE_OAUTH_TOKEN.env_name: token} if token.strip() else {},
            "subscription_login",
        )
    if settings.claude_auth_channel != "oauth_token":
        raise ProviderRuntimeUnavailableError("unsupported Claude auth channel")
    configured = settings.claude_code_oauth_token
    token = configured.get_secret_value() if configured is not None else ""
    if not token.strip():
        raise ProviderRuntimeUnavailableError(
            "Claude oauth_token auth channel requires a configured OAuth token"
        )
    return {CLAUDE_OAUTH_TOKEN.env_name: token}, "oauth_token"


def _zai_auth_env() -> tuple[dict[str, str], str]:
    """Select the configured Z.ai credential for the Claude ACP child.

    Z.ai rides the Claude ACP path: the wrapper's Claude Code CLI honours
    ``ANTHROPIC_BASE_URL``/``ANTHROPIC_AUTH_TOKEN`` to retarget the Anthropic
    Messages API at Z.ai's compatible gateway. The base env removes ambient
    credentials and gateway overrides, so the selected provider supplies both
    names explicitly after scrubbing. Whether a token is configured is the
    lane's configuration probe's answer. The token is a secret: it is placed in
    the returned dict but never logged.
    """
    token = settings.zai_auth_token
    if probe_provider_configuration(Provider.ZAI).reason is not None or token is None:
        return {}, "none_detected"
    env_vars: dict[str, str] = {}
    if settings.zai_base_url.strip():
        env_vars["ANTHROPIC_BASE_URL"] = settings.zai_base_url
    env_vars[ANTHROPIC_AUTH_TOKEN_ENV] = token
    return env_vars, "zai_auth_token"


@dataclass(frozen=True, slots=True)
class _AcpCatalogAuth:
    """The credential overlay one claude-agent-acp lane's probe launches with."""

    env: dict[str, str]
    mode: str


def _acp_catalog_auth_overlay(provider: Provider) -> _AcpCatalogAuth:
    """Return the credential a claude-agent-acp lane's catalog probe is launched with.

    The probe opens a real session, so it authenticates the way a served turn
    authenticates: Claude through its declared channel, Z.ai by retargeting the
    same adapter at its own gateway. One function, because the lanes differ in
    the credential and in nothing else.

    Raises:
        ProviderRuntimeUnavailableError: The lane's credential is absent. The
            message is the served reason: an unauthenticated probe would report
            a lane unavailable for a reason that is the probe's own doing, so
            the absent credential is named instead.
    """
    if provider is Provider.ZAI:
        env, mode = _zai_auth_env()
        if mode == "none_detected":
            raise ProviderRuntimeUnavailableError(
                probe_provider_configuration(Provider.ZAI).reason
                or "no Z.ai auth token configured"
            )
        return _AcpCatalogAuth(env=env, mode=mode)
    try:
        env, mode = claude_auth_env()
    except ProviderRuntimeUnavailableError as exc:
        raise ProviderRuntimeUnavailableError("claude_oauth_token_unavailable") from exc
    return _AcpCatalogAuth(env=env, mode=mode)


async def _discover_claude_family_catalog(
    provider: Provider, key: ProviderCatalogKey, workspace_root: Path
) -> ProviderCatalogDiscovery:
    """Enumerate one claude-agent-acp lane's catalog through the shared lifecycle.

    Claude and Z.ai run the SAME adapter through the same prompt-free session;
    only the credential overlay differs. Keeping one lifecycle is what makes a
    lane's served catalog describe the gateway its turns reach - a lane with its
    own enumeration path, or none at all, serves an answer no credential can
    change.

    The lane's own credential is read before any launcher is resolved, matching
    the order readiness already reports: an absent token is never served as a
    missing adapter.
    """
    try:
        auth = _acp_catalog_auth_overlay(provider)
    except ProviderRuntimeUnavailableError as exc:
        return unavailable_discovery(
            key, reason=str(exc), configured=HealthState.UNAVAILABLE
        )
    try:
        command = classify_provider_command(provider)
    except (ConfigError, ValueError):
        return unavailable_discovery(
            key,
            reason="provider catalog command is unavailable",
            transport=HealthState.UNAVAILABLE,
        )
    env = resolve_env_vars(workspace_root)
    # The probe drives the same CLI a served turn will. Unpinned, the adapter
    # falls back to its vendored binary, so the catalog this builds would
    # describe a different Claude from the one the lane then runs.
    try:
        cli_resolution = pin_claude_executable(env)
    except ProviderRuntimeUnavailableError as exc:
        return unavailable_discovery(
            key,
            reason=exc.reason.value if exc.reason else str(exc),
            transport=HealthState.UNAVAILABLE,
        )
    env.update(auth.env)
    use_exec, launch_env = acp_launch_options(command.acp_backend)
    env.update(launch_env)
    scope = capture_native_workspace(workspace_root)
    async with prepare_acp_role(
        scope, environment=env, provider=provider.value
    ) as native:
        if native is not None:
            env.update(role_environment(native))
        discovered = await discover_acp_catalog(
            command.argv,
            env=env,
            cwd=str(workspace_root),
            key=key,
            use_exec=use_exec,
            metadata={
                "provider": provider.value,
                **command.metadata(),
                "cli_runtime_authority": cli_resolution.authority,
                "cli_executable": str(cli_resolution.path),
                "auth_mode": auth.mode,
            },
            # The probe opens a real session, so it opens it under the same
            # permission posture a served turn gets. Leaving the bypass capability
            # granted here would qualify a lane nobody runs - and where the CLI
            # refuses the flag the capability arms, it would report the lane
            # unavailable for a reason that is this probe's own doing.
            session_meta=claude_bypass_declined_meta(),
            native_authority=native,
        )
    # The lane's own configuration axis: Claude's settings carry no answer and
    # stay unknown, while Z.ai's token presence is the answer its probe reports.
    normalized = replace(
        discovered, configured=probe_provider_configuration(provider).state
    )
    return replace(normalized, transport=_transport_evidence(normalized))


async def _discover_codex_catalog(
    key: ProviderCatalogKey, workspace_root: Path
) -> ProviderCatalogDiscovery:
    try:
        command = classify_provider_command(Provider.CODEX)
    except ConfigError:
        return unavailable_discovery(
            key,
            reason="provider catalog command is unavailable",
            transport=HealthState.UNAVAILABLE,
        )
    env = resolve_env_vars(workspace_root)
    if settings.codex_home:
        env[CODEX_HOME_ENV] = settings.codex_home
    scope = capture_native_workspace(workspace_root)
    home = None
    try:
        native = None
        if scope is not None:
            from ..utils.enums import CodexWebSearchMode
            from ._codex_config_home import (
                build_codex_config_home,
                resolve_codex_base_home,
            )

            base = resolve_codex_base_home(settings.codex_home)
            home = build_codex_config_home(
                [], base, web_search=CodexWebSearchMode.DISABLED
            )
            native = scope.for_home(home)
            env[CODEX_HOME_ENV] = str(home)
        discovered = await discover_codex_catalog(
            command.argv,
            env=env,
            cwd=str(workspace_root),
            key=key,
            native_authority=native,
        )
    finally:
        if home is not None:
            from ._codex_config_home import cleanup_codex_config_home

            await complete_cleanup(asyncio.to_thread(cleanup_codex_config_home, home))
    return replace(discovered, transport=_transport_evidence(discovered))


async def _discover_antigravity_catalog(
    key: ProviderCatalogKey, workspace_root: Path
) -> ProviderCatalogDiscovery:
    """Normalize the Antigravity listing into a registration-boundary result.

    Transport health follows the catalog: this lane's only surface IS the CLI
    invocation, so a listing that came back is a reachable transport and one
    that did not is an unreachable one. There is no separate handshake to
    distinguish the two. Configuration is the lane's own evidence, because
    resolving the CLI is the listing's first step.
    """
    discovered = await discover_antigravity_catalog(
        key,
        workspace_root,
        cli_path=settings.antigravity_cli_path,
        home=settings.antigravity_cli_home,
    )
    available = discovered.catalog.state.status is CatalogStatus.AVAILABLE
    return replace(
        discovered,
        transport=HealthState.AVAILABLE if available else HealthState.UNAVAILABLE,
    )


async def _discover_kimi_catalog(
    key: ProviderCatalogKey, workspace_root: Path
) -> ProviderCatalogDiscovery:
    from .kimi_config_home import KIMI_CODE_HOME_ENV, resolve_kimi_base_home

    configuration = probe_provider_configuration(Provider.KIMI)
    try:
        command = classify_provider_command(Provider.KIMI)
    except ConfigError:
        return unavailable_discovery(
            key,
            reason="provider catalog command is unavailable",
            configured=configuration.state,
            transport=HealthState.UNAVAILABLE,
        )
    if configuration.reason is not None:
        return unavailable_discovery(
            key,
            reason=configuration.reason,
            configured=configuration.state,
            transport=HealthState.AVAILABLE,
        )
    api_key = (
        settings.kimi_api_key.get_secret_value() if settings.kimi_api_key else None
    )
    env = resolve_env_vars(workspace_root)
    env.update(
        _build_kimi_env(
            kimi_api_key=api_key,
            kimi_base_url=settings.kimi_base_url,
            kimi_temporary_model_name=settings.kimi_temporary_model_name,
            kimi_temporary_model_max_context_size=(
                settings.kimi_temporary_model_max_context_size
            ),
            kimi_temporary_model_capabilities=(
                settings.kimi_temporary_model_capabilities
            ),
        )
    )
    # Discovery enumerates the models the OPERATOR configured, so it reads the
    # operator's own home, named rather than left to the CLI's default. Only a
    # served turn is isolated, and this command opens no agent session.
    env[KIMI_CODE_HOME_ENV] = str(resolve_kimi_base_home(settings.kimi_code_home))
    # Discovery is a sibling command, never `kimi acp provider list`.
    discovered = await discover_kimi_catalog(
        (command.argv[0],),
        env=env,
        cwd=str(workspace_root),
        key=key,
        metadata={"provider": Provider.KIMI.value, **command.metadata()},
    )
    normalized = replace(discovered, configured=configuration.state)
    return replace(normalized, transport=_transport_evidence(normalized))


async def _discover_openai_catalog(key: ProviderCatalogKey) -> ProviderCatalogDiscovery:
    discovered = await discover_openai_compatible_catalog(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        key=key,
    )
    return replace(
        discovered,
        configured=probe_provider_configuration(Provider.OPENAI).state,
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
    return replace(
        discover_in_process_catalog(key),
        configured=HealthState.AVAILABLE,
        transport=HealthState.AVAILABLE,
    )


async def _discover_unverified_catalog(
    key: ProviderCatalogKey,
) -> ProviderCatalogDiscovery:
    return unavailable_discovery(
        key,
        reason="provider lane has no verified prompt-free model enumeration",
        configured=probe_provider_configuration(Provider(key.provider_id)).state,
    )


def _external_catalog_key(provider: Provider) -> ProviderCatalogKey:
    """Return the catalog identity an external lane is served under now."""
    return ProviderCatalogKey(
        provider.value, external_execution_mode(provider, settings.acp_backend)
    )


def _admit_and_resolve_model_name(provider: Provider, model: object) -> str:
    """Admit the provider and resolve its model name, or raise.

    The admission path, separated from construction: it refuses an unsupported
    provider and requires the exact catalog-frozen model value.

    Every lane is selected from its served catalog and frozen into the run's
    role assignment. The factory therefore admits an exact value only; it never
    translates a capability tier or supplies an implicit default.

    Raises:
        ValueError: If the provider is unsupported or no exact value is supplied.
    """
    if provider not in _SUPPORTED_PROVIDERS and in_process_lane(provider) is None:
        logger.error("Failed to instantiate: Unsupported provider %s", provider)
        raise ValueError(f"Unsupported provider: {provider}")

    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            f"Provider {provider.value!r} requires the exact model value frozen "
            "from its served catalog"
        )
    return model


def _admit_execution_mode(
    provider: Provider, backend: str | None, execution_mode: object
) -> AcpBackend | None:
    if backend is not None and not is_acp_backend(backend):
        raise ValueError(f"Unsupported ACP backend: {backend!r}")
    if execution_mode is not None:
        if not isinstance(execution_mode, str):
            raise ValueError("execution_mode must be a string")
        acp_prefix = (
            f"{EXTERNAL_EXECUTION_MODES[provider]}:"
            if provider in ACP_BACKEND_LANES
            else None
        )
        if acp_prefix is not None and execution_mode.startswith(acp_prefix):
            frozen_backend = execution_mode.removeprefix(acp_prefix)
            if not is_acp_backend(frozen_backend):
                raise ValueError(
                    f"Provider {provider.value!r} cannot execute mode "
                    f"{execution_mode!r}"
                )
            if backend is not None and backend != frozen_backend:
                raise ValueError("backend conflicts with frozen execution_mode")
            backend = frozen_backend
        validate_current_execution_lane(provider, execution_mode)
    return backend


def _admit_native_controls(
    provider: Provider, native_controls: object
) -> dict[str, str]:
    if native_controls is None:
        selected_controls: dict[str, str] = {}
    elif isinstance(native_controls, dict):
        raw_controls = cast("dict[object, object]", native_controls)
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw_controls.items()
        ):
            raise ValueError("native_controls must map control ids to provider values")
        selected_controls = cast("dict[str, str]", dict(raw_controls))
    else:
        raise ValueError("native_controls must map control ids to provider values")
    validate_current_native_controls(provider, selected_controls)
    return selected_controls


def _native_control_fields(selected_controls: dict[str, str]) -> dict[str, str]:
    """Key admitted native controls by the provider field each one sets.

    Only reached after :func:`validate_current_native_controls`, which refuses an
    unsupported or repeated field for every lane that reads controls this way.
    """
    return {
        control_id.partition(":")[0]: value
        for control_id, value in selected_controls.items()
    }


def _admit_create_options(
    provider: Provider, backend: str | None, kwargs: dict[str, Any]
) -> tuple[Any, AcpBackend | None, dict[str, str]]:
    timeout = kwargs.pop("timeout", settings.provider_timeout_seconds)
    backend = _admit_execution_mode(
        provider, backend, kwargs.pop("execution_mode", None)
    )
    selected_controls = _admit_native_controls(
        provider, kwargs.pop("native_controls", None)
    )
    return timeout, backend, selected_controls


def _create_codex_model(
    model_name: str,
    agent_config: AgentConfig | None,
    workspace_root: Path | None,
    selected_controls: dict[str, str],
    timeout: Any,
) -> BaseChatModel:
    from .codex_chat_model import CodexChatModel

    command = classify_provider_command(Provider.CODEX)
    require_binary_proof(
        codex_binary_proof_reason(command, workspace_root=workspace_root)
    )
    # Codex auth is file-based; no secret env is injected.
    codex_controls = _native_control_fields(selected_controls)
    return CodexChatModel(
        command=list(command.argv),
        model_name=model_name,
        effort=codex_controls.get("reasoning_effort"),
        service_tier=codex_controls.get("service_tier"),
        agent_config=agent_config,
        workspace_root=str(workspace_root) if workspace_root else None,
        codex_home=settings.codex_home,
        timeout=float(timeout),
        provider=str(Provider.CODEX.value),
        execution_mode=EXTERNAL_EXECUTION_MODES[Provider.CODEX],
        provider_command=command,
        version_proof_required=True,
    )


def _require_claude_cli(workspace_root: Path | None) -> ClaudeCliResolution:
    """Refuse construction before a child can inherit an unpinned CLI."""
    env = resolve_env_vars(workspace_root) if workspace_root else dict(os.environ)
    return pin_claude_executable(env)


def _create_claude_model(
    model_name: str,
    agent_config: AgentConfig | None,
    workspace_root: Path | None,
    selected_controls: dict[str, str],
    backend: AcpBackend | None,
) -> BaseChatModel:
    from .acp_chat_model import AcpChatModel

    backend = backend if backend is not None else settings.acp_backend
    logger.debug("[%s] Instantiating ACP Wrapper. backend=%s", Provider.CLAUDE, backend)
    try:
        command = classify_provider_command(Provider.CLAUDE, backend=backend)
    except ConfigError as exc:
        raise ProviderRuntimeUnavailableError(str(exc)) from exc
    cli = _require_claude_cli(workspace_root)
    require_binary_proof(
        binary_proof_reason(
            Provider.CLAUDE, str(cli.path), cli.authority, workspace_root=workspace_root
        )
    )

    env_vars, auth_mode = claude_auth_env()
    use_exec, launch_env = acp_launch_options(backend)
    env_vars.update(launch_env)
    return AcpChatModel(
        command=list(command.argv),
        env_vars=env_vars,
        desired_model=model_name,
        desired_config_options=selected_controls,
        agent_config=agent_config,
        workspace_root=str(workspace_root) if workspace_root else None,
        use_exec=use_exec,
        provider=str(Provider.CLAUDE.value),
        execution_mode=external_execution_mode(Provider.CLAUDE, backend),
        provider_command=command,
        auth_mode=auth_mode,
        version_proof_required=True,
    )


def _create_zai_model(
    model_name: str,
    agent_config: AgentConfig | None,
    workspace_root: Path | None,
    selected_controls: dict[str, str],
    backend: AcpBackend | None,
) -> BaseChatModel:
    from .acp_chat_model import AcpChatModel

    backend = backend if backend is not None else settings.acp_backend
    env_vars, auth_mode = _zai_auth_env()
    logger.debug(
        "[%s] Instantiating ACP Wrapper. auth_mode=%s, backend=%s",
        Provider.ZAI,
        auth_mode,
        backend,
    )
    try:
        command = classify_provider_command(Provider.ZAI, backend=backend)
    except ConfigError as exc:
        raise ProviderRuntimeUnavailableError(str(exc)) from exc
    cli = _require_claude_cli(workspace_root)
    require_binary_proof(
        binary_proof_reason(
            Provider.ZAI, str(cli.path), cli.authority, workspace_root=workspace_root
        )
    )
    use_exec, launch_env = acp_launch_options(backend)
    env_vars.update(launch_env)
    return AcpChatModel(
        command=list(command.argv),
        env_vars=env_vars,
        desired_model=model_name,
        desired_config_options=selected_controls,
        agent_config=agent_config,
        workspace_root=str(workspace_root) if workspace_root else None,
        use_exec=use_exec,
        provider=str(Provider.ZAI.value),
        execution_mode=external_execution_mode(Provider.ZAI, backend),
        provider_command=command,
        auth_mode=auth_mode,
        version_proof_required=True,
    )


def _create_kimi_model(
    model_name: str,
    agent_config: AgentConfig | None,
    workspace_root: Path | None,
    selected_controls: dict[str, str],
) -> BaseChatModel:
    from .acp_chat_model import AcpChatModel

    # The lane's own proof first, before a launcher is resolved: Kimi is
    # unenrolled, so this refuses every construction today.
    require_binary_proof(kimi_binary_proof_reason(workspace_root=workspace_root))
    # The exact catalog alias travels through Kimi's own -m option.
    classified = classify_provider_command(Provider.KIMI)
    command = [classified.argv[0], "-m", model_name, *classified.argv[1:]]
    api_key = (
        settings.kimi_api_key.get_secret_value() if settings.kimi_api_key else None
    )
    env_vars = _build_kimi_env(
        kimi_api_key=api_key,
        kimi_base_url=settings.kimi_base_url,
        kimi_temporary_model_name=settings.kimi_temporary_model_name,
        kimi_temporary_model_max_context_size=(
            settings.kimi_temporary_model_max_context_size
        ),
        kimi_temporary_model_capabilities=settings.kimi_temporary_model_capabilities,
        kimi_thinking_effort=_native_control_fields(selected_controls).get(
            "thinking_effort"
        ),
    )
    if KIMI_API_KEY_ENV not in env_vars:
        # A served run reads an isolated home that carries no persisted login,
        # so there is no configuration for a run to authenticate from. Refused
        # before spawn rather than left to fail inside the child, and never by
        # handing the child the operator's own home back. Same reason text
        # readiness reports for the identical absence (provider_readiness.py
        # ``_kimi_configuration``), so the two never read differently.
        raise ProviderRuntimeUnavailableError(KIMI_NO_TEMPORARY_MODEL_REASON)
    # Per-run isolation: the operator's home holds their own provider table and
    # every ambient MCP server they configured, and an agent's tool surface must
    # be exactly the declared set. ``AcpChatModel`` builds and tears down its
    # own fresh ``KIMI_CODE_HOME`` for every session (``acp_chat_model.py``),
    # so this construction never bakes a single home into ``env_vars`` that a
    # later turn on the same model instance could outlive.
    logger.debug("[%s] Instantiating Kimi ACP agent.", Provider.KIMI)
    return AcpChatModel(
        command=command,
        env_vars=env_vars,
        agent_config=agent_config,
        workspace_root=str(workspace_root) if workspace_root else None,
        provider=str(Provider.KIMI.value),
        execution_mode=EXTERNAL_EXECUTION_MODES[Provider.KIMI],
        acp_family="kimi",
        provider_command=classified,
        auth_mode="temporary_model",
    )


def _create_openai_compatible_model(
    provider: Provider, model_name: str, timeout: Any, kwargs: dict[str, Any]
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if provider == Provider.ZHIPU:
        setting_key = settings.zhipu_api_key
        env_name = foreign_credential("zhipu_api_key").env_name
        base_url = "https://open.bigmodel.cn/api/paas/v4/"
    elif provider == Provider.OPENAI:
        setting_key = settings.openai_api_key
        env_name = foreign_credential("openai_api_key").env_name
        base_url = settings.openai_base_url
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    auth_resolved = (
        "kwargs" if "api_key" in kwargs else env_name if setting_key else None
    )
    api_key = kwargs.pop("api_key", None) or setting_key
    if not api_key:
        logger.error("Failed to authenticate %s: Missing %s", provider, env_name)
        raise ValueError(f"Authentication required for {provider}")
    logger.debug("[%s] Resolved authentication via: %s", provider, auth_resolved)
    kwargs["api_key"] = api_key
    kwargs["model"] = model_name
    kwargs["base_url"] = base_url
    kwargs["timeout"] = timeout
    kwargs["max_retries"] = 2
    return ChatOpenAI(**kwargs)


class ProviderFactory:
    """Factory for instantiating LangChain chat models for different providers."""

    def __init__(self) -> None:
        # Resolving the in-process lane set here makes a lane plugin that cannot
        # be honoured refuse the process that builds its factory at startup,
        # rather than surface at the first run that reaches a lane.
        registered_lanes()

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
            settings.serve_in_process_lanes
            if serve_in_process_lanes is None
            else serve_in_process_lanes
        )
        claude = _external_catalog_key(Provider.CLAUDE)
        codex = _external_catalog_key(Provider.CODEX)
        antigravity = _external_catalog_key(Provider.ANTIGRAVITY)
        kimi = _external_catalog_key(Provider.KIMI)
        openai = _external_catalog_key(Provider.OPENAI)
        zai = _external_catalog_key(Provider.ZAI)
        zhipu = _external_catalog_key(Provider.ZHIPU)
        in_process = tuple(
            # ``key=key`` binds this iteration's lane into the callback; a bare
            # closure over the loop variable would give every registration the
            # last lane's identity, and the loader fences a mismatched key.
            ProviderCatalogRegistration(
                key, lambda key=key: _discover_in_process_catalog(key)
            )
            for key in served_in_process_lanes(armed=armed)
        )
        return (
            ProviderCatalogRegistration(
                antigravity,
                lambda: _discover_antigravity_catalog(antigravity, discovery_root),
            ),
            ProviderCatalogRegistration(
                claude,
                lambda: _discover_claude_family_catalog(
                    Provider.CLAUDE, claude, discovery_root
                ),
                lambda: _claude_binary_proof_reason(Provider.CLAUDE, discovery_root),
            ),
            ProviderCatalogRegistration(
                codex,
                lambda: _discover_codex_catalog(codex, discovery_root),
                lambda: codex_binary_proof_reason(workspace_root=discovery_root),
            ),
            ProviderCatalogRegistration(
                kimi, lambda: _discover_kimi_catalog(kimi, discovery_root)
            ),
            ProviderCatalogRegistration(
                openai, lambda: _discover_openai_catalog(openai)
            ),
            ProviderCatalogRegistration(
                zai,
                lambda: _discover_claude_family_catalog(
                    Provider.ZAI, zai, discovery_root
                ),
                lambda: _claude_binary_proof_reason(Provider.ZAI, discovery_root),
            ),
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
        model: str,
        *,
        agent_config: AgentConfig | None = None,
        workspace_root: Path | None = None,
        backend: str | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Create a configured BaseChatModel for the given provider.

        Args:
            provider: The exact supported LLM provider selected by the caller.
            model: Exact model string frozen from a served catalog.
            agent_config: Optional agent configuration for provider initialization.
            workspace_root: Optional workspace root for ACP sandbox scoping.
            backend: ACP backend override (``"node"`` or ``"binary"``). When
                ``None`` the value from ``settings.acp_backend`` is used. Pass
                an explicit value to select a backend without mutating global
                settings (useful in tests and factory call sites that need
                non-default behaviour).
            kwargs: ``execution_mode``, ``native_controls`` and ``timeout``
                select the frozen lane, its native controls and the call
                deadline; anything else is a client override for the
                OpenAI-compatible providers.

        Returns:
            A LangChain BaseChatModel implementation.
        """
        timeout, backend, selected_controls = _admit_create_options(
            provider, backend, kwargs
        )

        # Admission: refuse an unsupported provider and resolve its model name
        # before any construction begins, so a bad request fails clearly rather
        # than partway through building a model.
        model_name = _admit_and_resolve_model_name(provider, model)

        logger.info(
            "Instantiating ProviderFactory for provider=%s, resolved_model=%s",
            provider,
            model_name,
        )

        lane = in_process_lane(provider)
        if lane is not None:
            return lane.create_model(agent_config)

        if provider == Provider.CODEX:
            return _create_codex_model(
                model_name, agent_config, workspace_root, selected_controls, timeout
            )

        if provider == Provider.CLAUDE:
            return _create_claude_model(
                model_name, agent_config, workspace_root, selected_controls, backend
            )

        if provider == Provider.ZAI:
            return _create_zai_model(
                model_name, agent_config, workspace_root, selected_controls, backend
            )

        if provider == Provider.KIMI:
            return _create_kimi_model(
                model_name, agent_config, workspace_root, selected_controls
            )

        if provider in {Provider.ZHIPU, Provider.OPENAI}:
            return _create_openai_compatible_model(
                provider, model_name, timeout, kwargs
            )

        logger.error("Failed to instantiate: Unsupported provider %s", provider)
        raise ValueError(f"Unsupported provider: {provider}")
