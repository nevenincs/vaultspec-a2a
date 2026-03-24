"""Tests for lifecycle.reconciliation — pure decision logic, zero I/O."""

from vaultspec_a2a.lifecycle.reconciliation import (
    ReconciliationAction,
    ThreadSnapshot,
    compute_reconciliation_actions,
)


class TestEmptyInput:
    """Empty thread list produces empty action list."""

    def test_no_threads(self) -> None:
        actions = compute_reconciliation_actions(
            threads=[],
            checkpoint_results={},
            checkpoint_errors={},
            pending_permissions={},
        )
        assert actions == []


class TestMissingCheckpoint:
    """Threads whose checkpoint is unavailable get repair actions."""

    def test_running_thread_missing_checkpoint(self) -> None:
        thread = ThreadSnapshot(thread_id="t1", status="running", recovery_epoch=0)
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": False},
            checkpoint_errors={"t1": "file not found"},
            pending_permissions={},
        )
        assert len(actions) == 1
        action = actions[0]
        assert action.thread_id == "t1"
        assert action.new_thread_status == "repair_needed"
        assert action.repair_status == "checkpoint_unavailable"
        assert action.repair_reason == "file not found"
        assert action.increment_generation is True
        assert action.increment_recovery_epoch is True

    def test_missing_checkpoint_default_error(self) -> None:
        """When checkpoint_errors has None, falls back to generic reason."""
        thread = ThreadSnapshot(thread_id="t2", status="running", recovery_epoch=1)
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t2": False},
            checkpoint_errors={"t2": None},
            pending_permissions={},
        )
        assert actions[0].repair_reason == "checkpoint_unavailable"

    def test_missing_checkpoint_no_error_entry(self) -> None:
        """Thread not in checkpoint_errors at all gets generic reason."""
        thread = ThreadSnapshot(thread_id="t3", status="running", recovery_epoch=0)
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t3": False},
            checkpoint_errors={},
            pending_permissions={},
        )
        assert actions[0].repair_reason == "checkpoint_unavailable"


class TestCancellingThread:
    """Threads with status='cancelling' get cancel-pending actions."""

    def test_cancelling_produces_cancel_pending(self) -> None:
        thread = ThreadSnapshot(thread_id="t1", status="cancelling", recovery_epoch=0)
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": True},
            checkpoint_errors={},
            pending_permissions={},
        )
        assert len(actions) == 1
        action = actions[0]
        assert action.thread_id == "t1"
        assert action.new_thread_status is None
        assert action.repair_status == "cancel_pending"
        assert action.increment_recovery_epoch is True
        assert action.increment_generation is False


class TestPendingPermissions:
    """Threads with pending permissions get input_required treatment."""

    def test_pending_permission_transitions_to_input_required(self) -> None:
        thread = ThreadSnapshot(thread_id="t1", status="running", recovery_epoch=0)
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": True},
            checkpoint_errors={},
            pending_permissions={"t1": True},
        )
        assert len(actions) == 1
        action = actions[0]
        assert action.thread_id == "t1"
        assert action.new_thread_status == "input_required"
        assert action.repair_status == "paused_resumable"
        assert action.last_applied_action == "permission_request_created"

    def test_already_input_required_no_status_change(self) -> None:
        """Thread already input_required keeps None new_thread_status."""
        thread = ThreadSnapshot(
            thread_id="t1", status="input_required", recovery_epoch=0
        )
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": True},
            checkpoint_errors={},
            pending_permissions={"t1": True},
        )
        assert actions[0].new_thread_status is None

    def test_already_repair_needed_no_status_change(self) -> None:
        """Thread already repair_needed keeps None new_thread_status."""
        thread = ThreadSnapshot(
            thread_id="t1", status="repair_needed", recovery_epoch=0
        )
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": True},
            checkpoint_errors={},
            pending_permissions={"t1": True},
        )
        assert actions[0].new_thread_status is None

    def test_pending_permission_takes_priority_over_cancelling(self) -> None:
        """Pending permissions are checked before cancelling status."""
        thread = ThreadSnapshot(thread_id="t1", status="cancelling", recovery_epoch=0)
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": True},
            checkpoint_errors={},
            pending_permissions={"t1": True},
        )
        assert actions[0].repair_status == "paused_resumable"
        assert actions[0].new_thread_status == "input_required"


class TestHealthyThreadConservative:
    """Healthy threads with checkpoint available get reconciling action."""

    def test_healthy_thread_gets_reconciling(self) -> None:
        thread = ThreadSnapshot(thread_id="t1", status="running", recovery_epoch=0)
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": True},
            checkpoint_errors={},
            pending_permissions={},
        )
        assert len(actions) == 1
        action = actions[0]
        assert action.thread_id == "t1"
        assert action.new_thread_status == "reconciling"
        assert action.repair_status == "needs_reconciliation"
        assert action.increment_generation is True
        assert action.increment_recovery_epoch is True


class TestMarkRepairNeededStrategy:
    """The 'mark_repair_needed' strategy forces all healthy threads to repair."""

    def test_healthy_thread_marked_repair_needed(self) -> None:
        thread = ThreadSnapshot(thread_id="t1", status="running", recovery_epoch=0)
        actions = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": True},
            checkpoint_errors={},
            pending_permissions={},
            strategy="mark_repair_needed",
        )
        assert actions[0].new_thread_status == "repair_needed"
        assert actions[0].repair_status == "checkpoint_unavailable"
        assert actions[0].increment_generation is True


class TestMultipleThreads:
    """Multiple threads produce one action per thread, in order."""

    def test_mixed_threads(self) -> None:
        threads = [
            ThreadSnapshot(thread_id="t1", status="running", recovery_epoch=0),
            ThreadSnapshot(thread_id="t2", status="cancelling", recovery_epoch=1),
            ThreadSnapshot(thread_id="t3", status="running", recovery_epoch=0),
        ]
        actions = compute_reconciliation_actions(
            threads=threads,
            checkpoint_results={"t1": True, "t2": True, "t3": False},
            checkpoint_errors={"t3": "corrupt"},
            pending_permissions={},
        )
        assert len(actions) == 3
        assert actions[0].thread_id == "t1"
        assert actions[0].new_thread_status == "reconciling"
        assert actions[1].thread_id == "t2"
        assert actions[1].repair_status == "cancel_pending"
        assert actions[2].thread_id == "t3"
        assert actions[2].new_thread_status == "repair_needed"
        assert actions[2].repair_reason == "corrupt"


class TestPureFunction:
    """Verify the function is deterministic and side-effect-free."""

    def test_same_input_same_output(self) -> None:
        thread = ThreadSnapshot(thread_id="t1", status="running", recovery_epoch=0)
        first = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": True},
            checkpoint_errors={},
            pending_permissions={},
        )
        second = compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results={"t1": True},
            checkpoint_errors={},
            pending_permissions={},
        )
        assert first == second

    def test_input_dicts_not_mutated(self) -> None:
        thread = ThreadSnapshot(thread_id="t1", status="running", recovery_epoch=0)
        cp_results = {"t1": False}
        cp_errors: dict[str, str | None] = {"t1": "gone"}
        perms = {"t1": False}

        cp_results_copy = dict(cp_results)
        cp_errors_copy = dict(cp_errors)
        perms_copy = dict(perms)

        compute_reconciliation_actions(
            threads=[thread],
            checkpoint_results=cp_results,
            checkpoint_errors=cp_errors,
            pending_permissions=perms,
        )

        assert cp_results == cp_results_copy
        assert cp_errors == cp_errors_copy
        assert perms == perms_copy

    def test_action_is_frozen_dataclass(self) -> None:
        action = ReconciliationAction(
            thread_id="t1",
            new_thread_status="repair_needed",
            repair_status="checkpoint_unavailable",
            repair_reason="test",
            execution_readiness="checkpoint_unavailable",
        )
        try:
            action.thread_id = "t2"  # type: ignore[misc]
            raised = False
        except AttributeError:
            raised = True
        assert raised, "ReconciliationAction should be frozen"
