"""Every reader of a thread's stored project answers the same for the same bytes.

Four control paths pull ``workspace_root`` out of a thread's stored metadata and
mint it into the run's canonical spelling: a resume, a recovery redrive, the
reconciling-thread sweep, and the deletion cleanup pass. They had each grown
their own copy of that reading, and the copies had already drifted in
production - one accepted the empty string where another refused it, and they
caught different decode failures, so one stored value could be a usable project
to one path and no project at all to another.

The drift was possible because agreement was a habit rather than a thing
asserted. These tests assert it: the two shapes of the shared reader answer
identically across the values that separated them, and the cleanup pass - the
one reader with a genuinely larger contract - agrees on everything except the
existence check it adds on purpose.

They run against real ORM rows and real directories.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ...control._thread_metadata import (
    dispatchable_workspace_root,
    workspace_root_from_metadata,
)
from ...control.cleanup.executor import _workspace_root_from_thread
from ...database.models import ThreadModel

if TYPE_CHECKING:
    from pathlib import Path

_UNUSABLE_ROOTS: list[tuple[str, object]] = [
    ("relative", "workspaces/project"),
    ("blank", ""),
    ("whitespace", "   "),
    ("wrong type", 17),
    ("a list", ["/tmp/project"]),
    ("absent", None),
]


def _stored(root: object) -> str:
    """The metadata column exactly as a thread row carries it."""
    return json.dumps({"workspace_root": root})


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A real existing project directory."""
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.mark.parametrize(("label", "stored"), _UNUSABLE_ROOTS)
def test_both_shapes_refuse_the_same_unusable_roots(label: str, stored: object) -> None:
    """The encoded and already-decoded readers cannot disagree about a refusal.

    The empty string is the case that actually shipped broken: one path treated
    it as a project and the other did not.
    """
    encoded = _stored(stored)

    assert dispatchable_workspace_root(encoded) is None, label
    assert workspace_root_from_metadata(json.loads(encoded)) is None, label


def test_both_shapes_admit_the_same_usable_root(workspace: Path) -> None:
    """The admitted case, without which the refusals above prove nothing.

    A reader that refused everything would satisfy every assertion above and
    still be broken, so agreement has to be asserted where a project survives.
    """
    encoded = _stored(str(workspace))

    from_encoded = dispatchable_workspace_root(encoded)
    from_decoded = workspace_root_from_metadata(json.loads(encoded))

    assert from_encoded == str(workspace)
    assert from_encoded == from_decoded


def test_metadata_that_never_decodes_is_only_the_encoded_reader_s_problem() -> None:
    """The decode belongs to one shape; the other is handed a mapping already."""
    for metadata in (None, "", "not json at all", "[]", "null"):
        assert dispatchable_workspace_root(metadata) is None


@pytest.mark.parametrize(("label", "stored"), _UNUSABLE_ROOTS)
def test_the_cleanup_pass_refuses_every_root_the_others_refuse(
    label: str, stored: object
) -> None:
    """Cleanup deletes files, so it must never admit a root a resume would not."""
    thread = ThreadModel(id="t-agree", thread_metadata=_stored(stored))

    assert _workspace_root_from_thread(thread) is None, label


def test_the_cleanup_pass_admits_a_real_root_and_agrees_on_its_spelling(
    workspace: Path,
) -> None:
    """Its extra return type is a wrapper, not a second answer."""
    thread = ThreadModel(id="t-agree", thread_metadata=_stored(str(workspace)))

    resolved = _workspace_root_from_thread(thread)

    assert resolved is not None
    assert str(resolved) == dispatchable_workspace_root(_stored(str(workspace)))


def test_the_cleanup_pass_alone_also_refuses_a_root_that_no_longer_exists(
    tmp_path: Path,
) -> None:
    """The one place cleanup is deliberately stricter, kept because it deletes.

    Containment is judged against a directory. A vanished root must refuse every
    artifact rather than admit paths under a tree that is gone - while a resume
    reading the identical bytes still gets a usable project back, because
    re-siting a run is not the same act as removing files.
    """
    gone = tmp_path / "deleted-checkout"
    encoded = _stored(str(gone))
    thread = ThreadModel(id="t-agree", thread_metadata=encoded)

    assert _workspace_root_from_thread(thread) is None
    assert dispatchable_workspace_root(encoded) == str(gone)
