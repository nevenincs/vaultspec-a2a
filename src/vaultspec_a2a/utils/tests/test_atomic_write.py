"""A failed publication must leave the filesystem as it found it.

The success path of write-and-rename is easy and was never the problem.  What
went wrong in this service was the failure path: three implementations each left
their temporary file behind when a publication did not complete, and one such
orphan sat beside a live discovery record for six days.

So these tests force real failures against real files - a target directory that
disappears, a rename denied for longer than the retry window, an interruption
mid-write - and assert on what is left on disk afterwards.  No mocks: the
failures are produced by genuinely unwritable or contended filesystem state.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest

from ..atomic_write import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path


def _temporaries(directory: Path) -> list[Path]:
    """Return every temporary-file residue in *directory*."""
    return sorted(directory.glob("*.tmp"))


def _plant_link(link: Path, file_target: Path) -> str:
    """Plant the strongest link this host can create at *link*; name its kind.

    A symbolic link to a FILE is the case worth proving, because a write that
    follows one lands on that file's bytes and destroys them.  Creating one on
    Windows needs a privilege not every host grants, so a host that refuses gets
    a directory junction instead - the privilege-free reparse point - which
    still proves the refusal but cannot demonstrate the destruction.
    """
    try:
        os.symlink(file_target, link)
    except OSError:
        junction_target = link.parent / "junction-target"
        junction_target.mkdir(exist_ok=True)
        interpreter = os.environ.get("COMSPEC", "cmd.exe")
        completed = subprocess.run(
            [interpreter, "/c", "mklink", "/J", str(link), str(junction_target)],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not link.is_junction():
            raise OSError(
                f"could not plant a link: {completed.stderr.strip()}"
            ) from None
        return "junction"
    return "symlink"


def test_content_is_published_and_no_temporary_survives(tmp_path: Path) -> None:
    """The ordinary case publishes the bytes and cleans up after itself."""
    target = tmp_path / "record.json"

    atomic_write_text(target, '{"port": 18000}')

    assert target.read_text(encoding="utf-8") == '{"port": 18000}'
    assert _temporaries(tmp_path) == []


def test_publication_replaces_existing_content_wholesale(tmp_path: Path) -> None:
    """A republish overwrites rather than appending or merging."""
    target = tmp_path / "record.json"
    atomic_write_text(target, "first-and-longer-content")

    atomic_write_text(target, "second")

    assert target.read_text(encoding="utf-8") == "second"
    assert _temporaries(tmp_path) == []


def test_a_failed_write_leaves_no_temporary_behind(tmp_path: Path) -> None:
    """When the destination directory does not exist, nothing is left behind.

    This is the failure the previous implementations mishandled: the temporary
    is created in the same directory as the target, so a directory problem
    surfaces mid-publication rather than before it.
    """
    missing = tmp_path / "absent-directory"
    target = missing / "record.json"

    with pytest.raises(OSError):
        atomic_write_text(target, "never-lands")

    assert not missing.exists()
    assert _temporaries(tmp_path) == []


def test_a_denied_rename_removes_the_temporary_before_propagating(
    tmp_path: Path,
) -> None:
    """A rename that stays denied past the retry window must not leak residue.

    A directory standing where the target file belongs makes ``os.replace``
    fail on every platform, which is a genuine unrecoverable rename rather than
    the transient contention the retry exists for.
    """
    target = tmp_path / "record.json"
    target.mkdir()

    with pytest.raises(OSError):
        atomic_write_text(target, "cannot-replace-a-directory", retry_seconds=0.0)

    assert target.is_dir()
    assert _temporaries(tmp_path) == []


def test_a_non_os_failure_mid_write_still_removes_the_temporary(
    tmp_path: Path,
) -> None:
    """A failure that is not an OSError must clean up too.

    An unpaired surrogate cannot be encoded as UTF-8, so the write raises a
    UnicodeEncodeError after the temporary file already exists.  Catching only
    OSError would leak residue here, which is why the helper catches every
    exception type on its way out.
    """
    target = tmp_path / "record.json"

    with pytest.raises(UnicodeEncodeError):
        atomic_write_text(target, "\ud800")

    assert not target.exists()
    assert _temporaries(tmp_path) == []


def test_the_hardening_hook_runs_on_the_temporary_before_the_rename(
    tmp_path: Path,
) -> None:
    """A file must be protected before it is reachable under its real name.

    The hook exists for an owner-restriction no permission bits can express, and
    a restriction applied after the rename would leave a genuine window in which
    another local principal could open the published file.  So the hook records
    what the filesystem actually looked like at the moment it ran: the target
    absent, and the temporary already holding the finished bytes.
    """
    target = tmp_path / "record.json"
    observed: list[tuple[Path, bool, str]] = []

    def observe(candidate: Path) -> None:
        observed.append(
            (candidate, target.exists(), candidate.read_text(encoding="utf-8"))
        )

    atomic_write_text(target, "protected-content", mode=0o600, harden=observe)

    expected_temporary = tmp_path / f"record.json.{os.getpid()}.tmp"
    assert observed == [(expected_temporary, False, "protected-content")]
    assert target.read_text(encoding="utf-8") == "protected-content"
    assert _temporaries(tmp_path) == []


def test_a_refused_hardening_publishes_nothing_and_leaves_no_residue(
    tmp_path: Path,
) -> None:
    """A file that could not be protected must never become the published file.

    Fail-closed hardening is the reason the hook exists: the real implementation
    raises when a Windows access-control list does not read back restricted.
    What that costs must be the publication, never the protection - so the prior
    content survives and no readable temporary is left where the new one was.
    """
    target = tmp_path / "worker-ipc.cred"
    target.write_text("previous-secret", encoding="utf-8")

    def refuse(candidate: Path) -> None:
        raise OSError(f"could not restrict {candidate}")

    with pytest.raises(OSError):
        atomic_write_text(target, "unprotectable-secret", mode=0o600, harden=refuse)

    assert target.read_text(encoding="utf-8") == "previous-secret"
    assert _temporaries(tmp_path) == []


def test_the_permission_bearing_path_writes_its_bytes_untranslated(
    tmp_path: Path,
) -> None:
    """Asking for permission bits must not also change the bytes on disk.

    Windows opens a descriptor in text mode unless told otherwise, so this path
    expanded every newline while the path without permission bits wrote them
    through: one function with two byte-level contracts, diverging only on the
    platform this service ships to.  A secret published this way is compared
    byte for byte by whoever reads it back.
    """
    plain = tmp_path / "plain.json"
    restricted = tmp_path / "restricted.json"

    atomic_write_text(plain, "first\nsecond\n")
    atomic_write_text(restricted, "first\nsecond\n", mode=0o600)

    assert restricted.read_bytes() == b"first\nsecond\n"
    assert restricted.read_bytes() == plain.read_bytes()


@pytest.mark.parametrize("mode", [None, 0o600])
def test_neither_write_path_follows_a_link_planted_at_the_temporary(
    tmp_path: Path, mode: int | None
) -> None:
    """The temporary name is predictable, so a link planted there must be refused.

    Both write paths are exercised, because they used to disagree: the path with
    permission bits asked for ``O_NOFOLLOW`` and the path without went through
    builtin ``open``, which follows.  One function, one name, one docstring, two
    postures - selected by whether an unrelated argument was passed.

    The refusal has to hold on Windows too, and ``O_NOFOLLOW`` does not exist
    there, so this is what proves the guarantee is real rather than nominal on
    the platform this product ships to.  Where the host can create a symbolic
    link to a file, the assertion has teeth: following it would overwrite that
    file's bytes, and the write under test carries a secret.
    """
    outside = tmp_path / "outside.secret"
    outside.write_text("must-survive", encoding="utf-8")
    target = tmp_path / "record.json"
    kind = _plant_link(tmp_path / f"record.json.{os.getpid()}.tmp", outside)

    with pytest.raises(OSError, match="refusing to write through a link"):
        atomic_write_text(target, "must-not-land-outside", mode=mode)

    assert outside.read_text(encoding="utf-8") == "must-survive", (
        f"a {kind} planted at the temporary name redirected the write"
    )
    assert not target.exists()


def test_the_temporary_is_named_for_the_writing_process(tmp_path: Path) -> None:
    """Two publishers must not collide on the temporary file itself.

    Occupying the expected temporary name with a directory makes the write fail,
    which proves the helper targets exactly that name rather than asserting on
    an implementation detail from the outside.
    """
    target = tmp_path / "record.json"
    expected_temporary = tmp_path / f"record.json.{os.getpid()}.tmp"
    expected_temporary.mkdir()

    with pytest.raises(OSError):
        atomic_write_text(target, "blocked-by-the-occupied-temporary")

    assert not target.exists()
    assert expected_temporary.is_dir()
