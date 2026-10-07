"""Asking a human for one tool permission, and recognising the answer.

The provider calls back from inside a model turn, where no graph state is
reachable, so a turn's recorded answers are bound here before the turn starts
and every later decision - which options may be offered, which stored answer
belongs to which call, when the run must park again - is made against that
binding. Kept apart from the worker node because the node runs the turn while
this decides what the turn is allowed to do.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn, cast

from langgraph.config import get_config
from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt, interrupt

from ...thread import PermissionAnswer
from ...thread.state import read_untrusted_state_value
from ..acp_options import option_id_of, valid_option_ids

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ...providers._acp_types import PermissionCallback
    from ...thread.state import TeamState

__all__ = [
    "permission_callback_for",
    "recorded_permission_answers",
]

_logger = logging.getLogger(__name__)


def _permission_request_id(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Name one permission request by its task and by the exact call it asks about.

    A resumed task replays under the same checkpoint namespace, so the same call
    asked again after a resume names the same request, while a different call -
    another tool, or the same tool with other arguments - names a different one.
    """
    namespace = get_config().get("configurable", {}).get("checkpoint_ns", "")
    canonical = json.dumps(
        [namespace, tool_name, tool_input],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"perm-{hashlib.sha256(canonical.encode()).hexdigest()[:32]}"


def _offered_options(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The choices a human is offered: never one the CLI would remember.

    The CLI persists an "always" answer as a rule in the operator's own
    settings, where it widens or narrows later runs - unattended ones included -
    and nothing here can retract it. The provider rung answers such a choice
    with the once-only option anyway, so offering it would promise a persistence
    the system deliberately never performs. A request offering nothing else
    keeps its options, so the run is never left without an answer to give.
    """
    once = [
        option
        for option in options
        if not str(option.get("kind", "")).endswith("_always")
        and "always" not in (option_id_of(option) or "").lower()
    ]
    return once or options


def recorded_permission_answers(state: TeamState) -> Mapping[str, str]:
    """The run's answered tool-permission requests, narrowed at the boundary.

    Read through the untrusted-state boundary because the annotation on the
    channel describes what its reducer produces, not what a checkpoint
    assembled elsewhere is guaranteed to hold; an entry that is not a pair of
    non-empty strings names no request and approves no option, so it is
    dropped rather than offered to a tool call.
    """
    recorded = read_untrusted_state_value(state, "permission_answers")
    if not isinstance(recorded, dict):
        return {}
    return {
        key: value
        for key, value in cast("dict[object, object]", recorded).items()
        if isinstance(key, str) and key and isinstance(value, str) and value
    }


def _park_on(payload: dict[str, Any]) -> NoReturn:
    """Suspend the run on *payload* without asking a second time.

    ``interrupt()`` matches a task's stored resume values to its calls
    strictly by position, so calling it again to turn an unusable answer away
    would make the turn's answers depend on the order a replayed provider turn
    happens to reach its tool calls in. Raising the suspension the call would
    have raised parks the run on the request actually being made while leaving
    the count of ``interrupt()`` calls in this execution at one.
    """
    namespace = get_config().get("configurable", {}).get("checkpoint_ns", "")
    raise GraphInterrupt((Interrupt.from_ns(value=payload, ns=namespace),))


def _answered_option(
    answers: Mapping[str, str], request_id: str, offered: list[dict[str, Any]]
) -> str | None:
    """The option already chosen for *request_id*, if it is one this call offers.

    An answer recorded for a request whose call now offers other options is
    treated as unanswered rather than forced through, so a replayed turn that
    reaches the same call with a different option set asks again.
    """
    chosen = answers.get(request_id)
    if chosen is None:
        return None
    if chosen not in valid_option_ids(offered):
        _logger.warning(
            "Recorded permission answer %r is not an option this call offers; "
            "asking again",
            chosen,
        )
        return None
    return chosen


@dataclass(frozen=True, slots=True)
class _PermissionRequest:
    """One tool call put to a human, and the options it may be answered with."""

    request_id: str
    tool_name: str
    tool_input: dict[str, Any]
    offered: list[dict[str, Any]]

    def payload(self) -> dict[str, Any]:
        """The interrupt payload this request suspends the run on."""
        return {
            "type": "permission_request",
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "options": self.offered,
        }


@dataclass(frozen=True, slots=True)
class _AnswerReading:
    """What one value handed back to a parked call turns out to settle.

    ``option`` is set only when the value answers this exact call. ``learned``
    carries an answer belonging to a DIFFERENT request, which a caller whose
    node cannot read the run's channels remembers for that request rather than
    discarding. A reading with neither settles nothing.
    """

    option: str | None = None
    learned: PermissionAnswer | None = None


def _read_permission_answer(
    answered: PermissionAnswer | None, request: _PermissionRequest
) -> _AnswerReading:
    """Judge one handed-back value against the call actually being made.

    A value that is not this request's answer never becomes one: it is
    reported and read past, so an approval given for one call can never land
    on another.
    """
    if answered is None:
        # Including a bare option id: an answer that names no request cannot
        # be shown to belong to this call, and applying it is how an approval
        # given for one call reaches another.
        _logger.warning(
            "Permission answer for the %r call names no request; asking again",
            request.tool_name,
        )
        return _AnswerReading()
    if answered.request_id != request.request_id:
        _logger.warning(
            "Permission answer names request %r, not the %r call now being "
            "made; asking again",
            answered.request_id,
            request.tool_name,
        )
        return _AnswerReading(learned=answered)
    if answered.option_id not in valid_option_ids(request.offered):
        _logger.warning(
            "Permission answer for the %r call chose option %r, which it "
            "does not offer; asking again",
            request.tool_name,
            answered.option_id,
        )
        return _AnswerReading()
    return _AnswerReading(option=answered.option_id)


def permission_callback_for(
    answers: Mapping[str, str], *, answers_reach_the_node: bool = True
) -> PermissionCallback:
    """Bind one worker turn's recorded permission answers to its callback.

    The callback is handed to the provider, which calls it from inside the
    model turn with no access to graph state, so the answers this turn already
    has are bound here instead. They are read by request id: a resumed turn
    replays in full and may reach its tool calls in a different order, and an
    answer found by the request it was given for reaches the call the human
    was shown whatever that order turns out to be.

    *answers_reach_the_node* is False for a node whose input is fixed when it
    is dispatched rather than read from the run's channels - a fan-out branch,
    whose input is the payload its dispatch sent and which LangGraph replays
    unchanged however far the run's channels have moved since. Such a node
    sees an empty *answers* on every replay no matter how many answers the run
    has recorded, so turning an unusable stored value away would strand it:
    the value stays at its position in the task's resume values and is handed
    to the same call on every later replay, and no channel exists to settle
    the request instead. The callback reads on past it rather than turning it
    away, keyed by the request each stored value names.
    """
    # Answers this execution read out of the task's resume values, for a node
    # whose input cannot carry them. Keyed by the request each names, so an
    # answer met while resolving one call still reaches the call it was
    # actually given for instead of being spent on the one that found it.
    learned: dict[str, str] = {}

    async def permission_callback(
        tool_name: str,
        tool_input: dict[str, Any],
        options: list[dict[str, Any]],
    ) -> str:
        """Return this call's approved option, or suspend the run for one.

        A value that is not this request's answer never becomes one - the run
        parks again on the call actually being made, so an approval can never
        land on a call nobody saw.

        Where the node's input carries the run's answers, ``interrupt()`` is
        reached at most once per execution: every request already answered is
        resolved from the bound answers without asking, and the first one that
        has not suspends the run. Where it cannot, one extra read happens per
        unusable stored value, and the suspension once they run out is the
        same "ask again for this call" outcome - reached after the values the
        branch was already handed have been accounted for rather than before.
        """
        request = _PermissionRequest(
            request_id=_permission_request_id(tool_name, tool_input),
            tool_name=tool_name,
            tool_input=tool_input,
            offered=_offered_options(options),
        )
        already = _answered_option(
            {**answers, **learned}, request.request_id, request.offered
        )
        if already is not None:
            return already

        payload = request.payload()
        while True:
            reading = _read_permission_answer(
                PermissionAnswer.from_resume_value(interrupt(payload)), request
            )
            if reading.option is not None:
                return reading.option
            # Parking raises, so a node whose input carries the run's answers
            # never reaches the line below: an answer belonging to another
            # request is remembered only where no channel can settle it.
            if answers_reach_the_node:
                _park_on(payload)
            if reading.learned is not None:
                learned[reading.learned.request_id] = reading.learned.option_id

    return permission_callback
