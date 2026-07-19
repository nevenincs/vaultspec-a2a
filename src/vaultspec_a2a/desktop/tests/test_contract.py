"""Production-model tests for the versioned component-manifest contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from ..contract import (
    ACP_VERSION_PIN,
    CONTRACT_VERSION,
    CPYTHON_VERSION_PIN,
    NODEJS_VERSION_PIN,
    ApiVersionRange,
    ComponentAsset,
    ComponentAssetKind,
    ComponentEntrypoint,
    ComponentManifest,
    DigestAlgorithm,
    EntrypointKind,
    TargetTriple,
    component_manifest_schema,
    contract_versions_compatible,
    export_component_manifest_schema,
)

_SCHEMA_SNAPSHOT = (
    Path(__file__).resolve().parents[4] / "schemas" / "desktop-capsule-manifest.json"
)


def _manifest_payload() -> dict[str, Any]:
    return {
        "contract_version": "1.0",
        "identity": {"name": "vaultspec-a2a", "version": "1.2.3"},
        "target": "x86_64-unknown-linux-gnu",
        "compatibility": {
            "api_versions": {"minimum": "v1", "maximum": "v1"},
            "migration_range": {"base": "0001_initial", "head": "0012_current"},
        },
        "entrypoints": {
            "gateway": {
                "kind": "gateway",
                "console_script": "vaultspec-a2a",
                "reference": "vaultspec_a2a.cli.main:main",
                "relative_command": ["bin", "vaultspec-a2a"],
            },
            "standalone_mcp": {
                "kind": "standalone-mcp",
                "console_script": "vaultspec-mcp",
                "reference": "vaultspec_a2a.protocols.mcp.__main__:main",
                "relative_command": ["bin", "vaultspec-mcp"],
            },
        },
        "digest_algorithm": "sha256",
        "assets": [
            {
                "kind": "python-runtime",
                "version": "3.13",
                "license": "PSF-2.0",
                "digest": "1" * 64,
            },
            {
                "kind": "a2a-distribution",
                "version": "1.2.3",
                "license": "MIT",
                "digest": "2" * 64,
            },
            {
                "kind": "node-runtime",
                "version": "22",
                "license": "MIT",
                "digest": "3" * 64,
            },
            {
                "kind": "acp-adapter",
                "version": "0.59.0",
                "license": "Apache-2.0",
                "digest": "4" * 64,
            },
        ],
        "dependency_lock": {
            "uv_lock_digest": "5" * 64,
            "package_lock_digest": "6" * 64,
        },
    }


def test_contract_versions_are_directionally_consumer_safe() -> None:
    assert contract_versions_compatible("1.0", "1.4")
    assert contract_versions_compatible("1.4", "1.4")
    assert not contract_versions_compatible("1.5", "1.4")
    assert not contract_versions_compatible("2.0", "1.9")
    assert not contract_versions_compatible("1.0", "2.0")


@pytest.mark.parametrize(
    ("declared", "supported"),
    [
        ("1", "1.0"),
        ("1.0.0", "1.0"),
        ("01.0", "1.0"),
        ("1.00", "1.0"),
        ("1.-1", "1.0"),
        ("1.a", "1.0"),
        ("1.0", "latest"),
        ("1000000.0", "1000000.0"),
    ],
)
def test_contract_versions_reject_malformed_values(
    declared: str, supported: str
) -> None:
    assert not contract_versions_compatible(declared, supported)


def test_current_contract_version_is_self_compatible() -> None:
    assert contract_versions_compatible(CONTRACT_VERSION, CONTRACT_VERSION)


@pytest.mark.parametrize("version", ["1", "1.0.0", "01.0", "1.00", "1.-1"])
def test_manifest_rejects_malformed_contract_version(version: str) -> None:
    payload = _manifest_payload()
    payload["contract_version"] = version
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)


def test_api_version_range_uses_ordered_vn_grammar() -> None:
    assert ApiVersionRange(minimum="v1", maximum="v12").maximum == "v12"
    with pytest.raises(ValidationError, match="must not exceed"):
        ApiVersionRange(minimum="v12", maximum="v2")


@pytest.mark.parametrize("version", ["1", "V1", "v0", "v01", "v1.0", "v-1"])
def test_api_version_range_rejects_noncanonical_values(version: str) -> None:
    with pytest.raises(ValidationError):
        ApiVersionRange(minimum=version, maximum="v1")


def test_target_triple_covers_exactly_the_five_accepted_targets() -> None:
    assert {target.value for target in TargetTriple} == {
        "aarch64-apple-darwin",
        "x86_64-apple-darwin",
        "aarch64-unknown-linux-gnu",
        "x86_64-unknown-linux-gnu",
        "x86_64-pc-windows-msvc",
    }


def test_runtime_versions_remain_pinned_to_the_approved_closure() -> None:
    assert CPYTHON_VERSION_PIN == "3.13"
    assert NODEJS_VERSION_PIN == "22"
    assert ACP_VERSION_PIN == "0.59.0"


def test_asset_digest_rejects_non_sha256_shape() -> None:
    with pytest.raises(ValidationError):
        ComponentAsset(
            kind=ComponentAssetKind.A2A_DISTRIBUTION,
            version="0.1.0",
            license="MIT",
            digest="not-a-digest",
        )


def test_manifest_accepts_exactly_the_complete_production_closure() -> None:
    manifest = ComponentManifest.model_validate(_manifest_payload())
    assert {asset.kind for asset in manifest.assets} == set(ComponentAssetKind)
    assert manifest.digest_algorithm is DigestAlgorithm.SHA256


def test_manifest_rejects_incomplete_asset_closure() -> None:
    payload = _manifest_payload()
    payload["assets"] = list(payload["assets"])[:-1]
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)


def test_manifest_rejects_duplicate_asset_kind() -> None:
    payload = _manifest_payload()
    assets = list(payload["assets"])
    assets[-1] = dict(assets[0])
    payload["assets"] = assets
    with pytest.raises(ValidationError, match="exactly one"):
        ComponentManifest.model_validate(payload)


@pytest.mark.parametrize(
    ("kind", "unpinned_version"),
    [("python-runtime", "3.12"), ("node-runtime", "21"), ("acp-adapter", "1.0")],
)
def test_manifest_rejects_unpinned_runtime_asset_version(
    kind: str, unpinned_version: str
) -> None:
    payload = _manifest_payload()
    assets = list(payload["assets"])
    for asset in assets:
        if asset["kind"] == kind:
            asset["version"] = unpinned_version
    with pytest.raises(ValidationError, match="must be pinned"):
        ComponentManifest.model_validate(payload)


def test_relative_command_accepts_bounded_capsule_segments() -> None:
    entrypoint = ComponentEntrypoint(
        kind=EntrypointKind.GATEWAY,
        console_script="vaultspec-a2a",
        reference="vaultspec_a2a.cli.main:main",
        relative_command=("runtime", "bin", "vaultspec-a2a"),
    )
    assert entrypoint.relative_command == ("runtime", "bin", "vaultspec-a2a")


@pytest.mark.parametrize(
    "command",
    [
        (),
        ("",),
        (".",),
        ("..",),
        ("/bin",),
        ("\\bin",),
        ("C:",),
        ("C:\\bin",),
        ("bin/tool",),
        ("bin\\tool",),
        ("bad\x00name",),
        tuple("segment" for _ in range(17)),
        ("x" * 129,),
    ],
)
def test_relative_command_rejects_unbounded_or_rooted_paths(
    command: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        ComponentEntrypoint(
            kind=EntrypointKind.GATEWAY,
            console_script="vaultspec-a2a",
            reference="vaultspec_a2a.cli.main:main",
            relative_command=command,
        )


def test_committed_schema_snapshot_exactly_matches_production_exporter() -> None:
    exported = export_component_manifest_schema()
    assert exported.endswith("\n")
    assert _SCHEMA_SNAPSHOT.read_text(encoding="utf-8") == exported
    assert json.loads(exported) == component_manifest_schema()


def test_exported_schema_carries_collection_and_path_bounds() -> None:
    schema = cast("dict[str, Any]", component_manifest_schema())
    assets = schema["properties"]["assets"]
    assert assets["minItems"] == 4
    assert assets["maxItems"] == 4
    assert len(assets["allOf"]) == 4

    command = schema["$defs"]["ComponentEntrypoint"]["properties"]["relative_command"]
    assert command["minItems"] == 1
    assert command["maxItems"] == 16
    assert command["items"]["minLength"] == 1
    assert command["items"]["maxLength"] == 128
    assert command["items"]["not"] == {"enum": [".", ".."]}


def test_manifest_rejects_extra_fields() -> None:
    payload = _manifest_payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)
