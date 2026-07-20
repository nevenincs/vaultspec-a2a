"""A2A desktop capsule standalone verifier.

Verifies a desktop capsule archive (produced by build_desktop_capsule.py)
without requiring a source checkout.  Requires only the capsule ZIP path and
the installed vaultspec-a2a package for schema and manifest types.

Checks performed by `verify`:
  - All required capsule entries are present.
  - The embedded manifest validates against the canonical JSON Schema.
  - The declared contract version is compatible with the consumer build.
  - Each asset entry in the ZIP matches the SHA-256 digest recorded in the
    manifest.
  - The component-manifest.canonical.bin entry is consistent with the
    component-manifest.json (re-derived from the manifest object).
  - The component-manifest.digest.sha256 matches SHA-256 of canonical.bin.

The `sbom` subcommand emits a minimal JSON software bill of materials that
lists the component identity, the four base-closure assets with their versions
and licenses, and the Python dependency closure extracted from pylock.toml.

Usage:
  uv run --no-sync python scripts/verify_desktop_capsule.py verify \\
      path/to/x86_64-pc-windows-msvc.zip

  uv run --no-sync python scripts/verify_desktop_capsule.py sbom \\
      path/to/x86_64-pc-windows-msvc.zip
"""

from __future__ import annotations

import hashlib
import json
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import click

from vaultspec_a2a.desktop import (
    CONTRACT_VERSION,
    ComponentAssetKind,
    ComponentManifest,
    component_manifest_canonical_bytes,
    component_manifest_schema,
    contract_versions_compatible,
)

# Fixed archive paths that every capsule must contain.
_MANIFEST_JSON: Final = "component-manifest.json"
_MANIFEST_CANONICAL: Final = "component-manifest.canonical.bin"
_MANIFEST_DIGEST: Final = "component-manifest.digest.sha256"
_PYLOCK_PATH: Final = "a2a/pylock.toml"
_REQUIRED_ASSET_PATHS: Final = {
    ComponentAssetKind.PYTHON_RUNTIME: "assets/python-runtime",
    ComponentAssetKind.NODE_RUNTIME: "assets/node-runtime",
    ComponentAssetKind.ACP_ADAPTER: "assets/acp-adapter",
    ComponentAssetKind.A2A_DISTRIBUTION: "assets/a2a-distribution",
}

_READ_CHUNK: Final = 1 << 20  # 1 MiB


class VerificationError(RuntimeError):
    """Raised when a capsule fails any verification check."""


# ---------------------------------------------------------------------------
# Core verification logic
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Collation of all facts gathered during capsule verification."""

    capsule_path: Path
    manifest: ComponentManifest
    manifest_data: dict[str, Any]
    canonical_digest: str
    zip_names: frozenset[str]
    pylock_packages: list[dict[str, Any]]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_stream(zf: zipfile.ZipFile, name: str) -> str:
    hasher = hashlib.sha256()
    with zf.open(name) as handle:
        while block := handle.read(_READ_CHUNK):
            hasher.update(block)
    return hasher.hexdigest()


def _check_required_entries(zip_names: frozenset[str]) -> None:
    missing = []
    for required in (
        _MANIFEST_JSON,
        _MANIFEST_CANONICAL,
        _MANIFEST_DIGEST,
        _PYLOCK_PATH,
        *_REQUIRED_ASSET_PATHS.values(),
    ):
        if required not in zip_names:
            missing.append(required)
    if missing:
        raise VerificationError(
            f"capsule is missing required entries: {', '.join(missing)}"
        )


def _validate_schema(manifest_data: dict[str, Any]) -> ComponentManifest:
    import jsonschema

    schema = component_manifest_schema()
    try:
        jsonschema.validate(manifest_data, schema)
    except jsonschema.ValidationError as exc:
        raise VerificationError(
            f"manifest fails JSON Schema validation: {exc.message}"
        ) from None
    return ComponentManifest.model_validate(manifest_data)


def _check_contract_version(manifest_data: dict[str, Any]) -> None:
    declared = str(manifest_data.get("contract_version", ""))
    if not contract_versions_compatible(declared, CONTRACT_VERSION):
        raise VerificationError(
            f"manifest contract version {declared!r} is incompatible with "
            f"supported version {CONTRACT_VERSION!r}"
        )


def _check_asset_digests(
    zf: zipfile.ZipFile,
    manifest_data: dict[str, Any],
) -> None:
    assets: list[dict[str, Any]] = manifest_data.get("assets", [])
    by_kind = {item["kind"]: item for item in assets}
    for kind, archive_path in _REQUIRED_ASSET_PATHS.items():
        asset = by_kind.get(kind.value)
        if asset is None:
            raise VerificationError(
                f"manifest does not declare asset kind {kind.value!r}"
            )
        expected = asset.get("digest", "")
        actual = _sha256_stream(zf, archive_path)
        if actual != expected:
            raise VerificationError(
                f"asset digest mismatch for {archive_path}:\n"
                f"  manifest: {expected}\n"
                f"  actual:   {actual}"
            )


def _check_canonical_consistency(
    zf: zipfile.ZipFile,
    manifest: ComponentManifest,
) -> str:
    """Verify canonical bytes round-trip and digest file; return the digest."""
    stored_canonical = zf.read(_MANIFEST_CANONICAL)
    stored_digest = zf.read(_MANIFEST_DIGEST).decode("ascii").strip()

    recomputed_canonical = component_manifest_canonical_bytes(manifest)
    if stored_canonical != recomputed_canonical:
        raise VerificationError(
            "canonical bytes in capsule do not match re-derived canonical bytes "
            "from the embedded manifest — the manifest may have been tampered with"
        )

    recomputed_digest = _sha256_bytes(stored_canonical)
    if stored_digest != recomputed_digest:
        raise VerificationError(
            f"canonical digest file mismatch:\n"
            f"  stored:     {stored_digest}\n"
            f"  recomputed: {recomputed_digest}"
        )
    return recomputed_digest


def _parse_pylock_packages(zf: zipfile.ZipFile) -> list[dict[str, Any]]:
    raw = zf.read(_PYLOCK_PATH).decode("utf-8")
    document = tomllib.loads(raw)
    packages: list[dict[str, Any]] = document.get("packages", [])
    return packages


def verify_capsule(capsule_path: Path) -> VerificationResult:
    """Run all verification checks on *capsule_path* and return a result.

    Raises `VerificationError` on any failure.
    """
    try:
        zf_handle = zipfile.ZipFile(capsule_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise VerificationError(f"cannot open capsule archive: {exc}") from None

    with zf_handle as zf:
        zip_names = frozenset(zf.namelist())

        _check_required_entries(zip_names)

        manifest_data: dict[str, Any] = json.loads(
            zf.read(_MANIFEST_JSON).decode("utf-8")
        )
        _check_contract_version(manifest_data)
        manifest = _validate_schema(manifest_data)

        _check_asset_digests(zf, manifest_data)
        canonical_digest = _check_canonical_consistency(zf, manifest)

        pylock_packages = _parse_pylock_packages(zf)

    return VerificationResult(
        capsule_path=capsule_path,
        manifest=manifest,
        manifest_data=manifest_data,
        canonical_digest=canonical_digest,
        zip_names=zip_names,
        pylock_packages=pylock_packages,
    )


# ---------------------------------------------------------------------------
# SBOM emission
# ---------------------------------------------------------------------------


def _build_sbom(result: VerificationResult) -> dict[str, Any]:
    """Build a minimal JSON SBOM from the verified capsule."""
    identity = result.manifest_data.get("identity", {})
    components: list[dict[str, Any]] = []

    for asset in result.manifest_data.get("assets", []):
        components.append(
            {
                "kind": asset.get("kind"),
                "version": asset.get("version"),
                "license": asset.get("license"),
                "digest": asset.get("digest"),
            }
        )

    python_packages = [
        {
            "name": pkg.get("name"),
            "version": pkg.get("version"),
        }
        for pkg in result.pylock_packages
    ]

    entrypoints = result.manifest_data.get("entrypoints", {})

    return {
        "sbom_version": "1",
        "capsule": str(result.capsule_path),
        "canonical_digest": result.canonical_digest,
        "identity": identity,
        "target": result.manifest_data.get("target"),
        "contract_version": result.manifest_data.get("contract_version"),
        "components": components,
        "entrypoints": entrypoints,
        "python_closure": python_packages,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """A2A desktop capsule verification and SBOM tools."""


@cli.command()
@click.argument("capsule", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress per-check progress output; print only the final status line.",
)
def verify(capsule: Path, quiet: bool) -> None:
    """Verify all integrity checks for a CAPSULE archive.

    Validates structure, schema, contract version, asset digests, canonical
    bytes consistency, and canonical digest file.  Exits 0 on success, 1 on
    any failure.
    """
    if not quiet:
        click.echo(f"Verifying {capsule.name}...")

    try:
        result = verify_capsule(capsule)
    except VerificationError as exc:
        click.echo(f"FAIL: {exc}", err=True)
        sys.exit(1)

    if not quiet:
        _print_verification_summary(result)
    click.echo("OK")


def _print_verification_summary(result: VerificationResult) -> None:
    manifest_data = result.manifest_data
    identity = manifest_data.get("identity", {})
    click.echo(f"  component:         {identity.get('name')} {identity.get('version')}")
    click.echo(f"  target:            {manifest_data.get('target')}")
    click.echo(f"  contract version:  {manifest_data.get('contract_version')}")
    click.echo(f"  canonical digest:  {result.canonical_digest}")

    assets = manifest_data.get("assets", [])
    click.echo("  assets:")
    for asset in assets:
        click.echo(
            f"    {asset.get('kind'):20s}  "
            f"{asset.get('version') or '<derived>'!s:12s}  "
            f"{asset.get('license') or 'n/a'!s}"
        )

    entrypoints = manifest_data.get("entrypoints", {})
    click.echo("  entrypoints:")
    for ep_name, ep_data in entrypoints.items():
        cmd = ep_data.get("relative_command", [])
        click.echo(f"    {ep_name}: {'/'.join(str(p) for p in cmd)}")

    click.echo(f"  python closure:    {len(result.pylock_packages)} packages")
    click.echo("  checks:            structure schema contract-version")
    click.echo("                     asset-digests canonical-consistency")


@cli.command()
@click.argument("capsule", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Write SBOM JSON to FILE instead of stdout.",
)
def sbom(capsule: Path, output: Path | None) -> None:
    """Emit a minimal JSON SBOM for a verified CAPSULE archive.

    Verifies the capsule first; emits SBOM only on success.
    """
    try:
        result = verify_capsule(capsule)
    except VerificationError as exc:
        click.echo(f"FAIL (verification): {exc}", err=True)
        sys.exit(1)

    sbom_doc = _build_sbom(result)
    sbom_json = json.dumps(sbom_doc, indent=2, sort_keys=True) + "\n"

    if output is not None:
        output.write_text(sbom_json, encoding="utf-8")
        click.echo(f"SBOM written to {output}")
    else:
        click.echo(sbom_json, nl=False)


if __name__ == "__main__":
    cli()
