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
    option_id_of,
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
    # A run is bound to one project, and a call naming another is outside what
    # the run was admitted to do, so neither an allowlist nor a human at the
    # prompt is the authority that could permit it. The refused ARGUMENT is not
    # logged, only the fact and the run's own bound project: a caller-chosen
    # path is agent-supplied payload.
    if (
        scope is not None
        and foreign_project_argument(request.arguments, scope) is not None
    ):
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


def _narrowed_to_one_use(option_id: str, options: list[JsonObject]) -> str:
    """Return the once-only spelling of a chosen answer.

    A remembered answer is not this project's to give. The CLI persists it as a
    permission rule in the operator's own settings, outside anything a run can
    see or retract, and a rule written that way widens or narrows every later
    run on that machine - including the unattended ones, whose whole posture is
    that nothing is approved that was not approved for them. A human at the
    prompt is answering for THIS call, so this call is what the answer is
    applied to.

    The answer keeps its polarity: a remembered approval becomes the once-only
    approval and a remembered refusal the once-only refusal, read through the
    same option kinds the autonomous answer is chosen from. If a session offers
    no once-only answer of that polarity, the choice is left as made rather
    than converted into one the human did not give - and that case is logged,
    because it is the one where an answer outlives its call. Whether that case
    should be refused instead is decided here and nowhere else.
    """
    chosen = offered_option(options, option_id)
    if chosen is None or not is_remembering(chosen):
        return option_id
    once = (
        PermissionOptionKind.ALLOW_ONCE
        if is_approval(chosen)
        else PermissionOptionKind.REJECT_ONCE
    )
    narrowed = option_id_of_kind(options, once)
    if narrowed is None:
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
    """Return the human rung's answer applied to this call, or None if it failed.

    ``GraphBubbleUp`` propagates rather than being caught: it is how a
    supervised rung suspends the run to ask a person, so swallowing it here
    would turn a pending question into a silent refusal. The rung that asked
    records it and refuses the still-open request. Any other failure refuses
    the call: a human rung that raised has approved nothing.
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


def _option_id_at(options: list[JsonObject], index: int, *, default: str) -> str:
    """Return the id of the option at ``index``, or ``default`` if it has none.

    Positional, never scanning: the caller picks an option by CONVENTION (first
    is the least restrictive), so silently sliding to a neighbour when the
    conventional entry is malformed would substitute an option with the opposite
    meaning. Reading the id through the canonical extractor instead of
    subscripting is what keeps a malformed entry from raising ``KeyError`` on a
    path that exists to handle malformed input.
    """
    if not options:
        return default
    return option_id_of(options[index]) or default


def _autonomous_answer(request: ToolPermissionRequest, *, covered: bool) -> str:
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

    An approval is the NARROWEST offered one: taking the first approval-kind
    option could grant a whole server for a session on the strength of one
    allowlisted tool. A refusal is the narrowest offered refusal, and otherwise
    the literal ``"reject"``. The literal is a deliberate answer rather than a
    gap: an id the agent does not recognise makes it decline the tool call,
    which is the direction a refusal must fail in, while any scan that could
    land on an approval turns one malformed or unusual option list into a grant.
    """
    options = request.options
    if covered:
        # A covered call whose request offers no approval-kind option is
        # answered with the first offered id, and with the literal "approve"
        # when no option carries one. Whether such a call should be refused
        # instead is decided here and nowhere else.
        return narrowest_option_id(options, approving=True) or _option_id_at(
            options, 0, default="approve"
        )
    logger.warning(
        "Refused a tool call at the autonomous rung: tool=%s is not covered by "
        "the run's composed surface",
        request.tool,
    )
    return narrowest_option_id(options, approving=False) or "reject"


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
    calls it decides. *scope* is the project the run is bound to; ``None``, a
    rung built with no project to measure against, skips the scope scan.

    ``None`` leaves the refusal to the rung, which spells it in its own lane's
    terms. ``GraphBubbleUp`` raised by *ask* propagates to the rung.
    """
    if _refused_ahead_of_both_rungs(request, scope):
        return None
    if ask is not None:
        chosen = await _human_answer(request, ask)
        if chosen is None:
            return None
    else:
        chosen = _autonomous_answer(request, covered=covered())
    # An answer naming an option that was never offered is not a decision a
    # rung can carry out, so the call is REFUSED rather than mapped onto a
    # neighbour: the pinned ACP adapter sorts its options with the approvals
    # first, so substituting the first offered option resolved a refusal whose
    # id did not match to a grant. A request offering no usable id leaves
    # nothing to check against, and the answer is forwarded as given - which
    # is the case the autonomous literals above are answering.
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
