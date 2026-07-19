from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from vaultspec_a2a.desktop.artifacts import (
    AcpClosureDescriptor,
    ArchiveKind,
    ArtifactInputError,
    LockInputDescriptor,
    SourceArtifactDescriptor,
    load_capsule_input_descriptor,
    validate_portable_archive_path,
    verify_acp_tarball_inventory,
    verify_lock_input,
)
from vaultspec_a2a.desktop.contract import ComponentAssetKind, TargetTriple

if TYPE_CHECKING:
    from pathlib import Path


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha512_sri(payload: bytes) -> str:
    digest = hashlib.sha512(payload).digest()
    return f"sha512-{base64.b64encode(digest).decode('ascii')}"


def _node_descriptor_fields() -> dict[str, object]:
    return {
        "kind": ComponentAssetKind.NODE_RUNTIME,
        "target": TargetTriple.WINDOWS_X86_64,
        "version": "22",
        "release": "22.23.1",
        "build": "node-v22.23.1",
        "url": "https://nodejs.org/dist/v22.23.1/node-v22.23.1-win-x64.zip",
        "sha256": "0" * 64,
        "size": 1,
        "archive_kind": ArchiveKind.ZIP,
        "archive_root": "node-v22.23.1-win-x64",
        "license_expression": "MIT",
        "license_members": ("node-v22.23.1-win-x64/LICENSE",),
        "redistribution_evidence": ("archive-license:LICENSE",),
    }


@pytest.mark.parametrize(
    "path",
    (
        "../escape",
        "/rooted",
        "C:/rooted",
        "payload/NUL.txt",
        "payload/name. ",
        "payload/back\\slash",
    ),
)
def test_portable_archive_path_rejects_cross_platform_escape_forms(path: str) -> None:
    with pytest.raises(ValueError):
        validate_portable_archive_path(path)


def test_source_descriptor_keeps_exact_node_release_visible() -> None:
    descriptor = SourceArtifactDescriptor.model_validate(_node_descriptor_fields())

    assert descriptor.version == "22"
    assert descriptor.exact_release == "22.23.1+node-v22.23.1"

    invalid = {**_node_descriptor_fields(), "release": "22.23.1-musl"}
    with pytest.raises(ValidationError, match="exact minor and patch"):
        SourceArtifactDescriptor.model_validate(invalid)


def test_redistribution_metadata_cannot_self_assert_approval() -> None:
    fields = {**_node_descriptor_fields(), "redistribution_approved": True}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceArtifactDescriptor.model_validate(fields)


def test_acp_closure_requires_a_complete_canonical_sha512_sri() -> None:
    valid = {
        "package_count": 111,
        "tarball_inventory_sha256": "1" * 64,
        "tarball_inventory_size": 128,
        "installed_inventory_sha256": "2" * 64,
        "target_sdk_package": "@anthropic-ai/claude-agent-sdk-win32-x64",
        "target_sdk_integrity": _sha512_sri(b"target-sdk-package"),
    }
    descriptor = AcpClosureDescriptor.model_validate(valid)
    assert descriptor.package_count == 111

    with pytest.raises(ValidationError, match="canonical base64"):
        AcpClosureDescriptor.model_validate(
            {**valid, "target_sdk_integrity": "sha512-not-a-complete-digest"}
        )


def test_lock_verification_reads_exact_bytes_and_detects_mutation(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "uv.lock"
    payload = b"version = 1\n"
    lock.write_bytes(payload)
    descriptor = LockInputDescriptor(sha256=_sha256(payload), size=len(payload))

    assert (
        verify_lock_input(lock, descriptor=descriptor, label="uv lock")
        == lock.absolute()
    )

    lock.write_bytes(payload + b"changed = true\n")
    with pytest.raises(ArtifactInputError, match="size does not match"):
        verify_lock_input(lock, descriptor=descriptor, label="uv lock")


def test_descriptor_digest_is_checked_before_toml_is_parsed(tmp_path: Path) -> None:
    descriptor = tmp_path / "descriptor.toml"
    descriptor.write_bytes(b"not valid toml = [")

    with pytest.raises(ArtifactInputError, match="digest does not match"):
        load_capsule_input_descriptor(descriptor, expected_sha256="0" * 64)


def test_acp_tarball_inventory_is_a_separate_content_addressed_input(
    tmp_path: Path,
) -> None:
    payload = b"opaque-package-inventory-bytes\n"
    digest = _sha256(payload)
    cache = tmp_path / "cache"
    cache.mkdir()
    inventory = cache / digest
    inventory.write_bytes(payload)
    descriptor = AcpClosureDescriptor(
        package_count=111,
        tarball_inventory_sha256=digest,
        tarball_inventory_size=len(payload),
        installed_inventory_sha256="3" * 64,
        target_sdk_package="@anthropic-ai/claude-agent-sdk-win32-x64",
        target_sdk_integrity=_sha512_sri(b"target-sdk-package"),
    )

    assert verify_acp_tarball_inventory(descriptor, input_dir=cache) == inventory

    inventory.write_bytes(payload + b" ")
    with pytest.raises(ArtifactInputError, match="size does not match"):
        verify_acp_tarball_inventory(descriptor, input_dir=cache)
