"""Pure-logic tests for the versioned component-manifest contract."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ..contract import (
    CONTRACT_VERSION,
    ComponentAsset,
    ComponentAssetKind,
    ComponentManifest,
    DigestAlgorithm,
    TargetTriple,
    component_manifest_schema,
    contract_versions_compatible,
    export_component_manifest_schema,
)


def test_contract_versions_compatible_is_major_equality() -> None:
    assert contract_versions_compatible("1.0", "1.4")
    assert contract_versions_compatible("1.9", "1.0")
    assert not contract_versions_compatible("2.0", "1.0")
    assert not contract_versions_compatible("1.0", "2.0")


def test_current_contract_version_is_self_compatible() -> None:
    assert contract_versions_compatible(CONTRACT_VERSION, CONTRACT_VERSION)


def test_target_triple_covers_exactly_the_five_accepted_targets() -> None:
    assert {target.value for target in TargetTriple} == {
        "aarch64-apple-darwin",
        "x86_64-apple-darwin",
        "aarch64-unknown-linux-gnu",
        "x86_64-unknown-linux-gnu",
        "x86_64-pc-windows-msvc",
    }


def test_asset_digest_rejects_non_sha256_shape() -> None:
    with pytest.raises(ValidationError):
        ComponentAsset(
            kind=ComponentAssetKind.A2A_DISTRIBUTION,
            version="0.1.0",
            license="MIT",
            digest="not-a-digest",
        )


def test_exported_schema_is_deterministic_and_matches_authority() -> None:
    first = export_component_manifest_schema()
    second = export_component_manifest_schema()
    assert first == second
    assert first.endswith("\n")
    assert json.loads(first) == component_manifest_schema()


def test_schema_forbids_additional_properties() -> None:
    schema = component_manifest_schema()
    assert schema["additionalProperties"] is False


def test_manifest_rejects_extra_fields() -> None:
    schema = component_manifest_schema()
    assert schema["additionalProperties"] is False
    # A frozen, extra-forbidding model rejects unknown keys at construction.
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(
            {
                "contract_version": CONTRACT_VERSION,
                "digest_algorithm": DigestAlgorithm.SHA256.value,
                "unexpected": True,
            }
        )
