from langgraph.errors import GraphBubbleUp, GraphInterrupt
from langgraph.types import Interrupt

from ..exceptions import WorkerExecutionError
from ..nodes.worker import _wrap_worker_exception

# ---------------------------------------------------------------------------
# T04 — WorkerExecutionError wrapping
# ---------------------------------------------------------------------------


def test_worker_exception_wraps_with_context() -> None:
    """Worker failures are wrapped with worker/model attribution context."""
    wrapped = _wrap_worker_exception(
        exc=RuntimeError("boom"),
        worker="coder",
        model_type="AcpChatModel",
        message_count=3,
    )

    err = wrapped
    assert err.worker == "coder"
    assert err.model == "AcpChatModel"
    assert "coder" in str(err)
    assert "AcpChatModel" in str(err)


def test_worker_exception_chains_original_cause() -> None:
    """The wrapping helper returns a WorkerExecutionError that can be chained."""
    original_message = "network timeout"
    original = RuntimeError(original_message)

    try:
        raise _wrap_worker_exception(
            exc=original,
            worker="planner",
            model_type="AcpChatModel",
            message_count=2,
        ) from original
    except WorkerExecutionError as exc:
        cause = exc.__cause__
        assert cause is not None
        assert original_message in str(cause)


def test_worker_graphinterrupt_not_wrapped() -> None:
    """LangGraph interrupts remain GraphBubbleUp values, not wrapped worker errors."""
    interrupt_exc = GraphInterrupt(
        (
            Interrupt(
                value={"type": "permission_request"},
                resumable=True,
                ns=(),
                when="during",
            ),
        )
    )

    assert isinstance(interrupt_exc, GraphBubbleUp)
    assert not isinstance(interrupt_exc, WorkerExecutionError)
    assert isinstance(interrupt_exc, GraphInterrupt)


def test_worker_execution_error_is_importable_from_core() -> None:
    """WorkerExecutionError is exported from vaultspec_a2a.core (public API)."""
    from vaultspec_a2a.core import WorkerExecutionError as WorkerExecErr

    assert WorkerExecErr is WorkerExecutionError
