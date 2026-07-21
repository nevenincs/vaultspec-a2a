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

from vaultspec_a2a.desktop.capsule_license import (
    AcpLicenseOverride,
    CapsuleInputAuthoringError,
    LicenseOverride,
    derive_acp_package_artifact,
    load_acp_license_overrides,
    load_license_overrides,
    validate_license_overrides,
)
from vaultspec_a2a.desktop.lock_reconciliation import AcpNodeSelection

_REPO_ROOT = Path(__file__).resolve().parents[4]


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
