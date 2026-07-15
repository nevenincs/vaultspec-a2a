"""Pure run-start eligibility policy for the v1 gateway (a2a-edge-conformance).

The ``run-start`` verb refuses a run before dispatch when the request cannot
produce a valid run: a document-authoring preset with no target feature, or an
actor-token bundle that does not cover the preset's required roles. This module
holds that decision as pure logic - no I/O, no database, no HTTP - so the gateway
route stays a thin translator to HTTP status codes and the policy is unit
testable against real ``TeamConfig`` objects.

Preset loadability and empty-prompt refusals are enforced at the route (they are
I/O and schema concerns respectively); this module covers the semantic
eligibility that depends on the loaded preset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..team.team_config import TopologyType

if TYPE_CHECKING:
    from ..team.team_config import TeamConfig
    from ..thread.actor_tokens import ActorTokenBundle

__all__ = [
    "RunStartEligibility",
    "evaluate_run_start_eligibility",
    "is_document_authoring_preset",
    "required_role_ids",
]

# Topologies whose runs author vault documents through engine proposals and so
# require a target feature and a per-role actor-token bundle. Kept as a set so
# future authoring topologies join without touching the eligibility logic.
_DOCUMENT_AUTHORING_TOPOLOGIES: frozenset[TopologyType] = frozenset(
    {TopologyType.RESEARCH_ADR}
)


@dataclass(frozen=True, slots=True)
class RunStartEligibility:
    """Whether a run-start request may dispatch, with a safe human reason.

    ``reason`` is populated only when ``eligible`` is False and is safe to return
    to the Rust backend: it names the missing precondition without echoing any
    token value or prompt content.
    """

    eligible: bool
    reason: str | None = None


def is_document_authoring_preset(team_config: TeamConfig) -> bool:
    """Return True when the preset authors documents through engine proposals."""
    return team_config.topology.type in _DOCUMENT_AUTHORING_TOPOLOGIES


def required_role_ids(team_config: TeamConfig) -> list[str]:
    """Return the role identifiers a run's token bundle must cover.

    Tokens are keyed by the worker ``agent_id`` (ADR R7), so the required roles
    are the preset's worker agent ids in declaration order.
    """
    return [worker.agent_id for worker in team_config.workers]


def evaluate_run_start_eligibility(
    team_config: TeamConfig,
    *,
    feature_tag: str | None,
    actor_tokens: ActorTokenBundle | None,
) -> RunStartEligibility:
    """Decide whether a run-start request is eligible to dispatch.

    Document-authoring presets require a target feature tag and an actor-token
    bundle with one token per required role; a role must never share another's
    token, so coverage is checked by explicit per-role presence. Non-authoring
    presets carry neither requirement here. The reason string is safe to surface.
    """
    if not is_document_authoring_preset(team_config):
        return RunStartEligibility(eligible=True)

    if not feature_tag:
        return RunStartEligibility(
            eligible=False,
            reason=(
                "document-authoring preset "
                f"{team_config.id!r} requires a target feature tag"
            ),
        )

    provided_roles = set(actor_tokens.tokens) if actor_tokens is not None else set()
    missing = [
        role for role in required_role_ids(team_config) if role not in provided_roles
    ]
    if missing:
        return RunStartEligibility(
            eligible=False,
            reason=(
                "actor token bundle for preset "
                f"{team_config.id!r} is missing a token for role(s): {missing}"
            ),
        )

    return RunStartEligibility(eligible=True)
