"""ACP license derivation proven through the real npm package verifier.

``derive_acp_package_artifact`` round-trips every derived artifact through the
production ``open_verified_acp_package_archive`` rather than asserting against
its own output.  Tarballs here are real gzip-compressed tar archives with a real
package.json and real license members.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from vaultspec_a2a.desktop.capsule_input_authoring import emit_acp_closure_inventory
from vaultspec_a2a.desktop.capsule_license import (
    AcpLicenseOverride,
    CapsuleInputAuthoringError,
    LicenseOverride,
    derive_acp_package_artifact,
    load_acp_license_overrides,
    load_license_overrides,
    validate_license_overrides,
)
from vaultspec_a2a.desktop.closure_inventory import (
    AcpClosureInventory,
    AcpPackageArtifact,
    canonical_closure_inventory_bytes,
)
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.lock_reconciliation import (
    AcpNodeSelection,
    reconcile_acp_closure_lock_bytes,
    resolve_acp_closure_selection,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ACP_ROOT = "@agentclientprotocol/claude-agent-acp"
_NODE_VERSION = "22.17.0"


def _member(name: str, payload: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o644
    return info, payload


def _build_tarball(
    cache_root: Path,
    *,
    name: str = "@scope/example",
    version: str = "2.3.4",
    package_license: str = "MIT",
    license_members: tuple[tuple[str, bytes], ...] = (("package/LICENSE", b"mit\n"),),
) -> tuple[AcpNodeSelection, str, int]:
    """Write one real npm tarball into the cache and return its node selection."""
    members = [
        _member(
            "package/package.json",
            json.dumps(
                {"license": package_license, "name": name, "version": version}
            ).encode(),
        ),
        _member("package/index.js", b"export {};\n"),
        *(_member(path, body) for path, body in license_members),
    ]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for info, payload in members:
            archive.addfile(info, io.BytesIO(payload))
    tarball = gzip.compress(raw.getvalue(), mtime=0)
    sha256 = hashlib.sha256(tarball).hexdigest()
    (cache_root / sha256).write_bytes(tarball)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode(
        "ascii"
    )
    install_path = f"node_modules/{name}"
    node = AcpNodeSelection(
        name=name,
        install_path=install_path,
        version=version,
        url=f"https://registry.example.test/{name}/-/example-{version}.tgz",
        integrity=integrity,
        dependency_paths=(),
    )
    return node, sha256, len(tarball)


def test_derives_a_canonical_spdx_npm_license(tmp_path: Path) -> None:
    node, sha256, size = _build_tarball(tmp_path, package_license="MIT")

    artifact = derive_acp_package_artifact(
        node, cache_root=tmp_path, sha256=sha256, size=size, overrides={}
    )

    assert artifact.license_expression == "MIT"
    assert artifact.license_members == ("package/LICENSE",)
    assert "tarball-license:package/LICENSE" in artifact.redistribution_evidence


def test_derives_a_curated_fallback_for_a_see_license_reference(tmp_path: Path) -> None:
    node, sha256, size = _build_tarball(
        tmp_path,
        name="@anthropic-ai/claude-agent-sdk",
        version="0.3.207",
        package_license="SEE LICENSE IN LICENSE.md",
        license_members=(("package/LICENSE.md", b"(c) proprietary. all rights.\n"),),
    )
    overrides = {
        "@anthropic-ai/claude-agent-sdk": AcpLicenseOverride(
            version="0.3.207",
            expression="LicenseRef-Anthropic-Commercial",
            evidence="package/LICENSE.md proprietary notice",
            license_member="package/LICENSE.md",
        )
    }

    artifact = derive_acp_package_artifact(
        node, cache_root=tmp_path, sha256=sha256, size=size, overrides=overrides
    )

    assert artifact.license_expression == "LicenseRef-Anthropic-Commercial"
    assert artifact.license_members == ("package/LICENSE.md",)
    assert (
        "curated-license-expression:LicenseRef-Anthropic-Commercial"
        in artifact.redistribution_evidence
    )


def test_fails_closed_on_a_see_license_reference_without_an_override(
    tmp_path: Path,
) -> None:
    node, sha256, size = _build_tarball(
        tmp_path,
        package_license="SEE LICENSE IN LICENSE.md",
        license_members=(("package/LICENSE.md", b"proprietary\n"),),
    )

    with pytest.raises(CapsuleInputAuthoringError, match="no curated override"):
        derive_acp_package_artifact(
            node, cache_root=tmp_path, sha256=sha256, size=size, overrides={}
        )


def test_fails_closed_when_the_override_version_does_not_match(tmp_path: Path) -> None:
    node, sha256, size = _build_tarball(
        tmp_path,
        name="@anthropic-ai/claude-agent-sdk",
        version="0.3.207",
        package_license="SEE LICENSE IN LICENSE.md",
        license_members=(("package/LICENSE.md", b"proprietary\n"),),
    )
    overrides = {
        "@anthropic-ai/claude-agent-sdk": AcpLicenseOverride(
            version="9.9.9",
            expression="LicenseRef-Anthropic-Commercial",
            evidence="notice",
            license_member="package/LICENSE.md",
        )
    }

    with pytest.raises(CapsuleInputAuthoringError, match="but the closure locks"):
        derive_acp_package_artifact(
            node, cache_root=tmp_path, sha256=sha256, size=size, overrides=overrides
        )


def test_fails_closed_when_a_canonical_package_ships_no_license_bytes(
    tmp_path: Path,
) -> None:
    node, sha256, size = _build_tarball(
        tmp_path, package_license="MIT", license_members=()
    )

    with pytest.raises(CapsuleInputAuthoringError, match="no recognizable license"):
        derive_acp_package_artifact(
            node, cache_root=tmp_path, sha256=sha256, size=size, overrides={}
        )


def _committed_overrides() -> tuple[
    dict[str, LicenseOverride], dict[str, AcpLicenseOverride]
]:
    toml = _REPO_ROOT / "scripts" / "desktop_capsule_inputs.toml"
    return load_license_overrides(toml), load_acp_license_overrides(toml)


def test_every_committed_override_resolves_against_the_real_locks() -> None:
    wheel_overrides, acp_overrides = _committed_overrides()

    validate_license_overrides(
        wheel_overrides=wheel_overrides,
        acp_overrides=acp_overrides,
        uv_lock_bytes=(_REPO_ROOT / "uv.lock").read_bytes(),
        package_lock_bytes=(_REPO_ROOT / "package-lock.json").read_bytes(),
    )


def test_a_stale_wheel_override_fails_closed() -> None:
    wheel_overrides, acp_overrides = _committed_overrides()
    stale = dict(wheel_overrides)
    stale["a-package-not-in-the-lock"] = LicenseOverride(
        version="1.0.0", expression="MIT", evidence="fabricated"
    )

    with pytest.raises(
        CapsuleInputAuthoringError, match="names no package in the uv lock"
    ):
        validate_license_overrides(
            wheel_overrides=stale,
            acp_overrides=acp_overrides,
            uv_lock_bytes=(_REPO_ROOT / "uv.lock").read_bytes(),
            package_lock_bytes=(_REPO_ROOT / "package-lock.json").read_bytes(),
        )


def test_an_orphaned_wheel_override_version_fails_closed() -> None:
    wheel_overrides, acp_overrides = _committed_overrides()
    orphaned = dict(wheel_overrides)
    existing = next(iter(wheel_overrides))
    orphaned[existing] = LicenseOverride(
        version="0.0.0-not-locked", expression="MIT", evidence="stale pin"
    )

    with pytest.raises(CapsuleInputAuthoringError, match="absent from the uv lock"):
        validate_license_overrides(
            wheel_overrides=orphaned,
            acp_overrides=acp_overrides,
            uv_lock_bytes=(_REPO_ROOT / "uv.lock").read_bytes(),
            package_lock_bytes=(_REPO_ROOT / "package-lock.json").read_bytes(),
        )


def _real_acp_artifacts(
    target: TargetTriple,
) -> tuple[tuple[AcpPackageArtifact, ...], bytes]:
    """Build ACP artifacts from the REAL committed package-lock selection.

    The selection - install paths, versions, resolved URLs, integrities, and
    dependency graph - is resolved from the committed package-lock.json for the
    target, so emission runs against the real multi-package closure.  Only the
    per-tarball sha256 and size are synthetic; the ACP reconciler intentionally
    does not check those for npm, so the assembled inventory still reconciles
    against the real lock.
    """
    lock = (_REPO_ROOT / "package-lock.json").read_bytes()
    selection = resolve_acp_closure_selection(
        lock_bytes=lock,
        target=target,
        root_package=_ACP_ROOT,
        node_full_version=_NODE_VERSION,
    )
    artifacts = tuple(
        AcpPackageArtifact(
            name=node.name,
            version=node.version,
            install_path=node.install_path,
            url=node.url,
            integrity=node.integrity,
            sha256=hashlib.sha256(node.install_path.encode()).hexdigest(),
            size=len(node.install_path) + 1,
            license_expression="MIT",
            license_members=("package/LICENSE",),
            redistribution_evidence=("tarball-license:package/LICENSE",),
            dependency_paths=node.dependency_paths,
        )
        for node in selection.packages
    )
    return artifacts, lock


def test_emits_a_reconciling_deterministic_acp_inventory(tmp_path: Path) -> None:
    artifacts, lock = _real_acp_artifacts(TargetTriple.LINUX_X86_64)
    assert len(artifacts) > 2

    inventory, emitted = emit_acp_closure_inventory(
        artifacts,
        target=TargetTriple.LINUX_X86_64,
        lock_bytes=lock,
        root_package=_ACP_ROOT,
        node_full_version=_NODE_VERSION,
        cache_root=tmp_path,
    )

    assert emitted.path.name == emitted.sha256
    assert emitted.path.read_bytes() == canonical_closure_inventory_bytes(inventory)
    # The written inventory round-trips: it loads and reconciles through the real
    # ACP reconciler, the same gate the consumer applies.
    loaded = AcpClosureInventory.model_validate_json(emitted.path.read_bytes())
    reconcile_acp_closure_lock_bytes(
        loaded, lock_bytes=lock, root_package=_ACP_ROOT, node_full_version=_NODE_VERSION
    )

    _, again = emit_acp_closure_inventory(
        artifacts,
        target=TargetTriple.LINUX_X86_64,
        lock_bytes=lock,
        root_package=_ACP_ROOT,
        node_full_version=_NODE_VERSION,
        cache_root=tmp_path,
    )
    assert again.sha256 == emitted.sha256


def test_acp_emission_fails_closed_when_the_inventory_does_not_reconcile(
    tmp_path: Path,
) -> None:
    artifacts, lock = _real_acp_artifacts(TargetTriple.LINUX_X86_64)

    # A Node runtime the lock's engine gate rejects makes reconciliation fail.
    with pytest.raises(CapsuleInputAuthoringError, match="does not reconcile"):
        emit_acp_closure_inventory(
            artifacts,
            target=TargetTriple.LINUX_X86_64,
            lock_bytes=lock,
            root_package=_ACP_ROOT,
            node_full_version="20.0.0",
            cache_root=tmp_path,
        )
