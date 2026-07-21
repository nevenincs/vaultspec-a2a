"""The agent's own account of a run must survive the home it was written in.

The spawned CLI writes its transcript, history, and todo state beneath its
config home, and teardown removes that home wholesale.  Preserving the record
before teardown is only defensible if the archive is bounded, so these tests
cover both halves: what is carried out, and what is evicted.

Real directories and real files throughout - the copy is the behaviour under
test, so mocking the filesystem would test nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._acp_config_home import (
    PRESERVED_SESSION_LIMIT,
    cleanup_isolated_config_home,
    preserve_session_record,
)

if TYPE_CHECKING:
    from pathlib import Path


def _home_with_record(root: Path, name: str) -> Path:
    """Build a config home carrying the artefacts the CLI leaves behind."""
    home = root / name
    (home / "projects" / "workspace-slug").mkdir(parents=True)
    (home / "projects" / "workspace-slug" / "session.jsonl").write_text(
        '{"type":"user"}\n', encoding="utf-8"
    )
    (home / "todos").mkdir()
    (home / "todos" / "state.json").write_text("[]", encoding="utf-8")
    (home / "history.jsonl").write_text('{"display":"hello"}\n', encoding="utf-8")
    (home / ".claude.json").write_text("{}", encoding="utf-8")
    return home


def test_the_transcript_survives_teardown(tmp_path: Path) -> None:
    """The record is readable after the home it came from is destroyed."""
    home = _home_with_record(tmp_path, "vaultspec-acp-home-abc")
    archive = tmp_path / "transcripts"

    preserved = preserve_session_record(home, destination_root=archive)
    cleanup_isolated_config_home(home)

    assert preserved is not None
    assert not home.exists()
    transcript = preserved / "projects" / "workspace-slug" / "session.jsonl"
    assert transcript.read_text(encoding="utf-8") == '{"type":"user"}\n'
    assert (preserved / "history.jsonl").exists()
    assert (preserved / "todos" / "state.json").exists()


def test_a_home_with_nothing_to_preserve_is_skipped(tmp_path: Path) -> None:
    """A run that wrote no record must not create an empty archive entry."""
    home = tmp_path / "vaultspec-acp-home-empty"
    home.mkdir()
    (home / ".claude.json").write_text("{}", encoding="utf-8")
    archive = tmp_path / "transcripts"

    assert preserve_session_record(home, destination_root=archive) is None
    assert not archive.exists()


def test_an_absent_home_is_tolerated(tmp_path: Path) -> None:
    """Preservation must never be the thing that fails a teardown."""
    assert preserve_session_record(None, destination_root=tmp_path) is None
    assert preserve_session_record(tmp_path / "gone", destination_root=tmp_path) is None


def test_the_archive_is_bounded_and_evicts_oldest_first(tmp_path: Path) -> None:
    """Preservation stays bounded, or it trades a small leak for a larger one."""
    archive = tmp_path / "transcripts"
    homes = tmp_path / "homes"
    homes.mkdir()

    preserved_names: list[str] = []
    for index in range(PRESERVED_SESSION_LIMIT + 3):
        home = _home_with_record(homes, f"vaultspec-acp-home-{index:03d}")
        result = preserve_session_record(home, destination_root=archive)
        assert result is not None
        preserved_names.append(result.name)
        cleanup_isolated_config_home(home)

    remaining = sorted(entry.name for entry in archive.iterdir())

    assert len(remaining) == PRESERVED_SESSION_LIMIT
    # The three oldest were evicted; the most recent survive.
    assert preserved_names[-1] in remaining
    for evicted in preserved_names[:3]:
        assert evicted not in remaining
