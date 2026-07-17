"""Deterministic in-process provider for the research_adr acceptance harness.

``DeterministicResearchAdrChatModel`` is a first-class ``BaseChatModel`` (the
``mock_chat_model.py`` precedent) that returns fixed, role-keyed research/ADR
content with no live model spend and no external service. Unlike ``MockChatModel``
(which proxies to the VidaiMock HTTP tape server), this provider runs entirely
in-process, so the standing acceptance harness can drive the full
Research -> ADR contract without Docker or provider credentials.

The content is keyed by the worker ``AgentConfig.id`` so each research_adr role
(researcher, synthesist, adr-author, doc-reviewer) receives role-appropriate
output: the writers emit a valid vault-shaped markdown document the submitter can
propose, and the reviewer emits the ``PASS`` sentinel that advances the inner
review loop. The feature tag and topic are configurable so a parameterized
harness can assert the materialized document stems.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any, override

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

from ..team.team_config import AgentConfig

logger = logging.getLogger(__name__)

__all__ = ["DeterministicResearchAdrChatModel"]

# Canonical research_adr worker roles (the authoring contract's
# DOCUMENT_AUTHORING_ROLES), matched as a suffix of the AgentConfig id so both bare
# ("researcher") and namespaced ("vaultspec-researcher") agent ids resolve to the
# same role content. Kept as individual per-role content-dispatch keys here rather
# than importing the contract tuple (the leaf provider stays free of a graph/team
# runtime edge); a contract-sync test asserts these never diverge from
# DOCUMENT_AUTHORING_ROLE_SET (authoring-contract ADR binding (b)).
_ROLE_RESEARCHER = "researcher"
_ROLE_SYNTHESIST = "synthesist"
_ROLE_ADR_AUTHOR = "adr-author"
_ROLE_DOC_REVIEWER = "doc-reviewer"

# The role dispatch keys as an introspectable collection, ordered so a namespaced
# agent id resolves against every candidate suffix. This is the module's single
# source for the resolver loop and the contract-sync guard.
_ROLE_DISPATCH_KEYS: tuple[str, ...] = (
    _ROLE_ADR_AUTHOR,
    _ROLE_DOC_REVIEWER,
    _ROLE_SYNTHESIST,
    _ROLE_RESEARCHER,
)

# The reviewer sentinel the research_adr inner-review router advances on (the
# REVISION path is driven by the gate verdict, not this provider).
_REVIEW_PASS = "PASS"


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


def _role_of(agent_id: str | None) -> str | None:
    """Resolve the research_adr role from a (possibly namespaced) agent id."""
    if not agent_id:
        return None
    for role in _ROLE_DISPATCH_KEYS:
        if agent_id == role or agent_id.endswith(role):
            return role
    return None


class DeterministicResearchAdrChatModel(BaseChatModel):
    """In-process ``BaseChatModel`` returning fixed research_adr role content.

    Selected through the real provider path via ``Provider.DETERMINISTIC``; the
    factory injects the run's ``AgentConfig`` so the model resolves its role. The
    output is deterministic and derives only from the role, feature tag, and
    topic, never from a network call.
    """

    feature_tag: str = "acceptance-harness"
    topic: str = "research_adr acceptance"
    permission_callback: Any | None = Field(default=None, exclude=True)

    _agent_config: AgentConfig | None = PrivateAttr(default=None)

    def __init__(self, **kwargs: Any) -> None:
        agent_config = kwargs.pop("agent_config", None)
        super().__init__(**kwargs)
        self._agent_config = agent_config

    @property
    def _llm_type(self) -> str:
        return "deterministic-research-adr-chat-model"

    def _content_for_role(self) -> str:
        """Return the deterministic content for this model's resolved role."""
        role = _role_of(self._agent_config.id if self._agent_config else None)
        if role == _ROLE_DOC_REVIEWER:
            return _REVIEW_PASS
        if role == _ROLE_ADR_AUTHOR:
            return _adr_document(self.feature_tag, self.topic)
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
            self._agent_config.id if self._agent_config else None,
        )
        return f"Deterministic content for `{self.topic}`."

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation is unsupported; use the async path."""
        del messages, stop, run_manager, kwargs  # interface-required, unused
        raise NotImplementedError(
            "DeterministicResearchAdrChatModel only supports async via "
            "_astream/_agenerate"
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Return the resolved role content as a single AIMessage."""
        del messages, stop, run_manager, kwargs  # interface-required, unused
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
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Yield the resolved role content as a single streaming chunk."""
        del messages, stop, run_manager, kwargs  # interface-required, unused
        content = self._content_for_role()
        yield ChatGenerationChunk(message=AIMessageChunk(content=content))
