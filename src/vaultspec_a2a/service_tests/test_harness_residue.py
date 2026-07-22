"""Constructing a service stack must not colonise the operator's real home.

The runtime directory lives in the machine-global A2A home by deliberate design -
the vault rejects foreign directories inside it - but creation used to happen in
the dataclass constructor. Several unit-shaped tests build a stack purely to
inspect environment and header wiring and never start anything, and each of those
left a permanent directory behind in the operator's real state home.

These tests assert the two properties that fixes: construction is inert, and the
accumulated directories are bounded.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from .harness import (
    RETAINED_RUNTIME_DIRS,
    RUNTIME_ROOT,
    ServiceStack,
    sweep_stale_runtime_dirs,
)

if TYPE_CHECKING:
    from pathlib import Path

_PORTS = {"gateway": 19000, "worker": 19001, "vidaimock": 19002, "jaeger": 19003}


def test_constructing_a_stack_creates_no_directory() -> None:
    """Construction resolves the path and touches the filesystem not at all."""
    stack = ServiceStack(project_name="residue-probe-unstarted", ports=dict(_PORTS))

    assert stack.runtime_dir == RUNTIME_ROOT / "residue-probe-unstarted"
    assert not stack.runtime_dir.exists()


def test_the_resolved_path_still_sits_under_the_machine_global_home() -> None:
    """The location is deliberate and must not drift while fixing the timing."""
    stack = ServiceStack(project_name="residue-probe-location", ports=dict(_PORTS))

    assert RUNTIME_ROOT in stack.runtime_dir.parents


def _aged_dir(root: Path, name: str, *, age_seconds: float) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "session-summary.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(directory, (stamp, stamp))
    return directory


def test_runtime_directories_are_bounded_and_evict_oldest_first(
    tmp_path: Path,
) -> None:
    """Recent post-mortems survive; older runs are reclaimed."""
    fake_root = tmp_path / "service-tests"
    fake_root.mkdir()

    created = [
        _aged_dir(fake_root, f"run-{index:03d}", age_seconds=1000 - index)
        for index in range(RETAINED_RUNTIME_DIRS + 3)
    ]

    removed = sweep_stale_runtime_dirs(root=fake_root)

    surviving = sorted(entry.name for entry in fake_root.iterdir())
    assert len(surviving) == RETAINED_RUNTIME_DIRS
    assert len(removed) == 3
    # The newest have the largest index because age decreases with index.
    assert created[-1].name in surviving
