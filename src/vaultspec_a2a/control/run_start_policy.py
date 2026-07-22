"""Pure run-start eligibility policy for the v1 gateway.

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

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

RUN_START_FINGERPRINT_FIELDS: tuple[str, ...] = (
    "team_preset",
    "message",
    "metadata",
    "autonomous",
    "title",
    "feature_tag",
    "profile_id",
    "feedback_batch_id",
)
"""Request fields whose value changes what a run DOES.

Deliberately enumerated rather than derived from the model. A field added later
must be classified by a person: silently folding every new field in would make
previously-valid replays conflict, and silently excluding them would let a
behaviour change replay as identical. Both failures are quiet, so the list is
explicit and its omissions are reasoned.

Excluded, and why. ``stage``, ``reservation_id`` and ``run_id`` identify the
request rather than describe the work: a prepare and its commit legitimately
differ on all three while driving one run. ``actor_tokens`` are minted per
attempt by the engine, so comparing them would make every honest retry conflict.
"""


def run_start_fingerprint(request: object) -> str:
    """Return a stable digest of the behaviour-affecting fields of *request*.

    Two requests that would produce the same run share a fingerprint; any
    difference in what the run would do produces a different one. That is what
    lets a replayed run id be answered with the original outcome when the body
    matches, and refused when it does not - a replay carrying a different prompt
    or a different preset is a new intention wearing an old id, and returning the
    first run's result would silently discard the second.

    Serialisation is canonical: keys sorted, separators fixed, non-ASCII
    preserved, so a digest depends on the values rather than on dictionary
    ordering or formatting.
    """
    payload: dict[str, object] = {}
    for field in RUN_START_FINGERPRINT_FIELDS:
        value = getattr(request, field, None)
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        payload[field] = value
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


if TYPE_CHECKING:
    from ..api.schemas.gateway import ProviderEligibility
    from ..context.harness import HarnessReadiness
    from ..team.team_config import TeamConfig
    from ..thread.actor_tokens import ActorTokenBundle

__all__ = [
    "ExecutionEligibility",
    "RunStartEligibility",
    "evaluate_execution_eligibility",
    "evaluate_run_start_eligibility",
    "is_document_authoring_preset",
    "required_role_ids",
]


@dataclass(frozen=True, slots=True)
class RunStartEligibility:
    """Whether a run-start request may dispatch, with a safe human reason.

    ``reason`` is populated only when ``eligible`` is False and is safe to return
    to the Rust backend: it names the missing precondition without echoing any
    token value or prompt content.
    """

    eligible: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionEligibility:
    """Whether the runtime and a provider are eligible to execute a run right now.

    The commit stage of desktop run-admission binds actor tokens and creates a
    durable run only when this is ``eligible``: the ADR mints run credentials only
    after the runtime (a reachable worker) and a provider have become eligible.
    ``reason`` is populated only on a refusal and is safe to return - it names the
    missing runtime or provider precondition without any path or secret.
    """

    eligible: bool
    reason: str | None = None


def evaluate_execution_eligibility(
    *,
    worker_reachable: bool,
    provider_eligibility: ProviderEligibility,
) -> ExecutionEligibility:
    """Decide whether execution is eligible before accepting tokens or a run.

    Pure policy over two facts the commit path probes live: whether the
    gateway-owned worker is reachable, and whether at least one subprocess
    provider command resolves on this host (the no-instantiation classify seam).
    Both must hold; a refusal composes the missing preconditions into one safe
    reason so a not-yet-ready worker and an unresolved provider are reported
    together rather than one at a time.
    """
    from ..api.schemas.gateway import ProviderEligibility

    reasons: list[str] = []
    if not worker_reachable:
        reasons.append("the gateway worker is not execution-ready")
    if provider_eligibility is not ProviderEligibility.ELIGIBLE:
        reasons.append("no subprocess provider command resolves on this host")
    if reasons:
        return ExecutionEligibility(eligible=False, reason="; ".join(reasons))
    return ExecutionEligibility(eligible=True)


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
    provided_roles = set(actor_tokens.tokens) if actor_tokens is not None else set()
    return [
        role for role in required_role_ids(team_config) if role not in provided_roles
    ]


def evaluate_run_start_eligibility(
    team_config: TeamConfig,
    *,
    feature_tag: str | None,
    actor_tokens: ActorTokenBundle | None,
    harness: HarnessReadiness | None = None,
) -> RunStartEligibility:
    """Decide whether a run-start request is eligible to dispatch.

    Document-authoring presets require a target feature tag, an actor-token
    bundle with one token per required role, and - when a ``harness`` verdict is
    supplied - a complete agent harness; a role must never share another's token,
    so coverage is checked by explicit per-role presence. Run-start REFUSES on an
    incomplete harness (the discovery-vs-launch binding: discovery serves the
    reason, launch refuses), unlike the acceptance gate which only certifies at
    discovery. A CODING preset that arms the engine authoring bridge
    (``[team.harness] authoring_bridge = true``) also requires per-role token
    coverage - each worker's bridge routes engine tool execution under that role's
    actor token - so the engine role-key gap becomes a cheap run-start refusal
    here rather than an opaque mid-run failure; it needs no feature tag or harness
    surfaces. Other non-authoring presets carry none of these requirements. The
    reason string is safe to surface.
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

    return RunStartEligibility(eligible=True)
