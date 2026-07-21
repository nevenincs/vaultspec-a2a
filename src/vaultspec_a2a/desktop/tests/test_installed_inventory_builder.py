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
    ExternalLicenseArtifact,
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


def _write_other_npm_tarball(path: Path) -> bytes:
    members = {
        "package/package.json": json.dumps(
            {"license": "MIT", "name": "@scope/other", "version": "1.0.0"}
        ).encode("utf-8"),
        "package/index.js": b"export const other = true;\n",
        "package/LICENSE": b"other npm license\n",
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


def _other_npm_descriptor(payload: bytes) -> AcpPackageArtifact:
    return AcpPackageArtifact(
        name="@scope/other",
        version="1.0.0",
        install_path="node_modules/@scope/other",
        url="https://registry.example.invalid/other-1.0.0.tgz",
        integrity=(
            f"sha512-{base64.b64encode(hashlib.sha512(payload).digest()).decode('ascii')}"
        ),
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        license_expression="MIT",
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


def _external_license(cache: Path) -> tuple[ExternalLicenseArtifact, bytes]:
    payload = b"Additional NOTICE terms for the example package.\n"
    artifact = ExternalLicenseArtifact(
        source_id="external/example-NOTICE",
        declared_member="NOTICE",
        url="https://example.invalid/example/NOTICE",
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )
    (cache / artifact.sha256).write_bytes(payload)
    return artifact, payload


def test_build_acp_closure_installed_inventory_carries_real_external_license_provenance(
    tmp_path: Path,
) -> None:
    """A standalone external license reconciles with no hand-extended evidence."""
    tarball_path = tmp_path / "example.tgz"
    payload = _write_npm_tarball(tarball_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    external, external_bytes = _external_license(cache)
    descriptor = _npm_descriptor(payload).model_copy(
        update={
            "external_licenses": (external,),
            "redistribution_evidence": (
                "tarball-license",
                f"external-license:{external.source_id}",
            ),
        }
    )

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
    external_file = InstalledFileRecord(
        relative_path="licenses/scope-example/NOTICE",
        mode="0644",
        size=external.size,
        sha256=external.sha256,
        source_sha256=external.sha256,
        source_member=external.source_id,
    )
    external_record = InstalledLicenseRecord(
        package="node_modules/@scope/example",
        component=license_component_token("acp", "node_modules/@scope/example"),
        license_expression="Apache-2.0",
        source_member=external.source_id,
        relative_path=external_file.relative_path,
        sha256=external_file.sha256,
    )

    with open_verified_acp_package_archive(tarball_path, descriptor) as session:
        resolved_descriptor, inventory = build_acp_closure_installed_inventory(
            target=_TARGET,
            source_inventory_sha256=_SOURCE_DIGEST,
            lock_sha256=_LOCK_DIGEST,
            tarball_sessions=(session,),
            bin_entrypoints=("node_modules/@scope/example/index.js",),
            licenses=(license_record, external_record),
            license_files=(license_file, external_file),
            input_dir=cache,
        )

    notice = next(
        file
        for file in inventory.files
        if file.relative_path == external_file.relative_path
    )
    assert notice.source_sha256 == external.sha256
    assert notice.source_member == external.source_id
    assert notice.sha256 == hashlib.sha256(external_bytes).hexdigest()

    loaded = load_installed_closure_inventory(resolved_descriptor, input_dir=cache)
    assert loaded.value.tree_digest == inventory.tree_digest


def test_build_acp_closure_installed_inventory_rejects_a_forged_external_license(
    tmp_path: Path,
) -> None:
    """A file naming an artifact never verified as an external license fails closed."""
    tarball_path = tmp_path / "example.tgz"
    payload = _write_npm_tarball(tarball_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    external, _external_bytes = _external_license(cache)
    descriptor = _npm_descriptor(payload).model_copy(
        update={
            "external_licenses": (external,),
            "redistribution_evidence": (
                "tarball-license",
                f"external-license:{external.source_id}",
            ),
        }
    )

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
    forged_bytes = b"a forged notice that was never verified\n"
    forged_file = InstalledFileRecord(
        relative_path="licenses/scope-example/FORGED-NOTICE",
        mode="0644",
        size=len(forged_bytes),
        sha256=hashlib.sha256(forged_bytes).hexdigest(),
        source_sha256=hashlib.sha256(b"never-verified-artifact").hexdigest(),
        source_member="external/never-verified",
    )

    with (
        open_verified_acp_package_archive(tarball_path, descriptor) as session,
        pytest.raises(InstalledInventoryError, match="verified closure member"),
    ):
        build_acp_closure_installed_inventory(
            target=_TARGET,
            source_inventory_sha256=_SOURCE_DIGEST,
            lock_sha256=_LOCK_DIGEST,
            tarball_sessions=(session,),
            bin_entrypoints=("node_modules/@scope/example/index.js",),
            licenses=(license_record,),
            license_files=(license_file, forged_file),
            input_dir=cache,
        )


_DATA_DIR = "example_pkg-1.0.0.data"
_DROPPED_HEADER = f"{_DATA_DIR}/headers/example_pkg/greenlet.h"
_DROPPED_SCRIPT = f"{_DATA_DIR}/scripts/jsonpointer"
_PURELIB_MEMBER = f"{_DATA_DIR}/purelib/example_pkg/pure.py"


def _write_wheel_with_dropped_data(path: Path) -> bytes:
    """A real wheel carrying greenlet-shaped headers and a jsonpointer-shaped script.

    The ``.data/headers`` member and the ``#!python`` ``.data/scripts`` member are the
    exact shapes the real closure audit found; the ``.data/purelib`` member is the
    importable library code that must still install.
    """
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
        _PURELIB_MEMBER: b"PURE = 1\n",
        _DROPPED_HEADER: b"/* greenlet.h */\n",
        _DROPPED_SCRIPT: b"#!python\nprint('jsonpointer cli')\n",
    }
    contents[record_path] = _record_bytes(contents, record_path=record_path)
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(contents):
            archive.writestr(member, contents[member])
    return path.read_bytes()


def test_build_python_closure_inventory_excludes_dropped_data_members(
    tmp_path: Path,
) -> None:
    """End-to-end: a wheel with .data/headers and .data/scripts flows through the
    production builder to an inventory that omits those members while the library
    (purelib) code and importable module are present, and the drop evidence is
    available at the layout seam the builder consumes.
    """
    wheel_path = tmp_path / "example_pkg.whl"
    payload = _write_wheel_with_dropped_data(wheel_path)
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

    with open_verified_python_wheel_archive(
        wheel_path, descriptor, target=_TARGET
    ) as session:
        # (c) The drop evidence is present at the layout seam the builder consumes.
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
                        for item in verified_archive_member_evidence(session)
                    ),
                ),
            ),
            console_scripts=_CONSOLE_SCRIPTS,
        )
        assert {member.source_member: member.reason for member in layout.dropped} == {
            _DROPPED_HEADER: "data-headers",
            _DROPPED_SCRIPT: "data-scripts",
        }

        _resolved_descriptor, inventory = build_python_closure_installed_inventory(
            target=_TARGET,
            source_inventory_sha256=_SOURCE_DIGEST,
            lock_sha256=_LOCK_DIGEST,
            wheel_sessions=(session,),
            console_scripts=_CONSOLE_SCRIPTS,
            licenses=(license_record,),
            license_files=(license_file,),
            input_dir=cache,
        )

    placed = {file.relative_path for file in inventory.files}
    # (b) The importable library member and the console-script module are installed.
    assert "example_pkg/pure.py" in placed
    assert _MODULE_MEMBER in placed
    # (a) No dropped member reached the built inventory - not the header, not the
    # script, and nothing under a .data spread directory.
    assert not any(".data" in path for path in placed)
    assert not any("greenlet.h" in path for path in placed)
    assert "jsonpointer" not in placed
    assert not any(path.endswith("/jsonpointer") for path in placed)


def test_build_acp_closure_installed_inventory_admits_two_licenses_sharing_a_digest(
    tmp_path: Path,
) -> None:
    """Two distinct external licenses with byte-identical content both reconcile.

    Packages routinely ship the same MIT/Apache-2.0/BSD boilerplate text, so two
    unrelated packages' external licenses legitimately collapse to one sha256
    while naming distinct source_ids; the evidence accumulator must admit both
    rather than letting the second overwrite the first.
    """
    example_tarball_path = tmp_path / "example.tgz"
    example_payload = _write_npm_tarball(example_tarball_path)
    other_tarball_path = tmp_path / "other.tgz"
    other_payload = _write_other_npm_tarball(other_tarball_path)
    cache = tmp_path / "cache"
    cache.mkdir()

    shared_bytes = b"Shared MIT boilerplate text.\n"
    shared_sha256 = hashlib.sha256(shared_bytes).hexdigest()
    (cache / shared_sha256).write_bytes(shared_bytes)

    example_external = ExternalLicenseArtifact(
        source_id="external/example-NOTICE",
        declared_member="NOTICE",
        url="https://example.invalid/example/NOTICE",
        sha256=shared_sha256,
        size=len(shared_bytes),
    )
    other_external = ExternalLicenseArtifact(
        source_id="external/other-NOTICE",
        declared_member="NOTICE",
        url="https://example.invalid/other/NOTICE",
        sha256=shared_sha256,
        size=len(shared_bytes),
    )
    example_descriptor = _npm_descriptor(example_payload).model_copy(
        update={
            "external_licenses": (example_external,),
            "redistribution_evidence": (
                "tarball-license",
                f"external-license:{example_external.source_id}",
            ),
        }
    )
    other_descriptor = _other_npm_descriptor(other_payload).model_copy(
        update={
            "external_licenses": (other_external,),
            "redistribution_evidence": (
                "tarball-license",
                f"external-license:{other_external.source_id}",
            ),
        }
    )

    example_license_file = InstalledFileRecord(
        relative_path="licenses/scope-example/LICENSE",
        mode="0644",
        size=len(b"npm license\n"),
        sha256=hashlib.sha256(b"npm license\n").hexdigest(),
        source_sha256=example_descriptor.sha256,
        source_member="package/LICENSE",
    )
    example_license_record = InstalledLicenseRecord(
        package="node_modules/@scope/example",
        component=license_component_token("acp", "node_modules/@scope/example"),
        license_expression="Apache-2.0",
        source_member="package/LICENSE",
        relative_path=example_license_file.relative_path,
        sha256=example_license_file.sha256,
    )
    example_notice_file = InstalledFileRecord(
        relative_path="licenses/scope-example/NOTICE",
        mode="0644",
        size=example_external.size,
        sha256=example_external.sha256,
        source_sha256=example_external.sha256,
        source_member=example_external.source_id,
    )
    example_notice_record = InstalledLicenseRecord(
        package="node_modules/@scope/example",
        component=license_component_token("acp", "node_modules/@scope/example"),
        license_expression="Apache-2.0",
        source_member=example_external.source_id,
        relative_path=example_notice_file.relative_path,
        sha256=example_notice_file.sha256,
    )

    other_license_file = InstalledFileRecord(
        relative_path="licenses/scope-other/LICENSE",
        mode="0644",
        size=len(b"other npm license\n"),
        sha256=hashlib.sha256(b"other npm license\n").hexdigest(),
        source_sha256=other_descriptor.sha256,
        source_member="package/LICENSE",
    )
    other_license_record = InstalledLicenseRecord(
        package="node_modules/@scope/other",
        component=license_component_token("acp", "node_modules/@scope/other"),
        license_expression="MIT",
        source_member="package/LICENSE",
        relative_path=other_license_file.relative_path,
        sha256=other_license_file.sha256,
    )
    other_notice_file = InstalledFileRecord(
        relative_path="licenses/scope-other/NOTICE",
        mode="0644",
        size=other_external.size,
        sha256=other_external.sha256,
        source_sha256=other_external.sha256,
        source_member=other_external.source_id,
    )
    other_notice_record = InstalledLicenseRecord(
        package="node_modules/@scope/other",
        component=license_component_token("acp", "node_modules/@scope/other"),
        license_expression="MIT",
        source_member=other_external.source_id,
        relative_path=other_notice_file.relative_path,
        sha256=other_notice_file.sha256,
    )

    with (
        open_verified_acp_package_archive(
            example_tarball_path, example_descriptor
        ) as example_session,
        open_verified_acp_package_archive(
            other_tarball_path, other_descriptor
        ) as other_session,
    ):
        resolved_descriptor, inventory = build_acp_closure_installed_inventory(
            target=_TARGET,
            source_inventory_sha256=_SOURCE_DIGEST,
            lock_sha256=_LOCK_DIGEST,
            tarball_sessions=(example_session, other_session),
            bin_entrypoints=("node_modules/@scope/example/index.js",),
            licenses=(
                example_license_record,
                example_notice_record,
                other_license_record,
                other_notice_record,
            ),
            license_files=(
                example_license_file,
                example_notice_file,
                other_license_file,
                other_notice_file,
            ),
            input_dir=cache,
        )

    notices = {
        file.relative_path: file
        for file in inventory.files
        if file.relative_path
        in {example_notice_file.relative_path, other_notice_file.relative_path}
    }
    assert notices[example_notice_file.relative_path].source_sha256 == shared_sha256
    assert (
        notices[example_notice_file.relative_path].source_member
        == example_external.source_id
    )
    assert notices[other_notice_file.relative_path].source_sha256 == shared_sha256
    assert (
        notices[other_notice_file.relative_path].source_member
        == other_external.source_id
    )

    loaded = load_installed_closure_inventory(resolved_descriptor, input_dir=cache)
    assert loaded.value.tree_digest == inventory.tree_digest
