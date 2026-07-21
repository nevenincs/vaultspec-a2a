"""Real-input builders for capsule materializer tests.

Unlike ``_capsule_inputs.open_real_capsule_session`` (whose installed
inventories are hand-authored fixture data with fabricated provenance, correct
for exercising the plan derivation but not the materializer), this module
builds the Python and ACP installed inventories through the real production
builders (``build_python_closure_installed_inventory`` /
``build_acp_closure_installed_inventory``), so every ``source_sha256`` /
``source_member`` pair names a real, RECORD-verified archive member the
materializer can actually resolve and stream. It also verifies the real root
A2A wheel (built via ``uv build --wheel``) as a proper
:class:`~vaultspec_a2a.desktop.closure_inventory.PythonWheelArtifact` so its
own members are part of the materialized Python closure, in addition to its
existing role as the digest-only ``A2A_DISTRIBUTION`` source manifest
emission reads directly.
"""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING, Final, Literal

from tomlkit import dumps as toml_dumps

from vaultspec_a2a.desktop.artifacts import (
    AcpClosureDescriptor,
    AcpClosureInventory,
    ArchiveKind,
    CapsuleInputDescriptor,
    LockInputDescriptor,
    PythonClosureDescriptor,
    PythonClosureInventory,
    PythonWheelArtifact,
    SourceArtifactDescriptor,
    build_acp_closure_installed_inventory,
    build_python_closure_installed_inventory,
    canonical_closure_inventory_bytes,
    open_verified_acp_package_archive,
    open_verified_capsule_inputs,
    open_verified_python_wheel_archive,
)
from vaultspec_a2a.desktop.contract import ComponentAssetKind, TargetTriple
from vaultspec_a2a.desktop.installed_inventory import (
    InstalledFileRecord,
    InstalledLicenseRecord,
    license_component_token,
)
from vaultspec_a2a.desktop.package_archives import verified_archive_member_evidence
from vaultspec_a2a.desktop.tests._capsule_inputs import (
    _build_real_a2a_wheel,
    _npm_tarball,
    _python_wheel,
    _sha256,
    _sha512_sri,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from vaultspec_a2a.desktop.artifacts import (
        AcpPackageArtifact,
        VerifiedCapsuleInputSession,
        VerifiedPackageArchiveSession,
    )

__all__ = ["open_real_materializer_session"]

#: Mirrors ``vaultspec_a2a.desktop.artifacts._TARGET_SDK_PACKAGES`` (the ACP
#: closure's target-native SDK package identity per target); duplicated here
#: as plain literal data rather than reaching into that module's private name.
_TARGET_SDK_PACKAGES: Final = {
    TargetTriple.MACOS_ARM64: "@anthropic-ai/claude-agent-sdk-darwin-arm64",
    TargetTriple.MACOS_X86_64: "@anthropic-ai/claude-agent-sdk-darwin-x64",
    TargetTriple.LINUX_ARM64: "@anthropic-ai/claude-agent-sdk-linux-arm64",
    TargetTriple.LINUX_X86_64: "@anthropic-ai/claude-agent-sdk-linux-x64",
    TargetTriple.WINDOWS_X86_64: "@anthropic-ai/claude-agent-sdk-win32-x64",
}


def _target_sdk_package_name(target: TargetTriple) -> str:
    return _TARGET_SDK_PACKAGES[target]


def _acp_packages(
    target: TargetTriple,
) -> tuple[tuple[AcpPackageArtifact, ...], dict[str, bytes]]:
    from vaultspec_a2a.desktop.artifacts import AcpPackageArtifact as _Artifact

    sdk_name = _target_sdk_package_name(target)
    root_bytes = _npm_tarball(
        "@agentclientprotocol/claude-agent-acp",
        "0.59.0",
        "Apache-2.0",
        "package/LICENSE",
    )
    sdk_bytes = _npm_tarball(
        sdk_name, "0.3.207", "LicenseRef-Anthropic-Commercial", "package/LICENSE.md"
    )
    packages = (
        _Artifact(
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
            dependency_paths=(f"node_modules/{sdk_name}",),
        ),
        _Artifact(
            name=sdk_name,
            version="0.3.207",
            install_path=f"node_modules/{sdk_name}",
            url=f"https://registry.npmjs.org/{sdk_name}-0.3.207.tgz",
            integrity=_sha512_sri(sdk_bytes),
            sha256=_sha256(sdk_bytes),
            size=len(sdk_bytes),
            license_expression="LicenseRef-Anthropic-Commercial",
            license_members=("package/LICENSE.md",),
            redistribution_evidence=("tarball-license:LICENSE.md",),
        ),
    )
    return packages, {_sha256(root_bytes): root_bytes, _sha256(sdk_bytes): sdk_bytes}


def _source_descriptors(
    target: TargetTriple, root_integrity: str
) -> tuple[SourceArtifactDescriptor, ...]:
    return tuple(
        sorted(
            (
                SourceArtifactDescriptor(
                    kind=ComponentAssetKind.PYTHON_RUNTIME,
                    target=target,
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
                    target=target,
                    version="22",
                    release="22.17.0",
                    build="node-v22.17.0",
                    url="https://nodejs.org/dist/v22.17.0/node-v22.17.0.zip",
                    sha256="1" * 64,
                    size=1,
                    archive_kind=ArchiveKind.ZIP,
                    archive_root="node-v22.17.0",
                    license_expression="MIT",
                    license_members=("node-v22.17.0/LICENSE",),
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


def _real_a2a_wheel_descriptor(wheel_bytes: bytes) -> PythonWheelArtifact:
    """Build a full ``PythonWheelArtifact`` from the real, already-built wheel.

    Every field is read from the wheel's own bytes (Metadata-Version 2.4,
    ``License-Expression: MIT``, ``License-File: LICENSE`` placed under
    ``<dist-info>/licenses/``) rather than fabricated, so the wheel passes the
    real ``package_archives`` RECORD/METADATA verification unmodified.
    """
    return PythonWheelArtifact(
        name="vaultspec-a2a",
        version="0.1.0",
        filename="vaultspec_a2a-0.1.0-py3-none-any.whl",
        url="https://example.invalid/vaultspec_a2a-0.1.0-py3-none-any.whl",
        sha256=_sha256(wheel_bytes),
        size=len(wheel_bytes),
        license_expression="MIT",
        license_members=("vaultspec_a2a-0.1.0.dist-info/licenses/LICENSE",),
        redistribution_evidence=("wheel-license:LICENSE",),
    )


def _license_records(
    sessions: tuple[VerifiedPackageArchiveSession, ...],
    *,
    closure_kind: Literal["python", "acp"],
) -> tuple[tuple[InstalledLicenseRecord, ...], tuple[InstalledFileRecord, ...]]:
    """Derive real license placements from already-open, already-verified sessions.

    Only ``license_members`` (in-archive license bytes) are placed; none of
    this fixture's packages declare ``external_licenses``.
    """
    licenses: list[InstalledLicenseRecord] = []
    files: list[InstalledFileRecord] = []
    for index, session in enumerate(sessions):
        descriptor = session.archive.descriptor
        identity = (
            descriptor.name
            if isinstance(descriptor, PythonWheelArtifact)
            else descriptor.install_path
        )
        evidence_by_path = {
            evidence.path: evidence
            for evidence in verified_archive_member_evidence(session)
        }
        for member_index, member in enumerate(descriptor.license_members):
            evidence = evidence_by_path[member]
            relative_path = f"licenses/{index:04d}/{member_index:04d}/LICENSE"
            files.append(
                InstalledFileRecord(
                    relative_path=relative_path,
                    mode="0644",
                    size=evidence.size,
                    sha256=evidence.sha256,
                    source_sha256=descriptor.sha256,
                    source_member=member,
                )
            )
            licenses.append(
                InstalledLicenseRecord(
                    package=identity,
                    component=license_component_token(closure_kind, identity),
                    license_expression=descriptor.license_expression,
                    source_member=member,
                    relative_path=relative_path,
                    sha256=evidence.sha256,
                )
            )
    return tuple(licenses), tuple(files)


@contextmanager
def open_real_materializer_session(
    tmp_path: Path, *, target: TargetTriple
) -> Iterator[VerifiedCapsuleInputSession]:
    """Open a real verified capsule session with production-provenance closures.

    The Python closure places both the retained "click" dependency wheel and
    the real root A2A wheel's own members; the ACP closure places both the
    root and target-native SDK npm packages. Every ``InstalledFileRecord`` in
    the resulting ``python_installed``/``acp_installed`` inventories names a
    real ``source_sha256``/``source_member`` pair a materializer can stream.
    """
    wheel, wheel_bytes = _python_wheel()
    packages, package_bytes = _acp_packages(target)
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
                    "os": ["linux", "win32", "darwin"],
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
        target=target,
        lock_sha256=_sha256(uv_bytes),
        roots=(wheel.name,),
        packages=(wheel,),
    )
    acp_inventory = AcpClosureInventory(
        inventory_version="vaultspec-acp-tarballs-v1",
        target=target,
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

    a2a_wheel_bytes = _build_real_a2a_wheel(tmp_path / "distribution")
    a2a_descriptor = _real_a2a_wheel_descriptor(a2a_wheel_bytes)
    (cache / a2a_descriptor.sha256).write_bytes(a2a_wheel_bytes)

    with ExitStack() as stack:
        click_session = stack.enter_context(
            open_verified_python_wheel_archive(
                cache / wheel.sha256, wheel, target=target
            )
        )
        a2a_session = stack.enter_context(
            open_verified_python_wheel_archive(
                cache / a2a_descriptor.sha256, a2a_descriptor, target=target
            )
        )
        root_acp_session = stack.enter_context(
            open_verified_acp_package_archive(cache / packages[0].sha256, packages[0])
        )
        sdk_session = stack.enter_context(
            open_verified_acp_package_archive(cache / packages[1].sha256, packages[1])
        )

        python_licenses, python_license_files = _license_records(
            (click_session,), closure_kind="python"
        )
        python_descriptor, _python_installed = build_python_closure_installed_inventory(
            target=target,
            source_inventory_sha256=python_digest,
            lock_sha256=_sha256(uv_bytes),
            wheel_sessions=(click_session, a2a_session),
            console_scripts=(
                ("vaultspec-a2a", "vaultspec_a2a.cli.main:main"),
                ("vaultspec-a2a-mcp", "vaultspec_a2a.protocols.mcp.__main__:main"),
            ),
            licenses=python_licenses,
            license_files=python_license_files,
            input_dir=cache,
        )
        acp_licenses, acp_license_files = _license_records(
            (root_acp_session, sdk_session), closure_kind="acp"
        )
        acp_descriptor, _acp_installed = build_acp_closure_installed_inventory(
            target=target,
            source_inventory_sha256=acp_digest,
            lock_sha256=_sha256(package_lock_bytes),
            tarball_sessions=(root_acp_session, sdk_session),
            # No dedicated bin script member exists in this fixture's npm
            # tarballs; mark the root package's real placed package.json as
            # the entrypoint purely to satisfy the model's non-empty
            # entrypoints bound with a real, resolvable placement.
            bin_entrypoints=(f"{packages[0].install_path}/package.json",),
            licenses=acp_licenses,
            license_files=acp_license_files,
            input_dir=cache,
        )

        python_closure = PythonClosureDescriptor(
            target=target,
            lock_sha256=_sha256(uv_bytes),
            package_count=1,
            wheel_inventory_sha256=python_digest,
            wheel_inventory_size=len(python_payload),
            installed=python_descriptor,
        )
        acp_closure = AcpClosureDescriptor(
            target=target,
            lock_sha256=_sha256(package_lock_bytes),
            package_count=len(packages),
            tarball_inventory_sha256=acp_digest,
            tarball_inventory_size=len(acp_payload),
            installed=acp_descriptor,
            root_package_integrity=packages[0].integrity,
            target_sdk_package=packages[1].name,
            target_sdk_integrity=packages[1].integrity,
        )

    source_payloads = {
        ComponentAssetKind.A2A_DISTRIBUTION: a2a_wheel_bytes,
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
        for source in _source_descriptors(target, packages[0].integrity)
    )
    for source in sources:
        if not (cache / source.sha256).exists():
            (cache / source.sha256).write_bytes(source_payloads[source.kind])

    descriptor = CapsuleInputDescriptor(
        descriptor_version="2",
        target=target,
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
