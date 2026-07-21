"""License derivation proven through the real package-archive verifier.

Each derived wheel artifact is round-tripped through the production
``open_verified_python_wheel_archive`` verifier by ``derive_python_wheel_artifact``
itself, so a successful derivation is proof the consumer accepts the identity -
never an assertion against the deriver's own output.  Wheels here are real ZIP
archives with real METADATA, WHEEL, RECORD, and license members.
"""

from __future__ import annotations

import base64
import hashlib
import stat
import zipfile
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop.capsule_input_authoring import (
    CapsuleInputAuthoringError,
    ExternalLicenseOverride,
    LicenseOverride,
    derive_python_wheel_artifact,
    emit_python_closure_inventory,
)
from vaultspec_a2a.desktop.closure_inventory import canonical_closure_inventory_bytes
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.lock_reconciliation import (
    LockedWheel,
    PythonClosureSelection,
    PythonPackageSelection,
)

if TYPE_CHECKING:
    from pathlib import Path

_TARGET = TargetTriple.WINDOWS_X86_64
_TAG = "cp313-cp313-win_amd64"


def _member(name: str, payload: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info, payload


def _build_wheel(
    cache_root: Path,
    *,
    name: str = "example_package",
    version: str = "1.2.3",
    metadata_version: str = "2.4",
    license_expression: str | None = "MIT",
    license_file: str | None = "LICENSE",
    include_license_member: bool = True,
) -> LockedWheel:
    """Write one real wheel into the cache and return its locked descriptor."""
    dist_info = f"{name}-{version}.dist-info"
    metadata = (
        f"Metadata-Version: {metadata_version}\nName: {name}\nVersion: {version}\n"
    )
    if license_expression is not None:
        metadata += f"License-Expression: {license_expression}\n"
    if license_file is not None:
        metadata += f"License-File: {license_file}\n"
    members = [
        _member(f"{name}/__init__.py", b"x = 1\n"),
        _member(f"{dist_info}/METADATA", (metadata + "\n").encode()),
    ]
    if include_license_member and license_file is not None:
        members.append(
            _member(f"{dist_info}/licenses/{license_file}", b"license text\n")
        )
    members.append(
        _member(
            f"{dist_info}/WHEEL",
            f"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: {_TAG}\n".encode(),
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
    rows.append(f"{dist_info}/RECORD,,\n")
    members.append(_member(f"{dist_info}/RECORD", "".join(rows).encode()))

    scratch = cache_root / "wheel-scratch.whl"
    with zipfile.ZipFile(scratch, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for info, payload in members:
            archive.writestr(info, payload)
    payload = scratch.read_bytes()
    sha256 = hashlib.sha256(payload).hexdigest()
    cached = cache_root / sha256
    scratch.rename(cached)
    filename = f"{name}-{version}-{_TAG}.whl"
    return LockedWheel(
        url=f"https://files.example.test/{filename}",
        filename=filename,
        sha256=sha256,
        size=len(payload),
    )


def _selection(
    wheel: LockedWheel, *, name: str = "example-package"
) -> PythonPackageSelection:
    return PythonPackageSelection(
        name=name,
        version="1.2.3",
        dependencies=(),
        wheels=(wheel,),
        compatible_wheels=(wheel,),
    )


def _write_blob(cache_root: Path, payload: bytes) -> str:
    sha256 = hashlib.sha256(payload).hexdigest()
    (cache_root / sha256).write_bytes(payload)
    return sha256


def test_derives_a_metadata_declared_expression_and_license_member(
    tmp_path: Path,
) -> None:
    wheel = _build_wheel(tmp_path)

    artifact = derive_python_wheel_artifact(
        _selection(wheel), wheel, target=_TARGET, cache_root=tmp_path, overrides={}
    )

    assert artifact.license_expression == "MIT"
    assert artifact.license_members == (
        "example_package-1.2.3.dist-info/licenses/LICENSE",
    )
    assert artifact.external_licenses == ()
    assert "wheel-license:example_package-1.2.3.dist-info/licenses/LICENSE" in (
        artifact.redistribution_evidence
    )


def test_derives_a_curated_expression_when_metadata_lacks_one(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path, license_expression=None)
    overrides = {
        "example-package": LicenseOverride(
            version="1.2.3", expression="MIT", evidence="legacy License field: MIT"
        )
    }

    artifact = derive_python_wheel_artifact(
        _selection(wheel),
        wheel,
        target=_TARGET,
        cache_root=tmp_path,
        overrides=overrides,
    )

    assert artifact.license_expression == "MIT"
    assert "curated-license-expression:MIT" in artifact.redistribution_evidence


def test_derives_an_external_blob_for_a_wheel_shipping_no_license_bytes(
    tmp_path: Path,
) -> None:
    wheel = _build_wheel(
        tmp_path,
        license_expression=None,
        license_file=None,
        include_license_member=False,
    )
    blob = b"MIT License\n\nPermission is hereby granted...\n"
    blob_sha = _write_blob(tmp_path, blob)
    overrides = {
        "example-package": LicenseOverride(
            version="1.2.3",
            expression="MIT",
            evidence="upstream LICENSE",
            external=(
                ExternalLicenseOverride(
                    member="LICENSE",
                    url="https://raw.example.test/LICENSE",
                    sha256=blob_sha,
                ),
            ),
        )
    }

    artifact = derive_python_wheel_artifact(
        _selection(wheel),
        wheel,
        target=_TARGET,
        cache_root=tmp_path,
        overrides=overrides,
    )

    assert artifact.license_members == ()
    assert len(artifact.external_licenses) == 1
    external = artifact.external_licenses[0]
    assert external.declared_member == "LICENSE"
    assert external.sha256 == blob_sha
    assert external.size == len(blob)
    assert f"external-license:{external.source_id}" in artifact.redistribution_evidence


def test_fails_closed_without_a_metadata_expression_or_override(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path, license_expression=None)

    with pytest.raises(CapsuleInputAuthoringError, match="lacks a metadata license"):
        derive_python_wheel_artifact(
            _selection(wheel), wheel, target=_TARGET, cache_root=tmp_path, overrides={}
        )


def test_fails_closed_when_the_override_version_does_not_match_the_lock(
    tmp_path: Path,
) -> None:
    wheel = _build_wheel(tmp_path, license_expression=None)
    overrides = {
        "example-package": LicenseOverride(
            version="9.9.9", expression="MIT", evidence="legacy License field: MIT"
        )
    }

    with pytest.raises(CapsuleInputAuthoringError, match="but the closure locks"):
        derive_python_wheel_artifact(
            _selection(wheel),
            wheel,
            target=_TARGET,
            cache_root=tmp_path,
            overrides=overrides,
        )


def _matching_lock(wheel: LockedWheel) -> bytes:
    return (
        "version = 1\n"
        "revision = 3\n"
        'requires-python = ">=3.13"\n\n'
        "[[package]]\n"
        'name = "vaultspec-a2a"\n'
        'version = "0.1.0"\n'
        'source = { editable = "." }\n'
        "dependencies = [\n"
        '  { name = "example-package" },\n'
        "]\n\n"
        "[[package]]\n"
        'name = "example-package"\n'
        'version = "1.2.3"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
        "wheels = [\n"
        f'  {{ url = "{wheel.url}", hash = "sha256:{wheel.sha256}", '
        f"size = {wheel.size} }},\n"
        "]\n"
    ).encode()


def _closure_selection(wheel: LockedWheel) -> PythonClosureSelection:
    return PythonClosureSelection(
        target=_TARGET, roots=("example-package",), packages=(_selection(wheel),)
    )


def test_emits_a_reconciling_deterministic_python_inventory(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path)
    artifact = derive_python_wheel_artifact(
        _selection(wheel), wheel, target=_TARGET, cache_root=tmp_path, overrides={}
    )
    lock = _matching_lock(wheel)

    inventory, emitted = emit_python_closure_inventory(
        _closure_selection(wheel),
        (artifact,),
        lock_bytes=lock,
        root_package="vaultspec-a2a",
        python_full_version="3.13.5",
        cache_root=tmp_path,
    )

    assert emitted.path.name == emitted.sha256
    assert emitted.path.read_bytes() == canonical_closure_inventory_bytes(inventory)
    assert inventory.packages == (artifact,)
    assert inventory.roots == ("example-package",)

    _, again = emit_python_closure_inventory(
        _closure_selection(wheel),
        (artifact,),
        lock_bytes=lock,
        root_package="vaultspec-a2a",
        python_full_version="3.13.5",
        cache_root=tmp_path,
    )
    assert again.sha256 == emitted.sha256
    assert again.size == emitted.size


def test_emission_fails_closed_when_the_inventory_does_not_reconcile(
    tmp_path: Path,
) -> None:
    wheel = _build_wheel(tmp_path)
    artifact = derive_python_wheel_artifact(
        _selection(wheel), wheel, target=_TARGET, cache_root=tmp_path, overrides={}
    )
    # A lock whose digest the inventory embeds but whose root omits the package.
    lock = (
        b"version = 1\nrevision = 3\n"
        b'requires-python = ">=3.13"\n\n'
        b"[[package]]\n"
        b'name = "vaultspec-a2a"\n'
        b'version = "0.1.0"\n'
        b'source = { editable = "." }\n'
    )

    with pytest.raises(CapsuleInputAuthoringError, match="does not reconcile"):
        emit_python_closure_inventory(
            _closure_selection(wheel),
            (artifact,),
            lock_bytes=lock,
            root_package="vaultspec-a2a",
            python_full_version="3.13.5",
            cache_root=tmp_path,
        )
