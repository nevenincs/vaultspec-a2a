"""A2A desktop capsule builder: the read-only consume stage.

The preparation stage authors one digest-pinned capsule input descriptor and an
explicit content-addressed input cache (``prepare_desktop_capsule.py``).  This
builder consumes exactly that descriptor plus that cache and assembles the
deterministic installed capsule tree inside one caller-owned, final-name
unpublished generation.  The build acquires nothing, derives nothing, and mints
nothing: it opens the pinned descriptor and cache read-only through the
production verified-input session and fails closed on any bound violation.

Generation layout (all targets), rooted at ``<out-dir>/<target>``:
  capsule/                         the materialized installed tree
    runtime/python                 Python wheelhouse, replayed byte-for-byte
    runtime/acp                    ACP node_modules, replayed byte-for-byte
    runtime/cpython                verbatim CPython interpreter subtree
    runtime/node                   verbatim Node.js interpreter subtree
    bin/ or Scripts/               relocatable product launchers
    locks/uv.lock, locks/package-lock.json
    component-manifest.json        emitted component manifest
    component-manifest.canonical.bin
    component-manifest.digest.sha256
    installed-tree.cdx.json        complete machine-readable installed-tree evidence
  capsule.zip                      deterministic archive, published once beside the tree

Every closure byte is verified against its declared installed record during the
write; the two interpreter subtrees are verbatim projections of the verified
runtime sources; the launchers, locks, manifest, and evidence are generated or
streamed directly from the retained session.  One directory authority for the
capsule root is claimed once inside the generation and shared across every
writer, so no writer opens a second lease and nothing is published inside the
generation but the single final ``capsule.zip``.

Usage:
  uv run --no-sync python scripts/build_desktop_capsule.py build \\
      --target x86_64-pc-windows-msvc \\
      --descriptor dist/capsules/x86_64-pc-windows-msvc/capsule-inputs.toml \\
      --descriptor-sha256 <hex> \\
      --input-dir dist/capsules/.cache \\
      --uv-lock uv.lock \\
      --package-lock package-lock.json \\
      --out-dir dist/capsules \\
      --launcher-stub-donor dist/capsules/.cache/<donor-wheel-sha256>
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import click

from vaultspec_a2a.desktop import (
    ApiVersionRange,
    GatewayApiVersion,
    TargetTriple,
    component_manifest_canonical_bytes,
    component_manifest_digest,
)
from vaultspec_a2a.desktop._filesystem_authority import (
    claim_new_directory,
    directory_lease,
    resolve_directory_authority,
)
from vaultspec_a2a.desktop.artifacts import (
    ArtifactInputError,
    open_verified_capsule_inputs,
    verify_cached_artifacts,
)
from vaultspec_a2a.desktop.capsule import (
    CapsuleAssemblyError,
    materialize_verified_member,
    project_source_archive_into_unpublished_generation,
)
from vaultspec_a2a.desktop.capsule_assembly import (
    CAPSULE_ARCHIVE_OUTPUT_NAME,
    CAPSULE_ROOT,
    CapsuleAssemblyPlanError,
    PlanReservationRole,
    derive_capsule_assembly_plan,
)
from vaultspec_a2a.desktop.capsule_evidence import (
    ProjectedFile,
    canonical_evidence_bytes,
    installed_tree_inventory,
    write_deterministic_capsule_zip_into_unpublished_generation,
)
from vaultspec_a2a.desktop.capsule_materializer import (
    CapsuleMaterializationError,
    extract_windows_launcher_stub,
    extract_windows_launcher_stub_license,
    materialize_capsule_closures,
)
from vaultspec_a2a.desktop.contract import ComponentAssetKind

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from typing import BinaryIO

    from vaultspec_a2a.desktop._filesystem_authority import DirectoryAuthority
    from vaultspec_a2a.desktop.artifacts import VerifiedCapsuleInputSession
    from vaultspec_a2a.desktop.capsule_assembly import (
        CapsuleAssemblyPlan,
        ReservedTreeFile,
    )

# The capsule contract fixes the gateway API surface at v1; a wider range is a
# future contract change, not a build-time choice.
_API_VERSIONS: Final = ApiVersionRange(
    minimum=GatewayApiVersion.V1, maximum=GatewayApiVersion.V1
)

# The two interpreter archives extract verbatim into these sibling subtrees
# under the materialized ``runtime`` directory the closures already create.
_INTERPRETER_SUBTREES: Final = (
    (ComponentAssetKind.PYTHON_RUNTIME, "cpython"),
    (ComponentAssetKind.NODE_RUNTIME, "node"),
)
_RUNTIME_ROOT: Final = "runtime"

# Installed-tree evidence key under which the per-member drop-audit-trail is
# surfaced so a library-runtime omission is auditable, not silent.
_DROPPED_EVIDENCE_KEY: Final = "vaultspec:dropped-members"

_UV_LOCK_BASENAME: Final = "uv.lock"
_PACKAGE_LOCK_BASENAME: Final = "package-lock.json"


class CapsuleBuildError(RuntimeError):
    """Fatal error while consuming pinned inputs into a capsule generation."""


# ---------------------------------------------------------------------------
# Reservation lookup
# ---------------------------------------------------------------------------


def _single_reservation(
    plan: CapsuleAssemblyPlan, role: PlanReservationRole
) -> ReservedTreeFile:
    """Return the sole plan reservation carrying *role*, failing closed otherwise."""
    matches = [file for file in plan.files if file.role is role]
    if len(matches) != 1:
        raise CapsuleBuildError(
            f"capsule plan does not reserve exactly one {role.value} destination"
        )
    return matches[0]


def _lock_reservations(
    plan: CapsuleAssemblyPlan,
) -> tuple[ReservedTreeFile, ReservedTreeFile]:
    """Return the (uv, package) dependency-lock reservations by their basenames."""
    by_name = {
        file.path.rsplit("/", 1)[-1]: file
        for file in plan.files
        if file.role is PlanReservationRole.DEPENDENCY_LOCK
    }
    uv = by_name.get(_UV_LOCK_BASENAME)
    package = by_name.get(_PACKAGE_LOCK_BASENAME)
    if uv is None or package is None or len(by_name) != 2:
        raise CapsuleBuildError("capsule plan does not reserve both dependency locks")
    return uv, package


# ---------------------------------------------------------------------------
# Generated- and streamed-byte materialization (into the shared capsule lease)
# ---------------------------------------------------------------------------


def _materialize_bytes(
    content: bytes,
    reserved: ReservedTreeFile,
    *,
    capsule: DirectoryAuthority,
    generation: DirectoryAuthority,
    parent_identities: dict[tuple[str, ...], tuple[int, int]],
    source_date_epoch: int,
) -> ProjectedFile:
    """Materialize one exact in-memory byte payload into its reserved destination."""
    with io.BytesIO(content) as stream:
        return materialize_verified_member(
            stream,
            reserved.path,
            destination_root=capsule.path,
            generation_authority=generation,
            destination_authority=capsule,
            parent_identities=parent_identities,
            expected_size=len(content),
            mode=reserved.mode,
            source_date_epoch=source_date_epoch,
        )


def _materialize_lock(
    open_lock: Callable[[], AbstractContextManager[BinaryIO]],
    reserved: ReservedTreeFile,
    *,
    capsule: DirectoryAuthority,
    generation: DirectoryAuthority,
    parent_identities: dict[tuple[str, ...], tuple[int, int]],
    source_date_epoch: int,
) -> ProjectedFile:
    """Stream one retained dependency lock into its reserved destination."""
    if reserved.size is None:
        raise CapsuleBuildError("dependency-lock reservation is missing its size")
    with open_lock() as stream:
        return materialize_verified_member(
            stream,
            reserved.path,
            destination_root=capsule.path,
            generation_authority=generation,
            destination_authority=capsule,
            parent_identities=parent_identities,
            expected_size=reserved.size,
            mode=reserved.mode,
            source_date_epoch=source_date_epoch,
        )


# ---------------------------------------------------------------------------
# Drop-audit-trail (consumed from the prepared descriptor)
# ---------------------------------------------------------------------------


def _drop_audit_trail(
    session: VerifiedCapsuleInputSession,
) -> list[dict[str, object]]:
    """Return the per-member drop-audit-trail carried by the installed inventories.

    The preparation stage records every verified closure member deliberately
    omitted from the installed tree - the library-runtime ``.data/headers`` and
    ``.data/scripts`` omissions - onto each closure's installed inventory, bound
    whole by the inventory digest.  The build reads that record off both
    retained inventories and surfaces it verbatim into the installed-tree
    evidence, tagging each record with the closure it came from; it derives
    nothing here.  ACP closures carry no ``.data`` members, so their trail is
    typically empty.
    """
    tagged = [
        (closure, record)
        for closure, inventory in (
            ("python", session.python_installed),
            ("acp", session.acp_installed),
        )
        for record in inventory.dropped
    ]
    tagged.sort(
        key=lambda item: (item[0], item[1].source_sha256, item[1].source_member)
    )
    return [
        {
            "closure": closure,
            "source_member": record.source_member,
            "source_sha256": record.source_sha256,
            "size": record.size,
            "sha256": record.sha256,
            "reason": record.reason,
        }
        for closure, record in tagged
    ]


# ---------------------------------------------------------------------------
# Interpreter subtree verbatim projection
# ---------------------------------------------------------------------------


def _project_interpreter_subtrees(
    session: VerifiedCapsuleInputSession,
    *,
    input_dir: Path,
    capsule: DirectoryAuthority,
    source_date_epoch: int,
) -> list[ProjectedFile]:
    """Verbatim-project both interpreter subtrees into the materialized runtime dir.

    The closures already created ``runtime`` (their install roots sit beneath
    it), so the two interpreter archives extract into fresh ``cpython`` and
    ``node`` children of that existing directory.  The verified runtime source
    bytes are re-resolved from the same content-addressed cache; nothing is
    re-derived.

    The projector roots its evidence at the leased ``runtime`` directory it
    claims into, so the returned paths are ``cpython/...``/``node/...``; they are
    re-rooted under ``runtime/`` here so every returned :class:`ProjectedFile`
    is capsule-relative, matching the closures, launchers, and locks.
    """
    verified = {
        artifact.descriptor.kind: artifact
        for artifact in verify_cached_artifacts(session.descriptor, input_dir=input_dir)
    }
    runtime_authority = resolve_directory_authority(capsule.path / _RUNTIME_ROOT)
    projected: list[ProjectedFile] = []
    with directory_lease(runtime_authority) as runtime:
        for kind, prefix in _INTERPRETER_SUBTREES:
            artifact = verified.get(kind)
            if artifact is None:
                raise CapsuleBuildError(
                    f"verified cache is missing the {kind.value} interpreter source"
                )
            projected.extend(
                ProjectedFile(
                    relative_path=f"{_RUNTIME_ROOT}/{emitted.relative_path}",
                    size=emitted.size,
                    sha256=emitted.sha256,
                    mode=emitted.mode,
                )
                for emitted in project_source_archive_into_unpublished_generation(
                    artifact,
                    generation_authority=runtime,
                    destination_prefix=prefix,
                    source_date_epoch=source_date_epoch,
                )
            )
    return projected


# ---------------------------------------------------------------------------
# Whole-generation assembly
# ---------------------------------------------------------------------------


def _assemble_generation(
    session: VerifiedCapsuleInputSession,
    plan: CapsuleAssemblyPlan,
    *,
    input_dir: Path,
    generation: DirectoryAuthority,
    capsule: DirectoryAuthority,
    windows_launcher_stub: bytes | None,
    windows_launcher_stub_license: bytes | None,
    source_date_epoch: int,
) -> tuple[str, int]:
    """Assemble the whole capsule tree and its final archive inside one generation.

    Returns the deterministic ``capsule.zip`` digest and the count of installed
    files surfaced into the installed-tree evidence.
    """
    projected: list[ProjectedFile] = list(
        materialize_capsule_closures(
            plan,
            session,
            api_versions=_API_VERSIONS,
            destination_root=capsule.path,
            generation_authority=generation,
            destination_authority=capsule,
            source_date_epoch=source_date_epoch,
            windows_launcher_stub=windows_launcher_stub,
            windows_launcher_stub_license=windows_launcher_stub_license,
        )
    )
    projected.extend(
        _project_interpreter_subtrees(
            session,
            input_dir=input_dir,
            capsule=capsule,
            source_date_epoch=source_date_epoch,
        )
    )

    parent_identities: dict[tuple[str, ...], tuple[int, int]] = {}
    uv_reservation, package_reservation = _lock_reservations(plan)
    projected.append(
        _materialize_lock(
            session.open_uv_lock,
            uv_reservation,
            capsule=capsule,
            generation=generation,
            parent_identities=parent_identities,
            source_date_epoch=source_date_epoch,
        )
    )
    projected.append(
        _materialize_lock(
            session.open_package_lock,
            package_reservation,
            capsule=capsule,
            generation=generation,
            parent_identities=parent_identities,
            source_date_epoch=source_date_epoch,
        )
    )

    manifest = session.emit_component_manifest(api_versions=_API_VERSIONS)
    manifest_json = (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    for content, role in (
        (manifest_json, PlanReservationRole.COMPONENT_MANIFEST),
        (
            component_manifest_canonical_bytes(manifest),
            PlanReservationRole.CANONICAL_MANIFEST,
        ),
        (
            component_manifest_digest(manifest).encode("ascii"),
            PlanReservationRole.MANIFEST_DIGEST,
        ),
    ):
        projected.append(
            _materialize_bytes(
                content,
                _single_reservation(plan, role),
                capsule=capsule,
                generation=generation,
                parent_identities=parent_identities,
                source_date_epoch=source_date_epoch,
            )
        )

    # The installed-tree evidence describes every materialized file except
    # itself (and the sibling archive, which is not inside the tree).
    evidence_document = installed_tree_inventory(
        manifest=manifest,
        files=projected,
        source_date_epoch=source_date_epoch,
    )
    dropped = _drop_audit_trail(session)
    if dropped:
        evidence_document[_DROPPED_EVIDENCE_KEY] = dropped
    _materialize_bytes(
        canonical_evidence_bytes(evidence_document),
        _single_reservation(plan, PlanReservationRole.INSTALLED_EVIDENCE),
        capsule=capsule,
        generation=generation,
        parent_identities=parent_identities,
        source_date_epoch=source_date_epoch,
    )

    archive_digest, _ = write_deterministic_capsule_zip_into_unpublished_generation(
        capsule.path,
        generation_authority=generation,
        output_name=CAPSULE_ARCHIVE_OUTPUT_NAME,
        source_date_epoch=source_date_epoch,
    )
    return archive_digest, len(projected)


def _acquire_windows_launcher_stub(donor_path: Path | None) -> tuple[bytes, bytes]:
    """Extract the pinned console stub and its license notice from the donor wheel."""
    if donor_path is None:
        raise CapsuleBuildError(
            "a Windows target requires --launcher-stub-donor pointing at the "
            "pinned donor wheel"
        )
    with donor_path.open("rb") as donor:
        stub = extract_windows_launcher_stub(donor)
    with donor_path.open("rb") as donor:
        stub_license = extract_windows_launcher_stub_license(donor)
    return stub, stub_license


def _run_build(
    *,
    target: TargetTriple,
    descriptor_path: Path,
    descriptor_sha256: str,
    input_dir: Path,
    uv_lock: Path,
    package_lock: Path,
    out_dir: Path,
    launcher_stub_donor: Path | None,
) -> tuple[Path, str]:
    """Open the pinned inputs read-only and assemble one capsule generation."""
    with open_verified_capsule_inputs(
        descriptor_path,
        expected_descriptor_sha256=descriptor_sha256,
        input_dir=input_dir,
        uv_lock_path=uv_lock,
        package_lock_path=package_lock,
    ) as session:
        descriptor = session.descriptor
        if descriptor.target is not target:
            raise CapsuleBuildError(
                f"descriptor target {descriptor.target.value} does not match the "
                f"requested target {target.value}"
            )
        source_date_epoch = descriptor.source_date_epoch
        plan = derive_capsule_assembly_plan(session, api_versions=_API_VERSIONS)

        stub: bytes | None = None
        stub_license: bytes | None = None
        if descriptor.target is TargetTriple.WINDOWS_X86_64:
            stub, stub_license = _acquire_windows_launcher_stub(launcher_stub_donor)

        out_dir.mkdir(parents=True, exist_ok=True)
        generation_dir = out_dir / target.value
        try:
            generation_dir.mkdir()
        except FileExistsError:
            raise CapsuleBuildError(
                f"generation directory {generation_dir} already exists; the build "
                "refuses to overwrite a prior generation"
            ) from None

        generation_root = resolve_directory_authority(generation_dir)
        with (
            directory_lease(generation_root) as generation,
            claim_new_directory(generation, CAPSULE_ROOT) as capsule,
        ):
            archive_digest, file_count = _assemble_generation(
                session,
                plan,
                input_dir=input_dir,
                generation=generation,
                capsule=capsule,
                windows_launcher_stub=stub,
                windows_launcher_stub_license=stub_license,
                source_date_epoch=source_date_epoch,
            )
    click.echo(f"  generation:        {generation_dir}")
    click.echo(f"  installed files:   {file_count}")
    click.echo(f"  capsule archive:   {generation_dir / CAPSULE_ARCHIVE_OUTPUT_NAME}")
    click.echo(f"  archive sha256:    {archive_digest}")
    return generation_dir, archive_digest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """A2A desktop capsule assembly tools."""


@cli.command()
@click.option(
    "--target",
    required=True,
    type=click.Choice([t.value for t in TargetTriple]),
    help="Target triple; must match the pinned descriptor's target.",
)
@click.option(
    "--descriptor",
    "descriptor",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Pinned capsule input descriptor produced by the preparation stage.",
)
@click.option(
    "--descriptor-sha256",
    required=True,
    help="Expected SHA-256 of the pinned descriptor bytes.",
)
@click.option(
    "--input-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Content-addressed input cache the descriptor was pinned against.",
)
@click.option(
    "--uv-lock",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="uv.lock whose digest the descriptor pins.",
)
@click.option(
    "--package-lock",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="package-lock.json whose digest the descriptor pins.",
)
@click.option(
    "--out-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory to hold the per-target generation.",
)
@click.option(
    "--launcher-stub-donor",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Pinned donor wheel supplying the Windows console launcher stub.",
)
def build(
    target: str,
    descriptor: Path,
    descriptor_sha256: str,
    input_dir: Path,
    uv_lock: Path,
    package_lock: Path,
    out_dir: Path,
    launcher_stub_donor: Path | None,
) -> None:
    """Assemble a deterministic desktop capsule generation from pinned inputs."""
    try:
        _run_build(
            target=TargetTriple(target),
            descriptor_path=descriptor,
            descriptor_sha256=descriptor_sha256,
            input_dir=input_dir,
            uv_lock=uv_lock,
            package_lock=package_lock,
            out_dir=out_dir,
            launcher_stub_donor=launcher_stub_donor,
        )
    except (
        CapsuleBuildError,
        ArtifactInputError,
        CapsuleAssemblyError,
        CapsuleAssemblyPlanError,
        CapsuleMaterializationError,
    ) as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
