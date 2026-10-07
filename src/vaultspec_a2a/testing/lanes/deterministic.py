"""Deterministic in-process provider for the certification and acceptance harnesses.

``DeterministicResearchAdrChatModel`` is a first-class ``BaseChatModel`` that
runs entirely in-process: no live model spend, no external service, no
credential. Its lane is registered through the product's lane-plugin seam, so it
is selected through the real ``ProviderFactory`` and every run it answers
crosses the same worker, graph and permission seams a real lane does.

Two kinds of turn come out of it, both keyed by the ``AgentConfig.id`` the
factory injects:

- research_adr role content. Each research_adr role (researcher, synthesist,
  adr-author, plan-author, doc-reviewer) receives role-appropriate output: the
  writers emit a valid vault-shaped markdown document the submitter can propose,
  and the reviewer emits the ``PASS`` sentinel that advances the inner review
  loop. The feature tag and topic are configurable so a parameterized harness can
  assert the materialized document stems.
- scripted scenarios: a turn that completes with fixed content, supervisor
  routing, a scripted supervisor, a reviewer that always requests revision, a
  research branch that asks before it reports, a supervised permission pause, a
  cancellation window, a relay burst, an endless generation loop, and a turn
  held until its test releases it, each selected by the bundled agent that
  names it.

A scenario that follows a script reads it from its agent's persona, one entry
per non-blank line. The scripted supervisor's entries are its routing replies,
given in order, the last repeating once the others are spent. The branch
researcher's entries are the tools it asks permission to run on its branch, in
order. Each bundled preset declares a default script; :func:`scripted_supervisor`
and :func:`branch_researcher` return that preset carrying a test's own, so the
script a test drives is stated beside the assertions that depend on it.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable
from enum import StrEnum
from pathlib import Path
from typing import override

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

from ...authoring.contract import RESEARCH_ADR_ROLES
from ...graph.nodes.phase_gate import REVIEW_REVISION_SENTINEL
from ...providers import JsonObject
from ...providers._acp_types import PermissionCallback
from ...team import AgentConfig, AgentPersonaConfig, load_agent_config
from ...thread.constants import DEFAULT_SUPERVISOR_ID

logger = logging.getLogger(__name__)

__all__ = [
    "UNATTENDED_REPLY",
    "DeterministicResearchAdrChatModel",
    "branch_researcher",
    "scripted_supervisor",
]


class _DeterministicScript(StrEnum):
    """Named in-process scenarios selected by their bundled agent identity."""

    COMPLETION = "completion"
    SUPERVISOR_ROUTING = "supervisor_routing"
    SCRIPTED_SUPERVISOR = "scripted_supervisor"
    REVISING_REVIEW = "revising_review"
    BRANCH_RESEARCH = "branch_research"
    PERMISSION_PAUSE = "permission_pause"
    CANCEL_WINDOW = "cancel_window"
    RELAY_BURST = "relay_burst"
    LOOPING = "looping"
    HOLD_THEN_COMPLETE = "hold_then_complete"


# The worker the scripted supervisor routes to. It is the supervised worker of
# the bundled supervisor-routing team, so one routed turn crosses the plan
# approval gate and then the worker's own permission pause.
_ROUTED_WORKER_ID = "deterministic-permission-pause"

_SCRIPTED_SUPERVISOR_ID = "deterministic-scripted-supervisor"
_BRANCH_RESEARCHER_ID = "deterministic-branch-researcher"

# These agents deliberately select a scenario through the same ``AgentConfig``
# injection that the production ``ProviderFactory`` uses for the role-keyed
# research_adr content. Each remains entirely in-process and exists only to
# exercise a real BaseChatModel/worker seam. A star supervisor a worker compiles
# is always built from the default supervisor agent, so the routing scenario is
# keyed on that id; the scripted supervisor has an agent of its own because a
# test hands it to the compiler directly. The revising verdict is served under
# two roles: the document topology seats its reviewer by the ``doc-reviewer``
# role, and a review loop outside it takes a plain ``reviewer``, since a document
# role in a coding topology would misstate what its preset authors. The
# completing turn is served under a coder and a reviewer for the same reason: a
# coding team's turn, and the review that ends its loop, finish with content that
# asks for no revision.
_SCRIPT_BY_AGENT_ID: dict[str, _DeterministicScript] = {
    "deterministic-coder-success": _DeterministicScript.COMPLETION,
    "deterministic-passing-reviewer": _DeterministicScript.COMPLETION,
    DEFAULT_SUPERVISOR_ID: _DeterministicScript.SUPERVISOR_ROUTING,
    _SCRIPTED_SUPERVISOR_ID: _DeterministicScript.SCRIPTED_SUPERVISOR,
    "deterministic-revising-doc-reviewer": _DeterministicScript.REVISING_REVIEW,
    "deterministic-revising-reviewer": _DeterministicScript.REVISING_REVIEW,
    _BRANCH_RESEARCHER_ID: _DeterministicScript.BRANCH_RESEARCH,
    _ROUTED_WORKER_ID: _DeterministicScript.PERMISSION_PAUSE,
    "deterministic-cancel-window": _DeterministicScript.CANCEL_WINDOW,
    "deterministic-relay-burst": _DeterministicScript.RELAY_BURST,
    "deterministic-looping": _DeterministicScript.LOOPING,
    "deterministic-hold-then-complete": _DeterministicScript.HOLD_THEN_COMPLETE,
}

# The supervisor node's own completion route.
_FINISH_ROUTE = "FINISH"

_PERMISSION_TOOL_NAME = "deterministic_permission"
_ALLOW_OPTION_ID = "allow_once"
_SCRIPTED_PERMISSION_OPTIONS: tuple[tuple[str, str], ...] = (
    (_ALLOW_OPTION_ID, "Allow once"),
    ("deny_once", "Deny once"),
)

UNATTENDED_REPLY = "Deterministic task completed unattended; no permission was asked."
"""A permission scenario's reply on a turn that has no one to ask."""

# The research producer states each branch's thread in a system message of its
# own; the branch researcher reads it back so its requests and its finding name
# the branch that made them.
_RESEARCH_BRANCH_LINE = re.compile(r"Research thread '([^']*)'")

_RELAY_BURST_CHUNKS = 1100
_RELAY_BURST_CHUNK_BYTES = 4096
_LOOP_INTERVAL_SECONDS = 0.05
# How often a held turn looks for its gate's removal. The hold ends on that
# signal, never on elapsed time, so this bounds only the release latency.
_HOLD_POLL_SECONDS = 0.05
_HELD_TURN_REPLY = "Deterministic held turn completed after its release."

# A completing turn's content: it carries no revision sentinel, so a reviewer that
# answers it ends a review loop on its first pass.
_COMPLETED_TURN_REPLY = "Deterministic turn completed."

# The verdict every role-keyed reviewer returns, which advances the inner review
# loop; only the revising reviewer scenario sends work back.
_REVIEW_PASS = "PASS"

# The revising reviewer's verdict: the sentinel the review routers send work back
# on, with one finding for the writer to address.
_REVIEW_REVISION = (
    f"{REVIEW_REVISION_SENTINEL}\n1. The claims need re-fetchable locators."
)

# This provider emits no clarification sentinel. A marker once lived here that
# made the researcher's turn ask a question instead of researching, for a ground
# stage that inferred questions from the run's own prompt. That stage is gone:
# questions now come from the preset, so no model output can trigger one, and an
# emitter whose only reader has been deleted is dead weight that reads as a
# feature. Driving the clarification loop is the preset's job, not this model's.


def _research_findings(feature: str, topic: str) -> str:
    """Return the researcher's findings text, which feeds synthesis."""
    return (
        f"Research findings for `{topic}` under `{feature}`: the phase machine, "
        "gate parking, and materialization are the three tenets to synthesize."
    )


def _research_document(feature: str, topic: str) -> str:
    """Return a valid research document body for the synthesist to propose."""
    return (
        "---\n"
        "tags:\n"
        "  - '#research'\n"
        f"  - '#{feature}'\n"
        "---\n\n"
        f"# `{feature}` research: `{topic}`\n\n"
        f"Deterministic research synthesis for `{topic}`, produced by the "
        "in-process acceptance provider.\n\n"
        "## Findings\n\n"
        "- The research_adr phase machine parks a proposal at the research gate.\n"
        "- The verdict is driven over the engine review surface, not in-graph.\n"
        "- Materialization is proven by the apply receipt plus the on-disk file.\n"
    )


def _adr_document(feature: str, topic: str) -> str:
    """Return a valid ADR document body for the adr-author to propose."""
    return (
        "---\n"
        "tags:\n"
        "  - '#adr'\n"
        f"  - '#{feature}'\n"
        "---\n\n"
        f"# `{feature}` adr: `{topic}` | (**status:** `accepted`)\n\n"
        "## Problem Statement\n\n"
        f"Prove the Research -> ADR contract end to end for `{topic}`.\n\n"
        "## Decision\n\n"
        "Adopt the deterministic acceptance harness as the standing proof that a "
        "prompt materializes exactly two governed documents on disk.\n\n"
        "## Consequences\n\n"
        "The harness is provider-agnostic; real providers are proven by the same "
        "driver against a live profile.\n"
    )


def _plan_document(feature: str, topic: str) -> str:
    """Return a valid plan document body for the plan-author to propose."""
    return (
        "---\n"
        "tags:\n"
        "  - '#plan'\n"
        f"  - '#{feature}'\n"
        "tier: 'L1'\n"
        "---\n\n"
        f"# `{feature}` plan\n\n"
        "## Description\n\n"
        f"Sequence the work the in-run ADR decided for `{topic}`, produced by the "
        "in-process acceptance provider. The plan re-argues nothing; it names the "
        "ordered Steps that carry the decision into the codebase.\n\n"
        "## Steps\n\n"
        "- [ ] `S01` - wire the plan phase behind the ADR gate; "
        "`src/vaultspec_a2a/graph/compiler.py`.\n"
        "- [ ] `S02` - extend the served capability declaration; "
        "`src/vaultspec_a2a/team/team_config.py`.\n\n"
        "## Parallelization\n\n"
        "Both Steps touch one topology definition and carry hard ordering; run them "
        "in sequence.\n\n"
        "## Verification\n\n"
        "The compiled graph parks on the plan gate after the ADR gate returns an "
        "approved verdict, and the served capability list names the plan document.\n"
    )


def _review_verdict(feature: str, topic: str) -> str:
    """Return the reviewer's verdict, which advances the inner review loop."""
    del feature, topic  # every review passes, whatever it reviewed
    return _REVIEW_PASS


# Each research_adr role's content, bound to the authoring contract's roles in
# their pipeline order. ``strict`` fails the import if the contract's roster
# changes length without this table changing with it.
_CONTENT_BY_ROLE: dict[str, Callable[[str, str], str]] = dict(
    zip(
        RESEARCH_ADR_ROLES,
        (
            _research_findings,
            _research_document,
            _adr_document,
            _plan_document,
            _review_verdict,
        ),
        strict=True,
    )
)


def _role_of(agent_id: str | None) -> str | None:
    """Resolve the research_adr role from a (possibly namespaced) agent id.

    Matched as a suffix, so a bare ("researcher") and a namespaced
    ("vaultspec-researcher") agent id resolve to the same role. No contract role
    is a suffix of another, so the order the roles are tried in is immaterial.
    """
    if not agent_id:
        return None
    for role in RESEARCH_ADR_ROLES:
        if agent_id == role or agent_id.endswith(role):
            return role
    return None


def _script_of(agent_id: str | None) -> _DeterministicScript | None:
    """Return the explicit deterministic scenario selected by an agent id."""
    return _SCRIPT_BY_AGENT_ID.get(agent_id) if agent_id else None


def _script_lines(persona: str) -> tuple[str, ...]:
    """Read a persona as a script: one entry per non-blank line."""
    return tuple(line.strip() for line in persona.splitlines() if line.strip())


def _scripted_preset(agent_id: str, script: tuple[str, ...]) -> AgentConfig:
    """Load *agent_id*'s bundled preset with *script* as its persona.

    Each entry must read back as itself - one non-blank line apiece - or the
    model would follow a script other than the one its test stated.
    """
    persona = "\n".join(script)
    if not script or _script_lines(persona) != script:
        raise ValueError(
            f"a script is one or more non-blank, single-line entries: {script!r}"
        )
    agent = load_agent_config(agent_id)
    return agent.model_copy(
        update={"persona": AgentPersonaConfig(system_prompt=persona)}
    )


def scripted_supervisor(*replies: str) -> AgentConfig:
    """Return the scripted supervisor's preset, routing by *replies* in order.

    The last reply repeats once the others are spent, so a single reply is a
    supervisor that answers the same way however often it is asked.
    """
    return _scripted_preset(_SCRIPTED_SUPERVISOR_ID, replies)


def branch_researcher(*tools: str) -> AgentConfig:
    """Return the branch researcher's preset, asking to run *tools* on each branch."""
    return _scripted_preset(_BRANCH_RESEARCHER_ID, tools)


def _research_branch(messages: list[BaseMessage]) -> str:
    """Return the research branch the producer stated for this turn."""
    for message in messages:
        found = _RESEARCH_BRANCH_LINE.search(str(message.content))
        if found is not None:
            return found.group(1)
    raise RuntimeError(
        "deterministic branch researcher was served outside a research branch"
    )


def _offered_permission_options() -> list[JsonObject]:
    """The options every scripted permission request offers, in wire shape."""
    return [
        {"optionId": choice_id, "name": name}
        for choice_id, name in _SCRIPTED_PERMISSION_OPTIONS
    ]


def _supervisor_route(messages: list[BaseMessage]) -> str:
    """Route to the scripted worker until it has answered the latest human turn.

    Scanning back from the newest message, the worker's reply ends the turn and
    a human message opens one, so a queued follow-up turn is routed to the
    worker again instead of being finished on the previous turn's answer.
    """
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and message.name == _ROUTED_WORKER_ID:
            return _FINISH_ROUTE
    return _ROUTED_WORKER_ID


class DeterministicResearchAdrChatModel(BaseChatModel):
    """In-process ``BaseChatModel`` returning fixed role content or a scenario.

    Selected through the real provider path by its registered lane; the
    factory injects the run's ``AgentConfig`` so the model resolves its role or
    its scenario. The output is deterministic and derives only from the agent
    id and persona, feature tag, topic, the turn's messages, the permission
    answers and how many scripted replies it has given, never from a network
    call. A held turn's content is fixed as well; its test decides only when it
    completes, through the hold gate.
    """

    feature_tag: str = "acceptance-harness"
    topic: str = "research_adr acceptance"
    agent_config: AgentConfig | None = Field(default=None, exclude=True)
    permission_callback: PermissionCallback | None = Field(default=None, exclude=True)
    hold_gate: Path | None = Field(default=None, exclude=True)

    _cancel_window_entered: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
    _replies_given: int = PrivateAttr(default=0)

    @property
    @override
    def _llm_type(self) -> str:
        return "deterministic-research-adr-chat-model"

    @property
    def _agent_id(self) -> str | None:
        return self.agent_config.id if self.agent_config else None

    def _content_for_role(self) -> str:
        """Return the deterministic content for this model's resolved role."""
        role = _role_of(self._agent_id)
        if role is not None:
            return _CONTENT_BY_ROLE[role](self.feature_tag, self.topic)
        # Unknown role: emit an honest, non-empty marker rather than silent empty
        # content, so a misconfigured preset surfaces instead of a blank proposal.
        logger.warning(
            "DeterministicResearchAdrChatModel: unresolved role for agent_id=%r",
            self._agent_id,
        )
        return f"Deterministic content for `{self.topic}`."

    async def wait_for_cancel_window(self) -> None:
        """Wait until the cancellation scenario has entered its blocking turn."""
        await self._cancel_window_entered.wait()

    def _script(self) -> tuple[str, ...]:
        """Return this model's script, read from its agent's persona."""
        if self.agent_config is None:
            return ()
        return _script_lines(self.agent_config.persona.system_prompt)

    def _scripted_reply(self) -> str:
        """Give the scripted supervisor's next reply; the last one repeats.

        Counted on this instance, which a compiled graph keeps for its
        supervisor across every routing turn of its runs.
        """
        replies = self._script()
        if not replies:
            raise RuntimeError(
                "deterministic scripted supervisor was served with no replies"
            )
        reply = replies[min(self._replies_given, len(replies) - 1)]
        self._replies_given += 1
        return reply

    async def _permission_pause_content(self) -> str:
        """Ask the worker's permission callback once and report the decision.

        The worker wires a callback into every supervised turn and none into an
        autonomous one, so a turn without a callback has no one to ask and
        proceeds unattended, as an autonomous run on any lane does.
        """
        callback = self.permission_callback
        if callback is None:
            return UNATTENDED_REPLY
        option_id = await callback(
            _PERMISSION_TOOL_NAME,
            {"purpose": "exercise the generic supervised permission seam"},
            _offered_permission_options(),
        )
        if option_id == _ALLOW_OPTION_ID:
            return f"Deterministic permission approved with {option_id}."
        return f"Deterministic permission denied with {option_id}."

    async def _branch_research_content(self, messages: list[BaseMessage]) -> str:
        """Ask to run each scripted tool on this branch, then report the answers.

        Every request names the branch and the call's place in the script, so
        each is its own request even when a script names one tool twice. As on
        the permission-pause worker, a turn without a callback has no one to ask
        and reports, for its branch, that it proceeded unattended.
        """
        branch = _research_branch(messages)
        callback = self.permission_callback
        if callback is None:
            return f"{branch}: {UNATTENDED_REPLY}"
        tools = self._script()
        if not tools:
            raise RuntimeError(
                "deterministic branch researcher was served with no tools to ask for"
            )
        granted = [
            await callback(
                tool, {"thread": branch, "call": index}, _offered_permission_options()
            )
            for index, tool in enumerate(tools)
        ]
        return f"{branch}: granted {' '.join(granted)}"

    async def _held_turn_content(self) -> str:
        """Hold the turn while its gate file exists, then complete it.

        The gate is a release signal the test controls from its own process: the
        turn waits for the file's removal, so it stays in flight for exactly as
        long as the test keeps the gate closed. A model given no gate has nothing
        to wait on and refuses the turn, so a stack that forgot to configure one
        fails loudly instead of completing a turn its test expected to hold.
        """
        gate = self.hold_gate
        if gate is None:
            raise RuntimeError(
                "deterministic hold-then-complete turn was served without a hold gate"
            )
        while gate.exists():
            await asyncio.sleep(_HOLD_POLL_SECONDS)
        return _HELD_TURN_REPLY

    async def _looping_chunks(self) -> AsyncIterator[ChatGenerationChunk]:
        """Generate output forever; only cancelling the turn ends it."""
        iteration = 0
        while True:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=f"Deterministic loop iteration {iteration}.\n"
                )
            )
            iteration += 1
            await asyncio.sleep(_LOOP_INTERVAL_SECONDS)

    async def _turn_content(self, messages: list[BaseMessage]) -> str:
        """Return one whole turn's content: its scenario's, else its role's.

        Both the generating and the streaming path end here, so a scenario
        behaves the same whichever one the caller's callbacks select.
        """
        script = _script_of(self._agent_id)
        if script is None:
            return self._content_for_role()

        if script is _DeterministicScript.COMPLETION:
            return _COMPLETED_TURN_REPLY

        if script is _DeterministicScript.SUPERVISOR_ROUTING:
            return _supervisor_route(messages)

        if script is _DeterministicScript.SCRIPTED_SUPERVISOR:
            return self._scripted_reply()

        if script is _DeterministicScript.REVISING_REVIEW:
            return _REVIEW_REVISION

        if script is _DeterministicScript.BRANCH_RESEARCH:
            return await self._branch_research_content(messages)

        if script is _DeterministicScript.PERMISSION_PAUSE:
            return await self._permission_pause_content()

        if script is _DeterministicScript.HOLD_THEN_COMPLETE:
            return await self._held_turn_content()

        if script is _DeterministicScript.CANCEL_WINDOW:
            self._cancel_window_entered.set()
            await asyncio.Event().wait()
            raise AssertionError(
                "deterministic cancellation window unexpectedly closed"
            )

        if script is _DeterministicScript.LOOPING:
            async for _chunk in self._looping_chunks():
                pass
            raise AssertionError("deterministic loop unexpectedly ended")

        raise AssertionError(f"unhandled deterministic script {script!r}")

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Synchronous generation is unsupported; use the async path."""
        del messages, stop, run_manager, kwargs  # interface-required, unused
        raise NotImplementedError(
            "DeterministicResearchAdrChatModel only supports async via "
            "_astream/_agenerate"
        )

    @override
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Return the turn's content as a single AIMessage."""
        del stop, run_manager, kwargs  # interface-required, unused
        content = await self._turn_content(messages)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    @override
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Yield the turn's content as one chunk, or a scenario's own stream."""
        del stop, run_manager, kwargs  # interface-required, unused
        script = _script_of(self._agent_id)
        if script is _DeterministicScript.RELAY_BURST:
            for index in range(_RELAY_BURST_CHUNKS):
                # One 4 KiB chunk reaches the production event producer's immediate
                # flush threshold, so every yield becomes one real progress frame.
                # Yield control as well so the bounded subscriber queue can drain.
                prefix = f"{index:04d}:"
                content = prefix + "r" * (_RELAY_BURST_CHUNK_BYTES - len(prefix))
                yield ChatGenerationChunk(message=AIMessageChunk(content=content))
                await asyncio.sleep(0)
            # Keep the real run open after the burst so a second relay subscriber
            # can ask for a cursor the resident ring has already evicted.
            await asyncio.Event().wait()
            raise AssertionError("deterministic relay burst window unexpectedly closed")
        if script is _DeterministicScript.LOOPING:
            async for chunk in self._looping_chunks():
                yield chunk
            raise AssertionError("deterministic loop unexpectedly ended")
        content = await self._turn_content(messages)
        yield ChatGenerationChunk(message=AIMessageChunk(content=content))
