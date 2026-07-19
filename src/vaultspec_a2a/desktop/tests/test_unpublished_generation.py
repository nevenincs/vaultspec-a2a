from __future__ import annotations

import errno
import hashlib
import multiprocessing
import os
import stat
import tarfile
import time
import zipfile
from contextlib import suppress
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
from vaultspec_a2a.desktop.artifacts import ArchiveKind
from vaultspec_a2a.desktop.capsule import (
    _MAX_PROJECTED_FILES as _MAX_ARCHIVE_PROJECTED_FILES,
)
from vaultspec_a2a.desktop.capsule import (
    ArchiveProjectionSource,
    project_archive,
    project_archive_into_unpublished_generation,
)
from vaultspec_a2a.desktop.capsule_evidence import (
    _MAX_PROJECTED_FILES as _MAX_CAPSULE_TREE_FILES,
)
from vaultspec_a2a.desktop.capsule_evidence import (
    CapsuleAssemblyError,
    write_deterministic_capsule_zip_into_unpublished_generation,
)

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess
    from pathlib import Path

_SOURCE_DATE_EPOCH = 1_700_000_000


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _write_projection_zip(path: Path, members: tuple[tuple[str, bytes], ...]) -> None:
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=(2023, 11, 14, 22, 13, 20))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, payload)


def _projection_source(path: Path) -> ArchiveProjectionSource:
    return ArchiveProjectionSource(
        path=path,
        sha256=_sha256(path),
        size=path.stat().st_size,
        archive_kind=ArchiveKind.ZIP,
        archive_root="payload",
    )


def _await_barrier(start: Path, *, label: str) -> None:
    deadline = time.monotonic() + 20
    while not start.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{label} start barrier timed out")
        time.sleep(0.001)


def _join_processes(processes: tuple[BaseProcess, ...]) -> None:
    for process in processes:
        process.join(timeout=20)
    assert all(not process.is_alive() for process in processes)
    assert [process.exitcode for process in processes] == [0] * len(processes)


def _await_process_ready(result: Path) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if result.read_text(encoding="utf-8"):
                return
        except FileNotFoundError:
            pass
        time.sleep(0.001)
    raise RuntimeError("competing process did not reach its barrier")


def _claim_generation_process(
    root: Path,
    start: Path,
    result: Path,
    payload: bytes,
) -> None:
    _await_barrier(start, label="generation claim")

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


def _project_into_generation_process(
    generation: Path,
    source_path: Path,
    start: Path,
    result: Path,
    contender: str,
) -> None:
    _await_barrier(start, label="direct projection")
    try:
        with directory_lease(resolve_directory_authority(generation)) as lease:
            evidence = project_archive_into_unpublished_generation(
                _projection_source(source_path),
                generation_authority=lease,
                destination_prefix="runtime",
                source_date_epoch=_SOURCE_DATE_EPOCH,
            )
    except CapsuleAssemblyError as error:
        result.write_text(f"error:{error}", encoding="utf-8")
    else:
        result.write_text(f"ok:{contender}:{len(evidence)}", encoding="utf-8")


def _write_zip_into_generation_process(
    generation: Path,
    source_root: Path,
    start: Path,
    result: Path,
    contender: str,
) -> None:
    _await_barrier(start, label="direct archive")
    try:
        with directory_lease(resolve_directory_authority(generation)) as lease:
            digest, evidence = (
                write_deterministic_capsule_zip_into_unpublished_generation(
                    source_root,
                    generation_authority=lease,
                    output_name="component.zip",
                    source_date_epoch=_SOURCE_DATE_EPOCH,
                )
            )
    except CapsuleAssemblyError as error:
        result.write_text(f"error:{error}", encoding="utf-8")
    else:
        result.write_text(f"ok:{contender}:{digest}:{len(evidence)}", encoding="utf-8")


def _swap_directory_process(
    current: Path,
    parked: Path,
    outside: Path,
    after_exists: Path,
    result: Path,
) -> None:
    result.write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not after_exists.exists():
        time.sleep(0.001)
    if not after_exists.exists():
        raise RuntimeError("directory-swap barrier timed out")
    try:
        current.rename(parked)
        current.symlink_to(outside, target_is_directory=True)
        result.write_text("swapped", encoding="utf-8")
    except OSError as error:
        result.write_text(f"blocked:{error.errno}", encoding="utf-8")


def _restore_swapped_directory(current: Path, parked: Path) -> None:
    if current.is_symlink():
        current.unlink()
    if parked.exists():
        parked.rename(current)


def _replace_file_after_output_process(
    target: Path,
    replacement: Path,
    output: Path,
    result: Path,
) -> None:
    result.write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if output.stat().st_size > 1 << 20:
                break
        except FileNotFoundError:
            pass
        time.sleep(0.001)
    else:
        raise RuntimeError("late-source replacement barrier timed out")
    try:
        os.replace(replacement, target)
    except OSError as error:
        result.write_text(f"blocked:{error.errno}", encoding="utf-8")
    else:
        result.write_text("replaced", encoding="utf-8")


def _churn_source_parent_process(
    current: Path,
    parked: Path,
    outside: Path,
    active: Path,
    done: Path,
    result: Path,
) -> None:
    result.write_text("ready", encoding="utf-8")
    _await_barrier(active, label="source-parent churn")
    swaps = 0
    blocked = 0
    while not done.exists():
        try:
            current.rename(parked)
            outside.rename(current)
            swaps += 1
            current.rename(outside)
            parked.rename(current)
        except OSError:
            blocked += 1
            try:
                if parked.exists():
                    if current.exists() and not outside.exists():
                        current.rename(outside)
                    if not current.exists():
                        parked.rename(current)
            except OSError:
                pass
        time.sleep(0)
    result.write_text(f"swaps:{swaps}:blocked:{blocked}", encoding="utf-8")


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


def test_direct_outputs_are_deterministic_across_claimed_generations(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "source.zip"
    archive_members = (
        ("payload/a.txt", b"projected-a\n"),
        ("payload/nested/b.txt", b"projected-b\n"),
    )
    _write_projection_zip(archive_path, archive_members)
    projection_source = _projection_source(archive_path)
    capsule_root = tmp_path / "capsule-root"
    capsule_root.mkdir()
    (capsule_root / "a.txt").write_bytes(b"archive-a\n")
    nested = capsule_root / "nested"
    nested.mkdir()
    (nested / "b.txt").write_bytes(b"archive-b\n")
    generations = tmp_path / "generations"
    generations.mkdir()
    generations_authority = resolve_directory_authority(generations)
    projected_runs = []
    archive_runs = []

    with directory_lease(generations_authority) as root_lease:
        for name in ("first", "second"):
            with claim_new_directory(root_lease, name) as generation_lease:
                projected = project_archive_into_unpublished_generation(
                    projection_source,
                    generation_authority=generation_lease,
                    destination_prefix="runtime",
                    source_date_epoch=_SOURCE_DATE_EPOCH,
                )
                digest, archived = (
                    write_deterministic_capsule_zip_into_unpublished_generation(
                        capsule_root,
                        generation_authority=generation_lease,
                        output_name="component.zip",
                        source_date_epoch=_SOURCE_DATE_EPOCH,
                    )
                )
                projected_runs.append(projected)
                archive_runs.append(
                    (
                        digest,
                        archived,
                        (generation_lease.path / "component.zip").read_bytes(),
                    )
                )

    assert projected_runs[0] == projected_runs[1]
    assert [item.relative_path for item in projected_runs[0]] == [
        "runtime/a.txt",
        "runtime/nested/b.txt",
    ]
    for item, (_, payload) in zip(
        projected_runs[0],
        (("a.txt", b"projected-a\n"), ("nested/b.txt", b"projected-b\n")),
        strict=True,
    ):
        assert item.size == len(payload)
        assert item.sha256 == hashlib.sha256(payload).hexdigest()
        assert item.mode == 0o644
    assert archive_runs[0] == archive_runs[1]
    assert archive_runs[0][0] == hashlib.sha256(archive_runs[0][2]).hexdigest()
    assert [item.relative_path for item in archive_runs[0][1]] == [
        "a.txt",
        "nested/b.txt",
    ]
    for item, payload in zip(
        archive_runs[0][1],
        (b"archive-a\n", b"archive-b\n"),
        strict=True,
    ):
        assert item.size == len(payload)
        assert item.sha256 == hashlib.sha256(payload).hexdigest()
        assert item.mode == 0o644
    for generation in (generations / "first", generations / "second"):
        assert (generation / "runtime/a.txt").read_bytes() == b"projected-a\n"
        assert (generation / "runtime/nested/b.txt").read_bytes() == b"projected-b\n"
        with zipfile.ZipFile(generation / "component.zip") as archive:
            assert archive.read("capsule/a.txt") == b"archive-a\n"
            assert archive.read("capsule/nested/b.txt") == b"archive-b\n"


def test_concurrent_direct_projectors_have_one_exact_winner(tmp_path: Path) -> None:
    contenders = (
        ("first", tmp_path / "first.zip", b"first-projection-winner\n" * 4096),
        ("second", tmp_path / "second.zip", b"second-projection-winner\n" * 4096),
    )
    for _, source_path, payload in contenders:
        _write_projection_zip(source_path, (("payload/data.bin", payload),))
    generation = tmp_path / "generation"
    generation.mkdir()
    start = tmp_path / "projection.start"
    results = (tmp_path / "first.result", tmp_path / "second.result")
    context = multiprocessing.get_context("spawn")
    projectors = tuple(
        context.Process(
            target=_project_into_generation_process,
            args=(generation, source_path, start, result, contender),
        )
        for (contender, source_path, _), result in zip(contenders, results, strict=True)
    )

    for projector in projectors:
        projector.start()
    start.write_bytes(b"go")
    _join_processes(projectors)

    outcomes = tuple(result.read_text(encoding="utf-8") for result in results)
    winner = next(item for item in outcomes if item.startswith("ok:"))
    assert len(tuple(item for item in outcomes if item.startswith("ok:"))) == 1
    assert len(tuple(item for item in outcomes if "refuses to overwrite" in item)) == 1
    winner_name = winner.split(":", maxsplit=2)[1]
    expected = next(payload for name, _, payload in contenders if name == winner_name)
    assert (generation / "runtime/data.bin").read_bytes() == expected


def test_concurrent_direct_zip_writers_have_one_exact_winner(tmp_path: Path) -> None:
    contenders = (
        ("first", tmp_path / "first-source", b"first-archive-winner\n" * 4096),
        ("second", tmp_path / "second-source", b"second-archive-winner\n" * 4096),
    )
    for _, source_root, payload in contenders:
        source_root.mkdir()
        (source_root / "data.bin").write_bytes(payload)
    generation = tmp_path / "generation"
    generation.mkdir()
    start = tmp_path / "archive.start"
    results = (tmp_path / "first.result", tmp_path / "second.result")
    context = multiprocessing.get_context("spawn")
    writers = tuple(
        context.Process(
            target=_write_zip_into_generation_process,
            args=(generation, source_root, start, result, contender),
        )
        for (contender, source_root, _), result in zip(contenders, results, strict=True)
    )

    for writer in writers:
        writer.start()
    start.write_bytes(b"go")
    _join_processes(writers)

    outcomes = tuple(result.read_text(encoding="utf-8") for result in results)
    winner = next(item for item in outcomes if item.startswith("ok:"))
    assert len(tuple(item for item in outcomes if item.startswith("ok:"))) == 1
    assert len(tuple(item for item in outcomes if "already exists" in item)) == 1
    _, winner_name, winner_digest, evidence_count = winner.split(":")
    assert evidence_count == "1"
    expected = next(payload for name, _, payload in contenders if name == winner_name)
    output = generation / "component.zip"
    assert _sha256(output) == winner_digest
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["capsule/data.bin"]
        assert archive.read("capsule/data.bin") == expected


def test_direct_apis_reject_path_only_generation_authority(tmp_path: Path) -> None:
    source_path = tmp_path / "source.zip"
    _write_projection_zip(source_path, (("payload/data", b"projection"),))
    capsule_root = tmp_path / "capsule-root"
    capsule_root.mkdir()
    (capsule_root / "data").write_bytes(b"archive")
    generation = tmp_path / "generation"
    generation.mkdir()
    path_only = resolve_directory_authority(generation)

    with pytest.raises(CapsuleAssemblyError, match="not continuously leased"):
        project_archive_into_unpublished_generation(
            _projection_source(source_path),
            generation_authority=path_only,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
    with pytest.raises(CapsuleAssemblyError, match="not continuously leased"):
        write_deterministic_capsule_zip_into_unpublished_generation(
            capsule_root,
            generation_authority=path_only,
            output_name="component.zip",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    assert tuple(generation.iterdir()) == ()


@pytest.mark.parametrize(
    "existing_kind",
    ("file", "directory", "symlink") if os.name == "posix" else ("file", "directory"),
)
def test_direct_projection_collision_preserves_existing_kind(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    source_path = tmp_path / "source.zip"
    _write_projection_zip(source_path, (("payload/data", b"new-data"),))
    generation = tmp_path / "generation"
    generation.mkdir()
    destination = generation / "runtime"
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_sentinel = outside / "sentinel"
    outside_sentinel.write_bytes(b"outside-preserved")
    if existing_kind == "file":
        destination.write_bytes(b"file-preserved")
        expected = destination
    elif existing_kind == "directory":
        destination.mkdir()
        expected = destination / "sentinel"
        expected.write_bytes(b"directory-preserved")
    else:
        destination.symlink_to(outside, target_is_directory=True)
        expected = outside_sentinel

    with (
        directory_lease(resolve_directory_authority(generation)) as lease,
        pytest.raises(CapsuleAssemblyError, match="refuses to overwrite"),
    ):
        project_archive_into_unpublished_generation(
            _projection_source(source_path),
            generation_authority=lease,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    if existing_kind == "symlink":
        assert destination.is_symlink()
        assert expected.read_bytes() == b"outside-preserved"
    elif existing_kind == "file":
        assert expected.read_bytes() == b"file-preserved"
    else:
        assert expected.read_bytes() == b"directory-preserved"
    assert outside_sentinel.read_bytes() == b"outside-preserved"


def test_direct_projection_retains_late_failure_poison(tmp_path: Path) -> None:
    source_path = tmp_path / "corrupt.zip"
    late_payload = b"late-member-unique-payload"
    _write_projection_zip(
        source_path,
        (
            ("payload/first", b"first-member"),
            ("payload/second", late_payload),
        ),
    )
    archive_bytes = bytearray(source_path.read_bytes())
    payload_offset = archive_bytes.find(late_payload)
    assert payload_offset >= 0
    archive_bytes[payload_offset] ^= 0xFF
    source_path.write_bytes(archive_bytes)
    generation = tmp_path / "generation"
    generation.mkdir()

    with (
        directory_lease(resolve_directory_authority(generation)) as lease,
        pytest.raises(CapsuleAssemblyError, match="cannot read zip archive member"),
    ):
        project_archive_into_unpublished_generation(
            _projection_source(source_path),
            generation_authority=lease,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    assert (generation / "runtime/first").read_bytes() == b"first-member"
    assert (generation / "runtime").is_dir()


def test_direct_projection_cardinality_bound_leaves_empty_poison(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "too-many-files.tar"
    with tarfile.open(source_path, "w") as archive:
        for index in range(_MAX_ARCHIVE_PROJECTED_FILES + 1):
            member = tarfile.TarInfo(f"payload/files/{index:05d}")
            member.mode = 0o644
            member.mtime = _SOURCE_DATE_EPOCH
            archive.addfile(member)
    source = ArchiveProjectionSource(
        path=source_path,
        sha256=_sha256(source_path),
        size=source_path.stat().st_size,
        archive_kind=ArchiveKind.TAR,
        archive_root="payload",
    )
    generation = tmp_path / "generation"
    generation.mkdir()

    with (
        directory_lease(resolve_directory_authority(generation)) as lease,
        pytest.raises(CapsuleAssemblyError, match="invalid file cardinality"),
    ):
        project_archive_into_unpublished_generation(
            source,
            generation_authority=lease,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    poisoned_prefix = generation / "runtime"
    assert poisoned_prefix.is_dir()
    assert tuple(poisoned_prefix.iterdir()) == ()


def test_direct_archive_cardinality_bound_leaves_zero_byte_poison(
    tmp_path: Path,
) -> None:
    capsule_root = tmp_path / "capsule-root"
    capsule_root.mkdir()
    for index in range(_MAX_CAPSULE_TREE_FILES + 1):
        (capsule_root / f"{index:05d}").touch()
    generation = tmp_path / "generation"
    generation.mkdir()

    with (
        directory_lease(resolve_directory_authority(generation)) as lease,
        pytest.raises(CapsuleAssemblyError, match="entry-count bound"),
    ):
        write_deterministic_capsule_zip_into_unpublished_generation(
            capsule_root,
            generation_authority=lease,
            output_name="component.zip",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    poison = generation / "component.zip"
    assert poison.is_file()
    assert poison.stat().st_size == 0


def test_legacy_projection_keeps_host_specific_publication_boundary(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.zip"
    _write_projection_zip(source_path, (("payload/data", b"legacy-data"),))
    output = tmp_path / "output"
    output.mkdir()

    if os.name == "posix":
        with pytest.raises(CapsuleAssemblyError, match="cannot publish"):
            project_archive(
                _projection_source(source_path),
                destination_root=output,
                destination_prefix="runtime",
                source_date_epoch=_SOURCE_DATE_EPOCH,
            )
        assert not (output / "runtime").exists()
        assert all(
            not candidate.is_dir() or not any(candidate.iterdir())
            for candidate in output.iterdir()
        )
    else:
        evidence = project_archive(
            _projection_source(source_path),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
        assert [item.relative_path for item in evidence] == ["runtime/data"]
        assert (output / "runtime/data").read_bytes() == b"legacy-data"


@pytest.mark.parametrize("operation", ("projection", "archive"))
def test_generation_name_swap_cannot_redirect_direct_output(
    tmp_path: Path,
    operation: str,
) -> None:
    source_path = tmp_path / "source.zip"
    projected_payload = b"projected-trusted\n" * 4096
    _write_projection_zip(
        source_path,
        tuple(
            (f"payload/files/{index:04d}.bin", projected_payload) for index in range(64)
        ),
    )
    capsule_root = tmp_path / "capsule-root"
    capsule_root.mkdir()
    archived_payload = b"archived-trusted\n" * 4096
    for index in range(64):
        (capsule_root / f"{index:04d}.bin").write_bytes(archived_payload)
    generation = tmp_path / "generation"
    generation.mkdir()
    parked = tmp_path / "generation-parked"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside-preserved")
    after_exists = (
        generation / "runtime/files/0000.bin"
        if operation == "projection"
        else generation / "component.zip"
    )
    swap_result = tmp_path / "swap.result"
    context = multiprocessing.get_context("spawn")
    swapper = context.Process(
        target=_swap_directory_process,
        args=(generation, parked, outside, after_exists, swap_result),
    )
    call_succeeded = False

    with directory_lease(resolve_directory_authority(generation)) as lease:
        swapper.start()
        _await_process_ready(swap_result)
        with suppress(CapsuleAssemblyError):
            if operation == "projection":
                project_archive_into_unpublished_generation(
                    _projection_source(source_path),
                    generation_authority=lease,
                    destination_prefix="runtime",
                    source_date_epoch=_SOURCE_DATE_EPOCH,
                )
            else:
                write_deterministic_capsule_zip_into_unpublished_generation(
                    capsule_root,
                    generation_authority=lease,
                    output_name="component.zip",
                    source_date_epoch=_SOURCE_DATE_EPOCH,
                )
            call_succeeded = True
        swapper.join(timeout=20)
        assert not swapper.is_alive()
        assert swapper.exitcode == 0
        swap_outcome = swap_result.read_text(encoding="utf-8")
        _restore_swapped_directory(generation, parked)

    assert sentinel.read_bytes() == b"outside-preserved"
    assert tuple(outside.iterdir()) == (sentinel,)
    if swap_outcome == "swapped":
        assert not call_succeeded
    else:
        assert swap_outcome.startswith("blocked:")
        assert call_succeeded
        if operation == "projection":
            assert (generation / "runtime/files/0063.bin").read_bytes() == (
                projected_payload
            )
        else:
            with zipfile.ZipFile(generation / "component.zip") as archive:
                assert archive.read("capsule/0063.bin") == archived_payload


def test_projection_destination_parent_swap_cannot_redirect_bytes(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.zip"
    payload = b"trusted-parent-payload\n" * 4096
    _write_projection_zip(
        source_path,
        tuple((f"payload/files/{index:04d}.bin", payload) for index in range(128)),
    )
    generation = tmp_path / "generation"
    generation.mkdir()
    destination_parent = generation / "runtime/files"
    parked = generation / "runtime/files-parked"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside-parent-preserved")
    swap_result = tmp_path / "parent-swap.result"
    context = multiprocessing.get_context("spawn")
    swapper = context.Process(
        target=_swap_directory_process,
        args=(
            destination_parent,
            parked,
            outside,
            destination_parent,
            swap_result,
        ),
    )
    projected = None

    with directory_lease(resolve_directory_authority(generation)) as lease:
        swapper.start()
        _await_process_ready(swap_result)
        with suppress(CapsuleAssemblyError):
            projected = project_archive_into_unpublished_generation(
                _projection_source(source_path),
                generation_authority=lease,
                destination_prefix="runtime",
                source_date_epoch=_SOURCE_DATE_EPOCH,
            )
        swapper.join(timeout=20)
        assert not swapper.is_alive()
        assert swapper.exitcode == 0
        swap_outcome = swap_result.read_text(encoding="utf-8")
        _restore_swapped_directory(destination_parent, parked)

    assert sentinel.read_bytes() == b"outside-parent-preserved"
    assert tuple(outside.iterdir()) == (sentinel,)
    if swap_outcome == "swapped":
        assert projected is None
    else:
        assert swap_outcome.startswith("blocked:")
        assert projected is not None
        assert len(projected) == 128
        assert (destination_parent / "0000.bin").read_bytes() == payload


def test_capsule_source_root_swap_cannot_import_replacement_bytes(
    tmp_path: Path,
) -> None:
    capsule_root = tmp_path / "capsule-root"
    trusted_parent = capsule_root / "payload"
    trusted_parent.mkdir(parents=True)
    trusted = b"trusted-source-root\n" * 4096
    for index in range(64):
        (trusted_parent / f"{index:04d}.bin").write_bytes(trusted)
    parked = tmp_path / "capsule-root-parked"
    outside = tmp_path / "outside-source"
    outside_parent = outside / "payload"
    outside_parent.mkdir(parents=True)
    untrusted = b"replacement-bytes-must-not-enter-output"
    (outside_parent / "0000.bin").write_bytes(untrusted)
    generation = tmp_path / "generation"
    generation.mkdir()
    output = generation / "component.zip"
    swap_result = tmp_path / "source-swap.result"
    context = multiprocessing.get_context("spawn")
    swapper = context.Process(
        target=_swap_directory_process,
        args=(capsule_root, parked, outside, output, swap_result),
    )
    archive_result = None

    with directory_lease(resolve_directory_authority(generation)) as lease:
        swapper.start()
        _await_process_ready(swap_result)
        with suppress(CapsuleAssemblyError):
            archive_result = (
                write_deterministic_capsule_zip_into_unpublished_generation(
                    capsule_root,
                    generation_authority=lease,
                    output_name="component.zip",
                    source_date_epoch=_SOURCE_DATE_EPOCH,
                )
            )
        swapper.join(timeout=20)
        assert not swapper.is_alive()
        assert swapper.exitcode == 0
        swap_outcome = swap_result.read_text(encoding="utf-8")
        _restore_swapped_directory(capsule_root, parked)

    assert (outside_parent / "0000.bin").read_bytes() == untrusted
    assert untrusted not in output.read_bytes()
    if swap_outcome == "swapped":
        assert archive_result is None
    else:
        assert swap_outcome.startswith("blocked:")
        assert archive_result is not None
        with zipfile.ZipFile(output) as archive:
            assert archive.read("capsule/payload/0000.bin") == trusted


def test_archive_source_parent_swap_preserves_declared_byte_identity(
    tmp_path: Path,
) -> None:
    source_parent = tmp_path / "source-parent"
    source_parent.mkdir()
    source_path = source_parent / "source.zip"
    trusted = b"declared-source-bytes\n" * (1 << 18)
    _write_projection_zip(source_path, (("payload/data.bin", trusted),))
    declared_source = _projection_source(source_path)
    parked = tmp_path / "source-parent-parked"
    outside = tmp_path / "outside-source-parent"
    outside.mkdir()
    untrusted = b"replacement-source-bytes\n" * (1 << 18)
    _write_projection_zip(outside / "source.zip", (("payload/data.bin", untrusted),))
    generation = tmp_path / "generation"
    generation.mkdir()
    active = tmp_path / "source-parent.active"
    done = tmp_path / "source-parent.done"
    swap_result = tmp_path / "source-parent.result"
    context = multiprocessing.get_context("spawn")
    swapper = context.Process(
        target=_churn_source_parent_process,
        args=(source_parent, parked, outside, active, done, swap_result),
    )
    projected = None

    with directory_lease(resolve_directory_authority(generation)) as lease:
        swapper.start()
        _await_process_ready(swap_result)
        active.write_bytes(b"go")
        try:
            with suppress(CapsuleAssemblyError):
                projected = project_archive_into_unpublished_generation(
                    declared_source,
                    generation_authority=lease,
                    destination_prefix="runtime",
                    source_date_epoch=_SOURCE_DATE_EPOCH,
                )
        finally:
            done.write_bytes(b"stop")
        swapper.join(timeout=20)
        assert not swapper.is_alive()
        assert swapper.exitcode == 0
        swap_outcome = swap_result.read_text(encoding="utf-8")

    if projected is not None:
        materialized = generation / "runtime/data.bin"
        assert materialized.read_bytes() == trusted
        assert projected[0].sha256 == hashlib.sha256(trusted).hexdigest()
    assert (
        not (generation / "runtime/data.bin").exists()
        or (generation / "runtime/data.bin").read_bytes() != untrusted
    )
    _, swaps, _, blocked = swap_outcome.split(":")
    assert int(swaps) > 0 or int(blocked) > 0
    assert source_path.exists()
    assert _sha256(source_path) == declared_source.sha256


def test_late_source_replacement_retains_nonempty_archive_poison(
    tmp_path: Path,
) -> None:
    capsule_root = tmp_path / "capsule-root"
    capsule_root.mkdir()
    first_payload = b"first-trusted-block\n" * (1 << 18)
    late_payload = b"late-trusted-block\n" * 4096
    (capsule_root / "a-first.bin").write_bytes(first_payload)
    late = capsule_root / "z-late.bin"
    late.write_bytes(late_payload)
    replacement = tmp_path / "replacement.bin"
    untrusted = b"late-replacement-block\n" * 4096
    replacement.write_bytes(untrusted)
    generation = tmp_path / "generation"
    generation.mkdir()
    output = generation / "component.zip"
    replace_result = tmp_path / "replace.result"
    context = multiprocessing.get_context("spawn")
    replacer = context.Process(
        target=_replace_file_after_output_process,
        args=(late, replacement, output, replace_result),
    )
    archive_result = None

    with directory_lease(resolve_directory_authority(generation)) as lease:
        replacer.start()
        _await_process_ready(replace_result)
        with suppress(CapsuleAssemblyError):
            archive_result = (
                write_deterministic_capsule_zip_into_unpublished_generation(
                    capsule_root,
                    generation_authority=lease,
                    output_name="component.zip",
                    source_date_epoch=_SOURCE_DATE_EPOCH,
                )
            )
        replacer.join(timeout=20)

    assert not replacer.is_alive()
    assert replacer.exitcode == 0
    replace_outcome = replace_result.read_text(encoding="utf-8")
    assert output.stat().st_size > 1 << 20
    assert untrusted not in output.read_bytes()
    if replace_outcome == "replaced":
        assert archive_result is None
    else:
        assert replace_outcome.startswith("blocked:")
        assert archive_result is not None
        with zipfile.ZipFile(output) as archive:
            assert archive.read("capsule/z-late.bin") == late_payload
