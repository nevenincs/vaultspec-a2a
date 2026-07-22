"""A2A desktop capsule generation verifier: producer-side, source-free.

Verifies one complete caller-owned capsule generation (produced by
``build_desktop_capsule.py``) against the same digest-pinned capsule input
descriptor and content-addressed cache the build consumed - with no source
checkout and no re-materialization. The verifier opens the pinned inputs
read-only through the production verified-input session and reconciles what is
actually on disk in the generation against that authority and against the
generation's own machine-readable evidence.

A generation is a directory holding exactly:
  capsule/            the materialized installed tree
  capsule.zip         the deterministic archive published beside it

``verify`` checks, all read-only and fail-closed:
  - structure: the generation holds exactly the capsule tree and its archive;
  - manifest: the on-disk component manifest (json + canonical + digest) equals
    the manifest re-emitted from the retained session evidence, is schema-valid,
    declares a compatible contract version, and names the requested target;
  - closures: every declared Python and ACP installed file is present with the
    exact size and SHA-256 its inventory records; the console-script entrypoints
    are placed and recorded executable;
  - licenses: every dependency and first-party license the inventories record is
    placed with its exact bytes;
  - dropped evidence: the installed-tree evidence's drop-audit-trail equals the
    inventory-bound ``.dropped`` records of both closures, tagged by closure -
    every declared omission recorded, nothing extra;
  - installed-tree evidence: every file the evidence enumerates exists on disk
    with the recorded digest, size, and mode (this covers the verbatim
    interpreter subtrees, the launchers, and the dependency locks);
  - archive: ``capsule.zip`` is well formed and every entry's bytes match the
    corresponding materialized file exactly.

The ``sbom`` subcommand emits a minimal JSON software bill of materials from the
verified generation.

Usage:
  uv run --no-sync python scripts/verify_desktop_capsule.py verify \\
      --target x86_64-pc-windows-msvc \\
      --generation dist/capsules/x86_64-pc-windows-msvc \\
      --descriptor dist/capsules/x86_64-pc-windows-msvc/capsule-inputs.toml \\
      --descriptor-sha256 <hex> \\
      --input-dir dist/capsules/.cache \\
      --uv-lock uv.lock --package-lock package-lock.json
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import click

from vaultspec_a2a.desktop import (
    CONTRACT_VERSION,
    ApiVersionRange,
    GatewayApiVersion,
    TargetTriple,
    component_manifest_canonical_bytes,
    component_manifest_digest,
    component_manifest_schema,
    contract_versions_compatible,
)
from vaultspec_a2a.desktop.artifacts import (
    ArtifactInputError,
    open_verified_capsule_inputs,
)
from vaultspec_a2a.desktop.capsule_assembly import (
    CAPSULE_ARCHIVE_OUTPUT_NAME,
    CAPSULE_ROOT,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from vaultspec_a2a.desktop.artifacts import VerifiedCapsuleInputSession
    from vaultspec_a2a.desktop.contract import ComponentManifest
    from vaultspec_a2a.desktop.installed_inventory import InstalledClosureInventory

_API_VERSIONS: Final = ApiVersionRange(
    minimum=GatewayApiVersion.V1, maximum=GatewayApiVersion.V1
)

_COMPONENT_MANIFEST: Final = "component-manifest.json"
_CANONICAL_MANIFEST: Final = "component-manifest.canonical.bin"
_MANIFEST_DIGEST: Final = "component-manifest.digest.sha256"
_INSTALLED_EVIDENCE: Final = "installed-tree.cdx.json"
_DROPPED_EVIDENCE_KEY: Final = "vaultspec:dropped-members"
_FILE_MODE_PROPERTY: Final = "vaultspec:file-mode"
_FILE_SIZE_PROPERTY: Final = "vaultspec:file-size"
_READ_CHUNK: Final = 1 << 20
_EXECUTABLE_MODE: Final = "0755"


class VerificationError(RuntimeError):
    """Raised when a capsule generation fails any verification check."""


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Facts gathered while verifying one capsule generation."""

    generation: Path
    manifest: ComponentManifest
    manifest_data: dict[str, Any]
    canonical_digest: str
    installed_file_count: int
    dropped: list[dict[str, object]]


# ---------------------------------------------------------------------------
# Byte helpers
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_READ_CHUNK):
            hasher.update(block)
    return hasher.hexdigest()


def _read_capsule_file(capsule: Path, relative: str, *, label: str) -> Path:
    """Resolve one materialized file inside the capsule tree, fail-closed."""
    candidate = capsule / relative
    if not candidate.is_file():
        raise VerificationError(f"{label} is absent from the capsule tree: {relative}")
    return candidate


# ---------------------------------------------------------------------------
# Structure and manifest
# ---------------------------------------------------------------------------


def _check_structure(generation: Path) -> tuple[Path, Path]:
    """Require the generation to hold exactly the capsule tree and its archive."""
    if not generation.is_dir():
        raise VerificationError(f"generation is not a directory: {generation}")
    capsule = generation / CAPSULE_ROOT
    archive = generation / CAPSULE_ARCHIVE_OUTPUT_NAME
    entries = sorted(entry.name for entry in generation.iterdir())
    if entries != sorted((CAPSULE_ROOT, CAPSULE_ARCHIVE_OUTPUT_NAME)):
        raise VerificationError(
            "generation must hold exactly the capsule tree and its archive; "
            f"found: {', '.join(entries)}"
        )
    if not capsule.is_dir():
        raise VerificationError("capsule tree is missing from the generation")
    if not archive.is_file():
        raise VerificationError("capsule archive is missing from the generation")
    return capsule, archive


def _check_manifest(
    session: VerifiedCapsuleInputSession, capsule: Path, target: TargetTriple
) -> tuple[ComponentManifest, dict[str, Any], str]:
    """Reconcile the on-disk manifest triple against the session-emitted manifest."""
    import jsonschema

    manifest = session.emit_component_manifest(api_versions=_API_VERSIONS)
    canonical = component_manifest_canonical_bytes(manifest)
    digest = component_manifest_digest(manifest)

    stored_canonical = _read_capsule_file(
        capsule, _CANONICAL_MANIFEST, label="canonical manifest"
    ).read_bytes()
    if stored_canonical != canonical:
        raise VerificationError(
            "on-disk canonical manifest bytes do not match the manifest re-emitted "
            "from the verified session"
        )
    stored_digest = (
        _read_capsule_file(capsule, _MANIFEST_DIGEST, label="manifest digest")
        .read_bytes()
        .decode("ascii")
        .strip()
    )
    if stored_digest != digest or stored_digest != _sha256_bytes(stored_canonical):
        raise VerificationError(
            "on-disk manifest digest does not match canonical bytes"
        )

    manifest_data: dict[str, Any] = json.loads(
        _read_capsule_file(capsule, _COMPONENT_MANIFEST, label="component manifest")
        .read_bytes()
        .decode("utf-8")
    )
    try:
        jsonschema.validate(manifest_data, component_manifest_schema())
    except jsonschema.ValidationError as exc:
        raise VerificationError(
            f"component manifest fails JSON Schema validation: {exc.message}"
        ) from None
    if (
        component_manifest_canonical_bytes(manifest.model_validate(manifest_data))
        != canonical
    ):
        raise VerificationError(
            "on-disk component manifest is not consistent with its canonical bytes"
        )
    declared = str(manifest_data.get("contract_version", ""))
    if not contract_versions_compatible(declared, CONTRACT_VERSION):
        raise VerificationError(
            f"manifest contract version {declared!r} is incompatible with "
            f"supported version {CONTRACT_VERSION!r}"
        )
    if manifest_data.get("target") != target.value or manifest.target is not target:
        raise VerificationError("manifest target does not match the requested target")
    return manifest, manifest_data, digest


# ---------------------------------------------------------------------------
# Closures, entrypoints, licenses
# ---------------------------------------------------------------------------


def _check_closure(inventory: InstalledClosureInventory, capsule: Path) -> int:
    """Reconcile one installed closure's declared files against the capsule tree."""
    by_path = {record.relative_path: record for record in inventory.files}
    for record in inventory.files:
        relative = f"{inventory.install_root}/{record.relative_path}"
        placed = _read_capsule_file(capsule, relative, label="installed file")
        if placed.stat().st_size != record.size:
            raise VerificationError(
                f"installed file size does not match its inventory: {relative}"
            )
        if _sha256_file(placed) != record.sha256:
            raise VerificationError(
                f"installed file digest does not match its inventory: {relative}"
            )
    for entrypoint in inventory.entrypoints:
        record = by_path.get(entrypoint)
        if record is None:
            raise VerificationError(
                f"closure entrypoint names no placed file: {entrypoint}"
            )
        if record.mode != _EXECUTABLE_MODE:
            raise VerificationError(
                f"closure entrypoint is not recorded executable: {entrypoint}"
            )
    for license_record in inventory.licenses:
        relative_path = license_record.relative_path
        if relative_path not in by_path:
            raise VerificationError(
                f"installed license names no placed file: {relative_path}"
            )
        placed = capsule / inventory.install_root / relative_path
        if _sha256_file(placed) != license_record.sha256:
            raise VerificationError(
                "installed license bytes do not match their record: "
                f"{license_record.relative_path}"
            )
    return len(inventory.files)


# ---------------------------------------------------------------------------
# Installed-tree evidence and drop-audit-trail
# ---------------------------------------------------------------------------


def _expected_drop_audit_trail(
    session: VerifiedCapsuleInputSession,
) -> list[dict[str, object]]:
    """Recompute the drop-audit-trail from the inventory-bound ``.dropped`` records."""
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


def _check_installed_tree_evidence(
    session: VerifiedCapsuleInputSession,
    capsule: Path,
    manifest_digest: str,
) -> list[dict[str, object]]:
    """Reconcile the installed-tree evidence against disk and the drop-audit-trail."""
    document = json.loads(
        _read_capsule_file(
            capsule, _INSTALLED_EVIDENCE, label="installed-tree evidence"
        )
        .read_bytes()
        .decode("utf-8")
    )
    metadata = document.get("metadata", {}).get("component", {})
    properties = {
        prop.get("name"): prop.get("value") for prop in metadata.get("properties", [])
    }
    if properties.get("vaultspec:component-manifest-sha256") != manifest_digest:
        raise VerificationError(
            "installed-tree evidence does not bind the component manifest digest"
        )

    components = document.get("components", [])
    if not components:
        raise VerificationError("installed-tree evidence enumerates no files")
    for component in components:
        name = component.get("name", "")
        placed = _read_capsule_file(capsule, name, label="evidence-listed file")
        hashes = {
            entry.get("alg"): entry.get("content")
            for entry in component.get("hashes", [])
        }
        props = {
            prop.get("name"): prop.get("value")
            for prop in component.get("properties", [])
        }
        if _sha256_file(placed) != hashes.get("SHA-256"):
            raise VerificationError(
                f"evidence-listed file digest does not match disk: {name}"
            )
        if str(placed.stat().st_size) != props.get(_FILE_SIZE_PROPERTY):
            raise VerificationError(
                f"evidence-listed file size does not match disk: {name}"
            )
        if props.get(_FILE_MODE_PROPERTY) not in {"0644", "0755"}:
            raise VerificationError(f"evidence-listed file mode is invalid: {name}")

    declared = document.get(_DROPPED_EVIDENCE_KEY, [])
    expected = _expected_drop_audit_trail(session)
    if declared != expected:
        raise VerificationError(
            "installed-tree drop-audit-trail does not match the inventory-bound "
            "dropped records of the two closures"
        )
    return expected


# ---------------------------------------------------------------------------
# Archive integrity
# ---------------------------------------------------------------------------


def _check_archive(capsule: Path, archive: Path) -> None:
    """Reconcile every archive entry's bytes against the materialized capsule tree."""
    try:
        handle = zipfile.ZipFile(archive, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise VerificationError(f"cannot open capsule archive: {exc}") from None
    with handle as archive_zip:
        if archive_zip.testzip() is not None:
            raise VerificationError("capsule archive contains a corrupt entry")
        entry_names = [
            name for name in archive_zip.namelist() if not name.endswith("/")
        ]
        prefix = f"{CAPSULE_ROOT}/"
        archived: set[str] = set()
        for name in entry_names:
            if not name.startswith(prefix):
                raise VerificationError(
                    f"capsule archive entry escapes the capsule root: {name}"
                )
            relative = name[len(prefix) :]
            archived.add(relative)
            placed = _read_capsule_file(capsule, relative, label="archived file")
            if _sha256_bytes(archive_zip.read(name)) != _sha256_file(placed):
                raise VerificationError(
                    f"archive entry does not match its materialized file: {name}"
                )
    on_disk = {
        str(path.relative_to(capsule).as_posix())
        for path in capsule.rglob("*")
        if path.is_file()
    }
    if archived != on_disk:
        raise VerificationError(
            "capsule archive entry set does not match the materialized capsule tree"
        )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def verify_generation(
    *,
    target: TargetTriple,
    generation: Path,
    descriptor_path: Path,
    descriptor_sha256: str,
    input_dir: Path,
    uv_lock: Path,
    package_lock: Path,
) -> VerificationResult:
    """Run every generation check against the pinned inputs, read-only."""
    capsule, archive = _check_structure(generation)
    try:
        with open_verified_capsule_inputs(
            descriptor_path,
            expected_descriptor_sha256=descriptor_sha256,
            input_dir=input_dir,
            uv_lock_path=uv_lock,
            package_lock_path=package_lock,
        ) as session:
            if session.descriptor.target is not target:
                raise VerificationError(
                    "descriptor target does not match the requested target"
                )
            manifest, manifest_data, digest = _check_manifest(session, capsule, target)
            installed = _check_closure(session.python_installed, capsule)
            installed += _check_closure(session.acp_installed, capsule)
            dropped = _check_installed_tree_evidence(session, capsule, digest)
    except ArtifactInputError as exc:
        raise VerificationError(f"pinned inputs failed to open: {exc}") from None
    _check_archive(capsule, archive)
    return VerificationResult(
        generation=generation,
        manifest=manifest,
        manifest_data=manifest_data,
        canonical_digest=digest,
        installed_file_count=installed,
        dropped=dropped,
    )


def _build_sbom(result: VerificationResult) -> dict[str, Any]:
    """Build a minimal JSON SBOM from the verified generation."""
    return {
        "sbom_version": "2",
        "generation": str(result.generation),
        "canonical_digest": result.canonical_digest,
        "identity": result.manifest_data.get("identity", {}),
        "target": result.manifest_data.get("target"),
        "contract_version": result.manifest_data.get("contract_version"),
        "components": [
            {
                "kind": asset.get("kind"),
                "version": asset.get("version"),
                "license": asset.get("license"),
                "digest": asset.get("digest"),
            }
            for asset in result.manifest_data.get("assets", [])
        ],
        "entrypoints": result.manifest_data.get("entrypoints", {}),
        "installed_file_count": result.installed_file_count,
        "dropped_members": result.dropped,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _common_options(command: Callable[..., Any]) -> Callable[..., Any]:
    options = (
        click.option(
            "--target",
            required=True,
            type=click.Choice([t.value for t in TargetTriple]),
            help="Target triple; must match the pinned descriptor's target.",
        ),
        click.option(
            "--generation",
            required=True,
            type=click.Path(exists=True, file_okay=False, path_type=Path),
            help="The per-target generation directory to verify.",
        ),
        click.option(
            "--descriptor",
            "descriptor",
            required=True,
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            help="Pinned capsule input descriptor the generation was built from.",
        ),
        click.option(
            "--descriptor-sha256", required=True, help="Expected descriptor SHA-256."
        ),
        click.option(
            "--input-dir",
            required=True,
            type=click.Path(exists=True, file_okay=False, path_type=Path),
            help="Content-addressed input cache the descriptor was pinned against.",
        ),
        click.option(
            "--uv-lock",
            required=True,
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            help="uv.lock whose digest the descriptor pins.",
        ),
        click.option(
            "--package-lock",
            required=True,
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            help="package-lock.json whose digest the descriptor pins.",
        ),
    )
    for option in reversed(options):
        command = option(command)
    return command


@click.group()
def cli() -> None:
    """A2A desktop capsule generation verification and SBOM tools."""


@cli.command()
@click.option(
    "--quiet", is_flag=True, default=False, help="Print only the status line."
)
@_common_options
def verify(
    target: str,
    generation: Path,
    descriptor: Path,
    descriptor_sha256: str,
    input_dir: Path,
    uv_lock: Path,
    package_lock: Path,
    quiet: bool,
) -> None:
    """Verify one complete capsule GENERATION against its pinned inputs."""
    if not quiet:
        click.echo(f"Verifying generation {generation}...")
    try:
        result = verify_generation(
            target=TargetTriple(target),
            generation=generation,
            descriptor_path=descriptor,
            descriptor_sha256=descriptor_sha256,
            input_dir=input_dir,
            uv_lock=uv_lock,
            package_lock=package_lock,
        )
    except VerificationError as exc:
        click.echo(f"FAIL: {exc}", err=True)
        sys.exit(1)
    if not quiet:
        click.echo(f"  target:            {result.manifest_data.get('target')}")
        click.echo(f"  canonical digest:  {result.canonical_digest}")
        click.echo(f"  installed files:   {result.installed_file_count}")
        click.echo(f"  dropped members:   {len(result.dropped)}")
    click.echo("OK")


@cli.command()
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Write SBOM JSON to FILE instead of stdout.",
)
@_common_options
def sbom(
    target: str,
    generation: Path,
    descriptor: Path,
    descriptor_sha256: str,
    input_dir: Path,
    uv_lock: Path,
    package_lock: Path,
    output: Path | None,
) -> None:
    """Emit a minimal JSON SBOM for a verified capsule GENERATION."""
    try:
        result = verify_generation(
            target=TargetTriple(target),
            generation=generation,
            descriptor_path=descriptor,
            descriptor_sha256=descriptor_sha256,
            input_dir=input_dir,
            uv_lock=uv_lock,
            package_lock=package_lock,
        )
    except VerificationError as exc:
        click.echo(f"FAIL (verification): {exc}", err=True)
        sys.exit(1)
    sbom_json = json.dumps(_build_sbom(result), indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.write_text(sbom_json, encoding="utf-8")
        click.echo(f"SBOM written to {output}")
    else:
        click.echo(sbom_json, nl=False)


if __name__ == "__main__":
    cli()
