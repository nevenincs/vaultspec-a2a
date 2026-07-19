from __future__ import annotations

import gzip
import hashlib
import importlib
import io
import lzma
import os
import stat
import tarfile
import threading
import time
import zipfile
from typing import TYPE_CHECKING, Protocol, cast

import pytest

from vaultspec_a2a.desktop._filesystem_authority import (
    directory_lease,
    resolve_directory_authority,
)
from vaultspec_a2a.desktop.artifacts import ArchiveKind
from vaultspec_a2a.desktop.capsule import (
    ArchiveProjectionSource,
    CapsuleAssemblyError,
    ProjectedFile,
    deterministic_tree_digest,
    project_archive,
    read_archive_members,
    write_deterministic_capsule_zip,
)
from vaultspec_a2a.desktop.capsule_evidence import (
    _archive_quarantine,
    _bounded_directory_names,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

_SOURCE_DATE_EPOCH = 1_700_000_000
_XZ_256_MIB_DICTIONARY_STREAM = bytes.fromhex(
    "fd377a585a000004e6d6b44602002101200000000988a576"
    "010000780000000045aeef83f8ee160a00011901a52c81cc"
    "1fb6f37d010000000004595a"
)
_ZSTD_256_MIB_WINDOW_STREAM = bytes.fromhex("28b52ffd009009000078")


class _ZstdCompressor(Protocol):
    def compress(self, payload: bytes) -> bytes: ...


class _ZstdFactory(Protocol):
    def __call__(self, *, level: int) -> _ZstdCompressor: ...


class _ZstdModule(Protocol):
    ZstdCompressor: _ZstdFactory


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _assert_no_published_projection(output: Path) -> None:
    """Accept only bounded empty quarantines after a failed projection."""
    assert not (output / "runtime").exists()
    assert all(
        entry.is_dir()
        and entry.name.startswith(".vaultspec-projection-")
        and not any(entry.iterdir())
        for entry in output.iterdir()
    )


def _source(
    path: Path, kind: ArchiveKind, root: str = "payload"
) -> ArchiveProjectionSource:
    return ArchiveProjectionSource(
        path=path,
        sha256=_sha256(path),
        size=path.stat().st_size,
        archive_kind=kind,
        archive_root=root,
    )


def _zip_member(
    name: str, payload: bytes, *, mode: int = 0o644
) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, date_time=(2023, 11, 14, 22, 13, 20))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info, payload


def _write_zip(path: Path, members: tuple[tuple[zipfile.ZipInfo, bytes], ...]) -> None:
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
        for info, payload in members:
            archive.writestr(info, payload)


def _tar_bytes(members: tuple[tuple[tarfile.TarInfo, bytes | None], ...]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for info, payload in members:
            archive.addfile(info, None if payload is None else io.BytesIO(payload))
    return output.getvalue()


def _regular_tar_member(
    name: str, payload: bytes, *, mode: int = 0o644
) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = mode
    info.mtime = _SOURCE_DATE_EPOCH
    return info, payload


def _prove_directory_symlink_swap(path: Path, parked: Path, outside: Path) -> None:
    path.rename(parked)
    try:
        path.symlink_to(outside, target_is_directory=True)
        assert path.is_symlink()
    finally:
        if path.is_symlink():
            path.unlink()
        parked.rename(path)


def _churn_directory_after_authority_lease(
    path: Path,
    parked: Path,
    outside: Path,
    *,
    stop: threading.Event,
    attempted: threading.Event,
    swapped: threading.Event,
    errors: list[OSError],
) -> None:
    while not stop.is_set():
        attempted.set()
        try:
            path.rename(parked)
        except OSError:
            time.sleep(0.001)
            continue
        try:
            path.symlink_to(outside, target_is_directory=True)
            swapped.set()
            time.sleep(0.001)
        except OSError as error:
            errors.append(error)
        finally:
            try:
                if path.is_symlink():
                    path.unlink()
                if parked.exists() and not path.exists():
                    parked.rename(path)
            except OSError as error:
                errors.append(error)
                return


def _zstd_compress(payload: bytes) -> bytes:
    module = cast("_ZstdModule", importlib.import_module("zstandard"))
    return module.ZstdCompressor(level=3).compress(payload)


def test_real_zip_projection_and_archive_emission_are_byte_stable(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "input.zip"
    _write_zip(
        source_path,
        (
            _zip_member("payload/bin/tool", b"tool-bytes\n", mode=0o755),
            _zip_member("payload/LICENSE", b"license-bytes\n"),
        ),
    )
    source = _source(source_path, ArchiveKind.ZIP)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    first_projection = project_archive(
        source,
        destination_root=first_root,
        destination_prefix="assets",
        source_date_epoch=_SOURCE_DATE_EPOCH,
    )
    second_projection = project_archive(
        source,
        destination_root=second_root,
        destination_prefix="assets",
        source_date_epoch=_SOURCE_DATE_EPOCH,
    )

    assert first_projection == second_projection
    assert (first_root / "assets/bin/tool").read_bytes() == b"tool-bytes\n"
    assert [file.relative_path for file in first_projection] == [
        "assets/LICENSE",
        "assets/bin/tool",
    ]
    assert [file.mode for file in first_projection] == [0o644, 0o755]
    assert read_archive_members(source, ("payload/LICENSE",)) == {
        "payload/LICENSE": b"license-bytes\n"
    }

    first_archive = tmp_path / "first-capsule.zip"
    second_archive = tmp_path / "second-capsule.zip"
    first_digest, first_inventory = write_deterministic_capsule_zip(
        first_root, first_archive, source_date_epoch=_SOURCE_DATE_EPOCH
    )
    second_digest, second_inventory = write_deterministic_capsule_zip(
        second_root, second_archive, source_date_epoch=_SOURCE_DATE_EPOCH
    )

    assert first_digest == second_digest
    assert first_archive.read_bytes() == second_archive.read_bytes()
    assert first_inventory == second_inventory
    with zipfile.ZipFile(first_archive) as archive:
        assert all(member.extract_version >= 45 for member in archive.infolist())
    with pytest.raises(CapsuleAssemblyError, match="already exists"):
        write_deterministic_capsule_zip(
            first_root, first_archive, source_date_epoch=_SOURCE_DATE_EPOCH
        )
    assert first_archive.read_bytes() == second_archive.read_bytes()
    assert not tuple(tmp_path.glob(".*-capsule.zip.*.tmp"))


def test_empty_capsule_tree_is_rejected_without_publishing_output(
    tmp_path: Path,
) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    output = tmp_path / "empty-capsule.zip"

    with pytest.raises(CapsuleAssemblyError, match="contains no files"):
        write_deterministic_capsule_zip(
            empty_root,
            output,
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    assert not output.exists()
    assert not tuple(tmp_path.glob(".empty-capsule.zip.*.tmp"))


def test_tar_file_symlink_materializes_only_inside_declared_root(
    tmp_path: Path,
) -> None:
    target = _regular_tar_member("payload/bin/tool-real", b"real-tool\n", mode=0o755)
    link = tarfile.TarInfo("payload/bin/tool")
    link.type = tarfile.SYMTYPE
    link.linkname = "tool-real"
    link.mode = 0o755
    link.mtime = _SOURCE_DATE_EPOCH
    source_path = tmp_path / "input.tar"
    source_path.write_bytes(_tar_bytes((target, (link, None))))
    output = tmp_path / "output"
    output.mkdir()

    projected = project_archive(
        _source(source_path, ArchiveKind.TAR),
        destination_root=output,
        destination_prefix="runtime",
        source_date_epoch=_SOURCE_DATE_EPOCH,
    )

    assert (output / "runtime/bin/tool").read_bytes() == b"real-tool\n"
    assert {file.relative_path for file in projected} == {
        "runtime/bin/tool",
        "runtime/bin/tool-real",
    }
    assert not (output / "runtime/bin/tool").is_symlink()


def test_tar_link_cannot_import_bytes_from_outside_declared_root(
    tmp_path: Path,
) -> None:
    outside = _regular_tar_member("other/private", b"not-runtime\n")
    link = tarfile.TarInfo("payload/tool")
    link.type = tarfile.SYMTYPE
    link.linkname = "../other/private"
    link.mtime = _SOURCE_DATE_EPOCH
    source_path = tmp_path / "escaping-link.tar"
    source_path.write_bytes(_tar_bytes((outside, (link, None))))
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="target escapes"):
        project_archive(
            _source(source_path, ArchiveKind.TAR),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    _assert_no_published_projection(output)


def test_zip_special_member_is_rejected_before_projection(tmp_path: Path) -> None:
    fifo = zipfile.ZipInfo("payload/channel")
    fifo.create_system = 3
    fifo.external_attr = (stat.S_IFIFO | 0o644) << 16
    source_path = tmp_path / "special.zip"
    _write_zip(source_path, ((fifo, b""),))
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="special filesystem member"):
        project_archive(
            _source(source_path, ArchiveKind.ZIP),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    _assert_no_published_projection(output)


def test_license_read_rejects_an_unselected_traversal_member(tmp_path: Path) -> None:
    source_path = tmp_path / "unsafe.zip"
    _write_zip(
        source_path,
        (
            _zip_member("payload/LICENSE", b"license\n"),
            _zip_member("../outside", b"unsafe\n"),
        ),
    )

    with pytest.raises(CapsuleAssemblyError, match="unsafe path"):
        read_archive_members(
            _source(source_path, ArchiveKind.ZIP), ("payload/LICENSE",)
        )


def test_zstd_tar_projection_uses_the_same_bounded_authority(tmp_path: Path) -> None:
    tar_payload = _tar_bytes(
        (_regular_tar_member("payload/bin/tool", b"zstd-tool\n", mode=0o755),)
    )
    source_path = tmp_path / "input.tar.zst"
    source_path.write_bytes(_zstd_compress(tar_payload))
    output = tmp_path / "output"
    output.mkdir()

    projected = project_archive(
        _source(source_path, ArchiveKind.TAR_ZSTD),
        destination_root=output,
        destination_prefix="runtime",
        source_date_epoch=_SOURCE_DATE_EPOCH,
    )

    assert projected[0].relative_path == "runtime/bin/tool"
    assert (output / "runtime/bin/tool").read_bytes() == b"zstd-tool\n"


def test_xz_projection_rejects_a_dictionary_above_the_decoder_memory_cap(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "oversized-dictionary.tar.xz"
    source_path.write_bytes(_XZ_256_MIB_DICTIONARY_STREAM)
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="cannot decompress source"):
        project_archive(
            _source(source_path, ArchiveKind.TAR_XZ),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    _assert_no_published_projection(output)


def test_zstd_projection_rejects_a_window_above_the_decoder_memory_cap(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "oversized-window.tar.zst"
    source_path.write_bytes(_ZSTD_256_MIB_WINDOW_STREAM)
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="cannot decompress source zstd"):
        project_archive(
            _source(source_path, ArchiveKind.TAR_ZSTD),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    _assert_no_published_projection(output)


def test_zip_projection_rejects_an_oversized_central_directory_before_parse(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "oversized-directory.zip"
    _write_zip(source_path, (_zip_member("payload/file", b"bytes"),))
    payload = bytearray(source_path.read_bytes())
    end_record = payload.rfind(b"PK\x05\x06")
    assert end_record >= 0
    payload[end_record + 12 : end_record + 16] = (65 << 20).to_bytes(4, "little")
    source_path.write_bytes(payload)
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="central directory exceeds"):
        project_archive(
            _source(source_path, ArchiveKind.ZIP),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    _assert_no_published_projection(output)


def test_zip_projection_accepts_zip64_local_header_with_ordinary_directory(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "local-zip64.zip"
    with zipfile.ZipFile(source_path, "x", compression=zipfile.ZIP_STORED) as archive:
        info, payload = _zip_member("payload/file", b"zip64-local-header\n")
        with archive.open(info, "w", force_zip64=True) as target:
            target.write(payload)
    output = tmp_path / "output"
    output.mkdir()

    projected = project_archive(
        _source(source_path, ArchiveKind.ZIP),
        destination_root=output,
        destination_prefix="runtime",
        source_date_epoch=_SOURCE_DATE_EPOCH,
    )

    assert [file.relative_path for file in projected] == ["runtime/file"]
    assert (output / "runtime/file").read_bytes() == b"zip64-local-header\n"


def test_zip_projection_rejects_zip64_central_directory_sentinel(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "central-zip64.zip"
    _write_zip(source_path, (_zip_member("payload/file", b"bytes"),))
    payload = bytearray(source_path.read_bytes())
    end_record = payload.rfind(b"PK\x05\x06")
    assert end_record >= 0
    payload[end_record + 8 : end_record + 12] = b"\xff\xff\xff\xff"
    source_path.write_bytes(payload)
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="zip64 central directories"):
        project_archive(
            _source(source_path, ArchiveKind.ZIP),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    _assert_no_published_projection(output)


def test_projection_normalizes_a_non_string_prefix_to_the_typed_boundary(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "input.zip"
    _write_zip(source_path, (_zip_member("payload/file", b"bytes"),))
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="inputs are invalid"):
        project_archive(
            _source(source_path, ArchiveKind.ZIP),
            destination_root=output,
            destination_prefix=cast("str", None),
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    _assert_no_published_projection(output)


@pytest.mark.parametrize(
    ("kind", "compress"),
    (
        (ArchiveKind.TAR_GZIP, gzip.compress),
        (ArchiveKind.TAR_XZ, lzma.compress),
        (ArchiveKind.TAR_ZSTD, _zstd_compress),
    ),
)
def test_compressed_tar_projection_rejects_excessive_expansion_before_publish(
    tmp_path: Path,
    kind: ArchiveKind,
    compress: Callable[[bytes], bytes],
) -> None:
    tar_payload = _tar_bytes(
        (_regular_tar_member("other/unselected", b"\0" * (2 << 20)),)
    )
    source_path = tmp_path / f"input.{kind.value}"
    source_path.write_bytes(compress(tar_payload))
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="decompressed-size bound"):
        project_archive(
            _source(source_path, kind),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    _assert_no_published_projection(output)


def test_archive_projection_source_rejects_an_invalid_root_with_typed_error(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "input.zip"
    _write_zip(source_path, (_zip_member("payload/file", b"bytes"),))

    with pytest.raises(CapsuleAssemblyError, match="root is not portable"):
        ArchiveProjectionSource(
            path=source_path,
            sha256=_sha256(source_path),
            size=source_path.stat().st_size,
            archive_kind=ArchiveKind.ZIP,
            archive_root="../invalid",
        )


def test_installed_tree_evidence_rejects_invalid_and_colliding_records() -> None:
    with pytest.raises(CapsuleAssemblyError, match="file size is invalid"):
        ProjectedFile(
            relative_path="runtime/file",
            size=-1,
            sha256="0" * 64,
            mode=0o644,
        )

    first = ProjectedFile(
        relative_path="runtime/café",
        size=1,
        sha256="1" * 64,
        mode=0o644,
    )
    equivalent = ProjectedFile(
        relative_path="runtime/café",
        size=1,
        sha256="2" * 64,
        mode=0o644,
    )
    with pytest.raises(CapsuleAssemblyError, match="colliding paths"):
        deterministic_tree_digest((first, equivalent))


def test_installed_tree_evidence_stops_at_its_cardinality_bound() -> None:
    record = ProjectedFile(
        relative_path="runtime/file",
        size=1,
        sha256="1" * 64,
        mode=0o644,
    )
    consumed = 0

    def records() -> Iterator[ProjectedFile]:
        nonlocal consumed
        for _ in range(80_002):
            consumed += 1
            yield record

    with pytest.raises(CapsuleAssemblyError, match="cardinality is invalid"):
        deterministic_tree_digest(records())

    assert consumed == 80_001


def test_capsule_entry_enumeration_caps_before_sorting_and_metadata(
    tmp_path: Path,
) -> None:
    for name in ("zeta", "alpha", "middle"):
        (tmp_path / name).write_bytes(name.encode("ascii"))

    with pytest.raises(CapsuleAssemblyError, match="entry-count bound"):
        _bounded_directory_names(tmp_path, 2)
    assert _bounded_directory_names(tmp_path, 3) == ("alpha", "middle", "zeta")

    if os.name == "posix":
        descriptor = os.open(
            tmp_path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        try:
            with pytest.raises(CapsuleAssemblyError, match="entry-count bound"):
                _bounded_directory_names(descriptor, 2)
        finally:
            os.close(descriptor)


def test_failed_named_archive_staging_is_truncated_before_close(
    tmp_path: Path,
) -> None:
    authority = resolve_directory_authority(tmp_path)
    with (
        directory_lease(authority) as lease,
        pytest.raises(CapsuleAssemblyError, match="late archive failure"),
        _archive_quarantine(
            tmp_path,
            lease,
            "failed.zip",
        ) as (temporary_path, raw_output),
    ):
        raw_output.write(b"failed-archive-bytes" * (1 << 18))
        raise CapsuleAssemblyError("late archive failure")

    assert raw_output is not None and raw_output.closed
    if temporary_path is not None:
        assert temporary_path.is_file()
        assert temporary_path.stat().st_size == 0


def test_projection_publishes_no_partial_tree_when_a_late_member_is_corrupt(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "corrupt.zip"
    late_payload = b"late-member-unique-payload"
    _write_zip(
        source_path,
        (
            _zip_member("payload/first", b"first-member"),
            _zip_member("payload/second", late_payload),
        ),
    )
    archive_bytes = bytearray(source_path.read_bytes())
    payload_offset = archive_bytes.find(late_payload)
    assert payload_offset >= 0
    archive_bytes[payload_offset] ^= 0xFF
    source_path.write_bytes(archive_bytes)
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="cannot read zip archive member"):
        project_archive(
            _source(source_path, ArchiveKind.ZIP),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )

    if os.name == "posix":
        assert tuple(output.iterdir()) == ()
    else:
        _assert_no_published_projection(output)


def test_projection_symlink_churn_cannot_redirect_published_bytes(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "race.zip"
    payload = b"archive-member-bytes\n" * 4096
    _write_zip(
        source_path,
        tuple(
            _zip_member(f"payload/files/{index:04d}.bin", payload)
            for index in range(256)
        ),
    )
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside-must-remain-unchanged\n")
    destination = output / "runtime"
    churn_started = threading.Event()
    stop_churn = threading.Event()
    churn_errors: list[OSError] = []

    def churn_destination() -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not any(
            output.glob(".vaultspec-projection-*")
        ):
            time.sleep(0.001)
        while not stop_churn.is_set():
            try:
                destination.symlink_to(outside, target_is_directory=True)
                churn_started.set()
            except FileExistsError:
                pass
            except PermissionError as error:
                churn_errors.append(error)
                return
            try:
                if destination.is_symlink():
                    destination.unlink()
                elif destination.exists():
                    return
            except OSError:
                continue

    churner = threading.Thread(target=churn_destination, daemon=True)
    churner.start()
    projected = None
    try:
        projected = project_archive(
            _source(source_path, ArchiveKind.ZIP),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
    except CapsuleAssemblyError:
        pass
    finally:
        stop_churn.set()
        churner.join(timeout=10)
        if destination.is_symlink():
            destination.unlink()

    assert not churner.is_alive()
    assert churn_started.is_set(), churn_errors
    assert not churn_errors
    assert sentinel.read_bytes() == b"outside-must-remain-unchanged\n"
    assert tuple(outside.iterdir()) == (sentinel,)
    if projected is not None:
        assert destination.is_dir()
        assert not destination.is_symlink()
        assert len(projected) == 256


def test_projection_staging_parent_symlink_churn_cannot_escape_authority(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "staging-parent-race.zip"
    payload = b"staging-parent-race\n" * 4096
    _write_zip(
        source_path,
        tuple(
            _zip_member(f"payload/files/{index:04d}.bin", payload)
            for index in range(128)
        ),
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    parked = tmp_path / "staging-parked"
    outside = tmp_path / "outside-staging"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside-staging-must-remain-unchanged\n")
    _prove_directory_symlink_swap(staging, parked, outside)
    stop = threading.Event()
    attempted = threading.Event()
    swapped = threading.Event()
    errors: list[OSError] = []
    churner = threading.Thread(
        target=_churn_directory_after_authority_lease,
        args=(staging, parked, outside),
        kwargs={
            "stop": stop,
            "attempted": attempted,
            "swapped": swapped,
            "errors": errors,
        },
        daemon=True,
    )
    churner.start()
    projected = None
    try:
        projected = project_archive(
            _source(source_path, ArchiveKind.ZIP),
            destination_root=staging,
            destination_prefix="runtime",
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
    except CapsuleAssemblyError:
        pass
    finally:
        stop.set()
        churner.join(timeout=10)

    assert not churner.is_alive()
    assert attempted.is_set(), (swapped.is_set(), errors)
    assert not errors
    assert sentinel.read_bytes() == b"outside-staging-must-remain-unchanged\n"
    assert tuple(outside.iterdir()) == (sentinel,)
    if projected is not None:
        assert len(projected) == 128
        assert (staging / "runtime/files/0000.bin").read_bytes() == payload


def test_archive_output_parent_symlink_churn_cannot_redirect_publication(
    tmp_path: Path,
) -> None:
    capsule_root = tmp_path / "capsule-root"
    capsule_root.mkdir()
    payload = b"output-parent-race\n" * 4096
    for index in range(128):
        (capsule_root / f"{index:04d}.bin").write_bytes(payload)
    output_parent = tmp_path / "publish"
    output_parent.mkdir()
    parked = tmp_path / "publish-parked"
    outside = tmp_path / "outside-publish"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside-publish-must-remain-unchanged\n")
    _prove_directory_symlink_swap(output_parent, parked, outside)
    stop = threading.Event()
    attempted = threading.Event()
    swapped = threading.Event()
    errors: list[OSError] = []
    churner = threading.Thread(
        target=_churn_directory_after_authority_lease,
        args=(output_parent, parked, outside),
        kwargs={
            "stop": stop,
            "attempted": attempted,
            "swapped": swapped,
            "errors": errors,
        },
        daemon=True,
    )
    churner.start()
    archive_path = output_parent / "capsule.zip"
    result = None
    try:
        result = write_deterministic_capsule_zip(
            capsule_root,
            archive_path,
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
    except CapsuleAssemblyError:
        pass
    finally:
        stop.set()
        churner.join(timeout=10)

    assert not churner.is_alive()
    assert attempted.is_set(), (swapped.is_set(), errors)
    assert not errors
    assert sentinel.read_bytes() == b"outside-publish-must-remain-unchanged\n"
    assert tuple(outside.iterdir()) == (sentinel,)
    if result is not None:
        assert archive_path.is_file()
        assert result[0] == _sha256(archive_path)


@pytest.mark.parametrize("churn_root", (True, False))
def test_capsule_source_authority_churn_cannot_import_outside_bytes(
    tmp_path: Path,
    *,
    churn_root: bool,
) -> None:
    capsule_root = tmp_path / "capsule-source"
    payload_dir = capsule_root / "payload"
    payload_dir.mkdir(parents=True)
    trusted = b"trusted-source-bytes\n" * (1 << 18)
    (payload_dir / "file.bin").write_bytes(trusted)
    outside = tmp_path / "outside-source"
    outside.mkdir()
    untrusted = b"outside-bytes-must-not-be-read\n"
    churned = capsule_root if churn_root else payload_dir
    if churn_root:
        (outside / "payload").mkdir()
        (outside / "payload/file.bin").write_bytes(untrusted)
    else:
        (outside / "file.bin").write_bytes(untrusted)
    parked = tmp_path / "source-parked"
    _prove_directory_symlink_swap(churned, parked, outside)
    stop = threading.Event()
    attempted = threading.Event()
    swapped = threading.Event()
    errors: list[OSError] = []
    churner = threading.Thread(
        target=_churn_directory_after_authority_lease,
        args=(churned, parked, outside),
        kwargs={
            "stop": stop,
            "attempted": attempted,
            "swapped": swapped,
            "errors": errors,
        },
        daemon=True,
    )
    churner.start()
    output = tmp_path / f"source-{churn_root}.zip"
    result = None
    try:
        result = write_deterministic_capsule_zip(
            capsule_root,
            output,
            source_date_epoch=_SOURCE_DATE_EPOCH,
        )
    except CapsuleAssemblyError:
        pass
    finally:
        stop.set()
        churner.join(timeout=10)

    assert not churner.is_alive()
    assert attempted.is_set(), (swapped.is_set(), errors)
    assert not errors
    if result is not None:
        with zipfile.ZipFile(output) as archive:
            assert archive.read("capsule/payload/file.bin") == trusted


def test_projection_rejects_invalid_source_date_epoch_before_writing(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "input.zip"
    _write_zip(source_path, (_zip_member("payload/file", b"bytes"),))
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(CapsuleAssemblyError, match="SOURCE_DATE_EPOCH"):
        project_archive(
            _source(source_path, ArchiveKind.ZIP),
            destination_root=output,
            destination_prefix="runtime",
            source_date_epoch=0,
        )

    _assert_no_published_projection(output)
