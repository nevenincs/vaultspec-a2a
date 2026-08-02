"""Tests for deterministic worker node helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ....thread.errors import WorkerExecutionError

if TYPE_CHECKING:
    from langchain_core.outputs import ChatResult

    from ....thread.state import TeamState

from ...nodes.worker import (
    _build_worker_messages,
    _describe_worker_model,
    _resolve_resume_option_id,
    _wrap_worker_exception,
)


def test_worker_exception_wraps_with_context() -> None:
    """Worker failures are wrapped with worker/model attribution context."""
    wrapped = _wrap_worker_exception(
        exc=RuntimeError("boom"),
        worker="coder",
        model_label="claude/claude-sonnet-4-5",
        message_count=3,
    )
    assert wrapped.worker == "coder"
    assert wrapped.model == "claude/claude-sonnet-4-5"
    assert "coder" in str(wrapped)


def test_worker_exception_chains_original_cause() -> None:
    """The wrapping helper returns a WorkerExecutionError that can be chained."""
    original = RuntimeError("root cause")
    wrapped = _wrap_worker_exception(
        exc=original,
        worker="coder",
        model_label="mock/coder",
        message_count=1,
    )
    assert isinstance(wrapped, WorkerExecutionError)


def test_worker_model_label_names_the_lane_and_the_model_id() -> None:
    """The label names what the turn ran on, not which class carried it.

    Driven against the real ACP chat model because the class name it would
    otherwise report - one class serving every ACP lane behind a redirected base
    URL - is exactly the identity this replaces.
    """
    from ....providers.acp_chat_model import AcpChatModel

    model = AcpChatModel(
        command=["true"],
        env_vars={},
        provider="zai",
        desired_model="glm-4.6",
    )

    assert _describe_worker_model(model) == "zai/glm-4.6"


def test_worker_model_label_falls_back_to_the_class_it_can_name() -> None:
    """A model declaring no lane and no id is still named, just less precisely."""

    class _Unidentified(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "unidentified"

        def _generate(self, *args: object, **kwargs: object) -> ChatResult:
            raise NotImplementedError

    assert _describe_worker_model(_Unidentified()) == "_Unidentified"


def test_worker_model_label_declines_an_unbounded_identity() -> None:
    """An overlong value is not an identity and is not truncated into one.

    A model id reaches a client-visible failure reason, so a pathological value
    must not eat the budget the provider's own message needs.
    """

    class _Overlong(BaseChatModel):
        model_name: str = "m" * 500

        @property
        def _llm_type(self) -> str:
            return "overlong"

        def _generate(self, *args: object, **kwargs: object) -> ChatResult:
            raise NotImplementedError

    assert _describe_worker_model(_Overlong()) == "_Overlong"


def test_resolve_resume_option_id_accepts_valid_string() -> None:
    """A valid string resume payload should pass through unchanged."""
    options = [{"optionId": "approve"}, {"optionId": "reject_once"}]
    assert _resolve_resume_option_id("approve", options) == "approve"


def test_resolve_resume_option_id_accepts_valid_dict_payload() -> None:
    """A valid dict resume payload should resolve by option_id."""
    options = [{"optionId": "approve"}, {"optionId": "reject_once"}]
    assert (
        _resolve_resume_option_id({"option_id": "reject_once"}, options)
        == "reject_once"
    )


def test_resolve_resume_option_id_rejects_unknown_string() -> None:
    """Unknown resume values must fail closed instead of coercing to allow."""
    options = [{"optionId": "approve"}, {"optionId": "reject_once"}]
    with pytest.raises(RuntimeError, match="unknown option_id"):
        _resolve_resume_option_id("hostile-option", options)


def test_resolve_resume_option_id_rejects_missing_option_id_in_dict() -> None:
    """Malformed dict resume payloads must fail closed."""
    options = [{"optionId": "approve"}, {"optionId": "reject_once"}]
    with pytest.raises(RuntimeError, match="option_id string"):
        _resolve_resume_option_id({"approved": True}, options)


def test_resolve_resume_option_id_accepts_snake_case_options() -> None:
    """Options offered in snake_case validate a resume answering in kind.

    The resume payload has always read ``option_id``; the interrupt's OPTIONS
    were camelCase-only, so a snake_case options list validated nothing and this
    legitimate answer failed closed with "no valid option ids".
    """
    options = [{"option_id": "approve"}, {"option_id": "reject_once"}]
    assert (
        _resolve_resume_option_id({"option_id": "reject_once"}, options)
        == "reject_once"
    )
    assert _resolve_resume_option_id("approve", options) == "approve"


def test_resolve_resume_option_id_still_rejects_an_unknown_snake_case_answer() -> None:
    """Accepting the spelling must not weaken the membership check."""
    options = [{"option_id": "approve"}]
    with pytest.raises(RuntimeError, match="unknown option_id"):
        _resolve_resume_option_id({"option_id": "hostile-option"}, options)


def test_resolve_resume_option_id_ignores_an_option_carrying_no_id() -> None:
    """A malformed option contributes no id, so it can never be resumed with."""
    options = [{"optionId": "approve"}, {"label": "Nameless option"}]
    with pytest.raises(RuntimeError, match="unknown option_id"):
        _resolve_resume_option_id({"option_id": "Nameless option"}, options)


def test_build_worker_messages_adds_rejection_revision_instruction() -> None:
    """Rejected supervisor plans should add a deterministic revision instruction."""
    state: TeamState = {
        "messages": [HumanMessage(content="Implement the approved feature.")],
        "active_agent": "mock-coder-human",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "thread-worker-reject",
        "token_usage": {},
        "next": "",
        "active_feature": "audit-five-reject",
        "approval_status": "rejected",
        "routing_error": (
            "Plan rejected by user — revise before proceeding to execution."
        ),
    }

    messages = _build_worker_messages(
        state=state,
        system_prompt="You are a mock coder.",
        workspace_root=None,
    )

    assert any(
        isinstance(message, SystemMessage)
        and (
            "revise the implementation plan before requesting privileged "
            "execution again"
        )
        in str(message.content)
        for message in messages
    )


def _minimal_state() -> TeamState:
    return {
        "messages": [HumanMessage(content="Revise the research document.")],
        "active_agent": "vaultspec-synthesist",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "thread-feedback",
        "token_usage": {},
        "next": "",
        "active_feature": "edge-feature",
    }


def test_build_worker_messages_grounds_feedback_when_present() -> None:
    """A revision run's feedback grounding rides as a labelled SystemMessage."""
    grounding = "- Overview: tighten the scope\n- Risks: add a fallback"
    messages = _build_worker_messages(
        state=_minimal_state(),
        system_prompt="You are the synthesist.",
        workspace_root=None,
        role="synthesist",
        feedback_grounding=grounding,
    )
    feedback_msgs = [
        m
        for m in messages
        if isinstance(m, SystemMessage)
        and "Reviewer feedback to address" in str(m.content)
    ]
    assert len(feedback_msgs) == 1
    assert grounding in str(feedback_msgs[0].content)


def test_build_worker_messages_has_no_feedback_block_when_absent() -> None:
    """Absent feedback grounding adds no block (zero behaviour change)."""
    for grounding in (None, ""):
        messages = _build_worker_messages(
            state=_minimal_state(),
            system_prompt="You are the synthesist.",
            workspace_root=None,
            role="synthesist",
            feedback_grounding=grounding,
        )
        assert not any(
            isinstance(m, SystemMessage)
            and "Reviewer feedback to address" in str(m.content)
            for m in messages
        )


def test_build_worker_messages_scopes_document_role_not_coder(tmp_path) -> None:
    """A document role gets role-scoped rules; a coder role gets the whole corpus.

    P04 wiring: ``_build_worker_messages`` routes a research_adr document role to the
    role-scoped bundled conventions and every other role (coders) to the unchanged
    whole-corpus compile, so a coder's rules are never stripped.
    """
    rules_dir = tmp_path / ".vaultspec" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "coder-only.md").write_text(
        "---\norder: 1\n---\n\nCODER ONLY GUIDANCE\n", encoding="utf-8"
    )
    state: TeamState = {
        "messages": [HumanMessage(content="go")],
        "active_agent": "a",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "t",
        "token_usage": {},
        "next": "",
        "active_feature": "f",
        "approval_status": None,
        "routing_error": None,
    }

    def _rules_text(role: str) -> str:
        messages = _build_worker_messages(
            state=state,
            system_prompt="sp",
            workspace_root=tmp_path,
            role=role,
        )
        return "\n".join(
            str(m.content)
            for m in messages
            if isinstance(m, SystemMessage) and "Project Coding Rules" in str(m.content)
        )

    # Document role: scoped to the bundled document-authoring conventions; the
    # untagged coder rule is NOT included.
    doc = _rules_text("researcher")
    assert "Emission mechanics" in doc  # a stable heading from the bundled conventions
    assert "CODER ONLY GUIDANCE" not in doc

    # Coder role: whole WORKSPACE corpus (role=None), so the untagged coder rule
    # IS included - scoping never strips it.
    coder = _rules_text("standard-executor")
    assert "CODER ONLY GUIDANCE" in coder
    # ...and the bundled document-authoring conventions do NOT leak into a coder
    # turn (the bundled dir is gated on document roles). A
    # one-sided "coder rules present" assertion would pass the leak green.
    assert "Emission mechanics" not in coder
