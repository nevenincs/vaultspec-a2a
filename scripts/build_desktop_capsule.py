"""A2A desktop capsule builder.

Assembles a target-specific, immutable A2A desktop capsule from pinned
CPython, Node.js, ACP, and package-owned wheel and pylock inputs.  The
produced capsule is a transport artifact containing verbatim source archives
for the four base-closure components.  Unpacking and environment setup are
the dashboard's responsibility.

Capsule layout (single ZIP archive, all targets):
  component-manifest.json           emitted component manifest
  component-manifest.canonical.bin  canonical JSON bytes for cross-language hashing
  component-manifest.digest.sha256  hex SHA-256 of canonical bytes (ASCII, no newline)
  assets/
    python-runtime    CPython 3.13 install_only archive (tar.gz, all targets)
    node-runtime      Node.js 22 archive (tar.gz POSIX; zip Windows)
    acp-adapter       ACP 0.59.0 npm tarball (tgz, all targets)
    a2a-distribution  vaultspec-a2a wheel (whl, all targets)
  a2a/
    pylock.toml       locked base Python dependency closure

Archive format: ZIP with DEFLATE compression for all targets.  All entry
timestamps are set to the minimum ZIP epoch (1980-01-01 00:00:00) for
determinism.  Entries are written in ascending lexicographic path order.

Digest semantics: the SHA-256 digests in the component manifest are computed
from the raw source-artifact bytes stored under assets/.  The standalone
verifier can therefore re-derive every asset digest directly from the
capsule archive without any external source.

Usage:
  uv run --no-sync python scripts/build_desktop_capsule.py build \\
      --target x86_64-pc-windows-msvc \\
      --out-dir dist/capsules

  uv run --no-sync python scripts/build_desktop_capsule.py compute-digests \\
      --target x86_64-pc-windows-msvc
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import Final
from urllib.request import urlopen

import click

from vaultspec_a2a.desktop import (
    ApiVersionRange,
    AssetSource,
    ComponentAssetKind,
    GatewayApiVersion,
    TargetTriple,
    component_manifest_canonical_bytes,
    component_manifest_digest,
    emit_component_manifest,
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_INPUTS_FILE: Final = _REPO_ROOT / "scripts" / "desktop_capsule_inputs.toml"

# Fixed archive paths for each base-closure asset kind inside the capsule ZIP.
_ASSET_PATH: Final[dict[ComponentAssetKind, str]] = {
    ComponentAssetKind.PYTHON_RUNTIME: "assets/python-runtime",
    ComponentAssetKind.NODE_RUNTIME: "assets/node-runtime",
    ComponentAssetKind.ACP_ADAPTER: "assets/acp-adapter",
    ComponentAssetKind.A2A_DISTRIBUTION: "assets/a2a-distribution",
}

_MANIFEST_JSON: Final = "component-manifest.json"
_MANIFEST_CANONICAL: Final = "component-manifest.canonical.bin"
_MANIFEST_DIGEST: Final = "component-manifest.digest.sha256"
_PYLOCK_PATH: Final = "a2a/pylock.toml"

# Minimum ZIP timestamp: deterministic epoch for all archive entries.
_ZIP_EPOCH: Final = (1980, 1, 1, 0, 0, 0)
_READ_CHUNK: Final = 1 << 20  # 1 MiB
_DOWNLOAD_TIMEOUT: Final = 300


class CapsuleError(RuntimeError):
    """Fatal error during capsule assembly or digest computation."""


# ---------------------------------------------------------------------------
# Pinned-inputs loading
# ---------------------------------------------------------------------------


def _load_inputs(
    triple: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return (acp_entry, python_entry, node_entry) for *triple*.

    Each entry is a mapping with at minimum ``version``, ``license``,
    ``url``, and ``sha256`` keys as strings.
    """
    try:
        document = tomllib.loads(_INPUTS_FILE.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CapsuleError(f"cannot read {_INPUTS_FILE.name}: {exc}") from None

    acp: dict[str, str] = document.get("acp", {})
    targets: dict[str, dict[str, dict[str, str]]] = document.get("targets", {})
    if triple not in targets:
        raise CapsuleError(f"target {triple!r} is not declared in {_INPUTS_FILE.name}")
    target_section = targets[triple]
    python_entry: dict[str, str] = target_section.get("python", {})
    node_entry: dict[str, str] = target_section.get("node", {})
    for label, entry in (("acp", acp), ("python", python_entry), ("node", node_entry)):
        for key in ("version", "license", "url", "sha256"):
            if key not in entry:
                raise CapsuleError(f"inputs file is missing [{triple}.{label}].{key}")
    return acp, python_entry, node_entry


# ---------------------------------------------------------------------------
# Download and content-addressed cache
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_READ_CHUNK):
            hasher.update(block)
    return hasher.hexdigest()


def _download_to(url: str, dest: Path) -> None:
    click.echo(f"    downloading {url}")
    try:
        with urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as response:
            dest.write_bytes(response.read())
    except Exception as exc:
        raise CapsuleError(f"download failed for {url}: {exc}") from None


def _is_pinned(sha256: str) -> bool:
    """Return True when *sha256* is a real 64-character hex digest."""
    return len(sha256) == 64 and all(c in "0123456789abcdef" for c in sha256)


def _ensure_cached(
    url: str,
    expected_sha256: str,
    cache_dir: Path,
    *,
    skip_download: bool,
    verify: bool = True,
) -> Path:
    """Return a path to the cached artifact, downloading when absent."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = url.rsplit("/", 1)[-1].replace("%", "_").replace("+", "_")
    cached = cache_dir / safe_name

    if cached.is_file():
        click.echo(f"  cache hit: {safe_name}")
        if verify and _is_pinned(expected_sha256):
            actual = _sha256_file(cached)
            if actual != expected_sha256:
                raise CapsuleError(
                    f"cached {safe_name} digest mismatch:\n"
                    f"  expected: {expected_sha256}\n"
                    f"  actual:   {actual}"
                )
        return cached

    if skip_download:
        raise CapsuleError(
            f"{safe_name} is absent from cache; cannot proceed with --skip-download"
        )

    _download_to(url, cached)
    actual = _sha256_file(cached)
    if verify and _is_pinned(expected_sha256) and actual != expected_sha256:
        cached.unlink(missing_ok=True)
        raise CapsuleError(
            f"download digest mismatch for {safe_name}:\n"
            f"  expected: {expected_sha256}\n"
            f"  actual:   {actual}\n"
            f"Update sha256 in {_INPUTS_FILE.name} if the upstream release changed."
        )
    return cached


# ---------------------------------------------------------------------------
# Wheel and pylock construction
# ---------------------------------------------------------------------------


def _build_env() -> dict[str, str]:
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    env["UV_NO_PROGRESS"] = "1"
    for name in ("PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"):
        env.pop(name, None)
    return env


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 600,
) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        rendered = subprocess.list2cmdline(command)
        raise CapsuleError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _build_wheel_from_head(sandbox: Path) -> Path:
    """Build the A2A wheel from a clean git archive of HEAD.

    Builds into *sandbox* which is created if absent.  Returns the path to
    the single wheel file.
    """
    git = shutil.which("git")
    uv = shutil.which("uv")
    if git is None or uv is None:
        raise CapsuleError("git and uv must be on PATH to build the capsule wheel")

    sandbox.mkdir(parents=True, exist_ok=True)
    env = _build_env()

    source_archive = sandbox / "source.tar"
    _run(
        [git, "archive", "--format=tar", "--output", str(source_archive), "HEAD"],
        cwd=_REPO_ROOT,
        env=env,
    )
    source_root = sandbox / "source"
    source_root.mkdir()
    with tarfile.open(source_archive, mode="r:") as archive:
        archive.extractall(source_root, filter="data")

    dist_dir = sandbox / "dist"
    dist_dir.mkdir()
    _run(
        [uv, "build", "--wheel", "--out-dir", str(dist_dir), "--no-sources"],
        cwd=source_root,
        env=env,
    )
    wheels = list(dist_dir.glob("vaultspec_a2a-*.whl"))
    if len(wheels) != 1:
        raise CapsuleError(f"expected one wheel from uv build, got: {wheels}")
    return wheels[0]


def _export_pylock(sandbox: Path) -> Path:
    """Export the locked base Python dependency closure to *sandbox*/pylock.toml."""
    uv = shutil.which("uv")
    if uv is None:
        raise CapsuleError("uv must be on PATH to export the pylock")

    sandbox.mkdir(parents=True, exist_ok=True)
    pylock = sandbox / "pylock.toml"
    env = _build_env()
    _run(
        [
            uv,
            "export",
            "--format",
            "pylock.toml",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(pylock),
        ],
        cwd=_REPO_ROOT,
        env=env,
    )
    if not pylock.is_file():
        raise CapsuleError("uv export did not produce pylock.toml")
    return pylock


# ---------------------------------------------------------------------------
# Capsule archive assembly
# ---------------------------------------------------------------------------


def _assemble_capsule(
    capsule_zip: Path,
    *,
    asset_files: dict[ComponentAssetKind, Path],
    pylock: Path,
    manifest_json: bytes,
    canonical_bytes: bytes,
    digest_hex: str,
) -> None:
    """Write the deterministic capsule ZIP to *capsule_zip*."""
    entries: list[tuple[str, bytes]] = [
        (_MANIFEST_JSON, manifest_json),
        (_MANIFEST_CANONICAL, canonical_bytes),
        (_MANIFEST_DIGEST, digest_hex.encode("ascii")),
        (_PYLOCK_PATH, pylock.read_bytes()),
    ]
    for kind, src in asset_files.items():
        entries.append((_ASSET_PATH[kind], src.read_bytes()))

    entries.sort(key=lambda pair: pair[0])
    with zipfile.ZipFile(capsule_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for archive_path, data in entries:
            info = zipfile.ZipInfo(archive_path, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)


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
    help="Target triple for the assembled capsule.",
)
@click.option(
    "--out-dir",
    required=True,
    type=click.Path(),
    help="Directory to write the capsule archive and detached manifest.",
)
@click.option(
    "--cache-dir",
    default=None,
    type=click.Path(),
    help="Content-addressed download cache.  Defaults to <out-dir>/.cache.",
)
@click.option(
    "--skip-download",
    is_flag=True,
    default=False,
    help="Use cached inputs only; fail if any input is absent.",
)
def build(
    target: str,
    out_dir: str,
    cache_dir: str | None,
    skip_download: bool,
) -> None:
    """Assemble a deterministic desktop capsule for TARGET.

    Produces <out-dir>/<target>.zip and <out-dir>/<target>.manifest.json.
    The manifest JSON is also embedded inside the ZIP for self-contained
    verification.
    """
    triple = TargetTriple(target)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out / ".cache"

    try:
        _run_build(triple, out, cache, skip_download=skip_download)
    except CapsuleError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


def _run_build(
    triple: TargetTriple,
    out: Path,
    cache: Path,
    *,
    skip_download: bool,
) -> None:
    acp_entry, python_entry, node_entry = _load_inputs(triple.value)

    click.echo(f"[1/5] Acquiring pinned inputs for {triple.value}...")
    python_archive = _ensure_cached(
        python_entry["url"],
        python_entry["sha256"],
        cache / "python",
        skip_download=skip_download,
    )
    node_archive = _ensure_cached(
        node_entry["url"],
        node_entry["sha256"],
        cache / "node",
        skip_download=skip_download,
    )
    acp_archive = _ensure_cached(
        acp_entry["url"],
        acp_entry["sha256"],
        cache / "acp",
        skip_download=skip_download,
    )

    click.echo("[2/5] Building wheel from git HEAD and exporting pylock...")
    with tempfile.TemporaryDirectory(prefix="vaultspec-capsule-") as tmp_str:
        tmp = Path(tmp_str)
        wheel = _build_wheel_from_head(tmp / "wheel")
        pylock = _export_pylock(tmp / "pylock")

        click.echo("[3/5] Emitting component manifest...")
        manifest = emit_component_manifest(
            target=triple,
            api_versions=ApiVersionRange(
                minimum=GatewayApiVersion.V1,
                maximum=GatewayApiVersion.V1,
            ),
            assets=[
                AssetSource(
                    kind=ComponentAssetKind.PYTHON_RUNTIME,
                    path=python_archive,
                    version=python_entry["version"],
                    license=python_entry["license"],
                ),
                AssetSource(
                    kind=ComponentAssetKind.A2A_DISTRIBUTION,
                    path=wheel,
                ),
                AssetSource(
                    kind=ComponentAssetKind.NODE_RUNTIME,
                    path=node_archive,
                    version=node_entry["version"],
                    license=node_entry["license"],
                ),
                AssetSource(
                    kind=ComponentAssetKind.ACP_ADAPTER,
                    path=acp_archive,
                    version=acp_entry["version"],
                    license=acp_entry["license"],
                ),
            ],
            uv_lock_path=_REPO_ROOT / "uv.lock",
            package_lock_path=_REPO_ROOT / "package-lock.json",
        )

        canonical = component_manifest_canonical_bytes(manifest)
        digest_hex = component_manifest_digest(manifest)
        manifest_payload = manifest.model_dump(mode="json")
        manifest_json = (
            json.dumps(manifest_payload, indent=2, sort_keys=True).encode("utf-8")
            + b"\n"
        )

        click.echo("[4/5] Assembling capsule archive...")
        capsule_zip = out / f"{triple.value}.zip"
        _assemble_capsule(
            capsule_zip,
            asset_files={
                ComponentAssetKind.PYTHON_RUNTIME: python_archive,
                ComponentAssetKind.NODE_RUNTIME: node_archive,
                ComponentAssetKind.ACP_ADAPTER: acp_archive,
                ComponentAssetKind.A2A_DISTRIBUTION: wheel,
            },
            pylock=pylock,
            manifest_json=manifest_json,
            canonical_bytes=canonical,
            digest_hex=digest_hex,
        )
        detached = out / f"{triple.value}.manifest.json"
        detached.write_bytes(manifest_json)

        click.echo("[5/5] Done.")
        size_mb = capsule_zip.stat().st_size / (1024 * 1024)
        click.echo(f"  capsule:           {capsule_zip}")
        click.echo(f"  capsule size:      {size_mb:.1f} MiB")
        click.echo(f"  manifest:          {detached}")
        click.echo(f"  canonical digest:  {digest_hex}")


@cli.command("compute-digests")
@click.option(
    "--target",
    required=True,
    type=click.Choice([t.value for t in TargetTriple]),
    help="Target triple whose inputs should be downloaded and hashed.",
)
@click.option(
    "--cache-dir",
    default=None,
    type=click.Path(),
    help="Download cache directory.",
)
def compute_digests(target: str, cache_dir: str | None) -> None:
    """Download pinned inputs for TARGET and print their SHA-256 digests.

    Use this command to bootstrap the sha256 values in
    desktop_capsule_inputs.toml after selecting new upstream release URLs.
    """
    try:
        _run_compute_digests(target, cache_dir)
    except CapsuleError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


def _run_compute_digests(target: str, cache_dir: str | None) -> None:
    acp_entry, python_entry, node_entry = _load_inputs(target)
    prefix = "vaultspec-digests-"
    cache = Path(cache_dir) if cache_dir else Path(tempfile.mkdtemp(prefix=prefix))
    click.echo(f"Computing digests for {target} (cache: {cache})...")

    python_archive = _ensure_cached(
        python_entry["url"],
        python_entry["sha256"],
        cache / "python",
        skip_download=False,
        verify=False,
    )
    python_sha256 = _sha256_file(python_archive)

    node_archive = _ensure_cached(
        node_entry["url"],
        node_entry["sha256"],
        cache / "node",
        skip_download=False,
        verify=False,
    )
    node_sha256 = _sha256_file(node_archive)

    acp_archive = _ensure_cached(
        acp_entry["url"],
        acp_entry["sha256"],
        cache / "acp",
        skip_download=False,
        verify=False,
    )
    acp_sha256 = _sha256_file(acp_archive)

    click.echo("")
    click.echo("# --- paste into desktop_capsule_inputs.toml ---")
    click.echo("# [acp]")
    click.echo(f'sha256 = "{acp_sha256}"')
    click.echo("")
    click.echo(f"# [targets.{target}.python]")
    click.echo(f'sha256 = "{python_sha256}"')
    click.echo("")
    click.echo(f"# [targets.{target}.node]")
    click.echo(f'sha256 = "{node_sha256}"')


if __name__ == "__main__":
    cli()
