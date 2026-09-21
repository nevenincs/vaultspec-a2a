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
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from langchain_core.language_models import BaseChatModel

    from ..team.team_config import AgentConfig

from ..control.config import settings
from ..graph.enums import Provider
from ..thread.errors import ConfigError
from ..workspace.environment import resolve_env_vars
from ._factory_commands import (
    _build_kimi_env,
    _build_zai_env,
    _classify_acp_command,
    _classify_codex_command,
    _classify_kimi_command,
    _kimi_home_env,
)
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
    "ProviderCatalogDiscovery",
    "ProviderCatalogRegistration",
    "ProviderFactory",
    "ProviderRuntimeUnavailableError",
    "UnsupportedExecutionLaneError",
    "validate_current_execution_lane",
    "validate_current_native_controls",
]


class UnsupportedExecutionLaneError(ValueError):
    """A frozen provider/mode pair is outside the current execution inventory."""


class ProviderRuntimeUnavailableError(ConfigError):
    """A structurally valid frozen lane cannot be constructed right now."""


def validate_current_execution_lane(provider: Provider, execution_mode: str) -> None:
    """Refuse a structurally impossible provider/mode pair without construction."""
    expected_modes = {
        Provider.ANTIGRAVITY: "antigravity-cli",
        Provider.CODEX: "codex-app-server",
        Provider.CLAUDE: f"claude-agent-acp:{settings.acp_backend}",
        Provider.ZAI: f"zai-claude-agent-acp:{settings.acp_backend}",
        Provider.KIMI: "kimi-code-acp",
        Provider.OPENAI: "openai-api",
        Provider.ZHIPU: "zhipu-openai-compatible-api",
        Provider.DETERMINISTIC: IN_PROCESS_EXECUTION_MODES[Provider.DETERMINISTIC],
        Provider.MOCK: IN_PROCESS_EXECUTION_MODES[Provider.MOCK],
    }
    if expected_modes.get(provider) != execution_mode:
        raise UnsupportedExecutionLaneError(
            f"Provider {provider.value!r} cannot execute mode {execution_mode!r}"
        )


def validate_current_native_controls(
    provider: Provider, controls: dict[str, str]
) -> None:
    """Validate provider-specific frozen control structure before construction."""
    no_control_lanes = {
        Provider.DETERMINISTIC,
        Provider.MOCK,
        Provider.OPENAI,
        Provider.ZHIPU,
    }
    if provider in no_control_lanes and controls:
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


_SUPPORTED_PROVIDERS: frozenset[Provider] = frozenset(
    {
        Provider.CLAUDE,
        Provider.CODEX,
        Provider.DETERMINISTIC,
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
            kimi_temporary_model_max_context_size=(
                settings.kimi_temporary_model_max_context_size
            ),
            kimi_temporary_model_capabilities=(
                settings.kimi_temporary_model_capabilities
            ),
        )
        injected.update(_kimi_home_env(settings.kimi_code_home))
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
    if provider not in _SUPPORTED_PROVIDERS:
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
) -> str | None:
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


def _admit_create_options(
    provider: Provider, backend: str | None, kwargs: dict[str, Any]
) -> tuple[Any, str | None, dict[str, str]]:
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

    command, command_meta = _classify_codex_command()
    # Codex auth is file-based; no secret env is injected.
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
        provider=str(Provider.CODEX.value),
        runtime_authority=command_meta["runtime_authority"],
        command_origin=command_meta["command_origin"],
        command_kind=command_meta["command_kind"],
        command_executable=command_meta["command_executable"],
        command_target=command_meta["command_target"],
    )


def _create_claude_model(
    model_name: str,
    agent_config: AgentConfig | None,
    workspace_root: Path | None,
    selected_controls: dict[str, str],
    backend: str | None,
) -> BaseChatModel:
    from .acp_chat_model import AcpChatModel

    backend = backend if backend is not None else settings.acp_backend
    logger.debug("[%s] Instantiating ACP Wrapper. backend=%s", Provider.CLAUDE, backend)
    try:
        command, command_meta = _classify_acp_command(backend)
    except ConfigError as exc:
        raise ProviderRuntimeUnavailableError(str(exc)) from exc

    # The CLI inherits ambient authentication; this lane injects no credential.
    env_vars: dict[str, str] = {}
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
        provider=str(Provider.CLAUDE.value),
        runtime_authority=command_meta["runtime_authority"],
        command_origin=command_meta["command_origin"],
        command_kind=command_meta["command_kind"],
        command_executable=command_meta["command_executable"],
        command_target=command_meta["command_target"],
        acp_backend=command_meta["acp_backend"],
        auth_mode="ambient",
    )


def _create_zai_model(
    model_name: str,
    agent_config: AgentConfig | None,
    workspace_root: Path | None,
    selected_controls: dict[str, str],
    backend: str | None,
) -> BaseChatModel:
    from .acp_chat_model import AcpChatModel

    backend = backend if backend is not None else settings.acp_backend
    auth_token = settings.zai_auth_token
    logger.debug(
        "[%s] Instantiating ACP Wrapper. Auth token present: %s, backend=%s",
        Provider.ZAI,
        bool(auth_token and auth_token.strip()),
        backend,
    )
    try:
        command, command_meta = _classify_acp_command(backend)
    except ConfigError as exc:
        raise ProviderRuntimeUnavailableError(str(exc)) from exc
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
        provider=str(Provider.ZAI.value),
        runtime_authority=command_meta["runtime_authority"],
        command_origin=command_meta["command_origin"],
        command_kind=command_meta["command_kind"],
        command_executable=command_meta["command_executable"],
        command_target=command_meta["command_target"],
        acp_backend=command_meta["acp_backend"],
        auth_mode=(
            "zai_auth_token" if "ANTHROPIC_AUTH_TOKEN" in env_vars else "none_detected"
        ),
    )


def _create_kimi_model(
    model_name: str,
    agent_config: AgentConfig | None,
    workspace_root: Path | None,
    selected_controls: dict[str, str],
) -> BaseChatModel:
    from .acp_chat_model import AcpChatModel

    # The exact catalog alias travels through Kimi's own -m option.
    base_command, command_meta = _classify_kimi_command()
    command = [base_command[0], "-m", model_name, *base_command[1:]]
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
    )
    env_vars.update(_kimi_home_env(settings.kimi_code_home))
    kimi_effort: str | None = None
    for control_id, value in selected_controls.items():
        if control_id.partition(":")[0] != "thinking_effort":
            raise ValueError(f"Unsupported Kimi native control {control_id!r}")
        if kimi_effort is not None:
            raise ValueError("Duplicate Kimi thinking-effort control")
        kimi_effort = value
    if kimi_effort is not None:
        env_vars["KIMI_MODEL_THINKING_EFFORT"] = kimi_effort
    logger.debug(
        "[%s] Instantiating Kimi ACP agent. Temporary definition present: %s",
        Provider.KIMI,
        "KIMI_MODEL_API_KEY" in env_vars,
    )
    return AcpChatModel(
        command=command,
        env_vars=env_vars,
        agent_config=agent_config,
        workspace_root=str(workspace_root) if workspace_root else None,
        provider=str(Provider.KIMI.value),
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


def _create_openai_compatible_model(
    provider: Provider, model_name: str, timeout: Any, kwargs: dict[str, Any]
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if provider == Provider.ZHIPU:
        setting_key = settings.zhipu_api_key
        env_name = "ZHIPU_API_KEY"
        base_url = "https://open.bigmodel.cn/api/paas/v4/"
    elif provider == Provider.OPENAI:
        setting_key = settings.openai_api_key
        env_name = "OPENAI_API_KEY"
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


def _create_in_process_model(
    provider: Provider, agent_config: AgentConfig | None, kwargs: dict[str, Any]
) -> BaseChatModel:
    if provider == Provider.MOCK:
        from .mock_chat_model import MockChatModel

        return MockChatModel(agent_config=agent_config)
    if provider != Provider.DETERMINISTIC:
        raise ValueError(f"Unsupported provider: {provider}")
    from .deterministic_chat_model import DeterministicResearchAdrChatModel

    det_kwargs = {key: kwargs[key] for key in ("feature_tag", "topic") if key in kwargs}
    return DeterministicResearchAdrChatModel(agent_config=agent_config, **det_kwargs)


def _bind_create_options(
    args: tuple[object, ...], kwargs: dict[str, Any]
) -> tuple[AgentConfig | None, Path | None, str | None]:
    names = ("agent_config", "workspace_root", "backend")
    if len(args) > len(names):
        raise TypeError(
            f"create() takes at most {len(names) + 2} positional arguments "
            f"({len(args) + 2} given)"
        )
    bound: list[object | None] = []
    for index, name in enumerate(names):
        if index < len(args):
            if name in kwargs:
                raise TypeError(f"create() got multiple values for argument {name!r}")
            bound.append(args[index])
        else:
            bound.append(kwargs.pop(name, None))
    return (
        cast("AgentConfig | None", bound[0]),
        cast("Path | None", bound[1]),
        cast("str | None", bound[2]),
    )


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
        model: str,
        *args: object,
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
            kwargs: Additional overrides for the specific provider.

        Returns:
            A LangChain BaseChatModel implementation.
        """
        agent_config, workspace_root, backend = _bind_create_options(args, kwargs)
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

        if provider in {Provider.MOCK, Provider.DETERMINISTIC}:
            return _create_in_process_model(provider, agent_config, kwargs)

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

        if selected_controls:
            raise ValueError(
                f"Provider {provider.value!r} has no exact native-control executor"
            )

        if provider in {Provider.ZHIPU, Provider.OPENAI}:
            return _create_openai_compatible_model(
                provider, model_name, timeout, kwargs
            )

        logger.error("Failed to instantiate: Unsupported provider %s", provider)
        raise ValueError(f"Unsupported provider: {provider}")
