"""The one permission decision both provider rungs make about a tool call.

A permission question reaches this process only for a call the provider's own
static pre-approval did not cover: the ACP adapters raise
``session/request_permission`` and codex raises an MCP elicitation. Both rungs
hand the question to :func:`decide`, so the two lanes cannot come to disagree
about which guard runs first, what an unattended run may approve, or what a
supervised run does when its human rung fails. A rung keeps only what is its
lane's own: how it names the tool, which calls its composed surface covers, and
how it spells the answer back to its provider.

Answers are chosen from options in the ACP permission-option shape on both
lanes - codex offers its two actions under that shape too - and every option is
read through :mod:`vaultspec_a2a.graph.acp_options`, so one option means one
thing to both rungs.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langgraph.errors import GraphBubbleUp

from ..graph.acp_options import (
    is_approval,
    is_remembering,
    narrowest_option_id,
    offered_option,
    option_id_of_kind,
    valid_option_ids,
)
from ..graph.enums import PermissionOptionKind
from ._harness_mcp_registry import harness_tool_is_withheld
from ._json_contract import JsonObject
from ._project_scope import RunProjectScope, foreign_project_argument

__all__ = ["ToolPermissionRequest", "decide"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolPermissionRequest:
    """One tool call a rung puts to :func:`decide`, in the terms both lanes share.

    ``tool`` is the identity the rung establishes for the call - the qualified
    ``mcp__<server>__<tool>`` spelling wherever the lane carries one - and is
    what the guards match and the log names. ``arguments`` are scanned, never
    logged. ``options`` are the answers the provider offered.
    """

    tool: str
    arguments: JsonObject
    options: list[JsonObject]


def _refused_ahead_of_both_rungs(
    request: ToolPermissionRequest, scope: RunProjectScope | None
) -> bool:
    """Whether a guard refuses the call before a human or an allowlist is asked.

    The guards run in one order on every lane, the scope check first, so the
    same call is refused for the same reason whichever lane raised it.
    """
    # A rung built with no project cannot measure a call against one, and a
    # check that cannot be made is not a check that passed: the project scan is
    # the first authority consulted, so a run with nothing to measure against
    # has no authority to permit anything. Production always supplies the run's
    # bound project; absence is a construction defect, and the deny-by-default
    # direction is to refuse rather than to let the call through unmeasured.
    #
    # A PRESENT scope that binds nothing is the same absence, and asking the
    # scope is what makes that so: a run whose workspace root is missing, blank,
    # or does not reduce to an absolute key yields a scope whose
    # ``bound_project_root()`` is None, and a call naming no project argument
    # passed the object test unmeasured straight to the human rung.
    if scope is None or scope.bound_project_root() is None:
        logger.warning(
            "Refused a tool call with no project to measure it against: tool=%s",
            request.tool,
        )
        return True
    # A run is bound to one project, and a call naming another is outside what
    # the run was admitted to do, so neither an allowlist nor a human at the
    # prompt is the authority that could permit it. The refused ARGUMENT is not
    # logged, only the fact and the run's own bound project: a caller-chosen
    # path is agent-supplied payload.
    if foreign_project_argument(request.arguments, scope) is not None:
        logger.warning(
            "Refused a cross-project tool call: tool=%s named a project outside "
            "the run's bound project (bound=%s)",
            request.tool,
            scope.bound_project_root(),
        )
        return True
    # A withheld harness tool is served by a server the run mounts but is never
    # callable. A person at the prompt cannot see that the call would send vault
    # text off the host, and the registry's no-egress declaration rests on
    # nobody being asked.
    if harness_tool_is_withheld(request.tool):
        logger.warning("Refused a withheld harness tool: tool=%s", request.tool)
        return True
    return False


def _narrowed_to_one_use(option_id: str, options: list[JsonObject]) -> str | None:
    """Return the once-only spelling of a chosen answer, or None to refuse.

    A remembered answer is not this project's to give. The CLI persists it as a
    permission rule in the operator's own settings, outside anything a run can
    see or retract, and a rule written that way widens or narrows every later
    run on that machine - including the unattended ones, whose whole posture is
    that nothing is approved that was not approved for them. A human at the
    prompt is answering for THIS call, so this call is what the answer is
    applied to.

    The answer keeps its polarity: a remembered approval becomes the once-only
    approval and a remembered refusal the once-only refusal, read through the
    same option kinds the autonomous answer is chosen from.

    Where the session offers no once-only answer of that polarity the two
    polarities part, and deliberately. A remembered REFUSAL is answered by
    refusing the call: refusing is what the human asked for, so the call is
    carried out exactly as given and the only thing dropped is the durable rule
    nobody asked to write. A remembered APPROVAL cannot be treated the same way,
    because refusing it would answer the opposite of what the human said; it is
    forwarded as chosen, and the rule it causes is logged as the cost.
    """
    chosen = offered_option(options, option_id)
    if chosen is None or not is_remembering(chosen):
        return option_id
    approving = is_approval(chosen)
    once = (
        PermissionOptionKind.ALLOW_ONCE
        if approving
        else PermissionOptionKind.REJECT_ONCE
    )
    narrowed = option_id_of_kind(options, once)
    if narrowed is None:
        if not approving:
            logger.info(
                "Refusing the tool call rather than forwarding a remembered "
                "refusal the session offers no single-use spelling for: tool "
                "option=%r",
                option_id,
            )
            return None
        logger.warning(
            "Permission option %r remembers the answer and the session offers "
            "no single-use alternative; the CLI will persist a rule this run "
            "cannot retract",
            option_id,
        )
        return option_id
    logger.info(
        "Narrowed a remembered permission answer to a single use: %r -> %r",
        option_id,
        narrowed,
    )
    return narrowed


async def _human_answer(
    request: ToolPermissionRequest, ask: Callable[[], Awaitable[str]]
) -> str | None:
    """Return the human rung's answer applied to this call, or None to refuse.

    ``GraphBubbleUp`` propagates rather than being caught: it is how a
    supervised rung suspends the run to ask a person, so swallowing it here
    would turn a pending question into a silent refusal. The rung that asked
    records it and refuses the still-open request. Any other failure refuses
    the call: a human rung that raised has approved nothing. A refusal the
    session can only spell as a durable rule refuses too, for the reason
    :func:`_narrowed_to_one_use` gives.
    """
    try:
        chosen = await ask()
    except GraphBubbleUp:
        raise
    except Exception:
        logger.exception(
            "Permission callback raised; refusing the tool call (fail-closed): tool=%s",
            request.tool,
        )
        return None
    return _narrowed_to_one_use(chosen, request.options)


def _autonomous_answer(request: ToolPermissionRequest, *, covered: bool) -> str | None:
    """Decide with no human rung: approve exactly what the composed surface covers.

    An unattended run has no human rung, so this IS the permission decision,
    and every lane answers it by one rule: approve a call the lane's composed
    surface covers and refuse everything else. Refusing the uncovered case is
    the point. A request reaches a rung only for a call the provider's static
    pre-approval did not cover, and what a server MOUNTS is wider than what the
    registry DECLARES - the search server also serves index-rebuild and
    index-clean verbs beside its declared reads - so approving the uncovered
    call would make the declared surface advisory and every unadvertised verb
    reachable.

    An approval is the NARROWEST offered one, and ONLY an offered one: taking
    the first approval-kind option could grant a whole server for a session on
    the strength of one allowlisted tool, and answering a covered call whose
    request offers no approval at all - by position, or with the conventional
    approve literal - would turn a malformed or unusual option list into a
    grant the provider never put on the table. Coverage decides that an approval
    is PERMITTED; it does not invent one, so such a call is refused.

    A refusal is the ONCE-ONLY offered refusal and nothing else. The remembering
    refusal is not a fallback here for the same reason it is not one on the human
    path: the CLI persists ``reject_always`` as a rule in the operator's own
    settings, where it outlives this call and narrows every later run on the
    machine - including the unattended ones, whose whole posture is that nothing
    is decided for them in advance. Nobody is even at the prompt to be told the
    rule was written. Where the session offers no once-only refusal the call is
    refused with ``None``, and each rung spells the abandonment its own lane's
    way: a conventional refusal literal would instead name an option id the
    request never listed, which the agent cannot match to anything it offered.
    """
    options = request.options
    if covered:
        approval = narrowest_option_id(options, approving=True)
        if approval is not None:
            return approval
        logger.warning(
            "Refused a covered tool call at the autonomous rung: tool=%s was "
            "offered no approval to select, so there is nothing to approve with",
            request.tool,
        )
        return None
    logger.warning(
        "Refused a tool call at the autonomous rung: tool=%s is not covered by "
        "the run's composed surface",
        request.tool,
    )
    return option_id_of_kind(options, PermissionOptionKind.REJECT_ONCE)


async def decide(
    request: ToolPermissionRequest,
    *,
    scope: RunProjectScope | None,
    covered: Callable[[], bool],
    ask: Callable[[], Awaitable[str]] | None,
) -> str | None:
    """Return the offered option id that answers one tool call, or None to refuse.

    The guards run first and refuse ahead of both rungs. A supervised run's
    human rung (*ask*, bound to this call) then answers, and an unattended run
    is answered by the composed-surface rule. *covered* is consulted only on the
    unattended path, so a lane's coverage check runs - and logs - only for the
    calls it decides. *scope* is the project the run is bound to; a rung built
    with ``None``, or with a scope that binds no project, has nothing to measure
    a call against and every call it puts here is refused.

    ``None`` leaves the refusal to the rung, which spells it in its own lane's
    terms. ``GraphBubbleUp`` raised by *ask* propagates to the rung.
    """
    if _refused_ahead_of_both_rungs(request, scope):
        return None
    if ask is not None:
        chosen = await _human_answer(request, ask)
    else:
        chosen = _autonomous_answer(request, covered=covered())
    if chosen is None:
        return None
    # An answer naming an option that was never offered is not a decision a
    # rung can carry out, so the call is REFUSED rather than mapped onto a
    # neighbour: the pinned ACP adapter sorts its options with the approvals
    # first, so substituting the first offered option resolved a refusal whose
    # id did not match to a grant. A request offering no usable id leaves
    # nothing to check against, and a human rung's answer is forwarded as given;
    # the unattended rung names no id of its own in that case and refuses.
    valid_ids = valid_option_ids(request.options)
    if valid_ids and chosen not in valid_ids:
        logger.warning(
            "Permission answer option_id=%r is not among the offered options %r; "
            "refusing the tool call rather than substituting one",
            chosen,
            sorted(valid_ids),
        )
        return None
    logger.info("Tool permission decision: tool=%s option=%s", request.tool, chosen)
    return chosen
