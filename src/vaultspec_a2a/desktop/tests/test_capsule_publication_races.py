from __future__ import annotations

import hashlib
import multiprocessing
import os
import stat
import time
import zipfile
from typing import TYPE_CHECKING

from vaultspec_a2a.desktop.artifacts import ArchiveKind
from vaultspec_a2a.desktop.capsule import (
    ArchiveProjectionSource,
    CapsuleAssemblyError,
    project_archive,
    write_deterministic_capsule_zip,
)

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE_DATE_EPOCH = 1_700_000_000


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _source(path: Path) -> ArchiveProjectionSource:
    return ArchiveProjectionSource(
        path=path,
        sha256=_sha256(path),
        size=path.stat().st_size,
        archive_kind=ArchiveKind.ZIP,
        archive_root="payload",
    )


def _write_zip(path: Path, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(2023, 11, 14, 22, 13, 20))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(info, payload)


def _publish_capsule_process(
    capsule_root: Path,
    output: Path,
    result: Path,
    start: Path,
) -> None:
    deadline = time.monotonic() + 20
    while not start.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("capsule publisher start barrier timed out")
        time.sleep(0.001)
    try:
        digest, _ = write_deterministic_capsule_zip(
            capsule_root,
            output,
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
    except CapsuleAssemblyError as error:
        result.write_text(f"error:{error}", encoding="utf-8")
    else:
        result.write_text(f"ok:{digest}", encoding="utf-8")


def _project_capsule_process(
    source_path: Path,
    output: Path,
    result: Path,
    start: Path,
) -> None:
    deadline = time.monotonic() + 20
    while not start.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("capsule projector start barrier timed out")
        time.sleep(0.001)
    try:
        projected = project_archive(
            _source(source_path),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
    except CapsuleAssemblyError as error:
        result.write_text(f"error:{error}", encoding="utf-8")
    else:
        result.write_text(f"ok:{len(projected)}", encoding="utf-8")


def test_concurrent_archive_publishers_cannot_delete_the_winner(tmp_path: Path) -> None:
    capsule_root = tmp_path / "capsule-root"
    capsule_root.mkdir()
    (capsule_root / "payload.bin").write_bytes(b"capsule-bytes\n" * 4096)
    output = tmp_path / "published.zip"
    start = tmp_path / "start"
    result_paths = (tmp_path / "first.result", tmp_path / "second.result")
    context = multiprocessing.get_context("spawn")
    publishers = tuple(
        context.Process(
            target=_publish_capsule_process,
            args=(capsule_root, output, result, start),
        )
        for result in result_paths
    )
    for publisher in publishers:
        publisher.start()
    start.write_bytes(b"go")
    for publisher in publishers:
        publisher.join(timeout=20)

    assert all(not publisher.is_alive() for publisher in publishers)
    assert [publisher.exitcode for publisher in publishers] == [0, 0]
    results = tuple(path.read_text(encoding="utf-8") for path in result_paths)
    assert len(tuple(result for result in results if result.startswith("ok:"))) == 1
    assert len(tuple(result for result in results if result.startswith("error:"))) == 1
    error = next(result for result in results if result.startswith("error:"))
    assert "already exists" in error
    winner = next(
        result.removeprefix("ok:") for result in results if result.startswith("ok:")
    )
    assert _sha256(output) == winner
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["capsule/payload.bin"]
        assert archive.read("capsule/payload.bin") == b"capsule-bytes\n" * 4096
    quarantines = tuple(tmp_path.glob(".published.zip.*.tmp"))
    assert len(quarantines) <= 1
    assert all(quarantine.stat().st_size == 0 for quarantine in quarantines)


def test_concurrent_directory_projectors_cannot_replace_the_winner(
    tmp_path: Path,
) -> None:
    payload = b"projected-bytes\n" * (1 << 18)
    source_path = tmp_path / "source.zip"
    _write_zip(source_path, "payload/data.bin", payload)
    output = tmp_path / "output"
    output.mkdir()
    start = tmp_path / "start"
    result_paths = (tmp_path / "first.result", tmp_path / "second.result")
    context = multiprocessing.get_context("spawn")
    projectors = tuple(
        context.Process(
            target=_project_capsule_process,
            args=(source_path, output, result, start),
        )
        for result in result_paths
    )
    for projector in projectors:
        projector.start()
    start.write_bytes(b"go")
    for projector in projectors:
        projector.join(timeout=20)

    assert all(not projector.is_alive() for projector in projectors)
    assert [projector.exitcode for projector in projectors] == [0, 0]
    results = tuple(path.read_text(encoding="utf-8") for path in result_paths)
    assert len(tuple(result for result in results if result.startswith("ok:"))) == 1
    assert len(tuple(result for result in results if result.startswith("error:"))) == 1
    error = next(result for result in results if result.startswith("error:"))
    assert "refuses to overwrite" in error
    assert (output / "runtime/data.bin").read_bytes() == payload
    quarantines = tuple(output.glob(".vaultspec-projection-*"))
    if os.name == "posix":
        assert quarantines == ()
    else:
        assert len(quarantines) <= 1
        assert all(
            quarantine.is_dir() and not any(quarantine.iterdir())
            for quarantine in quarantines
        )
