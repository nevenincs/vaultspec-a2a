"""Shared model-profile resolution and backend-served eligibility (model-profiles ADR).

One resolution-and-eligibility service consumed by graph compilation, discovery,
and run-start alike, so the picker's truth cannot drift from execution's. It
owns three concerns:

- **Resolution**: ``resolve_effective_assignment`` and the per-role
  ``resolve_role_assignment`` implement the ADR-013 S2.3 precedence chain with a
  selected profile as the topmost layer (profile > worker override > agent TOML
  > team defaults), attaching per-field source attribution and the stable,
  safe-to-expose concrete model name.
- **Readiness**: ``probe_provider_readiness`` answers "is this provider runnable"
  WITHOUT instantiating anything - credential presence from settings and command
  resolvability via the factory's classifiers. ``probe_engine_reachable`` checks
  the authoring backend via the discovery contract. Neither emits a secret.
- **Eligibility**: ``evaluate_profile_eligibility`` composes readiness into
  per-role and per-profile eligibility with safe reasons, including the
  production acceptance-gate term reported honestly (unavailable until it
  passes).

This module lives in ``providers`` because the graph compiler consumes the
resolver and cannot import ``control`` (that would cycle), while ``team`` cannot
host the readiness probe (it would cycle with ``providers``). Providers is the
one layer that is both graph-importable and owns provider readiness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from ..control.config import settings
from ..graph.enums import MODEL_MAP, PROVIDER_DEFAULT_MODELS, Model, Provider
from ..team.team_config import (
    DEFAULT_PROFILE_ID,
    AgentConfig,
    TeamConfig,
    TeamProfileRoleConfig,
    WorkerRef,
    load_agent_config,
)
from ..thread.errors import AgentConfigNotFoundError, ConfigError
from .factory import classify_provider_command

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "AssignmentSource",
    "ProfileAssignment",
    "ProfileEligibility",
    "ProviderReadiness",
    "RoleAssignment",
    "RoleEligibility",
    "acceptance_gate_reason",
    "evaluate_profile_eligibility",
    "probe_engine_reachable",
    "probe_provider_readiness",
    "resolve_effective_assignment",
    "resolve_role_assignment",
]

logger = logging.getLogger(__name__)

# The hardcoded final provider fallback when no layer sets a provider (mirrors
# the compiler's historical default).
_DEFAULT_PROVIDER = Provider.CLAUDE

# The production acceptance-gate term (ADR: still open until the research-to-ADR
# capability passes P04.S10). Reported honestly as an ineligibility reason.
_ACCEPTANCE_GATE_REASON = (
    "production acceptance gate for the research-to-ADR capability has not passed"
)


def acceptance_gate_reason() -> str:
    """Return the honest ineligibility reason while the acceptance gate is open."""
    return _ACCEPTANCE_GATE_REASON


class AssignmentSource(StrEnum):
    """Which precedence layer a resolved value came from (ADR exposure field)."""

    PROFILE = "profile"
    WORKER = "worker"
    AGENT = "agent"
    TEAM_DEFAULT = "team_default"


# Precedence rank (lower wins) for collapsing per-field sources to one coarse
# source that reports the topmost layer influencing a role's assignment.
_SOURCE_RANK: dict[AssignmentSource, int] = {
    AssignmentSource.PROFILE: 0,
    AssignmentSource.WORKER: 1,
    AssignmentSource.AGENT: 2,
    AssignmentSource.TEAM_DEFAULT: 3,
}


@dataclass(frozen=True, slots=True)
class RoleAssignment:
    """The resolved effective model assignment for one role, with attribution.

    Holds provider/capability as enums (the resolver's source of truth) plus the
    stable concrete ``model_name`` that is safe to expose. Never carries a
    credential, token, env value, or path.
    """

    role_id: str
    agent_id: str
    provider: Provider
    capability: Model | None
    model_name: str
    fallback_providers: list[Provider]
    provider_source: AssignmentSource
    capability_source: AssignmentSource
    # None when the worker's agent TOML could not be resolved (an eligibility
    # signal surfaced rather than raised).
    resolution_error: str | None = None

    @property
    def source(self) -> AssignmentSource:
        """The coarse assignment source: the topmost layer that shaped this role.

        Collapses the per-field ``provider_source`` and ``capability_source`` to
        the higher-precedence of the two, so a capability-only profile overlay is
        reported as ``profile`` (it did change the effective model) rather than
        hiding behind the provider's lower-layer source.
        """
        if _SOURCE_RANK[self.capability_source] < _SOURCE_RANK[self.provider_source]:
            return self.capability_source
        return self.provider_source


@dataclass(frozen=True, slots=True)
class ProfileAssignment:
    """The complete effective per-role assignment for a selected profile."""

    profile_id: str
    roles: list[RoleAssignment]


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    """No-instantiation readiness verdict for one provider. Never holds a secret."""

    provider: Provider
    ready: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RoleEligibility:
    """Per-role eligibility: the primary provider is ready or an eligible fallback."""

    role_id: str
    agent_id: str
    eligible: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileEligibility:
    """Per-profile eligibility composed from per-role readiness and gate terms."""

    profile_id: str
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    roles: list[RoleEligibility] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_role_assignment(
    worker_ref: WorkerRef,
    agent_config: AgentConfig,
    team_config: TeamConfig,
    profile_overlay: TeamProfileRoleConfig | None = None,
) -> RoleAssignment:
    """Resolve one role's effective assignment with profile-topped precedence.

    Precedence (highest to lowest): selected profile overlay > ``[[team.workers]]``
    override > agent TOML ``[agent.model]`` > ``[team.defaults]``. Each of
    provider, capability, and fallback resolves independently, so a partial
    overlay only redirects the fields it sets. With ``profile_overlay=None`` this
    is byte-identical to the historical ADR-013 chain.
    """
    overlay = profile_overlay

    provider: Provider
    provider_source: AssignmentSource
    if overlay is not None and overlay.provider is not None:
        provider, provider_source = overlay.provider, AssignmentSource.PROFILE
    elif worker_ref.model.provider is not None:
        provider, provider_source = worker_ref.model.provider, AssignmentSource.WORKER
    elif agent_config.model.provider is not None:
        provider, provider_source = agent_config.model.provider, AssignmentSource.AGENT
    elif team_config.defaults.provider is not None:
        provider = team_config.defaults.provider
        provider_source = AssignmentSource.TEAM_DEFAULT
    else:
        provider, provider_source = _DEFAULT_PROVIDER, AssignmentSource.TEAM_DEFAULT

    capability: Model | None
    capability_source: AssignmentSource
    if overlay is not None and overlay.capability is not None:
        capability, capability_source = overlay.capability, AssignmentSource.PROFILE
    elif worker_ref.model.capability is not None:
        capability = worker_ref.model.capability
        capability_source = AssignmentSource.WORKER
    elif agent_config.model.capability is not None:
        capability = agent_config.model.capability
        capability_source = AssignmentSource.AGENT
    elif team_config.defaults.capability is not None:
        capability = team_config.defaults.capability
        capability_source = AssignmentSource.TEAM_DEFAULT
    else:
        capability, capability_source = None, AssignmentSource.TEAM_DEFAULT

    if overlay is not None and overlay.provider_fallback:
        fallback_providers = list(overlay.provider_fallback)
    elif worker_ref.model.provider_fallback:
        fallback_providers = list(worker_ref.model.provider_fallback)
    elif agent_config.model.provider_fallback:
        fallback_providers = list(agent_config.model.provider_fallback)
    else:
        fallback_providers = list(team_config.defaults.provider_fallback)

    effective_capability = capability or PROVIDER_DEFAULT_MODELS.get(
        provider, Model.MID
    )
    model_name = MODEL_MAP.get(provider, {}).get(effective_capability, "")

    return RoleAssignment(
        role_id=agent_config.role,
        agent_id=worker_ref.agent_id,
        provider=provider,
        capability=capability,
        model_name=model_name,
        fallback_providers=fallback_providers,
        provider_source=provider_source,
        capability_source=capability_source,
    )


def resolve_effective_assignment(
    team_config: TeamConfig,
    profile_id: str,
    workspace_root: Path | None = None,
) -> ProfileAssignment:
    """Resolve every worker's effective assignment under the selected profile.

    ``profile_id`` must be a key of ``team_config.effective_profiles()``; the
    implicit ``team-defaults`` profile applies no overlay. A worker whose agent
    TOML cannot be resolved yields a ``RoleAssignment`` with a
    ``resolution_error`` rather than raising - the unresolved role is an
    eligibility signal, not a crash. An unknown ``profile_id`` is a ``ConfigError``.
    """
    profiles = team_config.effective_profiles()
    if profile_id not in profiles:
        raise ConfigError(
            f"Unknown model profile {profile_id!r} for team {team_config.id!r}; "
            f"available profiles: {sorted(profiles)!r}."
        )
    profile = profiles[profile_id]

    roles: list[RoleAssignment] = []
    for worker_ref in team_config.workers:
        overlay = (
            None
            if profile_id == DEFAULT_PROFILE_ID
            else profile.roles.get(worker_ref.agent_id)
        )
        try:
            agent_config = load_agent_config(worker_ref.agent_id, workspace_root)
        except AgentConfigNotFoundError as exc:
            roles.append(
                RoleAssignment(
                    role_id=worker_ref.agent_id,
                    agent_id=worker_ref.agent_id,
                    provider=_DEFAULT_PROVIDER,
                    capability=None,
                    model_name="",
                    fallback_providers=[],
                    provider_source=AssignmentSource.TEAM_DEFAULT,
                    capability_source=AssignmentSource.TEAM_DEFAULT,
                    resolution_error=str(exc),
                )
            )
            continue
        roles.append(
            resolve_role_assignment(worker_ref, agent_config, team_config, overlay)
        )
    return ProfileAssignment(profile_id=profile_id, roles=roles)


# ---------------------------------------------------------------------------
# Readiness probe (no instantiation, no secrets)
# ---------------------------------------------------------------------------


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def probe_provider_readiness(provider: Provider) -> ProviderReadiness:
    """Report whether ``provider`` is runnable without instantiating anything.

    Presence/resolvability only (never quota headroom): a configured credential
    and, for the subprocess providers, a resolvable command. Credentials and
    commands are workspace-independent, so no workspace is taken. The reason
    string is safe - it names what is missing, never a secret value.
    """
    if provider == Provider.MOCK:
        return ProviderReadiness(provider=provider, ready=True)

    if provider == Provider.CLAUDE:
        if not _has_text(settings.claude_code_oauth_token):
            return ProviderReadiness(
                provider=provider,
                ready=False,
                reason="no Claude OAuth token configured",
            )
        return _command_readiness(provider)

    if provider == Provider.GEMINI:
        has_credential = (
            _has_text(settings.gemini_api_key)
            or _has_text(settings.google_api_key)
            or _has_text(settings.google_application_credentials)
        )
        if not has_credential:
            return ProviderReadiness(
                provider=provider,
                ready=False,
                reason="no Gemini/Google credential configured",
            )
        return _command_readiness(provider)

    if provider == Provider.OPENAI:
        if not _has_text(settings.openai_api_key):
            return ProviderReadiness(
                provider=provider, ready=False, reason="no OpenAI API key configured"
            )
        return ProviderReadiness(provider=provider, ready=True)

    if provider == Provider.ZHIPU:
        if not _has_text(settings.zhipu_api_key):
            return ProviderReadiness(
                provider=provider, ready=False, reason="no Zhipu API key configured"
            )
        return ProviderReadiness(provider=provider, ready=True)

    return ProviderReadiness(
        provider=provider, ready=False, reason=f"unsupported provider {provider.value}"
    )


def _command_readiness(provider: Provider) -> ProviderReadiness:
    """Check a subprocess provider's command resolves via the factory classifier."""
    try:
        classify_provider_command(provider)
    except (ValueError, ConfigError, FileNotFoundError) as exc:
        return ProviderReadiness(
            provider=provider,
            ready=False,
            reason=f"provider command is not resolvable: {exc}",
        )
    return ProviderReadiness(provider=provider, ready=True)


def probe_engine_reachable() -> bool:
    """Return whether the authoring backend is reachable via the discovery contract.

    Uses the same ``resolve_engine`` attach-never-own discovery + liveness probe
    the subscriber uses; no secret is returned, only a boolean. Blocking (file
    read + a short ``/health`` probe); callers on an event loop should offload it.
    """
    from ..authoring import resolve_engine

    return resolve_engine() is not None


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def evaluate_profile_eligibility(
    assignment: ProfileAssignment,
    *,
    readiness: dict[Provider, ProviderReadiness] | None = None,
    engine_reachable: bool | None = None,
    acceptance_gate_passed: bool = False,
) -> ProfileEligibility:
    """Compose per-role and per-profile eligibility with safe reasons.

    A role is eligible when its primary provider is ready OR an eligible declared
    fallback is ready. A profile is eligible when every role is eligible, the
    authoring engine is reachable, and the production acceptance gate has passed -
    the last term is reported honestly and keeps the profile unavailable until it
    does. ``readiness`` may be injected (probed once by the caller); otherwise it
    is probed here.
    """
    cache: dict[Provider, ProviderReadiness] = dict(readiness or {})

    def _ready(provider: Provider) -> ProviderReadiness:
        if provider not in cache:
            cache[provider] = probe_provider_readiness(provider)
        return cache[provider]

    role_results: list[RoleEligibility] = []
    for role in assignment.roles:
        if role.resolution_error is not None:
            role_results.append(
                RoleEligibility(
                    role_id=role.role_id,
                    agent_id=role.agent_id,
                    eligible=False,
                    reason=f"role does not resolve: {role.resolution_error}",
                )
            )
            continue
        primary = _ready(role.provider)
        if primary.ready:
            role_results.append(
                RoleEligibility(
                    role_id=role.role_id, agent_id=role.agent_id, eligible=True
                )
            )
            continue
        eligible_fallback = next(
            (fb for fb in role.fallback_providers if _ready(fb).ready), None
        )
        if eligible_fallback is not None:
            role_results.append(
                RoleEligibility(
                    role_id=role.role_id, agent_id=role.agent_id, eligible=True
                )
            )
            continue
        role_results.append(
            RoleEligibility(
                role_id=role.role_id,
                agent_id=role.agent_id,
                eligible=False,
                reason=(
                    f"provider {role.provider.value} not ready "
                    f"({primary.reason}) and no eligible fallback"
                ),
            )
        )

    reasons: list[str] = []
    ineligible_roles = [r for r in role_results if not r.eligible]
    if ineligible_roles:
        reasons.append(
            "roles not eligible: "
            + ", ".join(f"{r.agent_id} ({r.reason})" for r in ineligible_roles)
        )

    if engine_reachable is None:
        engine_reachable = probe_engine_reachable()
    if not engine_reachable:
        reasons.append("authoring engine is not reachable")

    if not acceptance_gate_passed:
        reasons.append(_ACCEPTANCE_GATE_REASON)

    return ProfileEligibility(
        profile_id=assignment.profile_id,
        eligible=not reasons,
        reasons=reasons,
        roles=role_results,
    )
