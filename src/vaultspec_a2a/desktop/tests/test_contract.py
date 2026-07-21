"""Production-model tests for the versioned component-manifest contract."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from vaultspec_a2a.database.checkpoint_schema import CHECKPOINT_SCHEMA_VERSION

from .. import GatewayApiVersion, GatewayEntrypoint, StandaloneMcpEntrypoint
from ..contract import (
    ACP_VERSION_PIN,
    CONTRACT_VERSION,
    CPYTHON_VERSION_PIN,
    NODEJS_VERSION_PIN,
    PRIMARY_SCHEMA_VERSION,
    ApiVersionRange,
    ComponentAsset,
    ComponentAssetKind,
    ComponentEntrypoint,
    ComponentManifest,
    DigestAlgorithm,
    EntrypointKind,
    MutableStoreKind,
    StoreSchemaAuthority,
    TargetTriple,
    component_manifest_schema,
    contract_versions_compatible,
    export_component_manifest_schema,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_SCHEMA_SNAPSHOT = _PROJECT_ROOT / "schemas" / "desktop-capsule-manifest.json"
_WHEEL_SCHEMA_PATH = "vaultspec_a2a/desktop/schemas/desktop-capsule-manifest.json"
_INVALID_RELATIVE_COMMANDS = (
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
    ("bad\x1fname",),
    ("bad\x7fname",),
    ("bad<name",),
    ("bad>name",),
    ('bad"name',),
    ("bad|name",),
    ("bad?name",),
    ("bad*name",),
    ("CON",),
    ("con.txt",),
    ("CONIN$",),
    ("conout$",),
    ("NUL",),
    ("com1.exe",),
    ("LPT9",),
    ("COM¹",),
    ("com².log",),
    ("LPT³",),
    ("trailing.",),
    ("trailing ",),
    tuple("segment" for _ in range(17)),
    ("x" * 129,),
)


def _manifest_payload() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "identity": {"name": "vaultspec-a2a", "version": "1.2.3"},
        "target": "x86_64-unknown-linux-gnu",
        "compatibility": {
            "api_versions": {"minimum": "v1", "maximum": "v1"},
            "migration_range": {
                "base": "0001_initial",
                "head": PRIMARY_SCHEMA_VERSION,
            },
        },
        "consistency_group": {
            "stores": [
                {
                    "kind": "primary-database",
                    "derivable": False,
                    "schema_authority": "alembic-migration-range",
                    "schema_version": PRIMARY_SCHEMA_VERSION,
                },
                {
                    "kind": "checkpoint-database",
                    "derivable": False,
                    "schema_authority": "checkpointer-schema",
                    "schema_version": CHECKPOINT_SCHEMA_VERSION,
                },
            ]
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
                "console_script": "vaultspec-a2a-mcp",
                "reference": "vaultspec_a2a.protocols.mcp.__main__:main",
                "relative_command": ["bin", "vaultspec-a2a-mcp"],
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
    assert not contract_versions_compatible("1.1", CONTRACT_VERSION)


def test_legacy_manifest_is_neither_parseable_nor_currently_compatible() -> None:
    payload = _manifest_payload()
    payload["contract_version"] = "1.0"
    del payload["consistency_group"]
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)
    assert not contract_versions_compatible("1.0", CONTRACT_VERSION)


@pytest.mark.parametrize("version", ["1", "1.0.0", "01.0", "1.00", "1.-1"])
def test_manifest_rejects_malformed_contract_version(version: str) -> None:
    payload = _manifest_payload()
    payload["contract_version"] = version
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)


def test_api_version_range_accepts_the_production_v1_surface() -> None:
    api_range = ApiVersionRange(minimum="v1", maximum="v1")
    assert api_range.minimum.value == "v1"
    assert api_range.maximum.value == "v1"


def test_typed_contract_authorities_are_exported_from_desktop_facade() -> None:
    assert GatewayApiVersion.V1.value == "v1"
    assert GatewayEntrypoint.__name__ == "GatewayEntrypoint"
    assert StandaloneMcpEntrypoint.__name__ == "StandaloneMcpEntrypoint"


@pytest.mark.parametrize("version", ["1", "V1", "v0", "v01", "v1.0", "v-1", "v2"])
def test_api_version_range_rejects_unsupported_or_noncanonical_values(
    version: str,
) -> None:
    with pytest.raises(ValidationError):
        ApiVersionRange(minimum=version, maximum="v1")


def test_target_triple_covers_exactly_the_four_accepted_targets() -> None:
    assert {target.value for target in TargetTriple} == {
        "aarch64-apple-darwin",
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


def test_manifest_binds_identity_version_to_a2a_distribution_version() -> None:
    payload = _manifest_payload()
    payload["identity"]["version"] = "9.9.9"
    with pytest.raises(ValidationError, match=r"identity\.version must equal"):
        ComponentManifest.model_validate(payload)


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


@pytest.mark.parametrize("command", _INVALID_RELATIVE_COMMANDS)
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


@pytest.mark.parametrize(
    ("surface", "wrong_kind"),
    [("gateway", "standalone-mcp"), ("standalone_mcp", "gateway")],
)
def test_manifest_runtime_rejects_crossed_entrypoint_kinds(
    surface: str, wrong_kind: str
) -> None:
    payload = _manifest_payload()
    payload["entrypoints"][surface]["kind"] = wrong_kind
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)


def test_draft202012_schema_accepts_the_production_manifest() -> None:
    schema = component_manifest_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_manifest_payload())


@pytest.mark.parametrize(
    ("surface", "wrong_kind"),
    [("gateway", "standalone-mcp"), ("standalone_mcp", "gateway")],
)
def test_draft202012_schema_rejects_crossed_entrypoint_kinds(
    surface: str, wrong_kind: str
) -> None:
    payload = _manifest_payload()
    payload["entrypoints"][surface]["kind"] = wrong_kind
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(component_manifest_schema()).validate(payload)


@pytest.mark.parametrize("command", _INVALID_RELATIVE_COMMANDS)
def test_draft202012_schema_rejects_nonportable_relative_commands(
    command: tuple[str, ...],
) -> None:
    payload = _manifest_payload()
    payload["entrypoints"]["gateway"]["relative_command"] = command
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(component_manifest_schema()).validate(payload)


def test_draft202012_schema_rejects_unsupported_gateway_api_version() -> None:
    payload = _manifest_payload()
    payload["compatibility"]["api_versions"]["maximum"] = "v2"
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(component_manifest_schema()).validate(payload)


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

    assert schema["$defs"]["GatewayApiVersion"]["enum"] == ["v1"]
    for definition, expected_kind in (
        ("GatewayEntrypoint", "gateway"),
        ("StandaloneMcpEntrypoint", "standalone-mcp"),
    ):
        properties = schema["$defs"][definition]["properties"]
        assert properties["kind"]["const"] == expected_kind
        command = properties["relative_command"]
        assert command["minItems"] == 1
        assert command["maxItems"] == 16
        assert command["items"]["minLength"] == 1
        assert command["items"]["maxLength"] == 128
        assert "pattern" in command["items"]
        assert "not" in command["items"]

    assert "identity.version must equal" in schema["x-vaultspec-invariants"][0]


def test_working_tree_wheel_installs_schema_as_package_resource(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required by the repository build workflow"
    dist = tmp_path / "dist"
    build = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(dist)],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as archive:
        assert _WHEEL_SCHEMA_PATH in archive.namelist()
        assert archive.read(_WHEEL_SCHEMA_PATH) == _SCHEMA_SNAPSHOT.read_bytes()

    installed = tmp_path / "installed"
    install = subprocess.run(
        [uv, "pip", "install", "--target", str(installed), "--no-deps", str(wheels[0])],
        check=False,
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, install.stderr
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import importlib.resources as r, sys; "
                "sys.path.insert(0, sys.argv[1]); "
                "sys.stdout.write(r.files('vaultspec_a2a.desktop').joinpath("
                "'schemas', 'desktop-capsule-manifest.json')"
                ".read_text(encoding='utf-8'))"
            ),
            str(installed),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout == _SCHEMA_SNAPSHOT.read_text(encoding="utf-8")


def test_manifest_rejects_extra_fields() -> None:
    payload = _manifest_payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)


def test_manifest_declares_both_non_derivable_group_stores() -> None:
    """The manifest binds the mutable consistency-group membership and authority."""
    manifest = ComponentManifest.model_validate(_manifest_payload())
    stores = {store.kind: store for store in manifest.consistency_group.stores}
    assert set(stores) == set(MutableStoreKind)
    assert not stores[MutableStoreKind.PRIMARY_DATABASE].derivable
    assert not stores[MutableStoreKind.CHECKPOINT_DATABASE].derivable
    # The primary store's schema revision reconciles with the migration range;
    # the checkpoint store carries the checkpointer's own schema authority.
    assert (
        stores[MutableStoreKind.PRIMARY_DATABASE].schema_authority
        is StoreSchemaAuthority.ALEMBIC_MIGRATION_RANGE
    )
    assert (
        stores[MutableStoreKind.CHECKPOINT_DATABASE].schema_authority
        is StoreSchemaAuthority.CHECKPOINTER_SCHEMA
    )
    assert (
        stores[MutableStoreKind.PRIMARY_DATABASE].schema_version
        == PRIMARY_SCHEMA_VERSION
    )
    assert (
        stores[MutableStoreKind.CHECKPOINT_DATABASE].schema_version
        == CHECKPOINT_SCHEMA_VERSION
    )


def test_manifest_rejects_incomplete_consistency_group() -> None:
    """A group omitting a non-derivable mandatory store is refused."""
    payload = _manifest_payload()
    payload["consistency_group"]["stores"] = payload["consistency_group"]["stores"][:1]
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(component_manifest_schema()).validate(payload)


def test_manifest_rejects_duplicate_group_store_kind() -> None:
    """A group declaring a store kind twice is refused."""
    payload = _manifest_payload()
    stores = payload["consistency_group"]["stores"]
    stores[1] = dict(stores[0])
    with pytest.raises(ValidationError, match="each store kind once"):
        ComponentManifest.model_validate(payload)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(component_manifest_schema()).validate(payload)


def test_manifest_rejects_unproved_derivability() -> None:
    payload = _manifest_payload()
    payload["consistency_group"]["stores"][0]["derivable"] = True
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(component_manifest_schema()).validate(payload)


def test_manifest_rejects_mismatched_store_authority() -> None:
    payload = _manifest_payload()
    payload["consistency_group"]["stores"][0]["schema_authority"] = (
        "checkpointer-schema"
    )
    with pytest.raises(ValidationError, match="schema authority"):
        ComponentManifest.model_validate(payload)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(component_manifest_schema()).validate(payload)


@pytest.mark.parametrize(
    ("store_index", "version"),
    [(0, "9999_foreign"), (1, "9.0.0")],
)
def test_manifest_rejects_schema_versions_outside_generation_authority(
    store_index: int, version: str
) -> None:
    payload = _manifest_payload()
    payload["consistency_group"]["stores"][store_index]["schema_version"] = version
    with pytest.raises(ValidationError, match="schema_version"):
        ComponentManifest.model_validate(payload)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(component_manifest_schema()).validate(payload)
