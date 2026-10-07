"""Provider and harness readiness probes without model selection policy."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..control.config import settings
from ..control.provider_execution import native_execution_refusal_reason
from ..graph.enums import Provider
from ..thread.errors import ConfigError
from ._factory_commands import (
    COMMAND_LANES,
    classify_provider_command,
    kimi_temporary_model_configuration_reason,
)
from .in_process_catalog import in_process_lane
from .provider_catalog import HealthState

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ..context.harness import HarnessReadiness

__all__ = [
    "probe_harness_ready",
    "probe_provider_configuration",
    "probe_provider_readiness",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ProviderReadiness:
    """No-instantiation readiness verdict for one provider. Never holds a secret."""

    provider: Provider
    ready: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ProviderConfiguration:
    """Whether one lane's own settings are present. Never holds a secret.

    ``state`` is ``AVAILABLE`` when the settings the lane reads are present,
    ``UNAVAILABLE`` when they are missing or contradict each other, and
    ``UNKNOWN`` when the lane configures itself from state this probe does not
    read, such as an ambient or persisted CLI login. ``reason`` is set exactly
    when the state is ``UNAVAILABLE``, and names what is missing.

    Presence is all this answers. A configured lane can still fail
    authentication, and serving it also takes its completed-turn proof and
    binary identity, which are judged elsewhere.
    """

    state: HealthState
    reason: str | None = None


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _present(present: bool, missing: str) -> _ProviderConfiguration:
    if present:
        return _ProviderConfiguration(state=HealthState.AVAILABLE)
    return _ProviderConfiguration(state=HealthState.UNAVAILABLE, reason=missing)


def _kimi_configuration() -> _ProviderConfiguration:
    # Without a temporary definition Kimi runs on its persisted config or device
    # session, which this probe cannot read; an explicit home names where that
    # state lives. Only a partial definition is a refusal.
    key = settings.kimi_api_key.get_secret_value() if settings.kimi_api_key else None
    reason = kimi_temporary_model_configuration_reason(
        kimi_api_key=key,
        kimi_base_url=settings.kimi_base_url,
        kimi_temporary_model_name=settings.kimi_temporary_model_name,
        kimi_temporary_model_max_context_size=settings.kimi_temporary_model_max_context_size,
        kimi_temporary_model_capabilities=settings.kimi_temporary_model_capabilities,
    )
    if reason is not None:
        return _ProviderConfiguration(state=HealthState.UNAVAILABLE, reason=reason)
    if _has_text(key) or _has_text(settings.kimi_code_home):
        return _ProviderConfiguration(state=HealthState.AVAILABLE)
    return _ProviderConfiguration(state=HealthState.UNKNOWN)


def probe_provider_configuration(provider: Provider) -> _ProviderConfiguration:
    """Report whether ``provider``'s own settings are present.

    Readiness gates on this answer and catalog discovery serves it as the lane's
    ``configured`` axis, so neither restates what configured means for a lane
    read here. Only presence is read: no credential value leaves this function,
    and nothing is resolved or spawned. A lane whose configuration lives outside
    these settings answers ``UNKNOWN``.
    """
    if provider == Provider.OPENAI:
        return _present(
            _has_text(settings.openai_api_key), "no OpenAI API key configured"
        )
    if provider == Provider.ZHIPU:
        return _present(
            _has_text(settings.zhipu_api_key), "no Zhipu API key configured"
        )
    if provider == Provider.ZAI:
        return _present(
            _has_text(settings.zai_auth_token), "no Z.ai auth token configured"
        )
    if provider == Provider.KIMI:
        return _kimi_configuration()
    return _ProviderConfiguration(state=HealthState.UNKNOWN)


def probe_provider_readiness(provider: Provider) -> _ProviderReadiness:
    """Report whether ``provider`` is runnable without instantiating anything.

    Profile execution authority, then presence/resolvability (never quota
    headroom): the lane's configuration (:func:`probe_provider_configuration`)
    and a resolvable command. Credentials and commands are
    workspace-independent, so no workspace is taken. The reason string is safe -
    it names what is missing, never a secret value.
    """
    if provider in COMMAND_LANES:
        # The desktop profile refuses every lane launched as a native subprocess.
        reason = native_execution_refusal_reason()
        if reason is not None:
            return _ProviderReadiness(provider=provider, ready=False, reason=reason)
    if in_process_lane(provider) is not None:
        # A held in-process lane needs no credential or launch command.
        return _ProviderReadiness(provider=provider, ready=True)

    # A missing configuration is refused before any command is resolved.
    configuration = probe_provider_configuration(provider)
    if configuration.reason is not None:
        return _ProviderReadiness(
            provider=provider, ready=False, reason=configuration.reason
        )

    if provider in COMMAND_LANES:
        # This layer does not inspect CLI authentication. Claude inherits ambient
        # auth; Codex uses its persisted session. Each needs a resolvable command.
        return _command_readiness(provider)

    if provider in (Provider.OPENAI, Provider.ZHIPU):
        return _ProviderReadiness(provider=provider, ready=True)

    return _ProviderReadiness(
        provider=provider, ready=False, reason=f"unsupported provider {provider.value}"
    )


def _command_readiness(provider: Provider) -> _ProviderReadiness:
    """Check a subprocess provider's command resolves via the factory classifier.

    The reason string is path-free by construction: the classifier's exception can
    name a filesystem path (an ACP entry point, node_modules), so it is logged but
    never surfaced in the served reason.
    """
    try:
        classify_provider_command(provider)
    except (ValueError, ConfigError, FileNotFoundError) as exc:
        detail = str(exc)
    else:
        return _ProviderReadiness(provider=provider, ready=True)
    logger.debug("provider %s command not resolvable: %s", provider.value, detail)
    return _ProviderReadiness(
        provider=provider,
        ready=False,
        reason="provider launch command is not installed or resolvable",
    )


def probe_harness_ready(
    workspace_root: Path,
    *,
    required_skills: Sequence[str] = (),
) -> HarnessReadiness:
    """Verify a workspace's authoring harness for the shared eligibility service.

    Thin wrapper over :func:`context.harness.verify_harness` co-located with the
    other readiness probes so discovery and run-start reach every readiness term
    through one module. ``required_skills`` is the run's declared harness skills
    list (the ``[team.harness]`` schema supplies it); the canonical authoring
    templates are always required. Read-only: no write, no CLI spawn, no secret.

    The verifier is imported lazily: ``context`` pulls in the graph/thread import
    graph, and readiness is imported during graph compilation, so
    a top-level import would close a cycle.
    """
    from ..context.harness import verify_harness

    return verify_harness(workspace_root, required_skills=required_skills)
