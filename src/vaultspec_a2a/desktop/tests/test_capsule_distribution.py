"""Build of the project's own A2A distribution wheel from source head.

The build shells out to real ``git`` and ``uv`` and is therefore ``service``
marked; the default suite (``-m 'not service'``) skips it.  The offline suite
proves the input guards without a real build.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from vaultspec_a2a.desktop.capsule_input_authoring import (
    CapsuleInputAuthoringError,
    build_a2a_distribution_wheel,
)

_REPO_ROOT_PARENTS = 4
_SOURCE_DATE_EPOCH = 1_700_000_000


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[_REPO_ROOT_PARENTS]


def test_build_rejects_a_missing_tool_or_bad_commit(tmp_path: Path) -> None:
    # A directory that is not a git repository makes the very first step fail.
    with pytest.raises(
        CapsuleInputAuthoringError, match=r"build step failed|full commit"
    ):
        build_a2a_distribution_wheel(
            repo_root=tmp_path,
            sandbox=tmp_path / "sandbox",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )


@pytest.mark.service
def test_builds_and_pins_the_a2a_wheel_from_head(tmp_path: Path) -> None:
    built = build_a2a_distribution_wheel(
        repo_root=_repo_root(),
        sandbox=tmp_path / "build",
        source_date_epoch=_SOURCE_DATE_EPOCH,
    )

    payload = built.path.read_bytes()
    assert built.sha256 == hashlib.sha256(payload).hexdigest()
    assert built.size == len(payload)
    assert len(built.source_commit) == 40
    assert all(character in "0123456789abcdef" for character in built.source_commit)
    assert built.path.name.startswith("vaultspec_a2a-")
    assert built.path.name.endswith(".whl")
    # It is a real wheel: a readable zip carrying a dist-info METADATA member.
    with zipfile.ZipFile(built.path) as archive:
        metadata = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA") and name.count("/") == 1
        ]
    assert len(metadata) == 1


@pytest.mark.service
def test_the_head_build_is_reproducible(tmp_path: Path) -> None:
    first = build_a2a_distribution_wheel(
        repo_root=_repo_root(),
        sandbox=tmp_path / "a",
        source_date_epoch=_SOURCE_DATE_EPOCH,
    )
    second = build_a2a_distribution_wheel(
        repo_root=_repo_root(),
        sandbox=tmp_path / "b",
        source_date_epoch=_SOURCE_DATE_EPOCH,
    )

    assert first.sha256 == second.sha256
    assert first.source_commit == second.source_commit
