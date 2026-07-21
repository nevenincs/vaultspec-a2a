"""A crashed run's config home must not accumulate forever.

Teardown removes a home when the run unwinds; a killed worker leaves one behind
and nothing collected it.  That residue matters more since homes moved under the
application home on an armed install, where no system-wide temporary sweep will
ever reach them.

The sweep has no owning process id to check, so it uses age as a stand-in for
liveness.  These tests drive it against real directories with real modification
times, and the cases that matter are the ones it must NOT delete.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from .._acp_config_home import (
    ORPHAN_HOME_MIN_AGE_SECONDS,
    sweep_orphan_config_homes,
)

if TYPE_CHECKING:
    from pathlib import Path


def _home(root: Path, name: str, *, age_seconds: float) -> Path:
    """Create a config home whose modification time is *age_seconds* in the past."""
    home = root / name
    home.mkdir(parents=True)
    (home / ".claude.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(home, (stamp, stamp))
    return home


def test_a_stale_orphan_is_reclaimed(tmp_path: Path) -> None:
    """A home older than the threshold belonged to a run that is long gone."""
    stale = _home(
        tmp_path,
        "vaultspec-acp-home-stale",
        age_seconds=ORPHAN_HOME_MIN_AGE_SECONDS + 3600,
    )

    removed = sweep_orphan_config_homes(root=tmp_path)

    assert removed == [stale]
    assert not stale.exists()


def test_a_recent_home_is_left_alone(tmp_path: Path) -> None:
    """Deleting a live run's configuration is far worse than keeping residue."""
    recent = _home(tmp_path, "vaultspec-acp-home-recent", age_seconds=60)

    removed = sweep_orphan_config_homes(root=tmp_path)

    assert removed == []
    assert (recent / ".claude.json").exists()


def test_the_callers_own_home_survives_regardless_of_age(tmp_path: Path) -> None:
    """The sweep must never reclaim the home of the run that triggered it."""
    mine = _home(
        tmp_path,
        "vaultspec-acp-home-mine",
        age_seconds=ORPHAN_HOME_MIN_AGE_SECONDS * 10,
    )

    removed = sweep_orphan_config_homes(keep=mine, root=tmp_path)

    assert removed == []
    assert (mine / ".claude.json").exists()


def test_unrelated_directories_are_never_touched(tmp_path: Path) -> None:
    """The sweep is confined to its own naming scheme, however stale a neighbour is."""
    stranger = _home(
        tmp_path, "some-other-tool-cache", age_seconds=ORPHAN_HOME_MIN_AGE_SECONDS * 5
    )
    loose_file = tmp_path / "vaultspec-acp-home-not-a-directory"
    loose_file.write_text("x", encoding="utf-8")
    old_stamp = time.time() - ORPHAN_HOME_MIN_AGE_SECONDS * 5
    os.utime(loose_file, (old_stamp, old_stamp))

    removed = sweep_orphan_config_homes(root=tmp_path)

    assert removed == []
    assert (stranger / ".claude.json").exists()
    assert loose_file.exists()


def test_an_absent_root_is_tolerated(tmp_path: Path) -> None:
    """A sweep must never be the thing that fails a run."""
    assert sweep_orphan_config_homes(root=tmp_path / "absent") == []


def test_several_orphans_are_reclaimed_in_one_pass(tmp_path: Path) -> None:
    """Accumulated residue clears in a single sweep rather than one per run."""
    stale = [
        _home(
            tmp_path,
            f"vaultspec-acp-home-{index}",
            age_seconds=ORPHAN_HOME_MIN_AGE_SECONDS + 60,
        )
        for index in range(4)
    ]
    fresh = _home(tmp_path, "vaultspec-acp-home-live", age_seconds=5)

    removed = sweep_orphan_config_homes(root=tmp_path)

    assert sorted(removed) == sorted(stale)
    assert fresh.exists()
