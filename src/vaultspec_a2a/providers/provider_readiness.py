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
from .cli_resolution import ProviderRuntimeUnavailableError
from .in_process_catalog import in_process_lane
from .provider_catalog import HealthState

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ..context.harness import HarnessReadiness

__all__ = [
    "KIMI_NO_TEMPORARY_MODEL_REASON",
    "probe_harness_ready",
    "probe_provider_configuration",
    "probe_provider_readiness",
]

logger = logging.getLogger(__name__)

KIMI_NO_TEMPORARY_MODEL_REASON = (
    "the Kimi lane runs in a per-run configuration home, which carries "
    "no persisted login: configure the temporary model definition "
    "(KIMI_MODEL_NAME, KIMI_MODEL_API_KEY, KIMI_MODEL_BASE_URL) for this "
    "lane to authenticate"
)
"""Why Kimi refuses construction with no temporary-model definition.

Shared verbatim between this probe's :func:`_kimi_configuration` and
``factory._create_kimi_model``'s own construction-time refusal, so the two
can never read differently for the same environment (PV06's per-run
isolation left Kimi with no ambient credential a served run can fall back
to, so there is exactly one way this lane authenticates and exactly one
reason string for its absence).
"""


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
    # Under PV06's per-run isolation the factory always launches Kimi inside a
    # fresh, empty config home, so ``settings.kimi_code_home`` (read only for
    # prompt-free catalog discovery against the OPERATOR's own home) names no
    # credential a served run could ever authenticate from. Only the temporary
    # model definition does, so readiness reads exactly that - the same
    # presence check the factory's own construction refusal is built on - and
    # never the operator's home. Only a partial definition is refused as
    # malformed; a fully absent one is refused the same way the factory
    # refuses construction, with its exact reason.
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
    if _has_text(key):
        return _ProviderConfiguration(state=HealthState.AVAILABLE)
    return _ProviderConfiguration(
        state=HealthState.UNAVAILABLE, reason=KIMI_NO_TEMPORARY_MODEL_REASON
    )


def _claude_configuration() -> _ProviderConfiguration:
    """Read the declared Claude auth channel's own verdict on its credential.

    Which credential Claude is configured with is the channel selector's
    decision, and that selector already exists at the lane's root seam. It is
    asked here rather than re-derived, so the channel this probe reports
    configured is exactly the channel a served turn would launch under: a
    re-reading of the same settings would be a second definition of what a
    configured Claude is, and the two would disagree the moment a channel
    changed.

    The selector's own refusal - a declared channel with nothing to present -
    is the UNAVAILABLE reason, and its sentence is safe by construction (it
    names the channel and the setting, never a value). A channel that resolves
    to no explicit credential is the ambient case: the CLI runs on its own
    persisted login, which this probe cannot read, so it answers UNKNOWN
    rather than claiming either way. The returned credential is inspected for
    presence and discarded; nothing is logged and no value leaves this call.

    Imported at call time: the root seam's module reads this probe for its other
    lanes.
    """
    from .factory import claude_auth_env

    try:
        auth_env, _channel = claude_auth_env()
    except ProviderRuntimeUnavailableError as exc:
        return _ProviderConfiguration(state=HealthState.UNAVAILABLE, reason=str(exc))
    if any(_has_text(value) for value in auth_env.values()):
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
    if provider == Provider.CLAUDE:
        return _claude_configuration()
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
        # This layer does not inspect CLI authentication. Where a lane's declared
        # channel supplies no explicit credential the CLI runs on its own
        # persisted login, which the configuration probe above reports as
        # UNKNOWN rather than missing. Each lane needs a resolvable command.
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
