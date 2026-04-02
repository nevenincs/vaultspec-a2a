from vaultspec_a2a.thread.lifecycle_guards import can_delete


def test_can_delete_rejects_input_required_threads() -> None:
    """Paused/resumable threads must not be hard-deleted."""
    result = can_delete("input_required")

    assert result.allowed is False
    assert result.reason == "Cannot delete thread in 'input_required' state"


def test_can_delete_allows_terminal_threads() -> None:
    """Terminal threads remain eligible for hard delete."""
    for status in ("completed", "failed", "cancelled", "archived"):
        result = can_delete(status)
        assert result.allowed is True
        assert result.reason is None
