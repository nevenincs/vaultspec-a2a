from __future__ import annotations

import errno
import hashlib
import multiprocessing
import time
import zipfile
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop._filesystem_authority import (
    assert_directory_authority,
    assert_empty_directory_authority,
    claim_new_directory,
    create_private_file,
    directory_lease,
    resolve_directory_authority,
)
from vaultspec_a2a.desktop.capsule_evidence import (
    CapsuleAssemblyError,
    write_deterministic_capsule_zip_into_unpublished_generation,
)

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE_DATE_EPOCH = 1_700_000_000


def _claim_generation_process(
    root: Path,
    start: Path,
    result: Path,
    payload: bytes,
) -> None:
    deadline = time.monotonic() + 20
    while not start.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("generation claim start barrier timed out")
        time.sleep(0.001)

    authority = resolve_directory_authority(root)
    try:
        with (
            directory_lease(authority) as root_lease,
            claim_new_directory(root_lease, "candidate") as generation_lease,
            create_private_file(generation_lease, "winner") as output,
        ):
            output.write(payload)
            output.flush()
        result.write_text("claimed", encoding="utf-8")
    except FileExistsError:
        result.write_text("collision", encoding="utf-8")


def test_claim_new_directory_returns_a_live_exact_authority(tmp_path: Path) -> None:
    authority = resolve_directory_authority(tmp_path)

    with (
        directory_lease(authority) as root_lease,
        claim_new_directory(root_lease, "candidate") as generation_lease,
    ):
        assert generation_lease.path == tmp_path / "candidate"
        assert_directory_authority(generation_lease)
        with create_private_file(generation_lease, "payload") as output:
            output.write(b"generation-bytes")
            output.flush()

    assert (tmp_path / "candidate/payload").read_bytes() == b"generation-bytes"


@pytest.mark.parametrize("existing_kind", ("directory", "file"))
def test_claim_new_directory_refuses_existing_file_or_directory(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    candidate = tmp_path / "candidate"
    if existing_kind == "directory":
        candidate.mkdir()
        sentinel = candidate / "sentinel"
    else:
        sentinel = candidate
    sentinel.write_bytes(b"preserved")
    authority = resolve_directory_authority(tmp_path)

    with (
        directory_lease(authority) as root_lease,
        pytest.raises(FileExistsError),
        claim_new_directory(root_lease, "candidate"),
    ):
        raise AssertionError("an existing name must never be leased")

    assert sentinel.read_bytes() == b"preserved"


def test_failed_claim_body_leaves_the_whole_generation_poisoned(
    tmp_path: Path,
) -> None:
    authority = resolve_directory_authority(tmp_path)

    with (
        pytest.raises(RuntimeError, match="late generation failure"),
        directory_lease(authority) as root_lease,
        claim_new_directory(root_lease, "candidate") as generation_lease,
        create_private_file(generation_lease, "partial") as output,
    ):
        output.write(b"partial-generation-bytes")
        output.flush()
        raise RuntimeError("late generation failure")

    assert (tmp_path / "candidate/partial").read_bytes() == (
        b"partial-generation-bytes"
    )


def test_non_empty_directory_authority_is_refused_without_mutation(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    sentinel = candidate / "sentinel"
    sentinel.write_bytes(b"preserved-poisoned-generation")
    authority = resolve_directory_authority(candidate)

    with (
        directory_lease(authority) as generation_lease,
        pytest.raises(OSError) as raised,
    ):
        assert_empty_directory_authority(generation_lease)

    assert raised.value.errno == errno.ENOTEMPTY
    assert sentinel.read_bytes() == b"preserved-poisoned-generation"
    assert tuple(candidate.iterdir()) == (sentinel,)


def test_concurrent_generation_claims_have_exactly_one_winner(tmp_path: Path) -> None:
    start = tmp_path / "start"
    results = (tmp_path / "first.result", tmp_path / "second.result")
    payloads = (b"first-winner", b"second-winner")
    context = multiprocessing.get_context("spawn")
    claimers = tuple(
        context.Process(
            target=_claim_generation_process,
            args=(tmp_path, start, result, payload),
        )
        for result, payload in zip(results, payloads, strict=True)
    )

    for claimer in claimers:
        claimer.start()
    start.write_bytes(b"go")
    for claimer in claimers:
        claimer.join(timeout=20)

    assert all(not claimer.is_alive() for claimer in claimers)
    assert [claimer.exitcode for claimer in claimers] == [0, 0]
    outcomes = tuple(result.read_text(encoding="utf-8") for result in results)
    assert outcomes.count("claimed") == 1
    assert outcomes.count("collision") == 1
    assert (tmp_path / "candidate/winner").read_bytes() in payloads


def test_deterministic_zip_is_written_once_at_its_final_generation_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_bytes(b"capsule-payload\n")
    generations = tmp_path / "generations"
    generations.mkdir()
    generations_authority = resolve_directory_authority(generations)

    with (
        directory_lease(generations_authority) as root_lease,
        claim_new_directory(root_lease, "candidate") as generation_lease,
    ):
        digest, evidence = write_deterministic_capsule_zip_into_unpublished_generation(
            source,
            generation_authority=generation_lease,
            output_name="component.zip",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
        archive_path = generation_lease.path / "component.zip"
        original = archive_path.read_bytes()
        with pytest.raises(CapsuleAssemblyError, match="already exists"):
            write_deterministic_capsule_zip_into_unpublished_generation(
                source,
                generation_authority=generation_lease,
                output_name="component.zip",
                source_date_epoch=_SOURCE_DATE_EPOCH,
            )

    assert digest == hashlib.sha256(original).hexdigest()
    assert [(item.relative_path, item.size) for item in evidence] == [
        ("payload.txt", len(b"capsule-payload\n"))
    ]
    assert archive_path.read_bytes() == original
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ["capsule/payload.txt"]
        assert archive.read("capsule/payload.txt") == b"capsule-payload\n"


def test_failed_generation_zip_write_retains_exact_partial_file(
    tmp_path: Path,
) -> None:
    empty_source = tmp_path / "empty-source"
    empty_source.mkdir()
    generations = tmp_path / "generations"
    generations.mkdir()
    generations_authority = resolve_directory_authority(generations)

    with (
        directory_lease(generations_authority) as root_lease,
        claim_new_directory(root_lease, "candidate") as generation_lease,
        pytest.raises(CapsuleAssemblyError, match="contains no files"),
    ):
        write_deterministic_capsule_zip_into_unpublished_generation(
            empty_source,
            generation_authority=generation_lease,
            output_name="partial.zip",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    partial = generations / "candidate/partial.zip"
    assert partial.is_file()
    assert partial.stat().st_size == 0
