"""Real-behavior tests for the production installed-inventory builder.

Every archive here is a genuine on-disk wheel or npm tarball with a real
``RECORD``, run through the real :mod:`vaultspec_a2a.desktop.package_archives`
verification. No test double, monkeypatch, or fabricated byte identity is used.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import zipfile
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop.artifacts import (
    ArtifactInputError,
    build_acp_closure_installed_inventory,
    build_python_closure_installed_inventory,
)
from vaultspec_a2a.desktop.closure_inventory import (
    AcpPackageArtifact,
    PythonWheelArtifact,
)
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.install_layout import (
    ArchiveMember,
    WheelSource,
    build_python_closure_layout,
)
from vaultspec_a2a.desktop.installed_inventory import (
    InstalledClosureDescriptor,
    InstalledFileRecord,
    InstalledInventoryError,
    InstalledLicenseRecord,
    build_verified_installed_closure_inventory,
    canonical_installed_inventory_bytes,
    license_component_token,
    load_installed_closure_inventory,
)
from vaultspec_a2a.desktop.package_archives import (
    open_verified_acp_package_archive,
    open_verified_python_wheel_archive,
    verified_archive_member_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path

_TARGET = TargetTriple.WINDOWS_X86_64
_SOURCE_DIGEST = "1" * 64
_LOCK_DIGEST = "2" * 64
_MODULE_MEMBER = "example_pkg.py"
_LICENSE_MEMBER = "example_pkg-1.0.0.dist-info/licenses/LICENSE"
_CONSOLE_SCRIPTS = (("example", "example_pkg:main"),)


def _record_bytes(contents: dict[str, bytes], *, record_path: str) -> bytes:
    lines = []
    for member in sorted(contents):
        encoded = (
            base64.urlsafe_b64encode(hashlib.sha256(contents[member]).digest())
            .decode("ascii")
            .rstrip("=")
        )
        lines.append(f"{member},sha256={encoded},{len(contents[member])}")
    lines.append(f"{record_path},,")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_wheel(path: Path) -> bytes:
    dist_info = "example_pkg-1.0.0.dist-info"
    record_path = f"{dist_info}/RECORD"
    contents = {
        _MODULE_MEMBER: b"def main() -> None:\n    pass\n",
        f"{dist_info}/METADATA": (
            b"Metadata-Version: 2.4\nName: example-pkg\nVersion: 1.0.0\n"
            b"License-Expression: MIT\nLicense-File: LICENSE\n"
        ),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        _LICENSE_MEMBER: b"wheel license\n",
    }
    contents[record_path] = _record_bytes(contents, record_path=record_path)
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(contents):
            archive.writestr(member, contents[member])
    return path.read_bytes()


def _wheel_descriptor(payload: bytes) -> PythonWheelArtifact:
    return PythonWheelArtifact(
        name="example-pkg",
        version="1.0.0",
        filename="example_pkg-1.0.0-py3-none-any.whl",
        url="https://packages.example.invalid/example_pkg-1.0.0-py3-none-any.whl",
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        license_expression="MIT",
        license_members=(_LICENSE_MEMBER,),
        redistribution_evidence=("wheel-license",),
    )


def _write_npm_tarball(path: Path) -> bytes:
    members = {
        "package/package.json": json.dumps(
            {"license": "Apache-2.0", "name": "@scope/example", "version": "2.3.4"}
        ).encode("utf-8"),
        "package/index.js": b"export {};\n",
        "package/LICENSE": b"npm license\n",
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in sorted(members):
            payload = members[name]
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))
    path.write_bytes(buffer.getvalue())
    return path.read_bytes()


def _npm_descriptor(payload: bytes) -> AcpPackageArtifact:
    return AcpPackageArtifact(
        name="@scope/example",
        version="2.3.4",
        install_path="node_modules/@scope/example",
        url="https://registry.example.invalid/example-2.3.4.tgz",
        integrity=(
            f"sha512-{base64.b64encode(hashlib.sha512(payload).digest()).decode('ascii')}"
        ),
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        license_expression="Apache-2.0",
        license_members=("package/LICENSE",),
        redistribution_evidence=("tarball-license",),
    )


def test_build_verified_installed_closure_inventory_carries_real_provenance(
    tmp_path: Path,
) -> None:
    wheel_path = tmp_path / "example_pkg.whl"
    payload = _write_wheel(wheel_path)
    descriptor = _wheel_descriptor(payload)

    with open_verified_python_wheel_archive(
        wheel_path, descriptor, target=_TARGET
    ) as session:
        evidence = verified_archive_member_evidence(session)
        independent = {}
        with zipfile.ZipFile(wheel_path) as archive:
            for name in archive.namelist():
                data = archive.read(name)
                independent[name] = (len(data), hashlib.sha256(data).hexdigest())

        layout = build_python_closure_layout(
            wheels=(
                WheelSource(
                    source_sha256=descriptor.sha256,
                    distribution="example_pkg",
                    version="1.0.0",
                    members=tuple(
                        ArchiveMember(
                            member=item.path, size=item.size, sha256=item.sha256
                        )
                        for item in evidence
                    ),
                ),
            ),
            console_scripts=_CONSOLE_SCRIPTS,
        )
        verified_closure_members = {
            descriptor.sha256: frozenset(session.archive.members)
        }

    files = tuple(
        InstalledFileRecord(
            relative_path=file.relative_path,
            mode=file.mode,
            size=file.size,
            sha256=file.sha256,
            source_sha256=file.source_sha256,
            source_member=file.source_member,
        )
        for file in layout.files
    )
    license_file = InstalledFileRecord(
        relative_path="licenses/example-pkg/LICENSE",
        mode="0644",
        size=len(b"wheel license\n"),
        sha256=hashlib.sha256(b"wheel license\n").hexdigest(),
        source_sha256=descriptor.sha256,
        source_member=_LICENSE_MEMBER,
    )
    license_record = InstalledLicenseRecord(
        package="example-pkg",
        component=license_component_token("python", "example-pkg"),
        license_expression="MIT",
        source_member=_LICENSE_MEMBER,
        relative_path=license_file.relative_path,
        sha256=license_file.sha256,
    )
    all_files = tuple(
        sorted((*files, license_file), key=lambda file: file.relative_path)
    )

    inventory = build_verified_installed_closure_inventory(
        closure_kind="python",
        target=_TARGET,
        install_root=layout.install_root,
        source_inventory_sha256=_SOURCE_DIGEST,
        lock_sha256=_LOCK_DIGEST,
        entrypoints=layout.entrypoints,
        licenses=(license_record,),
        files=all_files,
        verified_closure_members=verified_closure_members,
    )

    assert inventory.inventory_version == "vaultspec-installed-closure-v2"
    for file in inventory.files:
        if file.relative_path == license_file.relative_path:
            continue
        assert file.source_sha256 == descriptor.sha256
        expected_size, expected_sha256 = independent[file.source_member]
        assert file.size == expected_size
        assert file.sha256 == expected_sha256


def test_build_verified_installed_closure_inventory_rejects_a_forged_member(
    tmp_path: Path,
) -> None:
    wheel_path = tmp_path / "example_pkg.whl"
    payload = _write_wheel(wheel_path)
    descriptor = _wheel_descriptor(payload)
    with open_verified_python_wheel_archive(
        wheel_path, descriptor, target=_TARGET
    ) as session:
        real_members = frozenset(session.archive.members)

    entrypoint_file = InstalledFileRecord(
        relative_path="bin/entry",
        mode="0755",
        size=1,
        sha256="a" * 64,
        source_sha256=descriptor.sha256,
        source_member=_MODULE_MEMBER,
    )
    license_file = InstalledFileRecord(
        relative_path="licenses/example-pkg/LICENSE",
        mode="0644",
        size=len(b"wheel license\n"),
        sha256=hashlib.sha256(b"wheel license\n").hexdigest(),
        source_sha256=descriptor.sha256,
        source_member=_LICENSE_MEMBER,
    )
    license_record = InstalledLicenseRecord(
        package="example-pkg",
        component=license_component_token("python", "example-pkg"),
        license_expression="MIT",
        source_member=_LICENSE_MEMBER,
        relative_path=license_file.relative_path,
        sha256=license_file.sha256,
    )
    forged_file = InstalledFileRecord(
        relative_path=_MODULE_MEMBER,
        mode="0644",
        size=1,
        sha256="a" * 64,
        source_sha256=descriptor.sha256,
        source_member="example_pkg/not-a-real-member.py",
    )
    with pytest.raises(InstalledInventoryError, match="verified closure member"):
        build_verified_installed_closure_inventory(
            closure_kind="python",
            target=_TARGET,
            install_root="runtime/python",
            source_inventory_sha256=_SOURCE_DIGEST,
            lock_sha256=_LOCK_DIGEST,
            entrypoints=("bin/entry",),
            licenses=(license_record,),
            files=(entrypoint_file, forged_file, license_file),
            verified_closure_members={descriptor.sha256: real_members},
        )


def test_build_verified_installed_closure_inventory_refuses_missing_evidence() -> None:
    file = InstalledFileRecord(
        relative_path="example_pkg/__init__.py",
        mode="0644",
        size=1,
        sha256="a" * 64,
        source_sha256="b" * 64,
        source_member="example_pkg/__init__.py",
    )
    with pytest.raises(
        InstalledInventoryError, match="verified closure-member evidence"
    ):
        build_verified_installed_closure_inventory(
            closure_kind="python",
            target=_TARGET,
            install_root="runtime/python",
            source_inventory_sha256=_SOURCE_DIGEST,
            lock_sha256=_LOCK_DIGEST,
            entrypoints=(),
            licenses=(),
            files=(file,),
            verified_closure_members={},
        )


def test_build_python_closure_installed_inventory_is_deterministic_and_caches(
    tmp_path: Path,
) -> None:
    wheel_path = tmp_path / "example_pkg.whl"
    payload = _write_wheel(wheel_path)
    descriptor = _wheel_descriptor(payload)
    cache = tmp_path / "cache"
    cache.mkdir()

    license_file = InstalledFileRecord(
        relative_path="licenses/example-pkg/LICENSE",
        mode="0644",
        size=len(b"wheel license\n"),
        sha256=hashlib.sha256(b"wheel license\n").hexdigest(),
        source_sha256=descriptor.sha256,
        source_member=_LICENSE_MEMBER,
    )
    license_record = InstalledLicenseRecord(
        package="example-pkg",
        component=license_component_token("python", "example-pkg"),
        license_expression="MIT",
        source_member=_LICENSE_MEMBER,
        relative_path=license_file.relative_path,
        sha256=license_file.sha256,
    )

    def _build() -> tuple[InstalledClosureDescriptor, bytes]:
        with open_verified_python_wheel_archive(
            wheel_path, descriptor, target=_TARGET
        ) as session:
            resolved_descriptor, inventory = build_python_closure_installed_inventory(
                target=_TARGET,
                source_inventory_sha256=_SOURCE_DIGEST,
                lock_sha256=_LOCK_DIGEST,
                wheel_sessions=(session,),
                console_scripts=_CONSOLE_SCRIPTS,
                licenses=(license_record,),
                license_files=(license_file,),
                input_dir=cache,
            )
        return resolved_descriptor, canonical_installed_inventory_bytes(inventory)

    first_descriptor, first_bytes = _build()
    second_descriptor, second_bytes = _build()

    assert first_bytes == second_bytes
    assert first_descriptor == second_descriptor
    assert first_descriptor.inventory_sha256 == hashlib.sha256(first_bytes).hexdigest()

    loaded = load_installed_closure_inventory(first_descriptor, input_dir=cache)
    assert loaded.value.inventory_version == "vaultspec-installed-closure-v2"
    module_files = {
        file.relative_path: file
        for file in loaded.value.files
        if file.relative_path == _MODULE_MEMBER
    }
    assert module_files[_MODULE_MEMBER].source_sha256 == descriptor.sha256
    assert module_files[_MODULE_MEMBER].source_member == _MODULE_MEMBER


def test_build_python_closure_installed_inventory_fails_closed_on_a_bad_console_script(
    tmp_path: Path,
) -> None:
    wheel_path = tmp_path / "example_pkg.whl"
    payload = _write_wheel(wheel_path)
    descriptor = _wheel_descriptor(payload)
    cache = tmp_path / "cache"
    cache.mkdir()

    with (
        open_verified_python_wheel_archive(
            wheel_path, descriptor, target=_TARGET
        ) as session,
        pytest.raises(ArtifactInputError, match="console-script"),
    ):
        build_python_closure_installed_inventory(
            target=_TARGET,
            source_inventory_sha256=_SOURCE_DIGEST,
            lock_sha256=_LOCK_DIGEST,
            wheel_sessions=(session,),
            console_scripts=(("bogus", "not_a_real_module:main"),),
            licenses=(),
            license_files=(),
            input_dir=cache,
        )


def test_build_acp_closure_installed_inventory_carries_real_npm_provenance(
    tmp_path: Path,
) -> None:
    tarball_path = tmp_path / "example.tgz"
    payload = _write_npm_tarball(tarball_path)
    descriptor = _npm_descriptor(payload)
    cache = tmp_path / "cache"
    cache.mkdir()

    license_file = InstalledFileRecord(
        relative_path="licenses/scope-example/LICENSE",
        mode="0644",
        size=len(b"npm license\n"),
        sha256=hashlib.sha256(b"npm license\n").hexdigest(),
        source_sha256=descriptor.sha256,
        source_member="package/LICENSE",
    )
    license_record = InstalledLicenseRecord(
        package="node_modules/@scope/example",
        component=license_component_token("acp", "node_modules/@scope/example"),
        license_expression="Apache-2.0",
        source_member="package/LICENSE",
        relative_path=license_file.relative_path,
        sha256=license_file.sha256,
    )

    with open_verified_acp_package_archive(tarball_path, descriptor) as session:
        resolved_descriptor, inventory = build_acp_closure_installed_inventory(
            target=_TARGET,
            source_inventory_sha256=_SOURCE_DIGEST,
            lock_sha256=_LOCK_DIGEST,
            tarball_sessions=(session,),
            bin_entrypoints=("node_modules/@scope/example/index.js",),
            licenses=(license_record,),
            license_files=(license_file,),
            input_dir=cache,
        )

    assert inventory.inventory_version == "vaultspec-installed-closure-v2"
    index_js = next(
        file
        for file in inventory.files
        if file.relative_path == "node_modules/@scope/example/index.js"
    )
    assert index_js.source_sha256 == descriptor.sha256
    assert index_js.source_member == "package/index.js"
    assert index_js.sha256 == hashlib.sha256(b"export {};\n").hexdigest()

    loaded = load_installed_closure_inventory(resolved_descriptor, input_dir=cache)
    assert loaded.value.tree_digest == inventory.tree_digest
