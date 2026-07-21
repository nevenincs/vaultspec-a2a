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
    canonical_closure_inventory_bytes,
)
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.lock_reconciliation import (
    AcpNodeSelection,
    reconcile_acp_closure_lock_bytes,
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


def _closure_member(
    cache_root: Path,
    *,
    name: str,
    version: str,
    install_path: str,
    dependency_paths: tuple[str, ...],
) -> tuple[AcpNodeSelection, str, int, str]:
    """Build one real tarball and its node; return node, sha256, size, integrity."""
    payload = json.dumps({"license": "MIT", "name": name, "version": version}).encode()
    members = [
        _member("package/package.json", payload),
        _member("package/index.js", b"export {};\n"),
        _member("package/LICENSE", b"mit\n"),
    ]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for info, body in members:
            archive.addfile(info, io.BytesIO(body))
    tarball = gzip.compress(raw.getvalue(), mtime=0)
    sha256 = hashlib.sha256(tarball).hexdigest()
    (cache_root / sha256).write_bytes(tarball)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode(
        "ascii"
    )
    filename = name.rsplit("/", 1)[-1]
    url = f"https://registry.npmjs.org/{name}/-/{filename}-{version}.tgz"
    node = AcpNodeSelection(
        name=name,
        install_path=install_path,
        version=version,
        url=url,
        integrity=integrity,
        dependency_paths=dependency_paths,
    )
    return node, sha256, len(tarball), integrity


def _linux_acp_closure(cache_root: Path) -> tuple[tuple, bytes]:
    """Build a real 4-node ACP closure for the Linux x64 target plus its lock."""
    native = "@anthropic-ai/claude-agent-sdk-linux-x64"
    acp_path = f"node_modules/{_ACP_ROOT}"
    sdk_path = "node_modules/@anthropic-ai/claude-agent-sdk"
    native_path = f"node_modules/{native}"
    peer_path = "node_modules/peer-runtime"

    acp = _closure_member(
        cache_root,
        name=_ACP_ROOT,
        version="0.59.0",
        install_path=acp_path,
        dependency_paths=(sdk_path,),
    )
    sdk = _closure_member(
        cache_root,
        name="@anthropic-ai/claude-agent-sdk",
        version="0.3.207",
        install_path=sdk_path,
        dependency_paths=tuple(sorted((native_path, peer_path))),
    )
    native_member = _closure_member(
        cache_root,
        name=native,
        version="0.3.207",
        install_path=native_path,
        dependency_paths=(),
    )
    peer = _closure_member(
        cache_root,
        name="peer-runtime",
        version="2.1.0",
        install_path=peer_path,
        dependency_paths=(),
    )

    artifacts = tuple(
        derive_acp_package_artifact(
            node, cache_root=cache_root, sha256=sha256, size=size, overrides={}
        )
        for node, sha256, size, _ in (acp, sdk, native_member, peer)
    )

    packages = {
        "": {"name": "vaultspec-a2a", "dependencies": {_ACP_ROOT: "0.59.0"}},
        acp_path: {
            "version": "0.59.0",
            "resolved": acp[0].url,
            "integrity": acp[3],
            "dependencies": {"@anthropic-ai/claude-agent-sdk": "0.3.207"},
        },
        sdk_path: {
            "version": "0.3.207",
            "resolved": sdk[0].url,
            "integrity": sdk[3],
            "optionalDependencies": {native: "0.3.207"},
            "peerDependencies": {"peer-runtime": ">=2"},
        },
        native_path: {
            "version": "0.3.207",
            "resolved": native_member[0].url,
            "integrity": native_member[3],
            "optional": True,
            "os": ["linux"],
            "cpu": ["x64"],
        },
        peer_path: {
            "version": "2.1.0",
            "resolved": peer[0].url,
            "integrity": peer[3],
            "peer": True,
        },
    }
    lock = json.dumps(
        {
            "name": "vaultspec-a2a",
            "lockfileVersion": 3,
            "requires": True,
            "packages": packages,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return artifacts, lock


def test_emits_a_reconciling_deterministic_acp_inventory(tmp_path: Path) -> None:
    artifacts, lock = _linux_acp_closure(tmp_path)

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
    artifacts, _ = _linux_acp_closure(tmp_path)
    broken = json.dumps(
        {
            "name": "vaultspec-a2a",
            "lockfileVersion": 3,
            "requires": True,
            "packages": {
                "": {"name": "vaultspec-a2a", "dependencies": {_ACP_ROOT: "0.59.0"}}
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    with pytest.raises(CapsuleInputAuthoringError, match="does not reconcile"):
        emit_acp_closure_inventory(
            artifacts,
            target=TargetTriple.LINUX_X86_64,
            lock_bytes=broken,
            root_package=_ACP_ROOT,
            node_full_version=_NODE_VERSION,
            cache_root=tmp_path,
        )
