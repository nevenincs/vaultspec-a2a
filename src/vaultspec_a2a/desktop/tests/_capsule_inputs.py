"""Real-input builders for whole-capsule assembly tests.

These helpers assemble a genuine content-addressed input cache, real dependency
locks that reconcile against the closures, real package archives, and the real
``uv``-built ``vaultspec-a2a`` wheel, then open a live
:class:`vaultspec_a2a.desktop.artifacts.VerifiedCapsuleInputSession`. No test
double, monkeypatch, or fabricated byte identity is used: every digest is
computed from the exact bytes written to disk.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from tomlkit import dumps as toml_dumps

from vaultspec_a2a.desktop.artifacts import (
    AcpClosureDescriptor,
    AcpClosureInventory,
    AcpPackageArtifact,
    ArchiveKind,
    CapsuleInputDescriptor,
    LockInputDescriptor,
    PythonClosureDescriptor,
    PythonClosureInventory,
    PythonWheelArtifact,
    SourceArtifactDescriptor,
    canonical_closure_inventory_bytes,
    open_verified_capsule_inputs,
)
from vaultspec_a2a.desktop.contract import ComponentAssetKind, TargetTriple
from vaultspec_a2a.desktop.installed_inventory import (
    InstalledClosureDescriptor,
    InstalledFileRecord,
    InstalledLicenseRecord,
    build_installed_closure_inventory,
    canonical_installed_inventory_bytes,
    license_component_token,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from vaultspec_a2a.desktop.artifacts import VerifiedCapsuleInputSession

_TARGET = TargetTriple.WINDOWS_X86_64


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha512_sri(payload: bytes) -> str:
    return (
        f"sha512-{base64.b64encode(hashlib.sha512(payload).digest()).decode('ascii')}"
    )


def _license_payload(identity: str, source_member: str) -> bytes:
    return f"license:{identity}:{source_member}\n".encode()


def _python_wheel() -> tuple[PythonWheelArtifact, bytes]:
    license_member = "click-8.3.1.dist-info/licenses/LICENSE.txt"
    metadata = (
        b"Metadata-Version: 2.4\nName: click\nVersion: 8.3.1\n"
        b"License-Expression: BSD-3-Clause\nLicense-File: LICENSE.txt\n"
    )
    members = {
        "click-8.3.1.dist-info/METADATA": metadata,
        "click-8.3.1.dist-info/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        license_member: _license_payload("click", license_member),
    }
    record_rows = []
    for name, payload in members.items():
        encoded = (
            base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            .decode("ascii")
            .rstrip("=")
        )
        record_rows.append(f"{name},sha256={encoded},{len(payload)}\n")
    record_name = "click-8.3.1.dist-info/RECORD"
    record_rows.append(f"{record_name},,\n")
    members[record_name] = "".join(record_rows).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    payload = buffer.getvalue()
    return (
        PythonWheelArtifact(
            name="click",
            version="8.3.1",
            filename="click-8.3.1-py3-none-any.whl",
            url="https://files.pythonhosted.org/click-8.3.1-py3-none-any.whl",
            sha256=_sha256(payload),
            size=len(payload),
            license_expression="BSD-3-Clause",
            license_members=(license_member,),
            redistribution_evidence=("wheel-license:LICENSE.txt",),
        ),
        payload,
    )


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
                    {"license": license_expression, "name": name, "version": version}
                ).encode(),
            ),
            (license_path, _license_payload(identity, license_path)),
        ):
            member = tarfile.TarInfo(path)
            member.size = len(payload)
            member.mtime = 0
            archive.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


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
    packages = (
        AcpPackageArtifact(
            name="@agentclientprotocol/claude-agent-acp",
            version="0.59.0",
            install_path="node_modules/@agentclientprotocol/claude-agent-acp",
            url="https://registry.npmjs.org/claude-agent-acp-0.59.0.tgz",
            integrity=_sha512_sri(root_bytes),
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
            integrity=_sha512_sri(sdk_bytes),
            sha256=_sha256(sdk_bytes),
            size=len(sdk_bytes),
            license_expression="LicenseRef-Anthropic-Commercial",
            license_members=("package/LICENSE.md",),
            redistribution_evidence=("tarball-license:LICENSE.md",),
        ),
    )
    return packages, {_sha256(root_bytes): root_bytes, _sha256(sdk_bytes): sdk_bytes}


def _cache_installed_descriptor(
    cache: Path,
    *,
    kind: Literal["python", "acp"],
    source_digest: str,
    lock_digest: str,
    packages: tuple[PythonWheelArtifact | AcpPackageArtifact, ...],
) -> InstalledClosureDescriptor:
    entry_bytes = b"#!/bin/sh\nexec runtime\n"
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
        identity = (
            package.name
            if isinstance(package, PythonWheelArtifact)
            else package.install_path
        )
        for member_index, source_member in enumerate(package.license_members):
            payload = _license_payload(identity, source_member)
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
        target=_TARGET,
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


def _source_descriptors(
    root_integrity: str,
) -> tuple[SourceArtifactDescriptor, ...]:
    return tuple(
        sorted(
            (
                SourceArtifactDescriptor(
                    kind=ComponentAssetKind.PYTHON_RUNTIME,
                    target=_TARGET,
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
                SourceArtifactDescriptor(
                    kind=ComponentAssetKind.NODE_RUNTIME,
                    target=_TARGET,
                    version="22",
                    release="22.17.0",
                    build="node-v22.17.0",
                    url="https://nodejs.org/dist/v22.17.0/node-v22.17.0-win-x64.zip",
                    sha256="1" * 64,
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
                    license_members=("vaultspec_a2a-0.1.0.dist-info/licenses/LICENSE",),
                    redistribution_evidence=("wheel-license",),
                    source_commit="7df84b1de4455ed79895136ab085c821ce988c9a",
                ),
            ),
            key=lambda source: tuple(ComponentAssetKind).index(source.kind),
        )
    )


def _build_real_a2a_wheel(destination: Path) -> bytes:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to build the production wheel")
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(destination), "--no-sources"],
        cwd=Path(__file__).resolve().parents[4],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)
    wheels = tuple(destination.glob("vaultspec_a2a-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one built wheel, found {wheels}")
    return wheels[0].read_bytes()


@contextmanager
def open_real_capsule_session(tmp_path: Path) -> Iterator[VerifiedCapsuleInputSession]:
    """Open a real verified capsule input session backed by on-disk fixtures."""
    wheel, wheel_bytes = _python_wheel()
    packages, package_bytes = _acp_packages()
    uv_bytes = f"""version = 1
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
""".encode()
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
        target=_TARGET,
        lock_sha256=_sha256(uv_bytes),
        roots=(wheel.name,),
        packages=(wheel,),
    )
    acp_inventory = AcpClosureInventory(
        inventory_version="vaultspec-acp-tarballs-v1",
        target=_TARGET,
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
    (cache / wheel.sha256).write_bytes(wheel_bytes)
    for digest, payload in package_bytes.items():
        (cache / digest).write_bytes(payload)

    python_closure = PythonClosureDescriptor(
        target=_TARGET,
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
        target=_TARGET,
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

    distribution_bytes = _build_real_a2a_wheel(tmp_path / "distribution")
    source_payloads = {
        ComponentAssetKind.A2A_DISTRIBUTION: distribution_bytes,
        ComponentAssetKind.PYTHON_RUNTIME: b"retained:python-runtime\n",
        ComponentAssetKind.NODE_RUNTIME: b"retained:node-runtime\n",
        ComponentAssetKind.ACP_ADAPTER: b"retained:acp-adapter\n",
    }
    sources = tuple(
        source.model_copy(
            update={
                "sha256": _sha256(source_payloads[source.kind]),
                "size": len(source_payloads[source.kind]),
                **(
                    {"package_lock_integrity": packages[0].integrity}
                    if source.kind is ComponentAssetKind.ACP_ADAPTER
                    else {}
                ),
            }
        )
        for source in _source_descriptors(packages[0].integrity)
    )
    for source in sources:
        (cache / source.sha256).write_bytes(source_payloads[source.kind])

    descriptor = CapsuleInputDescriptor(
        descriptor_version="2",
        target=_TARGET,
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
    descriptor_payload = toml_dumps(
        descriptor.model_dump(mode="json", exclude_none=True)
    ).encode()
    descriptor_path = tmp_path / "capsule-inputs.toml"
    descriptor_path.write_bytes(descriptor_payload)

    with open_verified_capsule_inputs(
        descriptor_path,
        expected_descriptor_sha256=_sha256(descriptor_payload),
        input_dir=cache,
        uv_lock_path=uv_path,
        package_lock_path=package_path,
    ) as session:
        yield session
