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

import contextlib
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from ...testing import plant_link_to_file
from ...utils import ProcessContainment, reap_contained, spawn_contained
from ..atomic_write import atomic_write_text

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


def _temporaries(directory: Path) -> list[Path]:
    """Return every temporary-file residue in *directory*."""
    return sorted(directory.glob("*.tmp"))


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

    Both write paths are exercised, because they must not disagree: the path with
    permission bits asks for ``O_NOFOLLOW`` and the path without must not go
    through builtin ``open``, which follows.  One function, one posture,
    whether or not an unrelated argument is passed.

    The refusal has to hold on Windows too, and ``O_NOFOLLOW`` does not exist
    there, so this is what proves the guarantee is real rather than nominal on
    the platform this product ships to.  Where the host can create a symbolic
    link to a file, the assertion has teeth: following it would overwrite that
    file's bytes, and the write under test carries a secret.
    """
    outside = tmp_path / "outside.secret"
    outside.write_text("must-survive", encoding="utf-8")
    target = tmp_path / "record.json"
    kind = plant_link_to_file(tmp_path / f"record.json.{os.getpid()}.tmp", outside)

    with pytest.raises(OSError, match="refusing to write through a link"):
        atomic_write_text(target, "must-not-land-outside", mode=mode)

    assert outside.read_text(encoding="utf-8") == "must-survive", (
        f"a {kind} planted at the temporary name redirected the write"
    )
    assert not target.exists()


# Holds a real read handle on the target for a measured interval, announcing the
# handle before the wait so the publisher races a reader that is already there.
# On Windows a handle opened this way carries no delete sharing, which is exactly
# what denies the rename - the contention the retry exists for, produced by a
# real second process rather than described.
_READER_HOLDING_THE_TARGET = (
    "import sys, time\n"
    "with open(sys.argv[1], 'rb') as handle:\n"
    "    print('HELD', flush=True)\n"
    "    time.sleep(float(sys.argv[2]))\n"
    "    handle.read()\n"
)


@contextlib.contextmanager
def _reader_holding(path: Path, hold_seconds: float) -> Generator[None]:
    """Run a real process holding *path* open, releasing it after *hold_seconds*."""
    containment = ProcessContainment.create()
    process = spawn_contained(
        [
            getattr(sys, "_base_executable", sys.executable),
            "-c",
            _READER_HOLDING_THE_TARGET,
            str(path),
            str(hold_seconds),
        ],
        containment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert process.stdout is not None
        announced = process.stdout.readline().decode("utf-8").strip()
        assert announced == "HELD", f"the reader never opened the target: {announced!r}"
        yield
    finally:
        reap_contained(process, containment, term_timeout=2.0, kill_timeout=2.0)
        with contextlib.suppress(OSError):
            if process.stdout is not None:
                process.stdout.close()


@pytest.mark.skipif(
    sys.platform != "win32", reason="only Windows denies a rename over an open target"
)
def test_a_publication_rides_out_a_real_reader_holding_the_target(
    tmp_path: Path,
) -> None:
    """A reader that holds the target open delays the publication, never fails it.

    The whole reason this helper retries: on Windows a reader's handle on the
    target denies ``os.replace`` outright, and a publisher that took the first
    denial as final would fail every time a reader happened to be mid-read.

    The elapsed assertion is what makes this discriminating. Without it the test
    would also pass on a host where the rename was never denied at all, which
    would prove nothing about the retry; a publication that returns only after
    the holder let go has demonstrably ridden out a real denial.
    """
    target = tmp_path / "record.json"
    atomic_write_text(target, '{"generation": "first"}')
    hold_seconds = 0.5

    started = time.monotonic()
    with _reader_holding(target, hold_seconds):
        atomic_write_text(target, '{"generation": "second"}')
    elapsed = time.monotonic() - started

    assert elapsed >= hold_seconds / 2, (
        f"the publication did not wait for the holder ({elapsed:.4f}s): "
        "the rename was never denied, so the retry was not exercised"
    )
    assert target.read_text(encoding="utf-8") == '{"generation": "second"}'
    assert _temporaries(tmp_path) == []


@pytest.mark.skipif(
    sys.platform != "win32", reason="only Windows denies a rename over an open target"
)
def test_a_zero_budget_publication_attempts_the_rename_exactly_once(
    tmp_path: Path,
) -> None:
    """Zero patience means one attempt, and a denied one leaves the record intact.

    The budget is waiting time rather than elapsed time, which only means
    anything if zero still buys no waiting at all: a caller that cannot afford to
    block - a shutdown path, a probe - must get its answer back immediately. The
    holder stays for far longer than this publication may take, so a returned
    failure can only be the first attempt's.
    """
    target = tmp_path / "record.json"
    atomic_write_text(target, '{"generation": "first"}')

    with _reader_holding(target, 5.0):
        started = time.monotonic()
        with pytest.raises(PermissionError):
            atomic_write_text(target, '{"generation": "second"}', retry_seconds=0.0)
        elapsed = time.monotonic() - started

    assert elapsed < 0.5, f"a zero budget still waited {elapsed:.4f}s"
    assert target.read_text(encoding="utf-8") == '{"generation": "first"}'
    assert _temporaries(tmp_path) == []


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="only Windows denies a rename whose source another opener holds",
)
def test_a_retry_renames_from_a_source_the_holder_has_never_seen(
    tmp_path: Path,
) -> None:
    """A holder latched onto the first source must not fail the publication.

    The denial this covers is on the rename's SOURCE, not its target: on Windows a
    rename is a delete-class operation, so any other opener holding the temporary
    without delete sharing denies it. Retrying from that same temporary re-offers
    the file the holder is latched onto, so the publication fails however long the
    budget is - the recurring ``WinError 5`` from a filesystem filter driver that
    samples a brand-new file and keeps it.

    Driven by a real second process holding the real first source for longer than
    the whole budget, taken through the hardening hook because that is where this
    helper hands out the source path. A retry that claims a new source publishes;
    one that re-offers the old source cannot.
    """
    target = tmp_path / "record.json"
    atomic_write_text(target, '{"generation": "first"}')
    sources: list[Path] = []

    with contextlib.ExitStack() as holders:

        def hold_the_first_source(candidate: Path) -> None:
            sources.append(candidate)
            if len(sources) == 1:
                holders.enter_context(_reader_holding(candidate, 30.0))

        atomic_write_text(
            target, '{"generation": "second"}', harden=hold_the_first_source
        )

        assert len(sources) >= 2, (
            "the publication landed from the held source, so no retry claimed a "
            f"fresh one: {sources}"
        )
        assert sources[0] not in sources[1:], sources
        assert target.read_text(encoding="utf-8") == '{"generation": "second"}'
        # The only residue is the source this test's holder still owns: Windows
        # denies the unlink for exactly the reason it denied the rename, so the
        # helper could not collect it. Every source it could collect, it did.
        assert _temporaries(tmp_path) == [sources[0]]

    sources[0].unlink(missing_ok=True)
    assert _temporaries(tmp_path) == []


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
