"""Immutable pre-mutation whole-capsule assembly plan.

Before any capsule byte is written, this module derives one deterministic,
immutable plan that reserves every destination path the assembler will create:
the two runtime-interpreter subtrees, the Python and ACP installed closures,
the relocatable console launchers, the dependency locks, the component
manifest with its canonical and digest evidence, the installed-tree inventory,
and the final capsule archive name. The planner is pure: it derives the plan
from the already-verified :class:`vaultspec_a2a.desktop.artifacts.
VerifiedCapsuleInputSession` and mutates no filesystem state.

The plan is the layout authority. It trusts the retained
:class:`vaultspec_a2a.desktop.installed_inventory.InstalledClosureInventory`
values as the declared closure trees, reuses the shared portable-path grammar,
and fails closed with :class:`CapsuleAssemblyPlanError` when a reservation
violates the dashboard-ASCII, whole-tree collision, ancestor, file-size, or
per-asset license bounds. Materialization consumes the returned plan; this
module never reads or writes a capsule byte.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from .closure_inventory import validate_portable_archive_path
from .contract import (
    ComponentAssetKind,
    EntrypointKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from .artifacts import VerifiedCapsuleInputSession
    from .contract import (
        ApiVersionRange,
        ComponentManifest,
        TargetTriple,
    )
    from .installed_inventory import InstalledClosureInventory

__all__ = [
    "CAPSULE_ARCHIVE_OUTPUT_NAME",
    "CAPSULE_ROOT",
    "CapsuleAssemblyPlan",
    "CapsuleAssemblyPlanError",
    "PlanReservationRole",
    "ReservedRuntimeSubtree",
    "ReservedTreeFile",
    "derive_capsule_assembly_plan",
]

CAPSULE_ROOT: Final = "capsule"
"""Top-level directory holding the materialized capsule tree in the generation."""

CAPSULE_ARCHIVE_OUTPUT_NAME: Final = "capsule.zip"
"""Deterministic archive name published beside the capsule tree, never inside it."""

# Layout authority: where each base-closure input lands inside the capsule root.
# The two installed closures declare their own install roots (runtime/python,
# runtime/acp); the two interpreter archives extract into sibling subtrees.
_CPYTHON_SUBTREE: Final = "runtime/cpython"
_NODE_SUBTREE: Final = "runtime/node"
_PYTHON_CLOSURE_ROOT: Final = "runtime/python"
_ACP_CLOSURE_ROOT: Final = "runtime/acp"
_UV_LOCK_PATH: Final = "locks/uv.lock"
_PACKAGE_LOCK_PATH: Final = "locks/package-lock.json"
_COMPONENT_MANIFEST_PATH: Final = "component-manifest.json"
_CANONICAL_MANIFEST_PATH: Final = "component-manifest.canonical.bin"
_MANIFEST_DIGEST_PATH: Final = "component-manifest.digest.sha256"
_INSTALLED_EVIDENCE_PATH: Final = "installed-tree.cdx.json"

_MAX_CAPSULE_FILES: Final = 80_000
_MAX_FILE_BYTES: Final = 2 << 30
_MAX_KNOWN_AGGREGATE_BYTES: Final = 8 << 30
_MAX_SUBTREE_SOURCE_BYTES: Final = 4 << 30
_MAX_RESERVATIONS: Final = _MAX_CAPSULE_FILES + 64

_FILE_MODES: Final = {"0644": 0o644, "0755": 0o755}


class CapsuleAssemblyPlanError(RuntimeError):
    """Raised when a whole-capsule assembly plan violates a declared bound."""


class PlanReservationRole(StrEnum):
    """The provenance class of one reserved capsule destination path."""

    CPYTHON_RUNTIME = "cpython-runtime"
    NODE_RUNTIME = "node-runtime"
    PYTHON_CLOSURE_FILE = "python-closure-file"
    ACP_CLOSURE_FILE = "acp-closure-file"
    PYTHON_LICENSE = "python-license"
    ACP_LICENSE = "acp-license"
    GATEWAY_LAUNCHER = "gateway-launcher"
    STANDALONE_MCP_LAUNCHER = "standalone-mcp-launcher"
    DEPENDENCY_LOCK = "dependency-lock"
    COMPONENT_MANIFEST = "component-manifest"
    CANONICAL_MANIFEST = "canonical-manifest"
    MANIFEST_DIGEST = "manifest-digest"
    INSTALLED_EVIDENCE = "installed-evidence"


_LICENSE_ROLES: Final = frozenset(
    {PlanReservationRole.PYTHON_LICENSE, PlanReservationRole.ACP_LICENSE}
)


@dataclass(frozen=True, slots=True)
class ReservedTreeFile:
    """One exact capsule-relative file the assembler will create.

    ``size`` is ``None`` for files whose bytes are generated during assembly
    (launchers, manifest, evidence) and known for files copied verbatim from a
    verified input (closure members, dependency locks). ``mode`` is the octal
    POSIX permission the materialized file must carry.
    """

    path: str
    role: PlanReservationRole
    mode: int
    size: int | None

    def __post_init__(self) -> None:
        _validate_dashboard_path(self.path)
        if self.mode not in _FILE_MODES.values():
            raise CapsuleAssemblyPlanError(
                f"reserved file {self.path} has an invalid mode"
            )
        if self.size is not None and (
            not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or self.size < 0
            or self.size > _MAX_FILE_BYTES
        ):
            raise CapsuleAssemblyPlanError(
                f"reserved file {self.path} has an out-of-bound size"
            )


@dataclass(frozen=True, slots=True)
class ReservedRuntimeSubtree:
    """One capsule-relative directory that a runtime archive extracts into.

    A subtree reserves a whole prefix rather than individual member paths
    because the interpreter archive is not enumerated at planning time.
    ``source_kind`` names the base-closure source and ``source_size`` is the
    exact archive byte count the materializer will bound-project.
    """

    prefix: str
    role: PlanReservationRole
    source_kind: ComponentAssetKind
    source_size: int

    def __post_init__(self) -> None:
        _validate_dashboard_path(self.prefix)
        if (
            not isinstance(self.source_size, int)
            or isinstance(self.source_size, bool)
            or self.source_size <= 0
            or self.source_size > _MAX_SUBTREE_SOURCE_BYTES
        ):
            raise CapsuleAssemblyPlanError(
                f"runtime subtree {self.prefix} has an out-of-bound source size"
            )


@dataclass(frozen=True, slots=True)
class CapsuleAssemblyPlan:
    """One immutable, deterministic whole-capsule reservation set.

    Every reservation is capsule-relative (rooted at :data:`CAPSULE_ROOT` during
    materialization). ``archive_output_name`` is published beside the capsule
    root, never inside it, so it is excluded from the capsule-tree collision
    domain. Reservations are sorted by path for deterministic evidence.
    """

    target: TargetTriple
    files: tuple[ReservedTreeFile, ...]
    subtrees: tuple[ReservedRuntimeSubtree, ...]
    archive_output_name: str
    known_aggregate_bytes: int

    def reserved_paths(self) -> frozenset[str]:
        """Return every capsule-relative path the plan reserves."""
        return frozenset(
            (
                *(file.path for file in self.files),
                *(sub.prefix for sub in self.subtrees),
            )
        )

    def license_reservations(self) -> tuple[ReservedTreeFile, ...]:
        """Return the closure license files reserved by this plan."""
        return tuple(file for file in self.files if file.role in _LICENSE_ROLES)


def _validate_dashboard_path(value: str) -> str:
    """Validate one bounded dashboard-ASCII, NFC, portable capsule-relative path."""
    if not isinstance(value, str):
        raise CapsuleAssemblyPlanError("capsule path must be a string")
    try:
        validated = validate_portable_archive_path(value)
    except (TypeError, ValueError):
        raise CapsuleAssemblyPlanError(
            f"capsule path {value!r} is not portable"
        ) from None
    if unicodedata.normalize("NFC", validated) != validated:
        raise CapsuleAssemblyPlanError(f"capsule path {value!r} is not NFC")
    if not validated.isascii():
        raise CapsuleAssemblyPlanError(
            f"capsule path {value!r} is outside the dashboard ASCII domain"
        )
    for segment in validated.split("/"):
        if not segment or any(
            character not in _DASHBOARD_SEGMENT_CHARACTERS for character in segment
        ):
            raise CapsuleAssemblyPlanError(
                f"capsule path {value!r} uses a non-dashboard segment"
            )
    return validated


_DASHBOARD_SEGMENT_CHARACTERS: Final = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@_+.-"
)


def _collision_key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _strict_ancestors(key: str) -> Iterator[str]:
    parts = key.split("/")
    for index in range(1, len(parts)):
        yield "/".join(parts[:index])


def _enforce_whole_capsule_collision(paths: Iterable[str]) -> None:
    """Reject case-insensitive duplicates and any file-or-subtree ancestor conflict."""
    owned: set[str] = set()
    for path in paths:
        key = _collision_key(path)
        if key in owned:
            raise CapsuleAssemblyPlanError(
                f"capsule plan reserves colliding path {path!r}"
            )
        owned.add(key)
    for key in owned:
        for ancestor in _strict_ancestors(key):
            if ancestor in owned:
                raise CapsuleAssemblyPlanError(
                    "capsule plan reserves a file-and-subtree ancestor conflict"
                )


def _enforce_aggregate_size(ordered_files: Iterable[ReservedTreeFile]) -> int:
    """Sum every sized reservation and reject an over-bound capsule aggregate."""
    known_aggregate = sum(file.size for file in ordered_files if file.size is not None)
    if known_aggregate > _MAX_KNOWN_AGGREGATE_BYTES:
        raise CapsuleAssemblyPlanError(
            "capsule plan exceeds its aggregate known-file size bound"
        )
    return known_aggregate


def _closure_files(
    inventory: InstalledClosureInventory,
    *,
    file_role: PlanReservationRole,
    license_role: PlanReservationRole,
) -> tuple[ReservedTreeFile, ...]:
    """Reserve every declared installed-closure file rooted at its install root."""
    license_paths = {license.relative_path for license in inventory.licenses}
    reserved: list[ReservedTreeFile] = []
    for record in inventory.files:
        mode = _FILE_MODES.get(record.mode)
        if mode is None:
            raise CapsuleAssemblyPlanError(
                f"installed file {record.relative_path} has an unsupported mode"
            )
        role = license_role if record.relative_path in license_paths else file_role
        reserved.append(
            ReservedTreeFile(
                path=f"{inventory.install_root}/{record.relative_path}",
                role=role,
                mode=mode,
                size=record.size,
            )
        )
    return tuple(reserved)


def _launcher_reservations(manifest: ComponentManifest) -> tuple[ReservedTreeFile, ...]:
    """Reserve the relocatable gateway and standalone-MCP console launchers."""
    roles = {
        EntrypointKind.GATEWAY: PlanReservationRole.GATEWAY_LAUNCHER,
        EntrypointKind.STANDALONE_MCP: PlanReservationRole.STANDALONE_MCP_LAUNCHER,
    }
    reserved: list[ReservedTreeFile] = []
    for entrypoint in (
        manifest.entrypoints.gateway,
        manifest.entrypoints.standalone_mcp,
    ):
        reserved.append(
            ReservedTreeFile(
                path="/".join(entrypoint.relative_command),
                role=roles[entrypoint.kind],
                mode=0o755,
                size=None,
            )
        )
    return tuple(reserved)


def _missing_license_packages(
    inventory: InstalledClosureInventory, *, package_names: Iterable[str]
) -> set[str]:
    """Return declared package identities that bind no installed license record."""
    licensed = {license.package for license in inventory.licenses}
    return {name for name in package_names if name not in licensed}


def _assert_closure_license_coverage(
    inventory: InstalledClosureInventory,
    *,
    package_names: Iterable[str],
    closure_label: str,
) -> None:
    """Require every declared closure package to bind an installed license."""
    if _missing_license_packages(inventory, package_names=package_names):
        raise CapsuleAssemblyPlanError(
            f"{closure_label} closure omits a per-package license reservation"
        )


def _assert_declared_source_licenses(
    entries: Iterable[tuple[str, tuple[str, ...]]],
) -> None:
    """Require every base-closure source to declare at least one license member."""
    for label, license_members in entries:
        if not license_members:
            raise CapsuleAssemblyPlanError(f"{label} source omits its license bytes")


def _assert_license_presence(
    session: VerifiedCapsuleInputSession,
) -> None:
    """Require every closure package and base-closure source to bind licenses."""
    _assert_closure_license_coverage(
        session.python_installed,
        package_names={package.name for package in session.python_inventory.packages},
        closure_label="Python",
    )
    _assert_closure_license_coverage(
        session.acp_installed,
        package_names={
            package.install_path for package in session.acp_inventory.packages
        },
        closure_label="ACP",
    )
    _assert_declared_source_licenses(
        (source.kind.value, source.license_members) for source in session.sources
    )


def _runtime_subtrees(
    session: VerifiedCapsuleInputSession,
) -> tuple[ReservedRuntimeSubtree, ...]:
    """Reserve the two interpreter-archive extraction subtrees."""
    layout = {
        ComponentAssetKind.PYTHON_RUNTIME: (
            _CPYTHON_SUBTREE,
            PlanReservationRole.CPYTHON_RUNTIME,
        ),
        ComponentAssetKind.NODE_RUNTIME: (
            _NODE_SUBTREE,
            PlanReservationRole.NODE_RUNTIME,
        ),
    }
    reserved: list[ReservedRuntimeSubtree] = []
    for source in session.sources:
        entry = layout.get(source.kind)
        if entry is None:
            continue
        prefix, role = entry
        reserved.append(
            ReservedRuntimeSubtree(
                prefix=prefix,
                role=role,
                source_kind=source.kind,
                source_size=source.size,
            )
        )
    if len(reserved) != len(layout):
        raise CapsuleAssemblyPlanError(
            "capsule plan requires exactly one CPython and one Node runtime source"
        )
    return tuple(reserved)


def derive_capsule_assembly_plan(
    session: VerifiedCapsuleInputSession,
    *,
    api_versions: ApiVersionRange,
) -> CapsuleAssemblyPlan:
    """Derive one immutable whole-capsule assembly plan from verified inputs.

    The planner reads only retained, already-verified session evidence and the
    component manifest emitted from that evidence. It reserves every runtime,
    package, launcher, lock, license, manifest, evidence, and archive path,
    enforces the dashboard-ASCII, whole-capsule collision, ancestor, file-size,
    and per-asset license bounds, and returns a deterministic plan. It performs
    no filesystem mutation and no acquisition.
    """
    _require_session(session)
    _assert_license_presence(session)

    manifest = session.emit_component_manifest(api_versions=api_versions)
    if manifest.target is not session.descriptor.target:
        raise CapsuleAssemblyPlanError(
            "component manifest target does not match inputs"
        )

    subtrees = _runtime_subtrees(session)
    descriptor = session.descriptor
    files: list[ReservedTreeFile] = [
        *_closure_files(
            session.python_installed,
            file_role=PlanReservationRole.PYTHON_CLOSURE_FILE,
            license_role=PlanReservationRole.PYTHON_LICENSE,
        ),
        *_closure_files(
            session.acp_installed,
            file_role=PlanReservationRole.ACP_CLOSURE_FILE,
            license_role=PlanReservationRole.ACP_LICENSE,
        ),
        *_launcher_reservations(manifest),
        ReservedTreeFile(
            path=_UV_LOCK_PATH,
            role=PlanReservationRole.DEPENDENCY_LOCK,
            mode=0o644,
            size=descriptor.uv_lock.size,
        ),
        ReservedTreeFile(
            path=_PACKAGE_LOCK_PATH,
            role=PlanReservationRole.DEPENDENCY_LOCK,
            mode=0o644,
            size=descriptor.package_lock.size,
        ),
        ReservedTreeFile(
            path=_COMPONENT_MANIFEST_PATH,
            role=PlanReservationRole.COMPONENT_MANIFEST,
            mode=0o644,
            size=None,
        ),
        ReservedTreeFile(
            path=_CANONICAL_MANIFEST_PATH,
            role=PlanReservationRole.CANONICAL_MANIFEST,
            mode=0o644,
            size=None,
        ),
        ReservedTreeFile(
            path=_MANIFEST_DIGEST_PATH,
            role=PlanReservationRole.MANIFEST_DIGEST,
            mode=0o644,
            size=None,
        ),
        ReservedTreeFile(
            path=_INSTALLED_EVIDENCE_PATH,
            role=PlanReservationRole.INSTALLED_EVIDENCE,
            mode=0o644,
            size=None,
        ),
    ]

    _validate_closure_roots(session)
    ordered_files = tuple(sorted(files, key=lambda file: file.path))
    ordered_subtrees = tuple(sorted(subtrees, key=lambda sub: sub.prefix))

    reservation_count = len(ordered_files) + len(ordered_subtrees)
    if not reservation_count or reservation_count > _MAX_RESERVATIONS:
        raise CapsuleAssemblyPlanError("capsule plan reservation count is out of bound")

    _enforce_whole_capsule_collision(
        (
            *(file.path for file in ordered_files),
            *(sub.prefix for sub in ordered_subtrees),
        )
    )

    known_aggregate = _enforce_aggregate_size(ordered_files)

    return CapsuleAssemblyPlan(
        target=descriptor.target,
        files=ordered_files,
        subtrees=ordered_subtrees,
        archive_output_name=CAPSULE_ARCHIVE_OUTPUT_NAME,
        known_aggregate_bytes=known_aggregate,
    )


def _validate_closure_roots(session: VerifiedCapsuleInputSession) -> None:
    if session.python_installed.install_root != _PYTHON_CLOSURE_ROOT:
        raise CapsuleAssemblyPlanError(
            "Python closure install root does not match the capsule layout"
        )
    if session.acp_installed.install_root != _ACP_CLOSURE_ROOT:
        raise CapsuleAssemblyPlanError(
            "ACP closure install root does not match the capsule layout"
        )


def _require_session(session: VerifiedCapsuleInputSession) -> None:
    from .artifacts import VerifiedCapsuleInputSession as _Session

    if not isinstance(session, _Session):
        raise CapsuleAssemblyPlanError("capsule assembly plan input is invalid")
