from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import zipfile
from typing import TYPE_CHECKING, Literal

import pytest
from pydantic import ValidationError

from vaultspec_a2a.desktop.artifacts import (
    AcpClosureDescriptor,
    AcpClosureInventory,
    AcpPackageArtifact,
    ArchiveKind,
    ArtifactInputError,
    CapsuleInputDescriptor,
    LockInputDescriptor,
    PythonClosureDescriptor,
    PythonClosureInventory,
    PythonWheelArtifact,
    SourceArtifactDescriptor,
    VerifiedArtifact,
    canonical_closure_inventory_bytes,
    load_acp_closure_inventory,
    load_capsule_closures,
    load_capsule_input_descriptor,
    load_python_closure_inventory,
    open_verified_a2a_wheel,
    open_verified_external_license,
    validate_portable_archive_path,
    verify_acp_tarballs,
    verify_lock_input,
    verify_python_wheelhouse,
)
from vaultspec_a2a.desktop.closure_inventory import ExternalLicenseArtifact
from vaultspec_a2a.desktop.contract import ComponentAssetKind, TargetTriple
from vaultspec_a2a.desktop.installed_inventory import (
    InstalledClosureDescriptor,
    InstalledClosureInventory,
    InstalledFileRecord,
    InstalledLicenseRecord,
    build_installed_closure_inventory,
    canonical_installed_inventory_bytes,
    license_component_token,
)

if TYPE_CHECKING:
    from pathlib import Path


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha512_sri(payload: bytes) -> str:
    digest = hashlib.sha512(payload).digest()
    return f"sha512-{base64.b64encode(digest).decode('ascii')}"


def _installed_descriptor(
    *, kind: Literal["python", "acp"], source_digest: str, lock_digest: str
) -> InstalledClosureDescriptor:
    return InstalledClosureDescriptor(
        descriptor_version="vaultspec-installed-closure-descriptor-v1",
        closure_kind=kind,
        target=TargetTriple.WINDOWS_X86_64,
        install_root=f"runtime/{kind}",
        source_inventory_sha256=source_digest,
        lock_sha256=lock_digest,
        inventory_sha256="a" * 64,
        inventory_size=1,
        file_count=1,
        license_count=1,
        expanded_size=1,
        tree_digest="b" * 64,
    )


def _cache_installed_descriptor(
    cache: Path,
    *,
    kind: Literal["python", "acp"],
    source_digest: str,
    lock_digest: str,
    packages: tuple[PythonWheelArtifact | AcpPackageArtifact, ...],
) -> InstalledClosureDescriptor:
    entry_bytes = b"entrypoint"
    files = [
        InstalledFileRecord(
            relative_path="bin/entry",
            mode="0755",
            size=len(entry_bytes),
            sha256=_sha256(entry_bytes),
        )
    ]
    licenses = []
    for package_index, package in enumerate(packages):
        if kind == "python" and isinstance(package, PythonWheelArtifact):
            identity = package.name
        elif kind == "acp" and isinstance(package, AcpPackageArtifact):
            identity = package.install_path
        else:
            raise TypeError("closure kind and package type disagree")
        license_sources = tuple(
            (source_member, _license_payload(identity, source_member))
            for source_member in package.license_members
        ) + tuple(
            (item.source_id, (cache / item.sha256).read_bytes())
            for item in package.external_licenses
        )
        for member_index, (source_member, payload) in enumerate(license_sources):
            path = f"licenses/{package_index:04d}/{member_index:04d}/LICENSE"
            files.append(
                InstalledFileRecord(
                    relative_path=path,
                    mode="0644",
                    size=len(payload),
                    sha256=_sha256(payload),
                )
            )
            licenses.append(
                InstalledLicenseRecord(
                    package=identity,
                    component=license_component_token(kind, identity),
                    license_expression=package.license_expression,
                    source_member=source_member,
                    relative_path=path,
                    sha256=_sha256(payload),
                )
            )
    inventory = build_installed_closure_inventory(
        closure_kind=kind,
        target=TargetTriple.WINDOWS_X86_64,
        install_root=f"runtime/{kind}",
        source_inventory_sha256=source_digest,
        lock_sha256=lock_digest,
        entrypoints=("bin/entry",),
        licenses=tuple(licenses),
        files=tuple(files),
    )
    payload = canonical_installed_inventory_bytes(inventory)
    digest = _sha256(payload)
    (cache / digest).write_bytes(payload)
    return InstalledClosureDescriptor(
        descriptor_version="vaultspec-installed-closure-descriptor-v1",
        closure_kind=inventory.closure_kind,
        target=inventory.target,
        install_root=inventory.install_root,
        source_inventory_sha256=inventory.source_inventory_sha256,
        lock_sha256=inventory.lock_sha256,
        inventory_sha256=digest,
        inventory_size=len(payload),
        file_count=inventory.file_count,
        license_count=len(inventory.licenses),
        expanded_size=inventory.expanded_size,
        tree_digest=inventory.tree_digest,
    )


def _license_payload(package_identity: str, source_member: str) -> bytes:
    return f"license:{package_identity}:{source_member}\n".encode()


def _mutate_installed_license(
    cache: Path,
    descriptor: InstalledClosureDescriptor,
    **changes: str,
) -> InstalledClosureDescriptor:
    inventory = InstalledClosureInventory.model_validate_json(
        (cache / descriptor.inventory_sha256).read_bytes()
    )
    original = inventory.licenses[0]
    mutated = original.model_copy(update=changes)
    files = tuple(
        file.model_copy(update={"sha256": mutated.sha256})
        if file.relative_path == original.relative_path
        else file
        for file in inventory.files
    )
    rebuilt = build_installed_closure_inventory(
        closure_kind=inventory.closure_kind,
        target=inventory.target,
        install_root=inventory.install_root,
        source_inventory_sha256=inventory.source_inventory_sha256,
        lock_sha256=inventory.lock_sha256,
        entrypoints=inventory.entrypoints,
        licenses=(mutated, *inventory.licenses[1:]),
        files=files,
    )
    payload = canonical_installed_inventory_bytes(rebuilt)
    digest = _sha256(payload)
    (cache / digest).write_bytes(payload)
    return InstalledClosureDescriptor(
        descriptor_version=descriptor.descriptor_version,
        closure_kind=rebuilt.closure_kind,
        target=rebuilt.target,
        install_root=rebuilt.install_root,
        source_inventory_sha256=rebuilt.source_inventory_sha256,
        lock_sha256=rebuilt.lock_sha256,
        inventory_sha256=digest,
        inventory_size=len(payload),
        file_count=rebuilt.file_count,
        license_count=len(rebuilt.licenses),
        expanded_size=rebuilt.expanded_size,
        tree_digest=rebuilt.tree_digest,
    )


def _python_wheel(
    payload: bytes | None = None,
    *,
    external_license: ExternalLicenseArtifact | None = None,
) -> tuple[PythonWheelArtifact, bytes]:
    license_member = "click-8.3.1.dist-info/licenses/LICENSE.txt"
    if payload is None:
        metadata = b"Metadata-Version: 2.4\nName: click\nVersion: 8.3.1\n"
        if external_license is None:
            metadata += b"License-Expression: BSD-3-Clause\n"
        metadata += b"License-File: LICENSE.txt\n"
        members = {
            "click-8.3.1.dist-info/METADATA": metadata,
            "click-8.3.1.dist-info/WHEEL": (
                b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            ),
        }
        if external_license is None:
            members[license_member] = _license_payload("click", license_member)
        record_rows = []
        for name, member_payload in members.items():
            encoded = (
                base64.urlsafe_b64encode(hashlib.sha256(member_payload).digest())
                .decode("ascii")
                .rstrip("=")
            )
            record_rows.append(f"{name},sha256={encoded},{len(member_payload)}\n")
        record_name = "click-8.3.1.dist-info/RECORD"
        record_rows.append(f"{record_name},,\n")
        members[record_name] = "".join(record_rows).encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, member_payload in members.items():
                archive.writestr(name, member_payload)
        payload = buffer.getvalue()
    redistribution_evidence = ["wheel-license:LICENSE.txt"]
    if external_license is not None:
        redistribution_evidence.extend(
            (
                "curated-license-expression:BSD-3-Clause",
                f"external-license:{external_license.source_id}",
            )
        )
    return (
        PythonWheelArtifact(
            name="click",
            version="8.3.1",
            filename="click-8.3.1-py3-none-any.whl",
            url="https://files.pythonhosted.org/click-8.3.1-py3-none-any.whl",
            sha256=_sha256(payload),
            size=len(payload),
            license_expression="BSD-3-Clause",
            license_members=(license_member,) if external_license is None else (),
            external_licenses=(external_license,)
            if external_license is not None
            else (),
            redistribution_evidence=tuple(redistribution_evidence),
        ),
        payload,
    )


def _acp_packages() -> tuple[tuple[AcpPackageArtifact, ...], dict[str, bytes]]:
    root_bytes = _npm_tarball(
        "@agentclientprotocol/claude-agent-acp",
        "0.59.0",
        "Apache-2.0",
        "package/LICENSE",
    )
    sdk_bytes = _npm_tarball(
        "@anthropic-ai/claude-agent-sdk-win32-x64",
        "0.3.207",
        "LicenseRef-Anthropic-Commercial",
        "package/LICENSE.md",
    )
    root_integrity = _sha512_sri(root_bytes)
    sdk_integrity = _sha512_sri(sdk_bytes)
    packages = (
        AcpPackageArtifact(
            name="@agentclientprotocol/claude-agent-acp",
            version="0.59.0",
            install_path="node_modules/@agentclientprotocol/claude-agent-acp",
            url="https://registry.npmjs.org/claude-agent-acp-0.59.0.tgz",
            integrity=root_integrity,
            sha256=_sha256(root_bytes),
            size=len(root_bytes),
            license_expression="Apache-2.0",
            license_members=("package/LICENSE",),
            redistribution_evidence=("tarball-license:LICENSE",),
            dependency_paths=("node_modules/@anthropic-ai/claude-agent-sdk-win32-x64",),
        ),
        AcpPackageArtifact(
            name="@anthropic-ai/claude-agent-sdk-win32-x64",
            version="0.3.207",
            install_path="node_modules/@anthropic-ai/claude-agent-sdk-win32-x64",
            url="https://registry.npmjs.org/claude-agent-sdk-win32-x64-0.3.207.tgz",
            integrity=sdk_integrity,
            sha256=_sha256(sdk_bytes),
            size=len(sdk_bytes),
            license_expression="LicenseRef-Anthropic-Commercial",
            license_members=("package/LICENSE.md",),
            redistribution_evidence=("tarball-license:LICENSE.md",),
        ),
    )
    return packages, {
        _sha256(root_bytes): root_bytes,
        _sha256(sdk_bytes): sdk_bytes,
    }


def _npm_tarball(
    name: str, version: str, license_expression: str, license_path: str
) -> bytes:
    identity = f"node_modules/{name}"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, payload in (
            (
                "package/package.json",
                json.dumps(
                    {
                        "license": license_expression,
                        "name": name,
                        "version": version,
                    }
                ).encode(),
            ),
            (license_path, _license_payload(identity, license_path)),
        ):
            member = tarfile.TarInfo(path)
            member.size = len(payload)
            member.mtime = 0
            archive.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


def _node_descriptor_fields() -> dict[str, object]:
    return {
        "kind": ComponentAssetKind.NODE_RUNTIME,
        "target": TargetTriple.WINDOWS_X86_64,
        "version": "22",
        "release": "22.17.0",
        "build": "node-v22.17.0",
        "url": "https://nodejs.org/dist/v22.17.0/node-v22.17.0-win-x64.zip",
        "sha256": "1" * 64,
        "size": 1,
        "archive_kind": ArchiveKind.ZIP,
        "archive_root": "node-v22.17.0-win-x64",
        "license_expression": "MIT",
        "license_members": ("node-v22.17.0-win-x64/LICENSE",),
        "redistribution_evidence": ("archive-license:LICENSE",),
    }


def _source_descriptors() -> tuple[tuple[SourceArtifactDescriptor, ...], str]:
    root_integrity = _sha512_sri(b"claude-agent-acp-root")
    return (
        tuple(
            sorted(
                (
                    SourceArtifactDescriptor(
                        kind=ComponentAssetKind.PYTHON_RUNTIME,
                        target=TargetTriple.WINDOWS_X86_64,
                        version="3.13",
                        release="3.13.5",
                        build="20250702",
                        url="https://example.invalid/python.tar.gz",
                        sha256="0" * 64,
                        size=1,
                        archive_kind=ArchiveKind.TAR_GZIP,
                        archive_root="python",
                        license_expression="PSF-2.0",
                        license_members=("python/LICENSE",),
                        redistribution_evidence=("python-license",),
                    ),
                    SourceArtifactDescriptor.model_validate(_node_descriptor_fields()),
                    SourceArtifactDescriptor(
                        kind=ComponentAssetKind.ACP_ADAPTER,
                        target=None,
                        version="0.59.0",
                        release="0.59.0",
                        build="npm",
                        url="https://example.invalid/claude-agent-acp.tgz",
                        sha256="2" * 64,
                        size=1,
                        archive_kind=ArchiveKind.TAR_GZIP,
                        archive_root="package",
                        license_expression="Apache-2.0",
                        license_members=("package/LICENSE",),
                        redistribution_evidence=("acp-license",),
                        package_lock_integrity=root_integrity,
                    ),
                    SourceArtifactDescriptor(
                        kind=ComponentAssetKind.A2A_DISTRIBUTION,
                        target=None,
                        version="0.1.0",
                        release="0.1.0",
                        build="wheel",
                        url="https://example.invalid/vaultspec_a2a-0.1.0.whl",
                        sha256="3" * 64,
                        size=1,
                        archive_kind=ArchiveKind.WHEEL,
                        archive_root=None,
                        license_expression="MIT",
                        license_members=(
                            "vaultspec_a2a-0.1.0.dist-info/licenses/LICENSE",
                        ),
                        redistribution_evidence=("wheel-license",),
                        source_commit="7df84b1de4455ed79895136ab085c821ce988c9a",
                    ),
                ),
                key=lambda source: tuple(ComponentAssetKind).index(source.kind),
            )
        ),
        root_integrity,
    )


@pytest.mark.parametrize(
    "path",
    (
        "../escape",
        "/rooted",
        "C:/rooted",
        "payload/NUL.txt",
        "payload/name. ",
        "payload/back\\slash",
    ),
)
def test_portable_archive_path_rejects_cross_platform_escape_forms(path: str) -> None:
    with pytest.raises(ValueError):
        validate_portable_archive_path(path)


def test_source_descriptor_keeps_exact_node_release_visible() -> None:
    descriptor = SourceArtifactDescriptor.model_validate(_node_descriptor_fields())

    assert descriptor.version == "22"
    assert descriptor.exact_release == "22.17.0+node-v22.17.0"

    invalid = {**_node_descriptor_fields(), "release": "22.23.1-musl"}
    with pytest.raises(ValidationError, match="exact minor and patch"):
        SourceArtifactDescriptor.model_validate(invalid)


def test_redistribution_metadata_cannot_self_assert_approval() -> None:
    fields = {**_node_descriptor_fields(), "redistribution_approved": True}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceArtifactDescriptor.model_validate(fields)


def test_acp_closure_requires_a_complete_canonical_sha512_sri() -> None:
    valid = {
        "target": TargetTriple.WINDOWS_X86_64,
        "lock_sha256": "8" * 64,
        "package_count": 111,
        "tarball_inventory_sha256": "1" * 64,
        "tarball_inventory_size": 128,
        "installed": _installed_descriptor(
            kind="acp", source_digest="1" * 64, lock_digest="8" * 64
        ),
        "root_package_integrity": _sha512_sri(b"root-package"),
        "target_sdk_package": "@anthropic-ai/claude-agent-sdk-win32-x64",
        "target_sdk_integrity": _sha512_sri(b"target-sdk-package"),
    }
    descriptor = AcpClosureDescriptor.model_validate(valid)
    assert descriptor.package_count == 111

    with pytest.raises(ValidationError, match="canonical base64"):
        AcpClosureDescriptor.model_validate(
            {**valid, "target_sdk_integrity": "sha512-not-a-complete-digest"}
        )


def test_capsule_descriptor_joins_targets_locks_and_acp_root_integrity() -> None:
    sources, root_integrity = _source_descriptors()
    python_closure = PythonClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="8" * 64,
        package_count=1,
        wheel_inventory_sha256="4" * 64,
        wheel_inventory_size=1,
        installed=_installed_descriptor(
            kind="python", source_digest="4" * 64, lock_digest="8" * 64
        ),
    )
    acp_closure = AcpClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="9" * 64,
        package_count=2,
        tarball_inventory_sha256="6" * 64,
        tarball_inventory_size=1,
        installed=_installed_descriptor(
            kind="acp", source_digest="6" * 64, lock_digest="9" * 64
        ),
        root_package_integrity=root_integrity,
        target_sdk_package="@anthropic-ai/claude-agent-sdk-win32-x64",
        target_sdk_integrity=_sha512_sri(b"target-sdk"),
    )
    valid = {
        "descriptor_version": "2",
        "target": TargetTriple.WINDOWS_X86_64,
        "source_date_epoch": 1_700_000_000,
        "sources": sources,
        "uv_lock": LockInputDescriptor(sha256="8" * 64, size=1),
        "package_lock": LockInputDescriptor(sha256="9" * 64, size=1),
        "python_closure": python_closure,
        "acp_closure": acp_closure,
    }

    assert CapsuleInputDescriptor.model_validate(valid).descriptor_version == "2"

    mismatched_python = PythonClosureDescriptor.model_validate(
        {
            **python_closure.model_dump(),
            "lock_sha256": "a" * 64,
            "installed": python_closure.installed.model_copy(
                update={"lock_sha256": "a" * 64}
            ),
        }
    )
    with pytest.raises(ValidationError, match="bind the declared uv lock"):
        CapsuleInputDescriptor.model_validate(
            {
                **valid,
                "python_closure": mismatched_python,
            }
        )
    with pytest.raises(ValidationError, match="root integrity"):
        CapsuleInputDescriptor.model_validate(
            {
                **valid,
                "acp_closure": acp_closure.model_copy(
                    update={"root_package_integrity": _sha512_sri(b"another-root")}
                ),
            }
        )

    with pytest.raises(ValidationError, match="in order"):
        CapsuleInputDescriptor.model_validate(
            {**valid, "sources": tuple(reversed(sources))}
        )


def test_a2a_distribution_binds_dashboard_commit_provenance() -> None:
    sources, _ = _source_descriptors()
    a2a = next(
        source
        for source in sources
        if source.kind is ComponentAssetKind.A2A_DISTRIBUTION
    )
    fields = a2a.model_dump(mode="python")
    fields.pop("source_commit")

    with pytest.raises(ValidationError, match="bind one source commit"):
        SourceArtifactDescriptor.model_validate(fields)


def test_root_a2a_wheel_has_a_retained_byte_handoff(tmp_path: Path) -> None:
    payload = b"exact root wheel bytes"
    sources, _ = _source_descriptors()
    descriptor = next(
        source
        for source in sources
        if source.kind is ComponentAssetKind.A2A_DISTRIBUTION
    ).model_copy(update={"sha256": _sha256(payload), "size": len(payload)})
    path = tmp_path / descriptor.sha256
    path.write_bytes(payload)
    artifact = VerifiedArtifact(descriptor=descriptor, path=path)

    with open_verified_a2a_wheel(artifact) as source:
        path.write_bytes(b"replacement root bytes")
        assert source.read() == payload
        retained_view = source
    with pytest.raises(ValueError, match="no longer active"):
        retained_view.read(1)


def test_python_inventory_rejects_cross_target_wheel_and_noncanonical_version() -> None:
    payload = b"mac-wheel"
    wheel = PythonWheelArtifact(
        name="cryptography",
        version="49.0.0",
        filename="cryptography-49.0.0-cp313-abi3-macosx_10_9_x86_64.whl",
        url="https://files.pythonhosted.org/cryptography-macos.whl",
        sha256=_sha256(payload),
        size=len(payload),
        license_expression="Apache-2.0 OR BSD-3-Clause",
        license_members=("cryptography-49.0.0.dist-info/LICENSE",),
        redistribution_evidence=("wheel-license",),
    )

    with pytest.raises(ValidationError, match="incompatible"):
        PythonClosureInventory(
            inventory_version="vaultspec-python-wheelhouse-v1",
            target=TargetTriple.WINDOWS_X86_64,
            lock_sha256="8" * 64,
            roots=("cryptography",),
            packages=(wheel,),
        )
    with pytest.raises(ValidationError, match="canonical spelling"):
        canonical, _ = _python_wheel(b"wheel")
        PythonWheelArtifact.model_validate(
            {**canonical.model_dump(), "version": "8.3.1+LOCAL"}
        )


def test_license_members_reject_nfc_equivalent_paths() -> None:
    canonical, _ = _python_wheel(b"wheel")
    with pytest.raises(ValidationError, match="collide portably"):
        PythonWheelArtifact.model_validate(
            {
                **canonical.model_dump(),
                "license_members": ("licenses/LICENSE-é", "licenses/LICENSE-e\u0301"),
            }
        )


def test_lock_verification_reads_exact_bytes_and_detects_mutation(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "uv.lock"
    payload = b"version = 1\n"
    lock.write_bytes(payload)
    descriptor = LockInputDescriptor(sha256=_sha256(payload), size=len(payload))

    assert (
        verify_lock_input(lock, descriptor=descriptor, label="uv lock")
        == lock.absolute()
    )

    lock.write_bytes(payload + b"changed = true\n")
    with pytest.raises(ArtifactInputError, match="size does not match"):
        verify_lock_input(lock, descriptor=descriptor, label="uv lock")


def test_descriptor_digest_is_checked_before_toml_is_parsed(tmp_path: Path) -> None:
    descriptor = tmp_path / "descriptor.toml"
    descriptor.write_bytes(b"not valid toml = [")

    with pytest.raises(ArtifactInputError, match="digest does not match"):
        load_capsule_input_descriptor(descriptor, expected_sha256="0" * 64)


def test_acp_tarball_inventory_is_a_separate_content_addressed_input(
    tmp_path: Path,
) -> None:
    packages, package_bytes = _acp_packages()
    inventory = AcpClosureInventory(
        inventory_version="vaultspec-acp-tarballs-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="8" * 64,
        packages=packages,
    )
    payload = canonical_closure_inventory_bytes(inventory)
    digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    inventory_path = cache / digest
    inventory_path.write_bytes(payload)
    for package_digest, package_payload in package_bytes.items():
        (cache / package_digest).write_bytes(package_payload)
    descriptor = AcpClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="8" * 64,
        package_count=2,
        tarball_inventory_sha256=digest,
        tarball_inventory_size=len(payload),
        installed=_cache_installed_descriptor(
            cache,
            kind="acp",
            source_digest=digest,
            lock_digest="8" * 64,
            packages=packages,
        ),
        root_package_integrity=packages[0].integrity,
        target_sdk_package="@anthropic-ai/claude-agent-sdk-win32-x64",
        target_sdk_integrity=packages[1].integrity,
    )

    loaded = load_acp_closure_inventory(descriptor, input_dir=cache)
    assert loaded.path == inventory_path
    assert [
        artifact.descriptor.name
        for artifact in verify_acp_tarballs(loaded, input_dir=cache)
    ] == [package.name for package in packages]

    inventory_path.write_bytes(payload + b" ")
    with pytest.raises(ArtifactInputError, match="size does not match"):
        load_acp_closure_inventory(descriptor, input_dir=cache)


def test_python_wheel_inventory_binds_canonical_graph_and_every_cached_byte(
    tmp_path: Path,
) -> None:
    wheel, wheel_bytes = _python_wheel()
    inventory = PythonClosureInventory(
        inventory_version="vaultspec-python-wheelhouse-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="9" * 64,
        roots=("click",),
        packages=(wheel,),
    )
    payload = canonical_closure_inventory_bytes(inventory)
    inventory_digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / inventory_digest).write_bytes(payload)
    wheel_path = cache / wheel.sha256
    wheel_path.write_bytes(wheel_bytes)
    descriptor = PythonClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="9" * 64,
        package_count=1,
        wheel_inventory_sha256=inventory_digest,
        wheel_inventory_size=len(payload),
        installed=_cache_installed_descriptor(
            cache,
            kind="python",
            source_digest=inventory_digest,
            lock_digest="9" * 64,
            packages=(wheel,),
        ),
    )

    loaded = load_python_closure_inventory(descriptor, input_dir=cache)
    verified = verify_python_wheelhouse(loaded, input_dir=cache)
    assert loaded.value == inventory
    assert verified[0].descriptor == wheel
    assert verified[0].path == wheel_path

    wheel_path.write_bytes(wheel_bytes + b"changed")
    with pytest.raises(ArtifactInputError, match="size does not match"):
        verify_python_wheelhouse(loaded, input_dir=cache)


def test_wheelhouse_binds_external_license_bytes_for_deficient_wheel(
    tmp_path: Path,
) -> None:
    license_bytes = b"curated upstream click license\n"
    external = ExternalLicenseArtifact(
        source_id="external/click/LICENSE.txt",
        declared_member="LICENSE.txt",
        url="https://files.pythonhosted.org/click-8.3.1.tar.gz",
        sha256=_sha256(license_bytes),
        size=len(license_bytes),
    )
    wheel, wheel_bytes = _python_wheel(external_license=external)
    inventory = PythonClosureInventory(
        inventory_version="vaultspec-python-wheelhouse-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="9" * 64,
        roots=(wheel.name,),
        packages=(wheel,),
    )
    payload = canonical_closure_inventory_bytes(inventory)
    inventory_digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / inventory_digest).write_bytes(payload)
    (cache / wheel.sha256).write_bytes(wheel_bytes)
    external_path = cache / external.sha256
    external_path.write_bytes(license_bytes)
    descriptor = PythonClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="9" * 64,
        package_count=1,
        wheel_inventory_sha256=inventory_digest,
        wheel_inventory_size=len(payload),
        installed=_cache_installed_descriptor(
            cache,
            kind="python",
            source_digest=inventory_digest,
            lock_digest="9" * 64,
            packages=(wheel,),
        ),
    )
    loaded = load_python_closure_inventory(descriptor, input_dir=cache)

    verified = verify_python_wheelhouse(loaded, input_dir=cache)
    assert verified[0].license_members[0].path == external.source_id
    assert verified[0].license_members[0].sha256 == external.sha256

    with open_verified_external_license(
        verified[0], external.source_id, input_dir=cache
    ) as source:
        external_path.write_bytes(b"replacement license bytes"[: len(license_bytes)])
        assert source.read() == license_bytes
        retained_view = source
    with pytest.raises(ValueError, match="no longer active"):
        retained_view.read(1)

    external_path.write_bytes(license_bytes + b"changed")
    with pytest.raises(ArtifactInputError, match="size does not match"):
        verify_python_wheelhouse(loaded, input_dir=cache)


@pytest.mark.parametrize(
    "license_change",
    (
        {"license_expression": "Apache-2.0"},
        {"source_member": "click-8.3.1.dist-info/licenses/OTHER"},
        {"sha256": "f" * 64},
    ),
)
def test_wheelhouse_rejects_installed_license_source_drift(
    tmp_path: Path, license_change: dict[str, str]
) -> None:
    wheel, wheel_bytes = _python_wheel()
    inventory = PythonClosureInventory(
        inventory_version="vaultspec-python-wheelhouse-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="9" * 64,
        roots=(wheel.name,),
        packages=(wheel,),
    )
    payload = canonical_closure_inventory_bytes(inventory)
    inventory_digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / inventory_digest).write_bytes(payload)
    (cache / wheel.sha256).write_bytes(wheel_bytes)
    installed = _cache_installed_descriptor(
        cache,
        kind="python",
        source_digest=inventory_digest,
        lock_digest="9" * 64,
        packages=(wheel,),
    )
    descriptor = PythonClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="9" * 64,
        package_count=1,
        wheel_inventory_sha256=inventory_digest,
        wheel_inventory_size=len(payload),
        installed=_mutate_installed_license(cache, installed, **license_change),
    )
    loaded = load_python_closure_inventory(descriptor, input_dir=cache)

    with pytest.raises(ArtifactInputError, match="installed license"):
        verify_python_wheelhouse(loaded, input_dir=cache)


def test_python_inventory_rejects_noncanonical_bytes_before_use(tmp_path: Path) -> None:
    wheel, _ = _python_wheel()
    inventory = PythonClosureInventory(
        inventory_version="vaultspec-python-wheelhouse-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="9" * 64,
        roots=("click",),
        packages=(wheel,),
    )
    payload = json.dumps(inventory.model_dump(mode="json"), indent=2).encode("utf-8")
    digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / digest).write_bytes(payload)
    descriptor = PythonClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="9" * 64,
        package_count=1,
        wheel_inventory_sha256=digest,
        wheel_inventory_size=len(payload),
        installed=_installed_descriptor(
            kind="python", source_digest=digest, lock_digest="9" * 64
        ),
    )

    with pytest.raises(ArtifactInputError, match="not canonical JSON"):
        load_python_closure_inventory(descriptor, input_dir=cache)


def test_capsule_closure_loader_reconciles_the_exact_lock_snapshots(
    tmp_path: Path,
) -> None:
    uv_bytes = b"["
    package_lock_bytes = b"{}"
    wheel, _ = _python_wheel()
    packages, _ = _acp_packages()
    python_inventory = PythonClosureInventory(
        inventory_version="vaultspec-python-wheelhouse-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256=_sha256(uv_bytes),
        roots=(wheel.name,),
        packages=(wheel,),
    )
    acp_inventory = AcpClosureInventory(
        inventory_version="vaultspec-acp-tarballs-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256=_sha256(package_lock_bytes),
        packages=packages,
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    python_payload = canonical_closure_inventory_bytes(python_inventory)
    python_digest = _sha256(python_payload)
    (cache / python_digest).write_bytes(python_payload)
    acp_payload = canonical_closure_inventory_bytes(acp_inventory)
    acp_digest = _sha256(acp_payload)
    (cache / acp_digest).write_bytes(acp_payload)
    python_closure = PythonClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256=_sha256(uv_bytes),
        package_count=1,
        wheel_inventory_sha256=python_digest,
        wheel_inventory_size=len(python_payload),
        installed=_cache_installed_descriptor(
            cache,
            kind="python",
            source_digest=python_digest,
            lock_digest=_sha256(uv_bytes),
            packages=(wheel,),
        ),
    )
    acp_closure = AcpClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256=_sha256(package_lock_bytes),
        package_count=len(packages),
        tarball_inventory_sha256=acp_digest,
        tarball_inventory_size=len(acp_payload),
        installed=_cache_installed_descriptor(
            cache,
            kind="acp",
            source_digest=acp_digest,
            lock_digest=_sha256(package_lock_bytes),
            packages=packages,
        ),
        root_package_integrity=packages[0].integrity,
        target_sdk_package=packages[1].name,
        target_sdk_integrity=packages[1].integrity,
    )
    sources, _ = _source_descriptors()
    sources = tuple(
        SourceArtifactDescriptor.model_validate(
            {
                **source.model_dump(),
                "package_lock_integrity": packages[0].integrity,
            }
        )
        if source.kind is ComponentAssetKind.ACP_ADAPTER
        else source
        for source in sources
    )
    descriptor = CapsuleInputDescriptor(
        descriptor_version="2",
        target=TargetTriple.WINDOWS_X86_64,
        source_date_epoch=1_700_000_000,
        sources=sources,
        uv_lock=LockInputDescriptor(sha256=_sha256(uv_bytes), size=len(uv_bytes)),
        package_lock=LockInputDescriptor(
            sha256=_sha256(package_lock_bytes), size=len(package_lock_bytes)
        ),
        python_closure=python_closure,
        acp_closure=acp_closure,
    )
    uv_path = tmp_path / "uv.lock"
    uv_path.write_bytes(uv_bytes)
    package_path = tmp_path / "package-lock.json"
    package_path.write_bytes(package_lock_bytes)

    with pytest.raises(ArtifactInputError, match="not valid UTF-8 TOML"):
        load_capsule_closures(
            descriptor,
            input_dir=cache,
            uv_lock_path=uv_path,
            package_lock_path=package_path,
        )


def test_capsule_closure_loader_cannot_omit_package_archive_verification(
    tmp_path: Path,
) -> None:
    wheel, wheel_bytes = _python_wheel()
    packages, package_bytes = _acp_packages()
    uv_bytes = f'''version = 1
revision = 3
requires-python = ">=3.13"

[[package]]
name = "vaultspec-a2a"
version = "0.1.0"
source = {{ editable = "." }}
dependencies = [{{ name = "click" }}]

[[package]]
name = "click"
version = "{wheel.version}"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [
  {{ url = "{wheel.url}", hash = "sha256:{wheel.sha256}", size = {wheel.size} }},
]
'''.encode()
    package_lock_bytes = json.dumps(
        {
            "lockfileVersion": 3,
            "name": "vaultspec-a2a",
            "packages": {
                "": {
                    "dependencies": {packages[0].name: packages[0].version},
                    "name": "vaultspec-a2a",
                },
                packages[0].install_path: {
                    "dependencies": {packages[1].name: packages[1].version},
                    "engines": {"node": ">=22"},
                    "integrity": packages[0].integrity,
                    "resolved": packages[0].url,
                    "version": packages[0].version,
                },
                packages[1].install_path: {
                    "cpu": ["x64"],
                    "engines": {"node": ">=18"},
                    "integrity": packages[1].integrity,
                    "os": ["win32"],
                    "resolved": packages[1].url,
                    "version": packages[1].version,
                },
            },
            "requires": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    python_inventory = PythonClosureInventory(
        inventory_version="vaultspec-python-wheelhouse-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256=_sha256(uv_bytes),
        roots=(wheel.name,),
        packages=(wheel,),
    )
    acp_inventory = AcpClosureInventory(
        inventory_version="vaultspec-acp-tarballs-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256=_sha256(package_lock_bytes),
        packages=packages,
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    python_payload = canonical_closure_inventory_bytes(python_inventory)
    python_digest = _sha256(python_payload)
    (cache / python_digest).write_bytes(python_payload)
    acp_payload = canonical_closure_inventory_bytes(acp_inventory)
    acp_digest = _sha256(acp_payload)
    (cache / acp_digest).write_bytes(acp_payload)
    wheel_path = cache / wheel.sha256
    wheel_path.write_bytes(wheel_bytes)
    for digest, payload in package_bytes.items():
        (cache / digest).write_bytes(payload)
    python_closure = PythonClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256=_sha256(uv_bytes),
        package_count=1,
        wheel_inventory_sha256=python_digest,
        wheel_inventory_size=len(python_payload),
        installed=_cache_installed_descriptor(
            cache,
            kind="python",
            source_digest=python_digest,
            lock_digest=_sha256(uv_bytes),
            packages=(wheel,),
        ),
    )
    acp_closure = AcpClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256=_sha256(package_lock_bytes),
        package_count=len(packages),
        tarball_inventory_sha256=acp_digest,
        tarball_inventory_size=len(acp_payload),
        installed=_cache_installed_descriptor(
            cache,
            kind="acp",
            source_digest=acp_digest,
            lock_digest=_sha256(package_lock_bytes),
            packages=packages,
        ),
        root_package_integrity=packages[0].integrity,
        target_sdk_package=packages[1].name,
        target_sdk_integrity=packages[1].integrity,
    )
    sources, _ = _source_descriptors()
    sources = tuple(
        source.model_copy(update={"package_lock_integrity": packages[0].integrity})
        if source.kind is ComponentAssetKind.ACP_ADAPTER
        else source
        for source in sources
    )
    descriptor = CapsuleInputDescriptor(
        descriptor_version="2",
        target=TargetTriple.WINDOWS_X86_64,
        source_date_epoch=1_700_000_000,
        sources=sources,
        uv_lock=LockInputDescriptor(sha256=_sha256(uv_bytes), size=len(uv_bytes)),
        package_lock=LockInputDescriptor(
            sha256=_sha256(package_lock_bytes), size=len(package_lock_bytes)
        ),
        python_closure=python_closure,
        acp_closure=acp_closure,
    )
    uv_path = tmp_path / "uv.lock"
    uv_path.write_bytes(uv_bytes)
    package_path = tmp_path / "package-lock.json"
    package_path.write_bytes(package_lock_bytes)

    loaded = load_capsule_closures(
        descriptor,
        input_dir=cache,
        uv_lock_path=uv_path,
        package_lock_path=package_path,
    )
    assert loaded.python_packages[0].path == wheel_path
    assert len(loaded.acp_packages) == len(packages)
    with (
        loaded.open_python_package(wheel.name) as session,
        session.open_snapshot() as source,
    ):
        assert hashlib.sha256(source.read()).hexdigest() == wheel.sha256
    with (
        loaded.open_acp_package(packages[0].install_path) as session,
        session.open_snapshot() as source,
    ):
        assert hashlib.sha256(source.read()).hexdigest() == packages[0].sha256

    wheel_path.unlink()
    with pytest.raises(ArtifactInputError, match="cannot read package archive"):
        load_capsule_closures(
            descriptor,
            input_dir=cache,
            uv_lock_path=uv_path,
            package_lock_path=package_path,
        )


@pytest.mark.parametrize("excluded", ("torch", "vaultspec-rag"))
def test_python_inventory_rejects_desktop_excluded_capabilities(excluded: str) -> None:
    excluded_wheel = PythonWheelArtifact(
        name=excluded,
        version="1.0",
        filename=f"{excluded.replace('-', '_')}-1.0-py3-none-any.whl",
        url=f"https://files.pythonhosted.org/{excluded}-1.0.whl",
        sha256="6" * 64,
        size=1,
        license_expression="LicenseRef-Test",
        license_members=("package.dist-info/LICENSE",),
        redistribution_evidence=("test-license-evidence",),
    )

    with pytest.raises(ValidationError, match="excluded capability"):
        PythonClosureInventory(
            inventory_version="vaultspec-python-wheelhouse-v1",
            target=TargetTriple.WINDOWS_X86_64,
            lock_sha256="9" * 64,
            roots=("torch",),
            packages=(excluded_wheel,),
        )


def test_acp_inventory_rejects_a_second_target_sdk(tmp_path: Path) -> None:
    packages, _ = _acp_packages()
    other_bytes = b"other-target-sdk"
    other = AcpPackageArtifact(
        name="@anthropic-ai/claude-agent-sdk-linux-x64",
        version="0.3.207",
        install_path="node_modules/@anthropic-ai/claude-agent-sdk-linux-x64",
        url="https://registry.npmjs.org/claude-agent-sdk-linux-x64-0.3.207.tgz",
        integrity=_sha512_sri(other_bytes),
        sha256=_sha256(other_bytes),
        size=len(other_bytes),
        license_expression="LicenseRef-Anthropic-Commercial",
        license_members=("package/LICENSE.md",),
        redistribution_evidence=("tarball-license:LICENSE.md",),
    )
    root = AcpPackageArtifact.model_validate(
        {
            **packages[0].model_dump(),
            "dependency_paths": tuple(
                sorted((*packages[0].dependency_paths, other.install_path))
            ),
        }
    )
    inventory = AcpClosureInventory(
        inventory_version="vaultspec-acp-tarballs-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="8" * 64,
        packages=tuple(
            sorted((root, packages[1], other), key=lambda package: package.install_path)
        ),
    )
    payload = canonical_closure_inventory_bytes(inventory)
    digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / digest).write_bytes(payload)
    descriptor = AcpClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="8" * 64,
        package_count=3,
        tarball_inventory_sha256=digest,
        tarball_inventory_size=len(payload),
        installed=_installed_descriptor(
            kind="acp", source_digest=digest, lock_digest="8" * 64
        ),
        root_package_integrity=packages[0].integrity,
        target_sdk_package=packages[1].name,
        target_sdk_integrity=packages[1].integrity,
    )

    with pytest.raises(ArtifactInputError, match="another target SDK"):
        load_acp_closure_inventory(descriptor, input_dir=cache)


def test_acp_tarball_bytes_must_match_both_sha256_and_lock_sri(tmp_path: Path) -> None:
    packages, package_bytes = _acp_packages()
    root = packages[0]
    contradictory = AcpPackageArtifact(
        **{
            **root.model_dump(),
            "integrity": _sha512_sri(b"different-root-bytes"),
        }
    )
    inventory = AcpClosureInventory(
        inventory_version="vaultspec-acp-tarballs-v1",
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="8" * 64,
        packages=(contradictory, packages[1]),
    )
    payload = canonical_closure_inventory_bytes(inventory)
    digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / digest).write_bytes(payload)
    for package_digest, package_payload in package_bytes.items():
        (cache / package_digest).write_bytes(package_payload)
    descriptor = AcpClosureDescriptor(
        target=TargetTriple.WINDOWS_X86_64,
        lock_sha256="8" * 64,
        package_count=2,
        tarball_inventory_sha256=digest,
        tarball_inventory_size=len(payload),
        installed=_cache_installed_descriptor(
            cache,
            kind="acp",
            source_digest=digest,
            lock_digest="8" * 64,
            packages=(contradictory, packages[1]),
        ),
        root_package_integrity=contradictory.integrity,
        target_sdk_package=packages[1].name,
        target_sdk_integrity=packages[1].integrity,
    )
    loaded = load_acp_closure_inventory(descriptor, input_dir=cache)

    with pytest.raises(ArtifactInputError, match="integrity does not match"):
        verify_acp_tarballs(loaded, input_dir=cache)
