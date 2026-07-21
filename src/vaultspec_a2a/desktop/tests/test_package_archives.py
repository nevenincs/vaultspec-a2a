from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
import stat
import struct
import tarfile
import zipfile
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop._archive_authority import (
    ArchiveAuthorityError,
    ArchiveLimits,
    bounded_gzip_payload,
    preflight_tar_headers,
)
from vaultspec_a2a.desktop.closure_inventory import (
    AcpPackageArtifact,
    PythonWheelArtifact,
)
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.package_archives import (
    PackageArchiveError,
    open_verified_acp_package_archive,
    open_verified_python_wheel_archive,
    verified_archive_member_evidence,
    verify_acp_package_archive,
    verify_python_wheel_archive,
)
from vaultspec_a2a.desktop.wheel_compatibility import wheel_filename_supports_target

if TYPE_CHECKING:
    from pathlib import Path


def _wheel_member(name: str, payload: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    member = zipfile.ZipInfo(name)
    member.create_system = 3
    member.compress_type = zipfile.ZIP_DEFLATED
    member.external_attr = (stat.S_IFREG | 0o644) << 16
    return member, payload


def _write_wheel(
    path: Path,
    *,
    name: str = "example-package",
    version: str = "1.2.3",
    extra: tuple[tuple[zipfile.ZipInfo, bytes], ...] = (),
    include_license: bool = True,
    include_wheel: bool = True,
    include_record: bool = True,
    license_expression: str | None = "MIT",
    license_file: str | None = "LICENSE",
    license_member: str = "example_package-1.2.3.dist-info/licenses/LICENSE",
    metadata_version: str = "2.4",
) -> bytes:
    metadata = (
        f"Metadata-Version: {metadata_version}\nName: {name}\nVersion: {version}\n"
    )
    if license_expression is not None:
        metadata += f"License-Expression: {license_expression}\n"
    if license_file is not None:
        metadata += f"License-File: {license_file}\n"
    members = [
        _wheel_member("example_package/__init__.py", b"__version__ = '1.2.3'\n"),
        _wheel_member(
            "example_package-1.2.3.dist-info/METADATA",
            (metadata + "\n").encode(),
        ),
    ]
    if include_license:
        members.append(
            _wheel_member(
                license_member,
                b"wheel license\n",
            )
        )
    members.extend(extra)
    if include_wheel:
        members.append(
            _wheel_member(
                "example_package-1.2.3.dist-info/WHEEL",
                b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\n"
                b"Tag: cp313-cp313-win_amd64\n",
            )
        )
    if include_record:
        rows = []
        for member, payload in members:
            encoded = (
                base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
                .decode("ascii")
                .rstrip("=")
            )
            rows.append(f"{member.filename},sha256={encoded},{len(payload)}\n")
        rows.append("example_package-1.2.3.dist-info/RECORD,,\n")
        members.append(
            _wheel_member(
                "example_package-1.2.3.dist-info/RECORD", "".join(rows).encode()
            )
        )
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, payload in members:
            archive.writestr(member, payload)
    return path.read_bytes()


def _wheel_descriptor(
    payload: bytes,
    *,
    curated_fallback: bool = False,
    license_member: str = "example_package-1.2.3.dist-info/licenses/LICENSE",
) -> PythonWheelArtifact:
    evidence = ["wheel-license"]
    if curated_fallback:
        evidence.append("curated-license-expression:MIT")
    return PythonWheelArtifact(
        name="example-package",
        version="1.2.3",
        filename="example_package-1.2.3-cp313-cp313-win_amd64.whl",
        url="https://packages.example.invalid/example.whl",
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        license_expression="MIT",
        license_members=(license_member,),
        redistribution_evidence=tuple(evidence),
    )


def _tar_member(name: str, payload: bytes) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o644
    return member, payload


def _write_npm_tarball(
    path: Path,
    *,
    name: str = "@scope/example",
    version: str = "2.3.4",
    extra: tuple[tuple[tarfile.TarInfo, bytes | None], ...] = (),
    include_license: bool = True,
    license_expression: str = "Apache-2.0",
) -> bytes:
    members: list[tuple[tarfile.TarInfo, bytes | None]] = [
        _tar_member(
            "package/package.json",
            json.dumps(
                {"license": license_expression, "name": name, "version": version}
            ).encode(),
        ),
        _tar_member("package/index.js", b"export {};\n"),
    ]
    if include_license:
        members.append(_tar_member("package/LICENSE", b"npm license\n"))
    members.extend(extra)
    tar_payload = io.BytesIO()
    with tarfile.open(
        fileobj=tar_payload, mode="w", format=tarfile.PAX_FORMAT
    ) as archive:
        for member, payload in members:
            archive.addfile(member, None if payload is None else io.BytesIO(payload))
    path.write_bytes(gzip.compress(tar_payload.getvalue(), mtime=0))
    return path.read_bytes()


def _npm_descriptor(payload: bytes) -> AcpPackageArtifact:
    return AcpPackageArtifact(
        name="@scope/example",
        version="2.3.4",
        install_path="node_modules/@scope/example",
        url="https://registry.example.invalid/example.tgz",
        integrity="sha512-"
        + base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii"),
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        license_expression="Apache-2.0",
        license_members=("package/LICENSE",),
        redistribution_evidence=("tarball-license",),
    )


def test_wheel_verifier_binds_metadata_members_and_license_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "example.whl"
    payload = _write_wheel(path)

    verified = verify_python_wheel_archive(
        path,
        _wheel_descriptor(payload),
        target=TargetTriple.WINDOWS_X86_64,
    )

    assert verified.members == (
        "example_package-1.2.3.dist-info/METADATA",
        "example_package-1.2.3.dist-info/RECORD",
        "example_package-1.2.3.dist-info/WHEEL",
        "example_package-1.2.3.dist-info/licenses/LICENSE",
        "example_package/__init__.py",
    )
    assert verified.license_members[0].path.endswith("/licenses/LICENSE")
    assert verified.license_members[0].size == len(b"wheel license\n")
    assert (
        verified.license_members[0].sha256
        == hashlib.sha256(b"wheel license\n").hexdigest()
    )


def test_wheel_verifier_rejects_identity_and_missing_license(tmp_path: Path) -> None:
    wrong_identity = tmp_path / "wrong-identity.whl"
    payload = _write_wheel(wrong_identity, version="9.9.9")
    with pytest.raises(PackageArchiveError, match="METADATA identity"):
        verify_python_wheel_archive(
            wrong_identity,
            _wheel_descriptor(payload),
            target=TargetTriple.WINDOWS_X86_64,
        )

    missing_license = tmp_path / "missing-license.whl"
    payload = _write_wheel(missing_license, include_license=False)
    with pytest.raises(PackageArchiveError, match="license member is absent"):
        verify_python_wheel_archive(
            missing_license,
            _wheel_descriptor(payload),
            target=TargetTriple.WINDOWS_X86_64,
        )

    wrong_license = tmp_path / "wrong-license.whl"
    payload = _write_wheel(wrong_license, license_expression="Apache-2.0")
    with pytest.raises(PackageArchiveError, match="METADATA license"):
        verify_python_wheel_archive(
            wrong_license,
            _wheel_descriptor(payload),
            target=TargetTriple.WINDOWS_X86_64,
        )


def test_wheel_verifier_requires_explicit_curated_legacy_license_fallback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-license.whl"
    payload = _write_wheel(path, license_expression=None, license_file=None)

    with pytest.raises(PackageArchiveError, match="curated fallback"):
        verify_python_wheel_archive(
            path,
            _wheel_descriptor(payload),
            target=TargetTriple.WINDOWS_X86_64,
        )

    verified = verify_python_wheel_archive(
        path,
        _wheel_descriptor(payload, curated_fallback=True),
        target=TargetTriple.WINDOWS_X86_64,
    )
    assert verified.license_members[0].path.endswith("/LICENSE")


def test_wheel_verifier_supports_versioned_legacy_license_file_layout(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-layout.whl"
    license_member = "example_package-1.2.3.dist-info/LICENSE"
    payload = _write_wheel(
        path,
        license_expression=None,
        license_member=license_member,
        metadata_version="2.1",
    )

    verified = verify_python_wheel_archive(
        path,
        _wheel_descriptor(
            payload,
            curated_fallback=True,
            license_member=license_member,
        ),
        target=TargetTriple.WINDOWS_X86_64,
    )
    assert verified.license_members[0].path == license_member


def test_wheel_verifier_reconciles_all_declared_license_files(
    tmp_path: Path,
) -> None:
    path = tmp_path / "wrong-license-file.whl"
    payload = _write_wheel(path, license_file="OTHER")

    with pytest.raises(PackageArchiveError, match="License-File metadata"):
        verify_python_wheel_archive(
            path,
            _wheel_descriptor(payload),
            target=TargetTriple.WINDOWS_X86_64,
        )


@pytest.mark.parametrize(
    ("include_wheel", "include_record"), ((False, True), (True, False))
)
def test_wheel_verifier_requires_wheel_and_record_metadata(
    tmp_path: Path, include_wheel: bool, include_record: bool
) -> None:
    path = tmp_path / f"metadata-{include_wheel}-{include_record}.whl"
    payload = _write_wheel(
        path, include_wheel=include_wheel, include_record=include_record
    )

    with pytest.raises(PackageArchiveError, match="required WHEEL or RECORD"):
        verify_python_wheel_archive(
            path,
            _wheel_descriptor(payload),
            target=TargetTriple.WINDOWS_X86_64,
        )


def test_wheel_verifier_rejects_unsafe_links_and_portable_collisions(
    tmp_path: Path,
) -> None:
    link = zipfile.ZipInfo("example_package/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    link_path = tmp_path / "link.whl"
    payload = _write_wheel(link_path, extra=((link, b"../outside"),))
    with pytest.raises(PackageArchiveError, match="link or special"):
        verify_python_wheel_archive(
            link_path,
            _wheel_descriptor(payload),
            target=TargetTriple.WINDOWS_X86_64,
        )

    collision_path = tmp_path / "collision.whl"
    payload = _write_wheel(
        collision_path,
        extra=(
            _wheel_member("example_package/Café.py", b"one"),
            _wheel_member("example_package/Cafe\u0301.py", b"two"),
        ),
    )
    with pytest.raises(PackageArchiveError, match="portably colliding"):
        verify_python_wheel_archive(
            collision_path,
            _wheel_descriptor(payload),
            target=TargetTriple.WINDOWS_X86_64,
        )


@pytest.mark.parametrize(
    ("target", "filename"),
    (
        (TargetTriple.MACOS_ARM64, "demo-1.0-cp313-cp313-macosx_13_0_arm64.whl"),
        (TargetTriple.LINUX_ARM64, "demo-1.0-cp313-abi3-manylinux_2_28_aarch64.whl"),
        (
            TargetTriple.LINUX_X86_64,
            "demo-1.0-cp313-cp313-manylinux_2_28_x86_64.whl",
        ),
        (TargetTriple.WINDOWS_X86_64, "demo-1.0-cp39-abi3-win_amd64.whl"),
    ),
)
def test_wheel_target_helper_supports_each_native_target(
    target: TargetTriple, filename: str
) -> None:
    assert wheel_filename_supports_target(filename, target)
    assert not wheel_filename_supports_target(filename, _different_target(target))


def _different_target(target: TargetTriple) -> TargetTriple:
    if target is TargetTriple.WINDOWS_X86_64:
        return TargetTriple.LINUX_X86_64
    return TargetTriple.WINDOWS_X86_64


def test_wheel_target_helper_accepts_universal_and_rejects_wrong_python() -> None:
    assert wheel_filename_supports_target(
        "demo-1.0-py3-none-any.whl", TargetTriple.LINUX_ARM64
    )
    assert not wheel_filename_supports_target(
        "demo-1.0-cp312-cp312-win_amd64.whl", TargetTriple.WINDOWS_X86_64
    )
    assert not wheel_filename_supports_target(
        "demo-1.0-py3-abi3-manylinux_bad_x86_64.whl",
        TargetTriple.LINUX_X86_64,
    )
    assert not wheel_filename_supports_target("not-a-wheel", TargetTriple.LINUX_X86_64)


@pytest.mark.parametrize(
    "filename",
    (
        "demo-1.0-cp40-abi3-win_amd64.whl",
        "demo-1.0-cp99-abi3-win_amd64.whl",
        "demo-1.0-cp313-cp313-manylinux_2_99_x86_64.whl",
        "demo-1.0-cp313-cp313-macosx_99_0_x86_64.whl",
        "demo-1.0-cp313-abi3-any.whl",
        "demo-1.0-cp313-cp313-any.whl",
        "demo-1.0-cp313-cp313-linux_x86_64.whl",
    ),
)
def test_wheel_target_helper_rejects_future_runtime_baselines(filename: str) -> None:
    assert not wheel_filename_supports_target(filename, TargetTriple.WINDOWS_X86_64)
    assert not wheel_filename_supports_target(filename, TargetTriple.LINUX_X86_64)
    assert not wheel_filename_supports_target(filename, TargetTriple.MACOS_ARM64)


def test_npm_verifier_binds_package_identity_members_and_license_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "package.tgz"
    payload = _write_npm_tarball(path)

    verified = verify_acp_package_archive(path, _npm_descriptor(payload))

    assert verified.members == (
        "package/LICENSE",
        "package/index.js",
        "package/package.json",
    )
    assert verified.license_members[0].path == "package/LICENSE"
    assert (
        verified.license_members[0].sha256
        == hashlib.sha256(b"npm license\n").hexdigest()
    )


def test_npm_verifier_rejects_identity_missing_license_and_digest_drift(
    tmp_path: Path,
) -> None:
    wrong_identity = tmp_path / "wrong-identity.tgz"
    payload = _write_npm_tarball(wrong_identity, version="9.9.9")
    with pytest.raises(PackageArchiveError, match=r"package\.json identity"):
        verify_acp_package_archive(wrong_identity, _npm_descriptor(payload))

    missing_license = tmp_path / "missing-license.tgz"
    payload = _write_npm_tarball(missing_license, include_license=False)
    with pytest.raises(PackageArchiveError, match="license member is absent"):
        verify_acp_package_archive(missing_license, _npm_descriptor(payload))

    wrong_license = tmp_path / "wrong-license.tgz"
    payload = _write_npm_tarball(wrong_license, license_expression="MIT")
    with pytest.raises(PackageArchiveError, match=r"package\.json identity"):
        verify_acp_package_archive(wrong_license, _npm_descriptor(payload))

    changed = tmp_path / "changed.tgz"
    payload = _write_npm_tarball(changed)
    descriptor = _npm_descriptor(payload)
    changed.write_bytes(payload + b"changed")
    with pytest.raises(PackageArchiveError, match="size does not match"):
        verify_acp_package_archive(changed, descriptor)


def _curated_npm_descriptor(
    payload: bytes, *, expression: str, evidence: tuple[str, ...]
) -> AcpPackageArtifact:
    return AcpPackageArtifact(
        name="@scope/example",
        version="2.3.4",
        install_path="node_modules/@scope/example",
        url="https://registry.example.invalid/example.tgz",
        integrity="sha512-"
        + base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii"),
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        license_expression=expression,
        license_members=("package/LICENSE.md",),
        redistribution_evidence=evidence,
    )


def test_npm_verifier_accepts_a_curated_fallback_for_a_see_license_reference(
    tmp_path: Path,
) -> None:
    path = tmp_path / "see-license.tgz"
    payload = _write_npm_tarball(
        path,
        license_expression="SEE LICENSE IN LICENSE.md",
        include_license=False,
        extra=(_tar_member("package/LICENSE.md", b"(c) proprietary. all rights.\n"),),
    )

    verified = verify_acp_package_archive(
        path,
        _curated_npm_descriptor(
            payload,
            expression="LicenseRef-Anthropic-Commercial",
            evidence=("curated-license-expression:LicenseRef-Anthropic-Commercial",),
        ),
    )

    assert verified.license_members[0].path == "package/LICENSE.md"


def test_npm_verifier_rejects_a_curated_fallback_without_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "no-evidence.tgz"
    payload = _write_npm_tarball(
        path,
        license_expression="SEE LICENSE IN LICENSE.md",
        include_license=False,
        extra=(_tar_member("package/LICENSE.md", b"(c) proprietary.\n"),),
    )

    with pytest.raises(PackageArchiveError, match="curated fallback evidence"):
        verify_acp_package_archive(
            path,
            _curated_npm_descriptor(
                payload,
                expression="LicenseRef-Anthropic-Commercial",
                evidence=("tarball-license:LICENSE.md",),
            ),
        )


def test_npm_verifier_rejects_a_non_spdx_license_that_is_not_a_see_reference(
    tmp_path: Path,
) -> None:
    path = tmp_path / "garbage-license.tgz"
    payload = _write_npm_tarball(
        path,
        license_expression="totally not a license",
        include_license=False,
        extra=(_tar_member("package/LICENSE.md", b"(c) proprietary.\n"),),
    )

    with pytest.raises(PackageArchiveError, match="neither SPDX nor a SEE LICENSE"):
        verify_acp_package_archive(
            path,
            _curated_npm_descriptor(
                payload,
                expression="LicenseRef-Anthropic-Commercial",
                evidence=(
                    "curated-license-expression:LicenseRef-Anthropic-Commercial",
                ),
            ),
        )


def test_npm_verifier_rejects_link_traversal_and_nfc_casefold_collision(
    tmp_path: Path,
) -> None:
    link = tarfile.TarInfo("package/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "../outside"
    link_path = tmp_path / "link.tgz"
    payload = _write_npm_tarball(link_path, extra=((link, None),))
    with pytest.raises(PackageArchiveError, match="link or special"):
        verify_acp_package_archive(link_path, _npm_descriptor(payload))

    traversal_path = tmp_path / "traversal.tgz"
    payload = _write_npm_tarball(
        traversal_path,
        extra=(_tar_member("package/../outside", b"outside"),),
    )
    with pytest.raises(PackageArchiveError, match="unsafe member path"):
        verify_acp_package_archive(traversal_path, _npm_descriptor(payload))

    collision_path = tmp_path / "collision.tgz"
    payload = _write_npm_tarball(
        collision_path,
        extra=(
            _tar_member("package/Café", b"one"),
            _tar_member("package/cafe\u0301", b"two"),
        ),
    )
    with pytest.raises(PackageArchiveError, match="portably colliding"):
        verify_acp_package_archive(collision_path, _npm_descriptor(payload))


def test_archive_verifiers_reject_compression_bombs_before_evidence_reads(
    tmp_path: Path,
) -> None:
    wheel_path = tmp_path / "bomb.whl"
    wheel_payload = _write_wheel(
        wheel_path,
        extra=(_wheel_member("example_package/bomb.bin", b"\0" * (1 << 20)),),
    )
    with pytest.raises(PackageArchiveError, match="expansion-ratio"):
        verify_python_wheel_archive(
            wheel_path,
            _wheel_descriptor(wheel_payload),
            target=TargetTriple.WINDOWS_X86_64,
        )

    npm_path = tmp_path / "bomb.tgz"
    npm_payload = _write_npm_tarball(
        npm_path,
        extra=(_tar_member("package/bomb.bin", b"\0" * (1 << 20)),),
    )
    with pytest.raises(PackageArchiveError, match="expansion-ratio"):
        verify_acp_package_archive(npm_path, _npm_descriptor(npm_payload))


def test_verified_wheel_session_retains_original_read_only_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "retained.whl"
    payload = _write_wheel(path)
    descriptor = _wheel_descriptor(payload)

    with open_verified_python_wheel_archive(
        path,
        descriptor,
        target=TargetTriple.WINDOWS_X86_64,
    ) as session:
        with pytest.raises(AttributeError):
            object.__setattr__(session, "archive", session.archive)
        replacement = tmp_path / "replacement.whl"
        _write_wheel(replacement, version="9.9.9")
        os.replace(replacement, path)
        with session.open_snapshot() as source:
            assert hashlib.sha256(source.read()).hexdigest() == descriptor.sha256
            source.seek(0)
            with pytest.raises(io.UnsupportedOperation, match="read-only"):
                source.write(b"mutate")
            with (
                pytest.raises(PackageArchiveError, match="active reader"),
                session.open_snapshot(),
            ):
                pass
            retained_view = source
        with pytest.raises(ValueError, match="no longer active"):
            retained_view.read(1)

    with (
        pytest.raises(PackageArchiveError, match="session is closed"),
        session.open_snapshot(),
    ):
        pass
    with pytest.raises(PackageArchiveError, match=r"size|digest"):
        verify_python_wheel_archive(
            path,
            descriptor,
            target=TargetTriple.WINDOWS_X86_64,
        )


def test_verified_acp_session_retains_original_bytes(tmp_path: Path) -> None:
    path = tmp_path / "retained.tgz"
    payload = _write_npm_tarball(path)
    descriptor = _npm_descriptor(payload)

    with open_verified_acp_package_archive(path, descriptor) as session:
        replacement = tmp_path / "replacement.tgz"
        _write_npm_tarball(replacement, version="9.9.9")
        os.replace(replacement, path)
        with session.open_snapshot() as source:
            assert hashlib.sha256(source.read()).hexdigest() == descriptor.sha256

    with (
        pytest.raises(PackageArchiveError, match="session is closed"),
        session.open_snapshot(),
    ):
        pass


def test_verified_archive_member_evidence_matches_independent_wheel_digests(
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.whl"
    payload = _write_wheel(path)
    descriptor = _wheel_descriptor(payload)

    with open_verified_python_wheel_archive(
        path, descriptor, target=TargetTriple.WINDOWS_X86_64
    ) as session:
        evidence = verified_archive_member_evidence(session)
        members = session.archive.members

    with zipfile.ZipFile(path) as archive:
        independent = {}
        for name in archive.namelist():
            data = archive.read(name)
            independent[name] = (len(data), hashlib.sha256(data).hexdigest())

    assert tuple(item.path for item in evidence) == members
    assert members == tuple(sorted(members))
    for item in evidence:
        expected_size, expected_sha256 = independent[item.path]
        assert item.size == expected_size
        assert item.sha256 == expected_sha256


def test_verified_archive_member_evidence_matches_independent_npm_digests(
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.tgz"
    payload = _write_npm_tarball(path)
    descriptor = _npm_descriptor(payload)

    with open_verified_acp_package_archive(path, descriptor) as session:
        evidence = verified_archive_member_evidence(session)
        members = session.archive.members

    independent = {}
    with tarfile.open(path, "r:gz") as archive:
        for entry in archive.getmembers():
            if not entry.isfile():
                continue
            source = archive.extractfile(entry)
            assert source is not None
            data = source.read()
            independent[entry.name] = (len(data), hashlib.sha256(data).hexdigest())

    assert tuple(item.path for item in evidence) == members
    assert members == tuple(sorted(members))
    for item in evidence:
        expected_size, expected_sha256 = independent[item.path]
        assert item.size == expected_size
        assert item.sha256 == expected_sha256


def test_verified_archive_member_evidence_requires_an_open_session(
    tmp_path: Path,
) -> None:
    path = tmp_path / "closed.whl"
    payload = _write_wheel(path)
    descriptor = _wheel_descriptor(payload)

    with open_verified_python_wheel_archive(
        path, descriptor, target=TargetTriple.WINDOWS_X86_64
    ) as session:
        pass

    with pytest.raises(PackageArchiveError, match="session is closed"):
        verified_archive_member_evidence(session)


def test_verified_archive_member_evidence_rejects_a_non_session_input() -> None:
    with pytest.raises(PackageArchiveError, match="session is invalid"):
        verified_archive_member_evidence(object())  # ty: ignore[invalid-argument-type]


def test_wheel_preflight_reconciles_real_central_directory_count(
    tmp_path: Path,
) -> None:
    path = tmp_path / "count.whl"
    payload = bytearray(_write_wheel(path))
    end_record = payload.rfind(b"PK\x05\x06")
    declared = struct.unpack_from("<H", payload, end_record + 8)[0]
    struct.pack_into("<H", payload, end_record + 8, declared - 1)
    struct.pack_into("<H", payload, end_record + 10, declared - 1)
    path.write_bytes(payload)

    with pytest.raises(PackageArchiveError, match="entry count is inconsistent"):
        verify_python_wheel_archive(
            path,
            _wheel_descriptor(bytes(payload)),
            target=TargetTriple.WINDOWS_X86_64,
        )


def test_wheel_preflight_rejects_zip64_override_before_zipfile(
    tmp_path: Path,
) -> None:
    path = tmp_path / "zip64-override.whl"
    payload = bytearray(_write_wheel(path))
    end_record = payload.rfind(b"PK\x05\x06")
    entries = struct.unpack_from("<H", payload, end_record + 10)[0]
    directory_size = struct.unpack_from("<L", payload, end_record + 12)[0]
    directory_offset = struct.unpack_from("<L", payload, end_record + 16)[0]
    zip64_record = struct.pack(
        "<4sQ2H2L4Q",
        b"PK\x06\x06",
        44,
        45,
        45,
        0,
        0,
        entries,
        entries,
        directory_size,
        directory_offset,
    )
    zip64_locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, end_record, 1)
    payload[end_record:end_record] = zip64_record + zip64_locator
    path.write_bytes(payload)

    with pytest.raises(PackageArchiveError, match="zip64 central directories"):
        verify_python_wheel_archive(
            path,
            _wheel_descriptor(bytes(payload)),
            target=TargetTriple.WINDOWS_X86_64,
        )


def test_wheel_comment_eocd_ambiguity_is_normalized(
    tmp_path: Path,
) -> None:
    path = tmp_path / "comment.whl"
    _write_wheel(path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.comment = b"bounded comment PK\x05\x06 not an end record"
    payload = path.read_bytes()

    with pytest.raises(PackageArchiveError, match="cannot parse wheel archive"):
        verify_python_wheel_archive(
            path,
            _wheel_descriptor(payload),
            target=TargetTriple.WINDOWS_X86_64,
        )


def test_wheel_codec_failure_is_normalized_to_package_error(tmp_path: Path) -> None:
    path = tmp_path / "malformed-deflate.whl"
    payload = bytearray(_write_wheel(path))
    name_size, extra_size = struct.unpack_from("<2H", payload, 26)
    compressed_offset = 30 + name_size + extra_size
    payload[compressed_offset] |= 0x06
    path.write_bytes(payload)

    with pytest.raises(PackageArchiveError):
        verify_python_wheel_archive(
            path,
            _wheel_descriptor(bytes(payload)),
            target=TargetTriple.WINDOWS_X86_64,
        )


def test_package_scanners_reject_file_descendant_conflicts(tmp_path: Path) -> None:
    wheel_path = tmp_path / "ancestor.whl"
    wheel_payload = _write_wheel(
        wheel_path,
        extra=(
            _wheel_member("example_package/conflict", b"file"),
            _wheel_member("example_package/conflict/child", b"child"),
        ),
    )
    with pytest.raises(PackageArchiveError, match="descendant path conflict"):
        verify_python_wheel_archive(
            wheel_path,
            _wheel_descriptor(wheel_payload),
            target=TargetTriple.WINDOWS_X86_64,
        )

    npm_path = tmp_path / "ancestor.tgz"
    npm_payload = _write_npm_tarball(
        npm_path,
        extra=(
            _tar_member("package/conflict", b"file"),
            _tar_member("package/conflict/child", b"child"),
        ),
    )
    with pytest.raises(PackageArchiveError, match="descendant path conflict"):
        verify_acp_package_archive(npm_path, _npm_descriptor(npm_payload))


def test_tar_preflight_bounds_cumulative_extension_metadata() -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for index in range(2):
            member = tarfile.TarInfo(f"package/member-{index}")
            member.size = 1
            member.pax_headers = {"comment": "x" * 700}
            archive.addfile(member, io.BytesIO(b"x"))
    payload.seek(0)
    limits = ArchiveLimits(
        maximum_members=16,
        maximum_member_bytes=1 << 20,
        maximum_expanded_bytes=1024,
        maximum_expansion_ratio=250,
        maximum_tar_control_bytes=1024,
    )

    with pytest.raises(ArchiveAuthorityError, match="cumulative bound"):
        preflight_tar_headers(payload, limits=limits, label="test tar")


def test_bounded_gzip_payload_requires_one_complete_stream() -> None:
    payload = b"bounded gzip payload"
    encoded = gzip.compress(payload, mtime=0)
    limits = ArchiveLimits(
        maximum_members=16,
        maximum_member_bytes=1 << 20,
        maximum_expanded_bytes=1 << 20,
        maximum_expansion_ratio=250,
    )

    with bounded_gzip_payload(
        io.BytesIO(encoded),
        compressed_size=len(encoded),
        limits=limits,
        label="test gzip",
    ) as source:
        assert source.read() == payload

    for invalid in (encoded + b"trailing", encoded + encoded):
        with (
            pytest.raises(ArchiveAuthorityError, match="trailing or concatenated"),
            bounded_gzip_payload(
                io.BytesIO(invalid),
                compressed_size=len(invalid),
                limits=limits,
                label="test gzip",
            ),
        ):
            pass
