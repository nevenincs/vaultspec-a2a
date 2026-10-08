"""Constructing a service stack must not colonise the operator's real home.

The runtime directory lives in the machine-global A2A home by deliberate design -
the vault rejects foreign directories inside it - but creation must not happen
in the dataclass constructor. Several unit-shaped tests build a stack purely to
inspect environment and header wiring and never start anything, and each of those
would otherwise leave a permanent directory behind in the operator's real state
home.

These tests assert the property that prevents it: construction is inert.
"""

from __future__ import annotations

from .harness import RUNTIME_ROOT, unstarted_service_stack


def test_constructing_a_stack_creates_no_directory() -> None:
    """Construction resolves the path and touches the filesystem not at all."""
    stack = unstarted_service_stack("residue-probe-unstarted")

    assert stack.runtime_dir == RUNTIME_ROOT / "residue-probe-unstarted"
    assert not stack.runtime_dir.exists()


def test_the_resolved_path_still_sits_under_the_machine_global_home() -> None:
    """The location is deliberate and must not drift while fixing the timing."""
    stack = unstarted_service_stack("residue-probe-location")

    assert RUNTIME_ROOT in stack.runtime_dir.parents
