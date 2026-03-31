"""Tests for deterministic worker node helpers."""

import pytest

from vaultspec_a2a.thread.errors import WorkerExecutionError

from ...nodes.worker import _resolve_resume_option_id, _wrap_worker_exception


def test_worker_exception_wraps_with_context() -> None:
    """Worker failures are wrapped with worker/model attribution context."""
    wrapped = _wrap_worker_exception(
        exc=RuntimeError("boom"),
        worker="coder",
        model_type="AcpChatModel",
        message_count=3,
    )
    assert wrapped.worker == "coder"
    assert wrapped.model == "AcpChatModel"
    assert "coder" in str(wrapped)


def test_worker_exception_chains_original_cause() -> None:
    """The wrapping helper returns a WorkerExecutionError that can be chained."""
    original = RuntimeError("root cause")
    wrapped = _wrap_worker_exception(
        exc=original,
        worker="coder",
        model_type="MockModel",
        message_count=1,
    )
    assert isinstance(wrapped, WorkerExecutionError)


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
