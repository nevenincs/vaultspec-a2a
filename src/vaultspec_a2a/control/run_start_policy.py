"""Pure run-start eligibility policy for the v1 gateway.

The ``run-start`` verb refuses a run before dispatch when the request cannot
produce a valid run: a document-authoring preset with no target feature, an
actor-token bundle that does not cover the preset's required roles, or an
incomplete authoring harness. It also refuses one condition of the GATEWAY
rather than of the request - a document-authoring topology asked of a gateway
running no authoring verdict subscriber - because such a run parks on a proposal
nothing could resume. This module holds those decisions as pure logic - no I/O,
no database, no HTTP - so the gateway route stays a thin translator to HTTP
status codes and the policy is unit testable against real ``TeamConfig``
objects.

**This eligibility carries no execution authority.** It says nothing about a
provider, lane, model, profile or catalog, and it must never be read as doing
so: whether a provider lane may be served is lane admission's answer (a
completed-turn proof and an admitted binary identity), and whether the gateway
would admit a run right now is the admission broker's. The word is shared with
those verdicts; the authority is not.

Preset loadability and empty-prompt refusals are enforced at the route (they are
I/O and schema concerns respectively); this module covers the semantic
eligibility that depends on the loaded preset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..thread.dispatch_policy import FailureType

if TYPE_CHECKING:
    from ..context.harness import HarnessReadiness
    from ..team.team_config import TeamConfig
    from ..thread.actor_tokens import ActorTokenBundle

__all__ = [
    "evaluate_run_start_eligibility",
    "is_document_authoring_preset",
    "required_role_ids",
]


@dataclass(frozen=True, slots=True)
class RunStartEligibility:
    """Whether a run-start request may dispatch, with a safe human reason.

    ``reason`` is populated only when ``eligible`` is False and is safe to return
    to the Rust backend: it names the missing precondition without echoing any
    token value or prompt content. A False verdict says the run cannot be served
    as asked, never that a provider or a profile is unavailable.

    ``failure`` names the refusal in the served vocabulary for the conditions a
    consumer must branch on by code rather than by sentence; it stays ``None``
    for a refusal whose only audience is the person reading the reason.
    """

    eligible: bool
    reason: str | None = None
    failure: FailureType | None = None


def is_document_authoring_preset(team_config: TeamConfig) -> bool:
    """Return True when the preset authors documents through engine proposals.

    Delegates to :attr:`TeamConfig.is_document_authoring`, which reads the single
    document-authoring-topology source of truth in the authoring contract.
    """
    return team_config.is_document_authoring


def required_role_ids(team_config: TeamConfig) -> list[str]:
    """Return the role identifiers a run's token bundle must cover.

    Tokens are keyed by the worker ``agent_id``, so the required roles
    are the preset's worker agent ids in declaration order.
    """
    return [worker.agent_id for worker in team_config.workers]


def _missing_role_tokens(
    team_config: TeamConfig, actor_tokens: ActorTokenBundle | None
) -> list[str]:
    """Return required roles whose actor token is absent from *actor_tokens*.

    Coverage is per-role by explicit presence, never shared: a role must carry
    its own token so one role's bridge or submitter can never route under
    another's principal.
    """
    provided_roles: set[str] = (
        set(actor_tokens.tokens) if actor_tokens is not None else set()
    )
    return [
        role for role in required_role_ids(team_config) if role not in provided_roles
    ]


def evaluate_run_start_eligibility(
    team_config: TeamConfig,
    *,
    feature_tag: str | None,
    actor_tokens: ActorTokenBundle | None,
    verdict_subscriber_running: bool,
    harness: HarnessReadiness | None = None,
) -> RunStartEligibility:
    """Decide whether a run-start request is eligible to dispatch.

    A document-authoring preset requires a gateway that can finish it, a target
    feature tag, an actor-token bundle with one token per required role, and -
    when a ``harness`` verdict is supplied - a complete agent harness; a role
    must never share another's token, so coverage is checked by explicit
    per-role presence. Run-start REFUSES on an incomplete harness (the
    discovery-vs-launch binding: discovery serves the reason, launch refuses),
    unlike the acceptance gate which only certifies at discovery.

    *verdict_subscriber_running* is a condition of the GATEWAY rather than of the
    request: a document gate parks on an engine proposal that only the verdict
    subscriber resumes, so without one the run cannot finish however complete
    the request is. It binds document topologies only, and it is answered LAST,
    once nothing the caller sent stands in the way. That ordering is what makes
    its typed code precise - it says "this request is fine and this gateway
    cannot serve it", so a consumer branching on the code never reports a
    missing engine for a request that was also incomplete, and the request-side
    refusals stay reachable on every gateway.

    A CODING preset that arms the engine authoring bridge (``[team.harness]
    authoring_bridge = true``) also requires per-role token coverage - each
    worker's bridge routes engine tool execution under that role's actor token -
    so the engine role-key gap becomes a cheap run-start refusal here rather
    than an opaque mid-run failure; it needs no feature tag, no harness surfaces
    and no verdict subscriber, because it authors no document proposals. Other
    non-authoring presets carry none of these requirements. The reason string is
    safe to surface.
    """
    if not is_document_authoring_preset(team_config):
        harness_cfg = team_config.effective_harness()
        if harness_cfg is not None and harness_cfg.authoring_bridge:
            missing = _missing_role_tokens(team_config, actor_tokens)
            if missing:
                return RunStartEligibility(
                    eligible=False,
                    reason=(
                        "authoring_bridge preset "
                        f"{team_config.id!r} is missing an actor token for "
                        f"role(s): {missing}"
                    ),
                )
        return RunStartEligibility(eligible=True)

    if not feature_tag:
        return RunStartEligibility(
            eligible=False,
            reason=(
                "document-authoring preset "
                f"{team_config.id!r} requires a target feature tag"
            ),
        )

    missing = _missing_role_tokens(team_config, actor_tokens)
    if missing:
        return RunStartEligibility(
            eligible=False,
            reason=(
                "actor token bundle for preset "
                f"{team_config.id!r} is missing a token for role(s): {missing}"
            ),
        )

    if harness is not None and not harness.ready:
        return RunStartEligibility(
            eligible=False,
            reason=(
                "agent harness incomplete for preset "
                f"{team_config.id!r}: " + "; ".join(harness.reasons)
            ),
        )

    if not verdict_subscriber_running:
        return RunStartEligibility(
            eligible=False,
            reason=(
                "document-authoring preset "
                f"{team_config.id!r} needs a running authoring verdict "
                "subscriber: its document gates park on an engine proposal and "
                "nothing else resumes them"
            ),
            failure=FailureType.AUTHORING_SUBSCRIBER_UNAVAILABLE,
        )

    return RunStartEligibility(eligible=True)
