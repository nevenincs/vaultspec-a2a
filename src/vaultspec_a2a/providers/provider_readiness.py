"""Provider and harness readiness probes without model selection policy."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..control.config import settings
from ..graph.enums import Provider
from ..thread.errors import ConfigError
from .factory import (
    classify_provider_command,
    kimi_temporary_model_configuration_reason,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ..context.harness import HarnessReadiness

__all__ = [
    "ProviderReadiness",
    "probe_harness_ready",
    "probe_provider_readiness",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    """No-instantiation readiness verdict for one provider. Never holds a secret."""

    provider: Provider
    ready: bool
    reason: str | None = None


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def probe_provider_readiness(provider: Provider) -> ProviderReadiness:
    """Report whether ``provider`` is runnable without instantiating anything.

    Presence/resolvability only (never quota headroom): a configured credential
    and, for the subprocess providers, a resolvable command. Credentials and
    commands are workspace-independent, so no workspace is taken. The reason
    string is safe - it names what is missing, never a secret value.
    """
    if provider in (Provider.MOCK, Provider.DETERMINISTIC):
        # Neither provider needs a credential or launch command. This readiness
        # probe says construction can proceed, not that MOCK's external tape
        # server is reachable or that it can satisfy the completion floor.
        return ProviderReadiness(provider=provider, ready=True)

    if provider == Provider.CLAUDE:
        # No credential term, by contract: this layer implements no
        # authentication and reads no credential. The spawned CLI inherits the
        # ambient environment and resolves whatever auth the operator has (a
        # logged-in session, a key in the env); if nothing authenticates it, the
        # provider itself says so at run time. Readiness is therefore command
        # resolvability only, the same shape as Codex.
        return _command_readiness(provider)

    if provider == Provider.OPENAI:
        if not _has_text(settings.openai_api_key):
            return ProviderReadiness(
                provider=provider, ready=False, reason="no OpenAI API key configured"
            )
        return ProviderReadiness(provider=provider, ready=True)

    if provider == Provider.CODEX:
        # Codex auth is a file-based persisted session in the Codex home, not a
        # configured secret, so readiness is command resolvability only — the
        # probe never spawns the CLI or reads the session file.
        return _command_readiness(provider)

    if provider == Provider.ZAI:
        if not _has_text(settings.zai_auth_token):
            return ProviderReadiness(
                provider=provider,
                ready=False,
                reason="no Z.ai auth token configured",
            )
        return _command_readiness(provider)

    if provider == Provider.ZHIPU:
        if not _has_text(settings.zhipu_api_key):
            return ProviderReadiness(
                provider=provider, ready=False, reason="no Zhipu API key configured"
            )
        return ProviderReadiness(provider=provider, ready=True)

    if provider == Provider.KIMI:
        # No temporary definition means persisted-config/device-session mode and
        # is eligible for the later provider-list probe. A complete temporary
        # definition is also eligible. Partial definitions fail before launch;
        # neither case is authentication or completed-turn proof.
        key = (
            settings.kimi_api_key.get_secret_value() if settings.kimi_api_key else None
        )
        reason = kimi_temporary_model_configuration_reason(
            kimi_api_key=key,
            kimi_base_url=settings.kimi_base_url,
            kimi_temporary_model_name=settings.kimi_temporary_model_name,
            kimi_temporary_model_max_context_size=(
                settings.kimi_temporary_model_max_context_size
            ),
            kimi_temporary_model_capabilities=(
                settings.kimi_temporary_model_capabilities
            ),
        )
        if reason is not None:
            return ProviderReadiness(
                provider=provider,
                ready=False,
                reason=reason,
            )
        return _command_readiness(provider)

    return ProviderReadiness(
        provider=provider, ready=False, reason=f"unsupported provider {provider.value}"
    )


def _command_readiness(provider: Provider) -> ProviderReadiness:
    """Check a subprocess provider's command resolves via the factory classifier.

    The reason string is path-free by construction: the classifier's exception can
    name a filesystem path (an ACP entry point, node_modules), so it is logged but
    never surfaced in the served reason.
    """
    try:
        classify_provider_command(provider)
    except (ValueError, ConfigError, FileNotFoundError) as exc:
        logger.debug("provider %s command not resolvable: %s", provider.value, exc)
        return ProviderReadiness(
            provider=provider,
            ready=False,
            reason="provider launch command is not installed or resolvable",
        )
    return ProviderReadiness(provider=provider, ready=True)


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
