"""Pre-diverge ground decision node for research_adr (agent-flow ADR D5 wiring).

The clarification interrupt node (:mod:`.clarification`) is the reusable
pause/resume primitive; this module is the ONE call site that decides WHEN to
use it for archetype B. One model turn, run once at the head of the research_
adr phase machine (before the researcher fan-out), decides whether the run's
request carries enough information to proceed straight to research, or
whether a bounded clarifying question must be asked first.

Sentinel-pattern precedent (mirrors ``PLAN READY``/``RESEARCH READY``/``ADR
READY`` and the doc-reviewer's exact-line ``REVISION REQUIRED``): the turn's
entire response is either the literal line ``GROUND READY`` (proceed), or the
literal line ``CLARIFICATION NEEDED`` followed by nothing but a JSON question
array (pause). Absent the clarification sentinel, or on any parse failure,
the run proceeds - fail-OPEN, mirroring the doc-review router's own
discipline ("absent an explicit revision verdict the loop advances"): a
malformed ground turn must never wedge the whole pipeline on a triage step.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.types import Command

from .clarification import bound_clarification_questions

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from ...thread.state import TeamState

__all__ = [
    "GROUND_CLARIFICATION_SENTINEL",
    "GROUND_READY_SENTINEL",
    "GROUND_SYSTEM_PROMPT",
    "create_ground_node",
]

logger = logging.getLogger(__name__)

GROUND_READY_SENTINEL = "GROUND READY"
GROUND_CLARIFICATION_SENTINEL = "CLARIFICATION NEEDED"

# The question-array schema the turn must emit, held apart from the prompt body
# because it is one unbreakable line: rewrapping it would change the shape the
# model is being shown, and a wrapped JSON example invites a wrapped answer.
_QUESTION_ARRAY_SCHEMA = (
    '[{"id": "<short-id>", "prompt": "<question text>", '
    '"kind": "choice"|"text", "options": ["..."], "required": true|false}]'
)

GROUND_SYSTEM_PROMPT = f"""\
You are the grounding gate for the vaultspec research-to-ADR-to-plan
pipeline. Before any research begins, decide whether the user's request
carries enough information to proceed, or whether you must ask the user a
small number of clarifying questions first.

## Mandate

- Read the user's request carefully. If it names a concrete feature, module,
  or decision to research, and nothing essential is ambiguous, proceed
  immediately - do not invent questions to pad the interaction.
- Ask a clarifying question ONLY when something essential is genuinely
  ambiguous or missing. At most 4 questions, each with at most 4 options for
  a choice question. Keep every prompt and option short and single-line
  (no newlines).
- You get exactly one clarification round per run. Ask everything you
  genuinely need now; you will not get a second chance before research
  begins.

## Output format (exact — no other text)

To proceed directly to research, your entire response is the literal line:

{GROUND_READY_SENTINEL}

To ask clarifying questions, your entire response is the literal sentinel
line followed by nothing but a JSON array of question objects:

{GROUND_CLARIFICATION_SENTINEL}
{_QUESTION_ARRAY_SCHEMA}

``options`` is required only when ``kind`` is ``"choice"``. Do not add any
narration, markdown fencing, or explanation before or after either form.
"""


def _parse_ground_clarification(content: str) -> list[dict[str, Any]]:
    """Extract a bounded question list from a ground turn's response.

    Recognizes the standalone sentinel line (matched whole-line, case- and
    whitespace-sensitive like the doc-reviewer's ``REVISION REQUIRED``
    convention); everything after that line is parsed as a JSON question
    array and bounded to the clarification node's own caps
    (:func:`bound_clarification_questions`). Absent the sentinel, or on any
    parse failure, returns an empty list.
    """
    lines = content.splitlines()
    sentinel_idx = next(
        (
            i
            for i, line in enumerate(lines)
            if line.strip() == GROUND_CLARIFICATION_SENTINEL
        ),
        None,
    )
    if sentinel_idx is None:
        return []
    remainder = "\n".join(lines[sentinel_idx + 1 :]).strip()
    if not remainder:
        return []
    try:
        parsed = json.loads(remainder)
    except json.JSONDecodeError:
        logger.warning(
            "ground node: %s sentinel present but the JSON question array did "
            "not parse; proceeding without clarification",
            GROUND_CLARIFICATION_SENTINEL,
        )
        return []
    if not isinstance(parsed, list):
        return []
    return bound_clarification_questions(parsed)


def create_ground_node(
    model: BaseChatModel,
    system_prompt: str,
    *,
    clarify_target: str,
    proceed_target: str,
    name: str = "ground",
) -> Any:
    """Create the pre-diverge ground decision node.

    Runs one model turn and routes via ``Command.goto`` rather than a static/
    conditional edge pair: the routing decision and the ``clarification_
    questions`` state write must commit together in the same superstep, since
    the downstream clarification node reads that field to build its interrupt
    payload — a separate conditional-edge function could read state but never
    write it.
    """

    async def ground_node(state: TeamState) -> Command:
        """Decide proceed-vs-clarify for this run, once."""
        messages: list[Any] = [SystemMessage(content=system_prompt)]
        messages.extend(state.get("messages", []))
        response = await model.ainvoke(messages)
        content = str(response.content)
        questions = _parse_ground_clarification(content)
        update: dict[str, Any] = {"messages": [AIMessage(content=content, name=name)]}
        if questions:
            update["clarification_questions"] = questions
            return Command(goto=clarify_target, update=update)
        return Command(goto=proceed_target, update=update)

    ground_node.__name__ = name
    return ground_node
