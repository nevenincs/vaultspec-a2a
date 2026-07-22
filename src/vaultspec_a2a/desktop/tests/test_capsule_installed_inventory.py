"""Installed-inventory building proven through the production build + load.

``build_python/acp_installed_inventory`` open real verified sessions, place
every license into the reserved ``.capsule-licenses`` subtree with provenance,
and drive the production builders.  Correctness is proven by loading the built
inventory back through ``load_installed_closure_inventory`` and matching the
tree digest - the same reconciliation the consumer applies - never asserting
against this code's own output.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import stat
import tarfile
import zipfile
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop.artifacts import load_installed_closure_inventory
from vaultspec_a2a.desktop.capsule_descriptor import (
    build_acp_installed_inventory,
    build_python_installed_inventory,
)
from vaultspec_a2a.desktop.capsule_input_authoring import CapsuleInputAuthoringError
from vaultspec_a2a.desktop.closure_inventory import (
    AcpPackageArtifact,
    PythonWheelArtifact,
)
from vaultspec_a2a.desktop.contract import TargetTriple

if TYPE_CHECKING:
    from pathlib import Path

_TARGET = TargetTriple.LINUX_X86_64
_TAG = "py3-none-any"
_DIST = "vaultspec_a2a-1.0.0"
_DEP_DIST = "deppkg-2.0.0"
_SOURCE_DIGEST = "a" * 64
_LOCK_DIGEST = "b" * 64
_CONSOLE_MODULES = (
    "vaultspec_a2a/cli/main.py",
    "vaultspec_a2a/protocols/mcp/__main__.py",
)


def _zip_member(name: str, payload: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info, payload


def _write_a2a_wheel(
    cache_root: Path, *, with_console: bool = True
) -> PythonWheelArtifact:
    members = []
    if with_console:
        members += [
            _zip_member(module, b"def main() -> None: ...\n")
            for module in _CONSOLE_MODULES
        ]
    else:
        members.append(_zip_member("vaultspec_a2a/__init__.py", b"x = 1\n"))
    license_member = f"{_DIST}.dist-info/licenses/LICENSE"
    members.append(_zip_member(license_member, b"MIT license text\n"))
    members.append(
        _zip_member(
            f"{_DIST}.dist-info/METADATA",
            b"Metadata-Version: 2.4\nName: vaultspec-a2a\nVersion: 1.0.0\n"
            b"License-Expression: MIT\nLicense-File: LICENSE\n\n",
        )
    )
    members.append(
        _zip_member(
            f"{_DIST}.dist-info/WHEEL",
            f"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: {_TAG}\n".encode(),
        )
    )
    rows = []
    for info, payload in members:
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            .decode("ascii")
            .rstrip("=")
        )
        rows.append(f"{info.filename},sha256={digest},{len(payload)}\n")
    rows.append(f"{_DIST}.dist-info/RECORD,,\n")
    members.append(_zip_member(f"{_DIST}.dist-info/RECORD", "".join(rows).encode()))

    scratch = cache_root / "scratch.whl"
    with zipfile.ZipFile(scratch, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for info, payload in members:
            archive.writestr(info, payload)
    payload = scratch.read_bytes()
    sha256 = hashlib.sha256(payload).hexdigest()
    scratch.rename(cache_root / sha256)
    return PythonWheelArtifact(
        name="vaultspec-a2a",
        version="1.0.0",
        filename=f"{_DIST}-{_TAG}.whl",
        url="https://files.example.test/vaultspec_a2a-1.0.0-py3-none-any.whl",
        sha256=sha256,
        size=len(payload),
        license_expression="MIT",
        license_members=(license_member,),
        redistribution_evidence=("wheel-license:LICENSE",),
    )


def _write_dependency_wheel(cache_root: Path) -> PythonWheelArtifact:
    license_member = f"{_DEP_DIST}.dist-info/licenses/LICENSE"
    members = [
        _zip_member("deppkg/__init__.py", b"value = 1\n"),
        _zip_member(license_member, b"dep license text\n"),
        _zip_member(
            f"{_DEP_DIST}.dist-info/METADATA",
            b"Metadata-Version: 2.4\nName: deppkg\nVersion: 2.0.0\n"
            b"License-Expression: MIT\nLicense-File: LICENSE\n\n",
        ),
        _zip_member(
            f"{_DEP_DIST}.dist-info/WHEEL",
            f"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: {_TAG}\n".encode(),
        ),
    ]
    rows = []
    for info, payload in members:
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            .decode("ascii")
            .rstrip("=")
        )
        rows.append(f"{info.filename},sha256={digest},{len(payload)}\n")
    rows.append(f"{_DEP_DIST}.dist-info/RECORD,,\n")
    members.append(_zip_member(f"{_DEP_DIST}.dist-info/RECORD", "".join(rows).encode()))

    scratch = cache_root / "dependency.whl"
    with zipfile.ZipFile(scratch, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for info, payload in members:
            archive.writestr(info, payload)
    payload = scratch.read_bytes()
    sha256 = hashlib.sha256(payload).hexdigest()
    scratch.rename(cache_root / sha256)
    return PythonWheelArtifact(
        name="deppkg",
        version="2.0.0",
        filename=f"{_DEP_DIST}-{_TAG}.whl",
        url="https://files.example.test/deppkg-2.0.0-py3-none-any.whl",
        sha256=sha256,
        size=len(payload),
        license_expression="MIT",
        license_members=(license_member,),
        redistribution_evidence=("wheel-license:LICENSE",),
    )


def test_python_installed_inventory_round_trips_through_the_consumer(
    tmp_path: Path,
) -> None:
    dependency = _write_dependency_wheel(tmp_path)
    project = _write_a2a_wheel(tmp_path)

    descriptor, inventory = build_python_installed_inventory(
        (dependency, project),
        target=_TARGET,
        source_inventory_sha256=_SOURCE_DIGEST,
        lock_sha256=_LOCK_DIGEST,
        cache_root=tmp_path,
    )

    # The two console-script modules are entrypoints (promoted to 0755).
    entrypoints = {
        file.relative_path for file in inventory.files if file.mode == "0755"
    }
    assert set(_CONSOLE_MODULES) <= entrypoints

    # The third-party dependency carries a reserved-subtree attribution record.
    assert {record.package for record in inventory.licenses} == {"deppkg"}
    dep_license = next(
        file
        for file in inventory.files
        if file.relative_path == ".capsule-licenses/deppkg/LICENSE"
    )
    assert dep_license.source_sha256 == dependency.sha256

    # The first-party A2A wheel gets NO reserved attribution record ...
    assert not any(
        file.relative_path.startswith(".capsule-licenses/vaultspec-a2a/")
        for file in inventory.files
    )
    # ... yet its own license still ships as a placed dist-info member.
    product_license = next(
        file
        for file in inventory.files
        if file.relative_path == f"{_DIST}.dist-info/licenses/LICENSE"
    )
    assert product_license.mode == "0644"
    assert product_license.source_sha256 == project.sha256
    assert product_license.sha256 == hashlib.sha256(b"MIT license text\n").hexdigest()

    # Round-trip: the consumer loads it and the tree digest matches.
    loaded = load_installed_closure_inventory(descriptor, input_dir=tmp_path)
    assert loaded.value.tree_digest == inventory.tree_digest


def test_python_inventory_fails_closed_without_a_console_script_module(
    tmp_path: Path,
) -> None:
    artifact = _write_a2a_wheel(tmp_path, with_console=False)

    with pytest.raises(CapsuleInputAuthoringError, match="console-script module"):
        build_python_installed_inventory(
            (artifact,),
            target=_TARGET,
            source_inventory_sha256=_SOURCE_DIGEST,
            lock_sha256=_LOCK_DIGEST,
            cache_root=tmp_path,
        )


def _tar_member(name: str, payload: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o644
    return info, payload


def _write_acp_tarball(cache_root: Path) -> AcpPackageArtifact:
    name = "@scope/example"
    members = [
        _tar_member(
            "package/package.json",
            b'{"license":"MIT","name":"@scope/example","version":"2.3.4"}',
        ),
        _tar_member("package/index.js", b"export {};\n"),
        _tar_member("package/LICENSE", b"npm mit text\n"),
    ]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for info, payload in members:
            archive.addfile(info, io.BytesIO(payload))
    tarball = gzip.compress(raw.getvalue(), mtime=0)
    sha256 = hashlib.sha256(tarball).hexdigest()
    (cache_root / sha256).write_bytes(tarball)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode(
        "ascii"
    )
    return AcpPackageArtifact(
        name=name,
        version="2.3.4",
        install_path=f"node_modules/{name}",
        url="https://registry.example.test/example.tgz",
        integrity=integrity,
        sha256=sha256,
        size=len(tarball),
        license_expression="MIT",
        license_members=("package/LICENSE",),
        redistribution_evidence=("tarball-license:package/LICENSE",),
    )


def test_acp_installed_inventory_round_trips_through_the_consumer(
    tmp_path: Path,
) -> None:
    artifact = _write_acp_tarball(tmp_path)

    descriptor, inventory = build_acp_installed_inventory(
        (artifact,),
        target=_TARGET,
        source_inventory_sha256=_SOURCE_DIGEST,
        lock_sha256=_LOCK_DIGEST,
        bin_entrypoints=("node_modules/@scope/example/index.js",),
        cache_root=tmp_path,
    )

    placed = next(
        file
        for file in inventory.files
        if file.relative_path.endswith("/LICENSE")
        and file.relative_path.startswith(".capsule-licenses/")
    )
    assert placed.source_sha256 == artifact.sha256
    loaded = load_installed_closure_inventory(descriptor, input_dir=tmp_path)
    assert loaded.value.tree_digest == inventory.tree_digest
