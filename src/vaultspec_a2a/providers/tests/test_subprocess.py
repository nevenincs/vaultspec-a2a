"""Tests for subprocess evidence helpers."""

from .._subprocess import _metadata_extra


def test_metadata_extra_filters_none_values() -> None:
    """subprocess metadata helper drops unset fields and keeps bounded values."""
    extra = _metadata_extra(
        {
            "provider": "claude",
            "runtime_authority": "project_local",
            "process_pid": None,
            "command_origin": "project_node_modules_entry",
        }
    )
    assert extra == {
        "provider": "claude",
        "runtime_authority": "project_local",
        "command_origin": "project_node_modules_entry",
    }
