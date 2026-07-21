"""Installed-inventory building and capsule input descriptor authoring.

Pass two of the preparation authority.  It opens verified archive sessions for
a target's derived closure, drives the production installed-inventory builders
(so every installed file carries provable source provenance and every license
is placed with its evidence), and - in a later increment - authors the
digest-pinned capsule input descriptor the build stage consumes read-only.

Selection, acquisition, license derivation, and closure-inventory emission live
in :mod:`vaultspec_a2a.desktop.capsule_input_authoring` and
:mod:`vaultspec_a2a.desktop.capsule_license`; this module consumes their
outputs.  The A2A distribution wheel is a first-class member of the Python
closure here, verified in full like every other wheel.
"""

from __future__ import annotations

import hashlib
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from .artifacts import (
    ArtifactInputError,
    build_acp_closure_installed_inventory,
    build_python_closure_installed_inventory,
)
from .capsule_input_authoring import CapsuleInputAuthoringError
from .installed_inventory import (
    InstalledFileRecord,
    InstalledLicenseRecord,
    license_component_token,
)
from .package_archives import (
    open_verified_acp_package_archive,
    open_verified_python_wheel_archive,
)

if TYPE_CHECKING:
    from .artifacts import CapsuleInputDescriptor
    from .closure_inventory import (
        AcpPackageArtifact,
        ExternalLicenseArtifact,
        PythonWheelArtifact,
    )
    from .contract import TargetTriple
    from .installed_inventory import (
        ClosureKind,
        InstalledClosureDescriptor,
        InstalledClosureInventory,
    )
    from .package_archives import LicenseMemberEvidence

__all__ = [
    "AuthoredDescriptor",
    "author_capsule_input_descriptor",
    "build_acp_installed_inventory",
    "build_python_installed_inventory",
]

_MAX_DESCRIPTOR_BYTES: Final = 1 << 20

# The two contract console-script entrypoints, backed by module files that live
# in the A2A distribution wheel; the layout promotes them to 0755.
_CONSOLE_SCRIPTS: Final[tuple[tuple[str, str], ...]] = (
    ("vaultspec-a2a", "vaultspec_a2a.cli.main:main"),
    ("vaultspec-a2a-mcp", "vaultspec_a2a.protocols.mcp.__main__:main"),
)
_CONSOLE_SCRIPT_MODULES: Final = (
    "vaultspec_a2a/cli/main.py",
    "vaultspec_a2a/protocols/mcp/__main__.py",
)
_LICENSE_SUBTREE: Final = ".capsule-licenses"


def _license_placement(
    *,
    closure_kind: ClosureKind,
    package: str,
    license_expression: str,
    relative_member: str,
    size: int,
    sha256: str,
    source_sha256: str,
    source_member: str,
) -> tuple[InstalledFileRecord, InstalledLicenseRecord]:
    """Build the reserved-subtree placement and compliance join for one license."""
    relative_path = f"{_LICENSE_SUBTREE}/{package}/{relative_member}"
    try:
        placed = InstalledFileRecord(
            relative_path=relative_path,
            mode="0644",
            size=size,
            sha256=sha256,
            source_sha256=source_sha256,
            source_member=source_member,
        )
        record = InstalledLicenseRecord(
            package=package,
            component=license_component_token(closure_kind, package),
            license_expression=license_expression,
            source_member=source_member,
            relative_path=relative_path,
            sha256=sha256,
        )
    except (ValueError, TypeError) as error:
        raise CapsuleInputAuthoringError(
            f"license placement for {package} is invalid: {error}"
        ) from None
    return placed, record


def _member_evidence_by_path(
    members: tuple[LicenseMemberEvidence, ...],
) -> dict[str, LicenseMemberEvidence]:
    return {evidence.path: evidence for evidence in members}


def _license_placements_for_package(
    *,
    closure_kind: ClosureKind,
    package: str,
    license_expression: str,
    session_license_members: tuple[LicenseMemberEvidence, ...],
    descriptor_license_members: tuple[str, ...],
    external_licenses: tuple[ExternalLicenseArtifact, ...],
    archive_sha256: str,
) -> tuple[tuple[InstalledFileRecord, ...], tuple[InstalledLicenseRecord, ...]]:
    evidence = _member_evidence_by_path(session_license_members)
    files: list[InstalledFileRecord] = []
    records: list[InstalledLicenseRecord] = []
    for member in descriptor_license_members:
        proof = evidence.get(member)
        if proof is None:
            raise CapsuleInputAuthoringError(
                f"{package} license member {member} has no verified evidence"
            )
        placed, record = _license_placement(
            closure_kind=closure_kind,
            package=package,
            license_expression=license_expression,
            relative_member=PurePosixPath(member).name,
            size=proof.size,
            sha256=proof.sha256,
            source_sha256=archive_sha256,
            source_member=member,
        )
        files.append(placed)
        records.append(record)
    for external in external_licenses:
        placed, record = _license_placement(
            closure_kind=closure_kind,
            package=package,
            license_expression=license_expression,
            relative_member=PurePosixPath(external.declared_member).name,
            size=external.size,
            sha256=external.sha256,
            source_sha256=external.sha256,
            source_member=external.source_id,
        )
        files.append(placed)
        records.append(record)
    return tuple(files), tuple(records)


def build_python_installed_inventory(
    artifacts: tuple[PythonWheelArtifact, ...],
    *,
    target: TargetTriple,
    source_inventory_sha256: str,
    lock_sha256: str,
    cache_root: Path,
) -> tuple[InstalledClosureDescriptor, InstalledClosureInventory]:
    """Build the Python closure's installed inventory from verified sessions.

    Every wheel - including the A2A distribution wheel, whose modules back the
    two contract console scripts - is opened and verified in full, its members
    laid out by the production authority with provable provenance, and its
    licenses placed into the reserved subtree.  A closure missing either
    console-script module fails closed.
    """
    if not artifacts:
        raise CapsuleInputAuthoringError("Python closure has no wheels to install")
    with ExitStack() as stack:
        sessions = tuple(
            stack.enter_context(
                open_verified_python_wheel_archive(
                    cache_root / artifact.sha256, artifact, target=target
                )
            )
            for artifact in artifacts
        )
        placed_members = {
            member for session in sessions for member in session.archive.members
        }
        for module in _CONSOLE_SCRIPT_MODULES:
            if module not in placed_members:
                raise CapsuleInputAuthoringError(
                    f"console-script module {module} is absent from the A2A wheel"
                )
        license_files: list[InstalledFileRecord] = []
        licenses: list[InstalledLicenseRecord] = []
        for session, artifact in zip(sessions, artifacts, strict=True):
            files, records = _license_placements_for_package(
                closure_kind="python",
                package=artifact.name,
                license_expression=artifact.license_expression,
                session_license_members=session.archive.license_members,
                descriptor_license_members=artifact.license_members,
                external_licenses=artifact.external_licenses,
                archive_sha256=artifact.sha256,
            )
            license_files.extend(files)
            licenses.extend(records)
        try:
            return build_python_closure_installed_inventory(
                target=target,
                source_inventory_sha256=source_inventory_sha256,
                lock_sha256=lock_sha256,
                wheel_sessions=sessions,
                console_scripts=_CONSOLE_SCRIPTS,
                licenses=tuple(licenses),
                license_files=tuple(license_files),
                input_dir=cache_root,
            )
        except (ArtifactInputError, ValueError) as error:
            raise CapsuleInputAuthoringError(
                f"Python installed inventory build failed: {error}"
            ) from None


def build_acp_installed_inventory(
    artifacts: tuple[AcpPackageArtifact, ...],
    *,
    target: TargetTriple,
    source_inventory_sha256: str,
    lock_sha256: str,
    bin_entrypoints: tuple[str, ...],
    cache_root: Path,
) -> tuple[InstalledClosureDescriptor, InstalledClosureInventory]:
    """Build the ACP closure's installed inventory from verified npm sessions."""
    if not artifacts:
        raise CapsuleInputAuthoringError("ACP closure has no tarballs to install")
    with ExitStack() as stack:
        sessions = tuple(
            stack.enter_context(
                open_verified_acp_package_archive(
                    cache_root / artifact.sha256, artifact
                )
            )
            for artifact in artifacts
        )
        license_files: list[InstalledFileRecord] = []
        licenses: list[InstalledLicenseRecord] = []
        for session, artifact in zip(sessions, artifacts, strict=True):
            files, records = _license_placements_for_package(
                closure_kind="acp",
                package=artifact.install_path,
                license_expression=artifact.license_expression,
                session_license_members=session.archive.license_members,
                descriptor_license_members=artifact.license_members,
                external_licenses=artifact.external_licenses,
                archive_sha256=artifact.sha256,
            )
            license_files.extend(files)
            licenses.extend(records)
        try:
            return build_acp_closure_installed_inventory(
                target=target,
                source_inventory_sha256=source_inventory_sha256,
                lock_sha256=lock_sha256,
                tarball_sessions=sessions,
                bin_entrypoints=bin_entrypoints,
                licenses=tuple(licenses),
                license_files=tuple(license_files),
                input_dir=cache_root,
            )
        except (ArtifactInputError, ValueError) as error:
            raise CapsuleInputAuthoringError(
                f"ACP installed inventory build failed: {error}"
            ) from None


@dataclass(frozen=True, slots=True)
class AuthoredDescriptor:
    """One pinned capsule input descriptor written for the build stage."""

    path: Path
    sha256: str
    size: int


def author_capsule_input_descriptor(
    descriptor: CapsuleInputDescriptor, *, output_dir: Path
) -> AuthoredDescriptor:
    """Serialize, digest, and write one validated capsule input descriptor.

    The descriptor is emitted as canonical TOML (``exclude_none`` matching the
    consumer's parse) and pinned by its own sha256 - the phase-boundary
    attestation the build stage opens read-only.  The digest is over the exact
    written bytes, so a caller round-tripping through ``open_verified_capsule_inputs``
    with this sha256 proves the descriptor is well-formed rather than trusting
    this authoring output.
    """
    # Lazy: the descriptor serializer is a build-time tool, so importing this
    # module at capsule runtime never requires the tomlkit build dependency.
    from tomlkit import dumps as toml_dumps

    payload = toml_dumps(descriptor.model_dump(mode="json", exclude_none=True)).encode()
    if len(payload) > _MAX_DESCRIPTOR_BYTES:
        raise CapsuleInputAuthoringError("authored descriptor exceeds its size bound")
    sha256 = hashlib.sha256(payload).hexdigest()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "capsule-inputs.toml"
        path.write_bytes(payload)
    except OSError as error:
        raise CapsuleInputAuthoringError(
            f"cannot write capsule input descriptor: {error}"
        ) from None
    return AuthoredDescriptor(path=path, sha256=sha256, size=len(payload))
