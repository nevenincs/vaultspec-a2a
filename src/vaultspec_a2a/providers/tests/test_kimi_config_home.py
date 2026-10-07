"""Per-run Kimi configuration homes, on the real filesystem.

Real directories under the real state root, created and removed through the
production builder. What is proven here is the property the lane's isolation
rests on: one run never reads another run's configuration, and no run reads the
operator's.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ...control.config import settings
from ...testing import settings_override
from .._config_home_roots import temp_home_root
from ..kimi_config_home import (
    build_kimi_config_home,
    cleanup_kimi_config_home,
    resolve_kimi_base_home,
    sweep_orphan_kimi_homes,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_two_runs_get_distinct_homes_under_the_accounted_root() -> None:
    first = build_kimi_config_home()
    try:
        second = build_kimi_config_home()
        try:
            assert first != second
            for home in (first, second):
                assert home.is_dir()
                assert home.parent == temp_home_root()
                # Nothing is carried in: the run authenticates from its own
                # injected environment, so there is no operator state to read.
                assert list(home.iterdir()) == []
        finally:
            cleanup_kimi_config_home(second)
    finally:
        cleanup_kimi_config_home(first)
    assert not first.exists()


def test_a_home_is_never_the_operators(tmp_path: Path) -> None:
    """The per-run home is a sibling of the operator's, never the same path."""
    operator = tmp_path / "operator-kimi-home"
    operator.mkdir()
    with settings_override(kimi_code_home=str(operator)):
        assert resolve_kimi_base_home(settings.kimi_code_home) == operator
        home = build_kimi_config_home()
        try:
            assert home != operator
            assert not home.is_relative_to(operator)
        finally:
            cleanup_kimi_config_home(home)


def test_the_sweep_reclaims_only_stale_kimi_homes(tmp_path: Path) -> None:
    """A crashed run's home is reclaimed; a live run's is left alone."""
    stale = tmp_path / "vaultspec-kimi-home-stale"
    stale.mkdir()
    fresh = tmp_path / "vaultspec-kimi-home-fresh"
    fresh.mkdir()
    foreign = tmp_path / "vaultspec-codex-home-other"
    foreign.mkdir()
    old = stale.stat().st_mtime - (48 * 60 * 60)
    os.utime(stale, (old, old))

    removed = sweep_orphan_kimi_homes(keep=fresh, root=tmp_path)

    assert removed == [stale]
    assert not stale.exists()
    assert fresh.is_dir()
    # Another lane's residue is never collected by this lane's sweep.
    assert foreign.is_dir()


def test_cleanup_tolerates_an_absent_home(tmp_path: Path) -> None:
    cleanup_kimi_config_home(None)
    cleanup_kimi_config_home(tmp_path / "never-created")
