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
- scripted scenarios: supervisor routing, a supervised permission pause, a
  provider failure, a cancellation window, a relay burst, and an endless
  generation loop, each selected by the bundled agent that names it.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from enum import StrEnum
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
from ...providers._acp_types import PermissionCallback
from ...team.team_config import AgentConfig
from ...thread.constants import DEFAULT_SUPERVISOR_ID

logger = logging.getLogger(__name__)

__all__ = ["UNATTENDED_REPLY", "DeterministicResearchAdrChatModel"]


class _DeterministicScript(StrEnum):
    """Named in-process scenarios selected by their bundled agent identity."""

    SUPERVISOR_ROUTING = "supervisor_routing"
    PERMISSION_PAUSE = "permission_pause"
    FAILURE = "failure"
    CANCEL_WINDOW = "cancel_window"
    RELAY_BURST = "relay_burst"
    LOOPING = "looping"


# The worker the scripted supervisor routes to. It is the supervised worker of
# the bundled supervisor-routing team, so one routed turn crosses the plan
# approval gate and then the worker's own permission pause.
_ROUTED_WORKER_ID = "deterministic-permission-pause"

# These agents deliberately select a scenario through the same ``AgentConfig``
# injection that the production ``ProviderFactory`` uses for the role-keyed
# research_adr content. Each remains entirely in-process and exists only to
# exercise a real BaseChatModel/worker seam. A star supervisor is always built
# from the default supervisor agent, so the routing scenario is keyed on that id
# rather than on an agent of its own.
_SCRIPT_BY_AGENT_ID: dict[str, _DeterministicScript] = {
    DEFAULT_SUPERVISOR_ID: _DeterministicScript.SUPERVISOR_ROUTING,
    _ROUTED_WORKER_ID: _DeterministicScript.PERMISSION_PAUSE,
    "deterministic-failure": _DeterministicScript.FAILURE,
    "deterministic-cancel-window": _DeterministicScript.CANCEL_WINDOW,
    "deterministic-relay-burst": _DeterministicScript.RELAY_BURST,
    "deterministic-looping": _DeterministicScript.LOOPING,
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
"""The permission-pause worker's reply on a turn that has no one to ask."""

_RELAY_BURST_CHUNKS = 1100
_RELAY_BURST_CHUNK_BYTES = 4096
_LOOP_INTERVAL_SECONDS = 0.05

# The reviewer sentinel the research_adr inner-review router advances on (the
# REVISION path is driven by the gate verdict, not this provider).
_REVIEW_PASS = "PASS"

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
    id, feature tag, topic, the turn's messages and the permission answer, never
    from a network call.
    """

    feature_tag: str = "acceptance-harness"
    topic: str = "research_adr acceptance"
    agent_config: AgentConfig | None = Field(default=None, exclude=True)
    permission_callback: PermissionCallback | None = Field(default=None, exclude=True)

    _cancel_window_entered: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)

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
            [
                {"optionId": choice_id, "name": name}
                for choice_id, name in _SCRIPTED_PERMISSION_OPTIONS
            ],
        )
        if option_id == _ALLOW_OPTION_ID:
            return f"Deterministic permission approved with {option_id}."
        return f"Deterministic permission denied with {option_id}."

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

        if script is _DeterministicScript.SUPERVISOR_ROUTING:
            return _supervisor_route(messages)

        if script is _DeterministicScript.PERMISSION_PAUSE:
            return await self._permission_pause_content()

        if script is _DeterministicScript.FAILURE:
            raise RuntimeError("deterministic scripted provider failure")

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
                # One 4 KiB chunk reaches the production aggregator's immediate
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
