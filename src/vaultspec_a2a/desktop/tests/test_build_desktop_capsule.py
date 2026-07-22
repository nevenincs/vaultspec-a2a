"""Prove the reworked capsule build (consume) stage against a real descriptor.

The offline unit tests exercise the build's pure reservation-mapping helpers
against a hand-built assembly plan. The service-marked end-to-end test drives
the real preparation authority (``prepare_capsule_inputs`` with an injected
offline byte-stream seam and real small archives) to mint a real pinned
descriptor, then runs the reworked build against it and pins the produced
generation: both installed closures, both verbatim interpreter subtrees, the
product launchers, the dependency locks, the component manifest and its
canonical/digest evidence, the complete installed-tree evidence, and the single
final deterministic archive published beside the tree.

No mocks, stubs, or expected failures: the offline stream seam yields real
archive bytes, and every assertion reads real materialized files.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import importlib.util
import io
import json
import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from vaultspec_a2a.desktop.artifacts import open_verified_capsule_inputs
from vaultspec_a2a.desktop.capsule_assembly import (
    CAPSULE_ARCHIVE_OUTPUT_NAME,
    CapsuleAssemblyPlan,
    PlanReservationRole,
    ReservedTreeFile,
)
from vaultspec_a2a.desktop.capsule_preparation import prepare_capsule_inputs
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.tests._capsule_inputs import _sha256, _sha512_sri

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

_REPO_ROOT: Final = Path(__file__).resolve().parents[4]
_BUILD_SCRIPT: Final = _REPO_ROOT / "scripts" / "build_desktop_capsule.py"
_ACP_ROOT: Final = "@agentclientprotocol/claude-agent-acp"
_SDK: Final = "@anthropic-ai/claude-agent-sdk-linux-x64"
_TARGET: Final = TargetTriple.LINUX_X86_64
_NODE_STEM: Final = "node-v22.17.0-linux-x64"
_EPOCH: Final = 1_700_000_000
# One real wheel member the library-runtime layout deterministically drops, so
# the build's drop-audit-trail has a real non-empty record to surface.
_DROPPED_SCRIPT: Final = "click-8.3.1.data/scripts/click-tool"


def _load_build_module() -> ModuleType:
    """Load the standalone build script as an importable module by its path."""
    spec = importlib.util.spec_from_file_location(
        "build_desktop_capsule", _BUILD_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BUILD: Final = _load_build_module()


# ---------------------------------------------------------------------------
# Offline unit tests: reservation-mapping helpers
# ---------------------------------------------------------------------------


def _plan(files: tuple[ReservedTreeFile, ...]) -> CapsuleAssemblyPlan:
    return CapsuleAssemblyPlan(
        target=_TARGET,
        files=files,
        subtrees=(),
        archive_output_name=CAPSULE_ARCHIVE_OUTPUT_NAME,
        known_aggregate_bytes=0,
    )


def test_single_reservation_returns_the_sole_role_holder() -> None:
    manifest = ReservedTreeFile(
        path="component-manifest.json",
        role=PlanReservationRole.COMPONENT_MANIFEST,
        mode=0o644,
        size=None,
    )
    plan = _plan((manifest,))
    assert (
        _BUILD._single_reservation(plan, PlanReservationRole.COMPONENT_MANIFEST)
        is manifest
    )


def test_single_reservation_fails_closed_when_absent() -> None:
    plan = _plan(())
    with pytest.raises(_BUILD.CapsuleBuildError, match="exactly one"):
        _BUILD._single_reservation(plan, PlanReservationRole.INSTALLED_EVIDENCE)


def test_single_reservation_fails_closed_when_duplicated() -> None:
    files = tuple(
        ReservedTreeFile(
            path=path,
            role=PlanReservationRole.COMPONENT_MANIFEST,
            mode=0o644,
            size=None,
        )
        for path in ("component-manifest.json", "component-manifest-2.json")
    )
    plan = _plan(files)
    with pytest.raises(_BUILD.CapsuleBuildError, match="exactly one"):
        _BUILD._single_reservation(plan, PlanReservationRole.COMPONENT_MANIFEST)


def test_lock_reservations_map_both_locks_by_basename() -> None:
    uv = ReservedTreeFile(
        path="locks/uv.lock",
        role=PlanReservationRole.DEPENDENCY_LOCK,
        mode=0o644,
        size=12,
    )
    package = ReservedTreeFile(
        path="locks/package-lock.json",
        role=PlanReservationRole.DEPENDENCY_LOCK,
        mode=0o644,
        size=34,
    )
    plan = _plan((uv, package))
    assert _BUILD._lock_reservations(plan) == (uv, package)


def test_lock_reservations_fail_closed_without_both_locks() -> None:
    uv = ReservedTreeFile(
        path="locks/uv.lock",
        role=PlanReservationRole.DEPENDENCY_LOCK,
        mode=0o644,
        size=12,
    )
    plan = _plan((uv,))
    with pytest.raises(_BUILD.CapsuleBuildError, match="both dependency locks"):
        _BUILD._lock_reservations(plan)


def test_windows_launcher_stub_is_required_for_a_windows_target() -> None:
    with pytest.raises(
        _BUILD.CapsuleBuildError, match="requires --launcher-stub-donor"
    ):
        _BUILD._acquire_windows_launcher_stub(None)


# ---------------------------------------------------------------------------
# Offline real-archive builders for the end-to-end descriptor
# ---------------------------------------------------------------------------


def _runtime_tar_gz(root: str, members: dict[str, bytes]) -> bytes:
    """Build a real gzipped tar with one ``root/`` prefix over every member."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(payload)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))
    return gzip.compress(raw.getvalue(), mtime=0)


def _npm_tarball(
    name: str,
    version: str,
    license_expression: str,
    license_path: str,
    *,
    bin_map: dict[str, str] | None = None,
) -> bytes:
    document: dict[str, object] = {
        "name": name,
        "version": version,
        "license": license_expression,
    }
    if bin_map is not None:
        document["bin"] = bin_map
    members = (
        ("package/package.json", json.dumps(document).encode()),
        (license_path, f"{license_expression} license text\n".encode()),
        ("package/dist/index.js", b"#!/usr/bin/env node\n"),
    )
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path, payload in members:
            info = tarfile.TarInfo(path)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
    return gzip.compress(raw.getvalue(), mtime=0)


def _click_wheel_with_dropped_script() -> tuple[str, str, str, int, bytes]:
    """Build a real click wheel carrying one ``.data/scripts`` member.

    The library-runtime install layout deterministically drops ``.data/scripts``
    members (they are outside the capsule's executable surface), so the built
    closure's installed inventory carries one real ``InstalledDroppedRecord`` the
    build's drop-audit-trail must surface. Returns (url, version, sha256, size,
    bytes).
    """
    dist_info = "click-8.3.1.dist-info"
    license_member = f"{dist_info}/licenses/LICENSE.txt"
    members = {
        f"{dist_info}/METADATA": (
            b"Metadata-Version: 2.4\nName: click\nVersion: 8.3.1\n"
            b"License-Expression: BSD-3-Clause\nLicense-File: LICENSE.txt\n"
        ),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        license_member: b"BSD-3-Clause license text\n",
        _DROPPED_SCRIPT: b"#!/bin/sh\necho click-tool\n",
    }
    record_rows = []
    for name, payload in members.items():
        encoded = (
            base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            .decode("ascii")
            .rstrip("=")
        )
        record_rows.append(f"{name},sha256={encoded},{len(payload)}\n")
    record_name = f"{dist_info}/RECORD"
    record_rows.append(f"{record_name},,\n")
    members[record_name] = "".join(record_rows).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    payload = buffer.getvalue()
    url = "https://files.pythonhosted.org/click-8.3.1-py3-none-any.whl"
    return url, "8.3.1", _sha256(payload), len(payload), payload


@contextmanager
def _prepared_inputs(tmp_path: Path) -> Iterator[tuple[Path, str, Path, Path, Path]]:
    """Mint a real pinned descriptor offline; yield the build's read-only inputs."""
    click_url, click_version, click_sha, click_size, click_bytes = (
        _click_wheel_with_dropped_script()
    )
    python_blob = _runtime_tar_gz(
        "python",
        {
            "bin/python3.13": b"#!/bin/sh\necho cpython\n",
            "lib/python3.13/LICENSE.txt": b"PSF-2.0 license text\n",
        },
    )
    node_blob = _runtime_tar_gz(
        _NODE_STEM,
        {"bin/node": b"#!/bin/sh\necho node\n", "LICENSE": b"MIT license text\n"},
    )
    acp_src_blob = _npm_tarball(_ACP_ROOT, "0.59.0", "Apache-2.0", "package/LICENSE")
    acp_root = _npm_tarball(
        _ACP_ROOT,
        "0.59.0",
        "Apache-2.0",
        "package/LICENSE",
        bin_map={"claude-agent-acp": "dist/index.js"},
    )
    sdk = _npm_tarball(
        _SDK, "0.3.207", "LicenseRef-Anthropic-Commercial", "package/LICENSE.md"
    )

    acp_root_url = "https://registry.npmjs.org/claude-agent-acp-0.59.0.tgz"
    sdk_url = "https://registry.npmjs.org/claude-agent-sdk-linux-x64-0.3.207.tgz"
    py_url = (
        "https://github.com/astral-sh/python-build-standalone/releases/download/"
        "20250702/cpython-3.13.5+20250702-x86_64-unknown-linux-gnu-install_only.tar.gz"
    )
    node_url = f"https://nodejs.org/dist/v22.17.0/{_NODE_STEM}.tar.gz"
    acp_src_url = (
        "https://registry.npmjs.org/@agentclientprotocol/claude-agent-acp/-/"
        "claude-agent-acp-0.59.0.tgz"
    )

    uv_lock = f"""version = 1
revision = 3
requires-python = ">=3.13"

[[package]]
name = "vaultspec-a2a"
version = "0.1.0"
source = {{ editable = "." }}
dependencies = [{{ name = "click" }}]

[[package]]
name = "click"
version = "{click_version}"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [
  {{ url = "{click_url}", hash = "sha256:{click_sha}", size = {click_size} }},
]
""".encode()
    package_lock = json.dumps(
        {
            "lockfileVersion": 3,
            "name": "vaultspec-a2a",
            "packages": {
                "": {"dependencies": {_ACP_ROOT: "0.59.0"}, "name": "vaultspec-a2a"},
                f"node_modules/{_ACP_ROOT}": {
                    "dependencies": {_SDK: "0.3.207"},
                    "engines": {"node": ">=22"},
                    "integrity": _sha512_sri(acp_root),
                    "resolved": acp_root_url,
                    "version": "0.59.0",
                },
                f"node_modules/{_SDK}": {
                    "cpu": ["x64"],
                    "engines": {"node": ">=18"},
                    "integrity": _sha512_sri(sdk),
                    "os": ["linux"],
                    "resolved": sdk_url,
                    "version": "0.3.207",
                },
            },
            "requires": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    inputs_toml = f"""[acp]
version = "0.59.0"
license = "Apache-2.0"
url = "{acp_src_url}"
sha256 = "{_sha256(acp_src_blob)}"

[targets.x86_64-unknown-linux-gnu.python]
version = "3.13"
license = "PSF-2.0"
url = "{py_url}"
sha256 = "{_sha256(python_blob)}"

[targets.x86_64-unknown-linux-gnu.node]
version = "22"
license = "MIT"
url = "{node_url}"
sha256 = "{_sha256(node_blob)}"
"""

    streams = {
        click_url: click_bytes,
        acp_root_url: acp_root,
        sdk_url: sdk,
        py_url: python_blob,
        node_url: node_blob,
        acp_src_url: acp_src_blob,
    }

    @contextmanager
    def open_stream(url: str) -> Iterator[io.BytesIO]:
        if url not in streams:
            raise AssertionError(f"unexpected acquisition url: {url}")
        yield io.BytesIO(streams[url])

    cache = tmp_path / "cache"
    cache.mkdir()
    inputs_path = tmp_path / "inputs.toml"
    inputs_path.write_text(inputs_toml, encoding="utf-8")
    uv_path = tmp_path / "uv.lock"
    uv_path.write_bytes(uv_lock)
    package_path = tmp_path / "package-lock.json"
    package_path.write_bytes(package_lock)

    descriptor_path, digest = prepare_capsule_inputs(
        _TARGET,
        inputs_toml=inputs_path,
        uv_lock=uv_path,
        package_lock=package_path,
        repo_root=_REPO_ROOT,
        cache_root=cache,
        output_dir=tmp_path / "prepared",
        source_date_epoch=_EPOCH,
        open_stream=open_stream,
    )
    yield descriptor_path, digest, cache, uv_path, package_path


def _installed_paths(
    descriptor_path: Path, digest: str, cache: Path, uv_path: Path, package_path: Path
) -> dict[str, tuple[int, str]]:
    """Re-open the pinned inputs and return each closure file's (size, sha256)."""
    installed: dict[str, tuple[int, str]] = {}
    with open_verified_capsule_inputs(
        descriptor_path,
        expected_descriptor_sha256=digest,
        input_dir=cache,
        uv_lock_path=uv_path,
        package_lock_path=package_path,
    ) as session:
        for inventory in (session.python_installed, session.acp_installed):
            for record in inventory.files:
                path = f"{inventory.install_root}/{record.relative_path}"
                installed[path] = (record.size, record.sha256)
    return installed


# ---------------------------------------------------------------------------
# Service-marked end-to-end build
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_build_assembles_a_complete_deterministic_generation(tmp_path: Path) -> None:
    with _prepared_inputs(tmp_path) as (descriptor_path, digest, cache, uv, package):
        generation_dir, archive_digest = _BUILD._run_build(
            target=_TARGET,
            descriptor_path=descriptor_path,
            descriptor_sha256=digest,
            input_dir=cache,
            uv_lock=uv,
            package_lock=package,
            out_dir=tmp_path / "out",
            launcher_stub_donor=None,
        )

        capsule = generation_dir / "capsule"
        # Single shared-lease generation, single final publish: the generation
        # holds exactly the capsule tree and its sibling archive, nothing else.
        assert sorted(p.name for p in generation_dir.iterdir()) == [
            "capsule",
            CAPSULE_ARCHIVE_OUTPUT_NAME,
        ]

        # Both closures materialized under their install roots.
        assert (capsule / "runtime/python").is_dir()
        assert (capsule / "runtime/acp").is_dir()
        # Both interpreter subtrees verbatim-projected beside the closures.
        assert (capsule / "runtime/cpython/bin/python3.13").read_bytes() == (
            b"#!/bin/sh\necho cpython\n"
        )
        assert (capsule / "runtime/node/bin/node").read_bytes() == (
            b"#!/bin/sh\necho node\n"
        )

        # Relocatable POSIX product launchers are materialized as real files.
        for launcher in ("bin/vaultspec-a2a", "bin/vaultspec-a2a-mcp"):
            assert (capsule / launcher).is_file()
            assert (capsule / launcher).stat().st_size > 0

        # Dependency locks streamed byte-exact into the tree.
        assert (capsule / "locks/uv.lock").read_bytes() == uv.read_bytes()
        assert (capsule / "locks/package-lock.json").read_bytes() == (
            package.read_bytes()
        )

        # Component manifest contract intact: digest file pins the canonical bytes.
        canonical = (capsule / "component-manifest.canonical.bin").read_bytes()
        stored_digest = (
            (capsule / "component-manifest.digest.sha256").read_bytes().decode("ascii")
        )
        assert stored_digest == hashlib.sha256(canonical).hexdigest()
        manifest_document = json.loads(
            (capsule / "component-manifest.json").read_text(encoding="utf-8")
        )
        assert manifest_document["target"] == _TARGET.value

        # Complete installed-tree evidence covers the materialized tree and
        # surfaces the per-member drop-audit-trail: the click wheel's
        # ``.data/scripts`` member is dropped (outside the library-runtime
        # surface) and recorded auditably, tagged with its closure.
        evidence = json.loads(
            (capsule / "installed-tree.cdx.json").read_text(encoding="utf-8")
        )
        assert evidence["inventory_version"] == "vaultspec-installed-tree-v1"
        assert evidence["components"]
        dropped = evidence[_BUILD._DROPPED_EVIDENCE_KEY]
        assert {
            "closure": "python",
            "source_member": _DROPPED_SCRIPT,
            "reason": "data-scripts",
        }.items() <= next(
            record for record in dropped if record["source_member"] == _DROPPED_SCRIPT
        ).items()
        # ACP tarballs have no ``.data`` members, so nothing ACP is dropped.
        assert all(record["closure"] == "python" for record in dropped)

        # The recorded launcher mode is cross-platform evidence (Windows cannot
        # carry a POSIX exec bit on disk): both product launchers are 0755.
        recorded_mode = {
            component["name"]: next(
                prop["value"]
                for prop in component["properties"]
                if prop["name"] == "vaultspec:file-mode"
            )
            for component in evidence["components"]
        }
        assert recorded_mode["bin/vaultspec-a2a"] == "0755"
        assert recorded_mode["bin/vaultspec-a2a-mcp"] == "0755"

        # Every declared closure file reconciles byte-for-byte on disk.
        for path, (size, sha256) in _installed_paths(
            descriptor_path, digest, cache, uv, package
        ).items():
            payload = (capsule / path).read_bytes()
            assert len(payload) == size
            assert hashlib.sha256(payload).hexdigest() == sha256

        # The single final archive: its digest is returned and its entries are
        # rooted at ``capsule/``.
        archive_path = generation_dir / CAPSULE_ARCHIVE_OUTPUT_NAME
        assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == archive_digest
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.namelist()
            assert all(name.startswith("capsule/") for name in archive.namelist())

        # Determinism: a second generation from the same pinned inputs yields a
        # byte-identical archive.
        _, second_digest = _BUILD._run_build(
            target=_TARGET,
            descriptor_path=descriptor_path,
            descriptor_sha256=digest,
            input_dir=cache,
            uv_lock=uv,
            package_lock=package,
            out_dir=tmp_path / "out-second",
            launcher_stub_donor=None,
        )
        assert second_digest == archive_digest


@pytest.mark.service
def test_build_refuses_to_overwrite_a_prior_generation(tmp_path: Path) -> None:
    with _prepared_inputs(tmp_path) as (descriptor_path, digest, cache, uv, package):
        out_dir = tmp_path / "out"
        _BUILD._run_build(
            target=_TARGET,
            descriptor_path=descriptor_path,
            descriptor_sha256=digest,
            input_dir=cache,
            uv_lock=uv,
            package_lock=package,
            out_dir=out_dir,
            launcher_stub_donor=None,
        )
        with pytest.raises(_BUILD.CapsuleBuildError, match="already exists"):
            _BUILD._run_build(
                target=_TARGET,
                descriptor_path=descriptor_path,
                descriptor_sha256=digest,
                input_dir=cache,
                uv_lock=uv,
                package_lock=package,
                out_dir=out_dir,
                launcher_stub_donor=None,
            )
