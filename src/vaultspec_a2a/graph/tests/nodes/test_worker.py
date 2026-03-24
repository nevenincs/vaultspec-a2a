"""Tests for deterministic worker node helpers."""

from vaultspec_a2a.thread.errors import WorkerExecutionError

from ...nodes.worker import _wrap_worker_exception


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
