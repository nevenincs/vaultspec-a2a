"""Wheel-aware and npm-aware capsule closure materialization (plan step S103).

:mod:`vaultspec_a2a.desktop.capsule_assembly` derives an immutable plan that
reserves every capsule destination path from the already-built v2 installed
inventories; it performs no filesystem mutation. :mod:`vaultspec_a2a.desktop.
capsule` offers a generic, bounded archive projector that deliberately refuses
wheel installation (spread-plus-``RECORD`` semantics, not verbatim prefix
projection). This module is the non-generic path beside that refusal: it
consumes only the plan and the session's already-verified v2 inventories, and
replays every ``InstalledFileRecord`` byte-for-byte by streaming its declared
``source_member`` from the archive named by its ``source_sha256`` through
:func:`vaultspec_a2a.desktop.capsule.materialize_verified_member`, verifying
size and sha256 during the write. The declared tree and the written tree are
the same artifact by construction; nothing here re-derives a layout the
inventory already declares.

License placement receives no special handling: a closure's license files are
ordinary entries of ``InstalledClosureInventory.files`` (the same records used
for every other closure member), already grammar-validated twice over — once
by the ``InstalledFileRecord``/``InstalledClosureInventory`` models at
inventory-build time, and again by :class:`vaultspec_a2a.desktop.
capsule_assembly.ReservedTreeFile` at plan-derivation time — so they flow
through the identical materialization path as non-license members.

Beside the replayed closures this module generates the two product launchers
the plan reserves. The POSIX pair is a rendered shell script; the Windows pair
is composed from a pinned, content-addressed console stub plus a fixed shebang
plus a deterministic zip payload, so the caller supplies the stub bytes
(:func:`extract_windows_launcher_stub`) for a Windows target.

Interpreter subtrees (``runtime/cpython``, ``runtime/node``) and the
dependency locks, component manifest, and installed-tree evidence stay outside
this module's scope; they are verbatim projections or directly-emitted bytes
the capsule build script assembles beside this module's output.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, Final, Literal, cast

from .capsule import CapsuleAssemblyError, materialize_verified_member
from .capsule_assembly import PlanReservationRole
from .closure_inventory import AcpPackageArtifact, PythonWheelArtifact
from .contract import CPYTHON_VERSION_PIN, ComponentAssetKind, TargetTriple

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager
    from pathlib import Path

    from ._filesystem_authority import DirectoryAuthority
    from .artifacts import CapsulePackageEvidence, VerifiedCapsuleInputSession
    from .capsule_assembly import CapsuleAssemblyPlan, ReservedTreeFile
    from .capsule_evidence import ProjectedFile
    from .contract import ApiVersionRange, ComponentEntrypoint
    from .installed_inventory import InstalledClosureInventory, InstalledFileRecord

__all__ = [
    "WINDOWS_LAUNCHER_STUB_MEMBER",
    "WINDOWS_LAUNCHER_STUB_SHA256",
    "CapsuleMaterializationError",
    "extract_windows_launcher_stub",
    "materialize_capsule_closures",
]

#: Reservation roles the plan derives from an ``InstalledClosureInventory``.
_PYTHON_CLOSURE_ROLES: Final = frozenset(
    {PlanReservationRole.PYTHON_CLOSURE_FILE, PlanReservationRole.PYTHON_LICENSE}
)
_ACP_CLOSURE_ROLES: Final = frozenset(
    {PlanReservationRole.ACP_CLOSURE_FILE, PlanReservationRole.ACP_LICENSE}
)

#: python-build-standalone "install_only" release layout
#: (`scripts/desktop_capsule_inputs.toml` pins the astral-sh/python-build-
#: standalone `install_only` flavor): the archive's top-level `python/`
#: directory becomes the capsule's `runtime/cpython` subtree, containing an
#: ordinary POSIX prefix install (`bin/pythonX.Y`, `lib/`, `include/`). This
#: relative binary path is an ASSUMPTION about a subtree this module never
#: writes (the interpreter subtree is materialized verbatim elsewhere); it is
#: exercised only through generated launcher content, never dereferenced here.
_CPYTHON_LAUNCHER_BINARY: Final = f"runtime/cpython/bin/python{CPYTHON_VERSION_PIN}"
_PYTHON_LIBRARY_ROOT: Final = "runtime/python"

#: The Windows standalone layout has no `bin/` segment and no version-suffixed
#: interpreter name: the interpreter sits at the interpreter subtree root. The
#: path is spelled with backslashes because it is consumed by the launcher
#: stub's own shebang parser and by `CreateProcess`, not by this process.
_WINDOWS_CPYTHON_LAUNCHER_BINARY: Final = "runtime\\cpython\\python.exe"

#: Isolated-mode interpreter flags carried by both generated launchers: `-I`
#: keeps every ambient Python environment variable, user site directory, and
#: unsafe path out of the capsule's interpreter, and `-B` keeps it from
#: writing `.pyc` files into the immutable capsule tree.
_LAUNCHER_INTERPRETER_FLAGS: Final = "-I -B"

#: Relocation token the console stub replaces with its own directory (the
#: stub matches the token including its trailing separator). It makes the
#: composed executable address the bundled interpreter relative to itself, so
#: the capsule stays relocatable exactly as the POSIX launcher is.
_WINDOWS_LAUNCHER_DIR_TOKEN: Final = "<launcher_dir>\\"

#: Fixed epoch for the launcher's appended zip entries (the minimum ZIP
#: timestamp, matching the capsule archive's own entry stamping): the composed
#: launcher must be byte-identical from identical inputs regardless of when or
#: on which host it is built.
_LAUNCHER_ZIP_EPOCH: Final = (1980, 1, 1, 0, 0, 0)

#: Donor archive member and pinned digest for the x86-64 console launcher
#: stub. The stub is a content-addressed build input declared beside every
#: other pinned download; the packaging library shipping it is a stub donor
#: only and is never imported at build or run time. The single vendored binary
#: is architecture-specific: another Windows architecture needs its own stub.
WINDOWS_LAUNCHER_STUB_MEMBER: Final = "distlib/t64.exe"
WINDOWS_LAUNCHER_STUB_SHA256: Final = (
    "81a618f21cb87db9076134e70388b6e9cb7c2106739011b6a51772d22cae06b7"
)


class CapsuleMaterializationError(CapsuleAssemblyError):
    """Raised when a plan reservation cannot be reconciled against evidence."""


def _validated_session(session: object) -> VerifiedCapsuleInputSession:
    from .artifacts import VerifiedCapsuleInputSession as _Session

    if not isinstance(session, _Session):
        raise CapsuleMaterializationError("capsule materialization session is invalid")
    return session


def _validated_plan(plan: object) -> CapsuleAssemblyPlan:
    from .capsule_assembly import CapsuleAssemblyPlan as _Plan

    if not isinstance(plan, _Plan):
        raise CapsuleMaterializationError("capsule materialization plan is invalid")
    return plan


@dataclass(frozen=True, slots=True)
class _ClosureSource:
    """One byte source a materializer file record's ``source_sha256`` may name."""

    archive_format: Literal["zip", "tar", "raw"]
    open_bytes: Callable[[], AbstractContextManager[BinaryIO]]


@contextmanager
def _open_python_package(
    session: VerifiedCapsuleInputSession, name: str
) -> Iterator[BinaryIO]:
    with (
        session.open_python_package(name) as package,
        package.open_snapshot() as stream,
    ):
        yield stream


@contextmanager
def _open_acp_package(
    session: VerifiedCapsuleInputSession, install_path: str
) -> Iterator[BinaryIO]:
    with (
        session.open_acp_package(install_path) as package,
        package.open_snapshot() as stream,
    ):
        yield stream


@contextmanager
def _open_base_source(
    session: VerifiedCapsuleInputSession, kind: ComponentAssetKind
) -> Iterator[BinaryIO]:
    with session.open_source(kind) as stream:
        yield stream


@contextmanager
def _open_external_license(
    session: VerifiedCapsuleInputSession,
    archive: CapsulePackageEvidence,
    source_id: str,
) -> Iterator[BinaryIO]:
    with session.open_external_license(archive, source_id) as stream:
        yield stream


def _register_source(
    sources: dict[str, _ClosureSource], sha256: str, source: _ClosureSource
) -> None:
    if sha256 in sources:
        raise CapsuleMaterializationError(
            "materializer source digest collides across the verified session"
        )
    sources[sha256] = source


def _indexed_closure_sources(
    session: VerifiedCapsuleInputSession,
) -> dict[str, _ClosureSource]:
    """Index every byte source a file record's ``source_sha256`` may name.

    Covers the retained Python wheels, the root A2A distribution wheel, the
    retained ACP npm packages, and every package's external license bytes.
    Runtime interpreter sources are excluded: their bytes never appear as a
    closure file's provenance, only as a verbatim-projected subtree.
    """
    sources: dict[str, _ClosureSource] = {}
    for evidence in session.python_packages:
        descriptor = evidence.descriptor
        if not isinstance(descriptor, PythonWheelArtifact):
            raise CapsuleMaterializationError("Python package evidence is invalid")
        _register_source(
            sources,
            descriptor.sha256,
            _ClosureSource(
                archive_format="zip",
                open_bytes=lambda s=session, n=descriptor.name: _open_python_package(
                    s, n
                ),
            ),
        )
        for item in descriptor.external_licenses:
            _register_source(
                sources,
                item.sha256,
                _ClosureSource(
                    archive_format="raw",
                    open_bytes=(
                        lambda s=session, a=evidence, i=item.source_id: (
                            _open_external_license(s, a, i)
                        )
                    ),
                ),
            )
    for evidence in session.acp_packages:
        descriptor = evidence.descriptor
        if not isinstance(descriptor, AcpPackageArtifact):
            raise CapsuleMaterializationError("ACP package evidence is invalid")
        _register_source(
            sources,
            descriptor.sha256,
            _ClosureSource(
                archive_format="tar",
                open_bytes=(
                    lambda s=session, p=descriptor.install_path: _open_acp_package(s, p)
                ),
            ),
        )
        for item in descriptor.external_licenses:
            _register_source(
                sources,
                item.sha256,
                _ClosureSource(
                    archive_format="raw",
                    open_bytes=(
                        lambda s=session, a=evidence, i=item.source_id: (
                            _open_external_license(s, a, i)
                        )
                    ),
                ),
            )
    for source in session.sources:
        if source.kind is ComponentAssetKind.A2A_DISTRIBUTION:
            _register_source(
                sources,
                source.sha256,
                _ClosureSource(
                    archive_format="zip",
                    open_bytes=(
                        lambda s=session, k=source.kind: _open_base_source(s, k)
                    ),
                ),
            )
    return sources


@contextmanager
def _opened_archive(closure_source: _ClosureSource) -> Iterator[object]:
    """Open the underlying archive, then yield it outside any exception guard.

    Only the archive-opening step itself is exception-translated. Once control
    passes to the caller's ``with`` body, no guard here re-catches whatever the
    caller raises while consuming the yielded archive (a per-record digest or
    provenance failure, for instance) — a broader ``try`` around the ``yield``
    would otherwise relabel that failure as an unrelated "cannot open" error.
    """
    with closure_source.open_bytes() as stream:
        if closure_source.archive_format == "zip":
            try:
                archive = zipfile.ZipFile(stream)
            except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
                raise CapsuleMaterializationError(
                    "cannot open materializer source archive"
                ) from None
            with archive:
                yield archive
        elif closure_source.archive_format == "tar":
            try:
                tar_archive = tarfile.open(fileobj=stream, mode="r:*")  # noqa: SIM115
            except (OSError, tarfile.TarError):
                raise CapsuleMaterializationError(
                    "cannot open materializer source archive"
                ) from None
            with tar_archive:
                yield tar_archive
        else:
            yield stream


@contextmanager
def _extracted_member(
    closure_source: _ClosureSource,
    opened: object,
    member: str,
    *,
    expected_size: int,
) -> Iterator[BinaryIO]:
    """Locate and open one member stream, yielded outside any exception guard.

    Only the lookup and ``open`` calls are exception-translated (mirrors
    :func:`_opened_archive`): the caller consumes the yielded stream through
    :func:`~vaultspec_a2a.desktop.capsule.materialize_verified_member`, whose
    own ``CapsuleAssemblyError`` (a ``RuntimeError``) must propagate with its
    specific message rather than being re-caught here and relabeled.
    """
    if closure_source.archive_format == "zip":
        archive = cast("zipfile.ZipFile", opened)
        try:
            info = archive.getinfo(member)
        except KeyError:
            raise CapsuleMaterializationError(
                f"materializer source member {member!r} is absent from its archive"
            ) from None
        if info.file_size != expected_size:
            raise CapsuleMaterializationError(
                f"materializer source member {member!r} size does not match"
            )
        try:
            source = archive.open(info, "r")
        except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
            raise CapsuleMaterializationError(
                f"cannot read materializer source member {member!r}"
            ) from None
        with source:
            yield cast("BinaryIO", source)
    elif closure_source.archive_format == "tar":
        archive = cast("tarfile.TarFile", opened)
        try:
            info = archive.getmember(member)
        except KeyError:
            raise CapsuleMaterializationError(
                f"materializer source member {member!r} is absent from its archive"
            ) from None
        if not info.isfile() or info.size != expected_size:
            raise CapsuleMaterializationError(
                f"materializer source member {member!r} size does not match"
            )
        extracted = archive.extractfile(info)
        if extracted is None:
            raise CapsuleMaterializationError(
                f"materializer source member {member!r} is not a regular file"
            )
        with extracted:
            yield cast("BinaryIO", extracted)
    else:
        yield cast("BinaryIO", opened)


def _reserved_file(
    plan_files: dict[str, ReservedTreeFile],
    capsule_path: str,
    *,
    allowed_roles: frozenset[PlanReservationRole],
) -> ReservedTreeFile:
    reserved = plan_files.get(capsule_path)
    if reserved is None or reserved.role not in allowed_roles:
        raise CapsuleMaterializationError(
            f"installed file {capsule_path!r} is not reserved by the capsule plan"
        )
    return reserved


def _materialize_closure(
    inventory: InstalledClosureInventory,
    *,
    plan_files: dict[str, ReservedTreeFile],
    allowed_roles: frozenset[PlanReservationRole],
    closure_sources: dict[str, _ClosureSource],
    destination_root: Path,
    generation_authority: DirectoryAuthority,
    destination_authority: DirectoryAuthority,
    parent_identities: dict[tuple[str, ...], tuple[int, int]],
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    by_source: dict[str, list[InstalledFileRecord]] = {}
    for record in inventory.files:
        by_source.setdefault(record.source_sha256, []).append(record)

    projected: list[ProjectedFile] = []
    for source_sha256 in sorted(by_source):
        closure_source = closure_sources.get(source_sha256)
        if closure_source is None:
            raise CapsuleMaterializationError(
                "installed file provenance names an unavailable materializer "
                f"source {source_sha256!r}"
            )
        records = sorted(
            by_source[source_sha256], key=lambda record: record.relative_path
        )
        with _opened_archive(closure_source) as opened:
            for record in records:
                capsule_path = f"{inventory.install_root}/{record.relative_path}"
                reserved = _reserved_file(
                    plan_files, capsule_path, allowed_roles=allowed_roles
                )
                if reserved.size != record.size:
                    raise CapsuleMaterializationError(
                        f"installed file {capsule_path!r} size does not match "
                        "its capsule reservation"
                    )
                with _extracted_member(
                    closure_source,
                    opened,
                    record.source_member,
                    expected_size=record.size,
                ) as stream:
                    emitted = materialize_verified_member(
                        stream,
                        capsule_path,
                        destination_root=destination_root,
                        generation_authority=generation_authority,
                        destination_authority=destination_authority,
                        parent_identities=parent_identities,
                        expected_size=record.size,
                        mode=reserved.mode,
                        source_date_epoch=source_date_epoch,
                    )
                if emitted.sha256 != record.sha256:
                    raise CapsuleMaterializationError(
                        f"materialized file {capsule_path!r} does not match its "
                        "installed digest"
                    )
                projected.append(emitted)
    return tuple(projected)


def _validated_console_reference(reference: str) -> tuple[str, str]:
    """Split and validate one ``module.path:attribute`` console-script reference.

    Every part must be a plain Python identifier so the generated launcher can
    embed it directly in its inline import statement without further escaping.
    """
    module, separator, attribute = reference.partition(":")
    if not separator or not module or not attribute:
        raise CapsuleMaterializationError("console-script reference is malformed")
    parts = module.split(".")
    if any(not part.isidentifier() for part in parts) or not attribute.isidentifier():
        raise CapsuleMaterializationError(
            "console-script reference is not directly importable"
        )
    if not reference.isascii():
        raise CapsuleMaterializationError(
            "console-script reference is not representable in a launcher"
        )
    return module, attribute


def _posix_launcher_bytes(entrypoint: ComponentEntrypoint) -> bytes:
    """Render one relocatable POSIX shell launcher for a contract entrypoint.

    The launcher resolves its own installation root at run time (so the
    capsule stays relocatable), pins the bundled interpreter's import path to
    the materialized ``runtime/python`` library root before importing the
    entrypoint (the reviewer-s102 runtime import-path carry-forward), and
    execs the bundled interpreter in isolated mode (``-I``) so no ambient
    Python environment or ``.pyc`` write can influence or mutate the capsule.
    """
    module, attribute = _validated_console_reference(entrypoint.reference)
    script = f"""#!/bin/sh
set -e
capsule_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export VAULTSPEC_A2A_CAPSULE_ROOT="$capsule_root"
exec "$capsule_root/{_CPYTHON_LAUNCHER_BINARY}" {_LAUNCHER_INTERPRETER_FLAGS} -c '
import os
import sys

_capsule_root = os.environ["VAULTSPEC_A2A_CAPSULE_ROOT"]
sys.path.insert(0, os.path.join(_capsule_root, "{_PYTHON_LIBRARY_ROOT}"))
from {module} import {attribute} as _entrypoint

sys.exit(_entrypoint())
' "$@"
"""
    return script.encode("ascii")


def _validated_launcher_stub(stub: bytes | None) -> bytes:
    """Content-address the console stub bytes before they enter a launcher.

    The stub is a pinned build input like every other download, so bytes that
    do not hash to the pinned digest are refused here rather than concatenated
    into an executable nobody can re-derive.
    """
    if stub is None:
        raise CapsuleMaterializationError(
            "Windows launcher stub bytes were not supplied; cannot materialize "
            "the Scripts launcher pair"
        )
    if hashlib.sha256(stub).hexdigest() != WINDOWS_LAUNCHER_STUB_SHA256:
        raise CapsuleMaterializationError(
            "Windows launcher stub bytes do not match the pinned stub digest"
        )
    return stub


def extract_windows_launcher_stub(donor: BinaryIO) -> bytes:
    """Extract and content-address the console stub from its donor archive.

    ``donor`` is the pinned, already digest-verified donor wheel declared in
    the capsule input cache. Only the single console stub member is read; the
    donor's Python modules are never imported, so the library shipping the
    stub is not a build- or run-time dependency of this project.
    """
    try:
        archive = zipfile.ZipFile(donor)
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
        raise CapsuleMaterializationError(
            "cannot open the Windows launcher stub donor archive"
        ) from None
    with archive:
        try:
            payload = archive.read(WINDOWS_LAUNCHER_STUB_MEMBER)
        except (KeyError, OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
            raise CapsuleMaterializationError(
                "Windows launcher stub member is absent from its donor archive"
            ) from None
    return _validated_launcher_stub(payload)


def _windows_launcher_shebang(depth: int) -> bytes:
    """Render the relocatable, quoted shebang line the console stub parses.

    ``depth`` is the launcher's own directory depth below the capsule root, so
    the interpreter is addressed by walking back up from the stub's
    substituted ``<launcher_dir>``. The executable is double-quoted because a
    capsule may be installed under a path containing spaces.
    """
    interpreter = (
        _WINDOWS_LAUNCHER_DIR_TOKEN + "..\\" * depth + _WINDOWS_CPYTHON_LAUNCHER_BINARY
    )
    return f'#!"{interpreter}" {_LAUNCHER_INTERPRETER_FLAGS}\n'.encode("ascii")


def _windows_launcher_zipapp(module: str, attribute: str, *, depth: int) -> bytes:
    """Render the deterministic zip payload the bundled interpreter executes.

    The interpreter places the launcher archive itself at the head of the
    import path, so ``__main__`` resolves the capsule root from its own
    location and re-pins the materialized ``runtime/python`` library root
    ahead of it before importing the entrypoint (the same runtime import-path
    pin the POSIX launcher performs). ``depth + 2`` parents lead from
    ``<launcher>/__main__.py`` back to the capsule root: one for the
    ``__main__.py`` entry inside the launcher archive, one for the launcher
    file itself, and ``depth`` for the directories holding it.
    """
    source = f"""import os
import sys

_capsule_root = __file__
for _ in range({depth + 2}):
    _capsule_root = os.path.dirname(_capsule_root)
os.environ["VAULTSPEC_A2A_CAPSULE_ROOT"] = _capsule_root
sys.path.insert(0, os.path.join(_capsule_root, "{_PYTHON_LIBRARY_ROOT}"))
from {module} import {attribute} as _entrypoint

sys.exit(_entrypoint())
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        info = zipfile.ZipInfo("__main__.py", date_time=_LAUNCHER_ZIP_EPOCH)
        info.compress_type = zipfile.ZIP_STORED
        # ``ZipInfo`` defaults these to the *building* host's platform and
        # umask; pinning them keeps a launcher built on Windows byte-identical
        # to one built on a POSIX release runner.
        info.create_system = 0
        info.external_attr = 0
        archive.writestr(info, source.encode("ascii"))
    return buffer.getvalue()


def _windows_launcher_bytes(entrypoint: ComponentEntrypoint, stub: bytes) -> bytes:
    """Compose one relocatable Windows console launcher for a contract entrypoint.

    The composition is the console stub's own documented format — stub bytes,
    then one ASCII shebang line, then an appended zip whose ``__main__`` the
    interpreter runs. Every part is fixed or content-addressed, so identical
    inputs yield a byte-identical executable.
    """
    module, attribute = _validated_console_reference(entrypoint.reference)
    depth = len(entrypoint.relative_command) - 1
    return (
        stub
        + _windows_launcher_shebang(depth)
        + _windows_launcher_zipapp(module, attribute, depth=depth)
    )


def _materialize_launchers(
    session: VerifiedCapsuleInputSession,
    *,
    plan_files: dict[str, ReservedTreeFile],
    windows_launcher_stub: bytes | None,
    api_versions: ApiVersionRange,
    destination_root: Path,
    generation_authority: DirectoryAuthority,
    destination_authority: DirectoryAuthority,
    parent_identities: dict[tuple[str, ...], tuple[int, int]],
    source_date_epoch: int,
) -> tuple[ProjectedFile, ...]:
    manifest = session.emit_component_manifest(api_versions=api_versions)
    if manifest.target is not session.descriptor.target:
        raise CapsuleMaterializationError(
            "component manifest target does not match the verified session"
        )
    stub: bytes | None = None
    if manifest.target is TargetTriple.WINDOWS_X86_64:
        stub = _validated_launcher_stub(windows_launcher_stub)

    projected: list[ProjectedFile] = []
    for entrypoint, role in (
        (manifest.entrypoints.gateway, PlanReservationRole.GATEWAY_LAUNCHER),
        (
            manifest.entrypoints.standalone_mcp,
            PlanReservationRole.STANDALONE_MCP_LAUNCHER,
        ),
    ):
        capsule_path = "/".join(entrypoint.relative_command)
        reserved = _reserved_file(
            plan_files, capsule_path, allowed_roles=frozenset({role})
        )
        content = (
            _posix_launcher_bytes(entrypoint)
            if stub is None
            else _windows_launcher_bytes(entrypoint, stub)
        )
        with io.BytesIO(content) as stream:
            emitted = materialize_verified_member(
                stream,
                capsule_path,
                destination_root=destination_root,
                generation_authority=generation_authority,
                destination_authority=destination_authority,
                parent_identities=parent_identities,
                expected_size=len(content),
                mode=reserved.mode,
                source_date_epoch=source_date_epoch,
            )
        projected.append(emitted)
    return tuple(projected)


def materialize_capsule_closures(
    plan: CapsuleAssemblyPlan,
    session: VerifiedCapsuleInputSession,
    *,
    api_versions: ApiVersionRange,
    destination_root: Path,
    generation_authority: DirectoryAuthority,
    destination_authority: DirectoryAuthority,
    source_date_epoch: int,
    windows_launcher_stub: bytes | None = None,
) -> tuple[ProjectedFile, ...]:
    """Materialize every wheel-, npm-, and launcher-sourced capsule reservation.

    ``destination_authority`` must already be a continuously leased,
    exclusively claimed directory authority for the capsule root
    (:data:`vaultspec_a2a.desktop.capsule_assembly.CAPSULE_ROOT`) inside
    ``generation_authority``'s unpublished generation; the caller claims and
    retains it (this module never claims or publishes a generation). Every
    written byte is verified against its declared ``InstalledFileRecord``
    during the write; interpreter subtrees, dependency locks, the component
    manifest, and installed-tree evidence are the caller's responsibility.

    ``windows_launcher_stub`` carries the pinned console stub bytes obtained
    through :func:`extract_windows_launcher_stub`; a Windows target without
    them fails loud rather than emitting a launcher pair nobody can execute.
    Every other target ignores it.
    """
    plan = _validated_plan(plan)
    session = _validated_session(session)
    plan_files = {file.path: file for file in plan.files}
    if len(plan_files) != len(plan.files):
        raise CapsuleMaterializationError("capsule plan reserves a colliding path")

    closure_sources = _indexed_closure_sources(session)
    parent_identities: dict[tuple[str, ...], tuple[int, int]] = {}
    projected: list[ProjectedFile] = []

    projected.extend(
        _materialize_closure(
            session.python_installed,
            plan_files=plan_files,
            allowed_roles=_PYTHON_CLOSURE_ROLES,
            closure_sources=closure_sources,
            destination_root=destination_root,
            generation_authority=generation_authority,
            destination_authority=destination_authority,
            parent_identities=parent_identities,
            source_date_epoch=source_date_epoch,
        )
    )
    projected.extend(
        _materialize_closure(
            session.acp_installed,
            plan_files=plan_files,
            allowed_roles=_ACP_CLOSURE_ROLES,
            closure_sources=closure_sources,
            destination_root=destination_root,
            generation_authority=generation_authority,
            destination_authority=destination_authority,
            parent_identities=parent_identities,
            source_date_epoch=source_date_epoch,
        )
    )
    projected.extend(
        _materialize_launchers(
            session,
            plan_files=plan_files,
            windows_launcher_stub=windows_launcher_stub,
            api_versions=api_versions,
            destination_root=destination_root,
            generation_authority=generation_authority,
            destination_authority=destination_authority,
            parent_identities=parent_identities,
            source_date_epoch=source_date_epoch,
        )
    )
    return tuple(projected)
