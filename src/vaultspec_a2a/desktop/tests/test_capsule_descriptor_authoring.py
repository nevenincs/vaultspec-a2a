"""Descriptor authoring proven through the real descriptor loader.

The offline proof constructs a model-valid ``CapsuleInputDescriptor``, authors
it to canonical TOML, and loads it back through the production
``load_capsule_input_descriptor`` - a successful load with the authored sha256
proves the serialization round-trips faithfully, never asserting against the
authored bytes.  The byte-consistent full-closure round-trip through
``open_verified_capsule_inputs`` is the service-marked run.
"""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING, Literal

import pytest

from vaultspec_a2a.desktop.artifacts import (
    AcpClosureDescriptor,
    ArchiveKind,
    ArtifactInputError,
    CapsuleInputDescriptor,
    ComponentAssetKind,
    InstalledClosureDescriptor,
    LockInputDescriptor,
    PythonClosureDescriptor,
    SourceArtifactDescriptor,
    load_capsule_input_descriptor,
)
from vaultspec_a2a.desktop.capsule_descriptor import author_capsule_input_descriptor
from vaultspec_a2a.desktop.contract import TargetTriple

if TYPE_CHECKING:
    from pathlib import Path

_TARGET = TargetTriple.WINDOWS_X86_64
_SDK = "@anthropic-ai/claude-agent-sdk-win32-x64"


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _sri(seed: str) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(seed.encode()).digest()).decode(
        "ascii"
    )


def _installed(
    kind: Literal["python", "acp"],
    *,
    source_inventory_sha256: str,
    lock_sha256: str,
) -> InstalledClosureDescriptor:
    return InstalledClosureDescriptor(
        descriptor_version="vaultspec-installed-closure-descriptor-v1",
        closure_kind=kind,
        target=_TARGET,
        install_root=f"runtime/{kind}",
        source_inventory_sha256=source_inventory_sha256,
        lock_sha256=lock_sha256,
        inventory_sha256=_digest(f"{kind}-installed-inventory"),
        inventory_size=4096,
        file_count=12,
        license_count=3,
        expanded_size=1 << 20,
        tree_digest=_digest(f"{kind}-tree"),
    )


def _valid_descriptor() -> CapsuleInputDescriptor:
    uv_sha = _digest("uv.lock")
    pkg_sha = _digest("package-lock.json")
    py_inv = _digest("python-wheelhouse")
    acp_inv = _digest("acp-tarballs")
    root_sri = _sri("acp-root-integrity")
    sdk_sri = _sri("sdk-integrity")
    sources = sorted(
        (
            SourceArtifactDescriptor(
                kind=ComponentAssetKind.PYTHON_RUNTIME,
                target=_TARGET,
                version="3.13",
                release="3.13.5",
                build="20250702",
                url="https://example.invalid/python.tar.gz",
                sha256=_digest("python-runtime"),
                size=1,
                archive_kind=ArchiveKind.TAR_GZIP,
                archive_root="python",
                license_expression="PSF-2.0",
                license_members=("python/LICENSE",),
                redistribution_evidence=("python-license",),
            ),
            SourceArtifactDescriptor(
                kind=ComponentAssetKind.NODE_RUNTIME,
                target=_TARGET,
                version="22",
                release="22.17.0",
                build="node-v22.17.0",
                url="https://nodejs.org/dist/v22.17.0/node-v22.17.0-win-x64.zip",
                sha256=_digest("node-runtime"),
                size=1,
                archive_kind=ArchiveKind.ZIP,
                archive_root="node-v22.17.0-win-x64",
                license_expression="MIT",
                license_members=("node-v22.17.0-win-x64/LICENSE",),
                redistribution_evidence=("archive-license:LICENSE",),
            ),
            SourceArtifactDescriptor(
                kind=ComponentAssetKind.ACP_ADAPTER,
                target=None,
                version="0.59.0",
                release="0.59.0",
                build="npm",
                url="https://example.invalid/claude-agent-acp.tgz",
                sha256=_digest("acp-adapter"),
                size=1,
                archive_kind=ArchiveKind.TAR_GZIP,
                archive_root="package",
                license_expression="Apache-2.0",
                license_members=("package/LICENSE",),
                redistribution_evidence=("acp-license",),
                package_lock_integrity=root_sri,
            ),
            SourceArtifactDescriptor(
                kind=ComponentAssetKind.A2A_DISTRIBUTION,
                target=None,
                version="0.1.0",
                release="0.1.0",
                build="wheel",
                url="https://example.invalid/vaultspec_a2a-0.1.0.whl",
                sha256=_digest("a2a-distribution"),
                size=1,
                archive_kind=ArchiveKind.WHEEL,
                archive_root=None,
                license_expression="MIT",
                license_members=("vaultspec_a2a-0.1.0.dist-info/licenses/LICENSE",),
                redistribution_evidence=("wheel-license",),
                source_commit="7df84b1de4455ed79895136ab085c821ce988c9a",
            ),
        ),
        key=lambda source: tuple(ComponentAssetKind).index(source.kind),
    )
    return CapsuleInputDescriptor(
        descriptor_version="2",
        target=_TARGET,
        source_date_epoch=1_700_000_000,
        sources=tuple(sources),
        uv_lock=LockInputDescriptor(sha256=uv_sha, size=1024),
        package_lock=LockInputDescriptor(sha256=pkg_sha, size=2048),
        python_closure=PythonClosureDescriptor(
            target=_TARGET,
            lock_sha256=uv_sha,
            package_count=84,
            wheel_inventory_sha256=py_inv,
            wheel_inventory_size=8192,
            installed=_installed(
                "python", source_inventory_sha256=py_inv, lock_sha256=uv_sha
            ),
        ),
        acp_closure=AcpClosureDescriptor(
            target=_TARGET,
            lock_sha256=pkg_sha,
            package_count=104,
            tarball_inventory_sha256=acp_inv,
            tarball_inventory_size=8192,
            installed=_installed(
                "acp", source_inventory_sha256=acp_inv, lock_sha256=pkg_sha
            ),
            root_package_integrity=root_sri,
            target_sdk_package=_SDK,
            target_sdk_integrity=sdk_sri,
        ),
    )


def test_authored_descriptor_round_trips_through_the_real_loader(
    tmp_path: Path,
) -> None:
    descriptor = _valid_descriptor()

    authored = author_capsule_input_descriptor(descriptor, output_dir=tmp_path)

    assert authored.path.name == "capsule-inputs.toml"
    assert authored.sha256 == hashlib.sha256(authored.path.read_bytes()).hexdigest()
    # The real consumer loads the authored bytes and the model round-trips.
    loaded = load_capsule_input_descriptor(
        authored.path, expected_sha256=authored.sha256
    )
    assert loaded.value == descriptor
    assert loaded.sha256 == authored.sha256


def test_authoring_is_deterministic(tmp_path: Path) -> None:
    descriptor = _valid_descriptor()

    first = author_capsule_input_descriptor(descriptor, output_dir=tmp_path / "a")
    second = author_capsule_input_descriptor(descriptor, output_dir=tmp_path / "b")

    assert first.sha256 == second.sha256
    assert first.size == second.size


def test_loader_rejects_a_tampered_descriptor(tmp_path: Path) -> None:
    authored = author_capsule_input_descriptor(_valid_descriptor(), output_dir=tmp_path)

    with pytest.raises(ArtifactInputError, match="digest does not match"):
        load_capsule_input_descriptor(authored.path, expected_sha256="0" * 64)
