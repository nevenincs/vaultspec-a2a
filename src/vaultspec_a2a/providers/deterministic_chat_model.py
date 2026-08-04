"""Deterministic in-process provider for the research_adr acceptance harness.

``DeterministicResearchAdrChatModel`` is a first-class ``BaseChatModel`` (the
``mock_chat_model.py`` precedent) that returns fixed, role-keyed research/ADR
content with no live model spend and no external service. Unlike ``MockChatModel``
(which proxies to the VidaiMock HTTP tape server), this provider runs entirely
in-process, so the standing acceptance harness can drive the full
Research -> ADR -> Plan contract without Docker or provider credentials.

The content is keyed by the worker ``AgentConfig.id`` so each research_adr role
(researcher, synthesist, adr-author, plan-author, doc-reviewer) receives
role-appropriate output: the writers emit a valid vault-shaped markdown document
the submitter can propose, and the reviewer emits the ``PASS`` sentinel that
advances the inner review loop. The feature tag and topic are configurable so a
parameterized harness can assert the materialized document stems.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
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
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

from ..team.team_config import AgentConfig
from ._acp_types import PermissionCallback

logger = logging.getLogger(__name__)

__all__ = ["DeterministicResearchAdrChatModel"]


class _DeterministicScript(StrEnum):
    """Named in-process scenarios selected by their bundled agent identity."""

    TOOL_CALL = "tool_call"
    PERMISSION_PAUSE = "permission_pause"
    FAILURE = "failure"
    CANCEL_WINDOW = "cancel_window"


# These agents deliberately select a scenario through the same ``AgentConfig``
# injection that the production ``ProviderFactory`` uses for the role-keyed
# research_adr content. They are not mock/tape aliases: each remains entirely
# in-process and exists only to exercise a real BaseChatModel/worker seam.
_SCRIPT_BY_AGENT_ID: dict[str, _DeterministicScript] = {
    "deterministic-tool-call": _DeterministicScript.TOOL_CALL,
    "deterministic-permission-pause": _DeterministicScript.PERMISSION_PAUSE,
    "deterministic-failure": _DeterministicScript.FAILURE,
    "deterministic-cancel-window": _DeterministicScript.CANCEL_WINDOW,
}

_SCRIPTED_TOOL_CALL_ID = "deterministic-mark-task-complete"
_SCRIPTED_PERMISSION_OPTIONS: tuple[tuple[str, str], ...] = (
    ("allow_once", "Allow once"),
    ("deny_once", "Deny once"),
)

# Canonical research_adr worker roles (the authoring contract's
# RESEARCH_ADR_ROLES), matched as a suffix of the AgentConfig id so both bare
# ("researcher") and namespaced ("vaultspec-researcher") agent ids resolve to the
# same role content. Kept as individual per-role content-dispatch keys here rather
# than importing the contract tuple (the leaf provider stays free of a graph/team
# runtime edge); a contract-sync test asserts these never diverge from
# RESEARCH_ADR_ROLES (authoring-contract ADR binding (b)).
_ROLE_RESEARCHER = "researcher"
_ROLE_SYNTHESIST = "synthesist"
_ROLE_ADR_AUTHOR = "adr-author"
_ROLE_PLAN_AUTHOR = "plan-author"
_ROLE_DOC_REVIEWER = "doc-reviewer"

# The role dispatch keys as an introspectable collection, ordered so a namespaced
# agent id resolves against every candidate suffix. This is the module's single
# source for the resolver loop and the contract-sync guard.
_ROLE_DISPATCH_KEYS: tuple[str, ...] = (
    _ROLE_ADR_AUTHOR,
    _ROLE_PLAN_AUTHOR,
    _ROLE_DOC_REVIEWER,
    _ROLE_SYNTHESIST,
    _ROLE_RESEARCHER,
)

# The reviewer sentinel the research_adr inner-review router advances on (the
# REVISION path is driven by the gate verdict, not this provider).
_REVIEW_PASS = "PASS"

# This provider emits no clarification sentinel. A marker once lived here that
# made the researcher's turn ask a question instead of researching, for a ground
# stage that inferred questions from the run's own prompt. That stage is gone:
# questions now come from the preset, so no model output can trigger one, and an
# emitter whose only reader has been deleted is dead weight that reads as a
# feature. Driving the clarification loop is the preset's job, not this model's.


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


def _role_of(agent_id: str | None) -> str | None:
    """Resolve the research_adr role from a (possibly namespaced) agent id."""
    if not agent_id:
        return None
    for role in _ROLE_DISPATCH_KEYS:
        if agent_id == role or agent_id.endswith(role):
            return role
    return None


def _script_of(agent_id: str | None) -> _DeterministicScript | None:
    """Return the explicit deterministic scenario selected by an agent id."""
    return _SCRIPT_BY_AGENT_ID.get(agent_id) if agent_id else None


class DeterministicResearchAdrChatModel(BaseChatModel):
    """In-process ``BaseChatModel`` returning fixed research_adr role content.

    Selected through the real provider path via ``Provider.DETERMINISTIC``; the
    factory injects the run's ``AgentConfig`` so the model resolves its role. The
    output is deterministic and derives only from the role, feature tag, and
    topic, never from a network call.
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

    def _content_for_role(self) -> str:
        """Return the deterministic content for this model's resolved role."""
        role = _role_of(self.agent_config.id if self.agent_config else None)
        if role == _ROLE_DOC_REVIEWER:
            return _REVIEW_PASS
        if role == _ROLE_ADR_AUTHOR:
            return _adr_document(self.feature_tag, self.topic)
        if role == _ROLE_PLAN_AUTHOR:
            return _plan_document(self.feature_tag, self.topic)
        if role == _ROLE_SYNTHESIST:
            return _research_document(self.feature_tag, self.topic)
        if role == _ROLE_RESEARCHER:
            return (
                f"Research findings for `{self.topic}` under `{self.feature_tag}`: "
                "the phase machine, gate parking, and materialization are the "
                "three tenets to synthesize."
            )
        # Unknown role: emit an honest, non-empty marker rather than silent empty
        # content, so a misconfigured preset surfaces instead of a blank proposal.
        logger.warning(
            "DeterministicResearchAdrChatModel: unresolved role for agent_id=%r",
            self.agent_config.id if self.agent_config else None,
        )
        return f"Deterministic content for `{self.topic}`."

    async def wait_for_cancel_window(self) -> None:
        """Wait until the cancellation scenario has entered its blocking turn."""
        await self._cancel_window_entered.wait()

    async def _scripted_result(
        self,
        script: _DeterministicScript,
        messages: list[BaseMessage],
    ) -> ChatResult:
        """Execute one bounded non-tape scenario through this real model."""
        if script is _DeterministicScript.TOOL_CALL:
            settled = any(
                isinstance(message, ToolMessage)
                and message.tool_call_id == _SCRIPTED_TOOL_CALL_ID
                for message in messages
            )
            if settled:
                response = AIMessage(content="Deterministic task queue update settled.")
            else:
                response = AIMessage(
                    content="Marking the deterministic task complete.",
                    tool_calls=[
                        {
                            "id": _SCRIPTED_TOOL_CALL_ID,
                            "name": "mark_task_complete",
                            "args": {"task_id": "D-1"},
                            "type": "tool_call",
                        }
                    ],
                )
            return ChatResult(generations=[ChatGeneration(message=response)])

        if script is _DeterministicScript.PERMISSION_PAUSE:
            callback = self.permission_callback
            if callback is None:
                raise RuntimeError(
                    "deterministic permission-pause scenario requires the worker "
                    "permission callback"
                )
            option_id = await callback(
                "deterministic_permission",
                {"purpose": "exercise the generic supervised permission seam"},
                [
                    {"optionId": choice_id, "name": name}
                    for choice_id, name in _SCRIPTED_PERMISSION_OPTIONS
                ],
            )
            response = AIMessage(
                content=f"Deterministic permission approved with {option_id}."
            )
            return ChatResult(generations=[ChatGeneration(message=response)])

        if script is _DeterministicScript.FAILURE:
            raise RuntimeError("deterministic scripted provider failure")

        if script is _DeterministicScript.CANCEL_WINDOW:
            self._cancel_window_entered.set()
            await asyncio.Event().wait()
            raise AssertionError(
                "deterministic cancellation window unexpectedly closed"
            )

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
        """Return the resolved role content as a single AIMessage."""
        del stop, run_manager, kwargs  # interface-required, unused
        script = _script_of(self.agent_config.id if self.agent_config else None)
        if script is not None:
            return await self._scripted_result(script, messages)
        content = self._content_for_role()
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
        """Yield the resolved role content as a single streaming chunk."""
        del messages, stop, run_manager, kwargs  # interface-required, unused
        content = self._content_for_role()
        yield ChatGenerationChunk(message=AIMessageChunk(content=content))
