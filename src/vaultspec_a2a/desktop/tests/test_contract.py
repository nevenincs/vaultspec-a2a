"""Production-model tests for the desktop component launch contract."""

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

from .. import GatewayEntrypoint, StandaloneMcpEntrypoint
from ..contract import (
    ComponentEntrypoint,
    ComponentManifest,
    EntrypointKind,
    component_manifest_schema,
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
        "identity": {"name": "vaultspec-a2a", "version": "1.2.3"},
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
    }


def test_typed_entrypoints_are_exported_from_desktop_facade() -> None:
    assert GatewayEntrypoint.__name__ == "GatewayEntrypoint"
    assert StandaloneMcpEntrypoint.__name__ == "StandaloneMcpEntrypoint"


def test_manifest_accepts_the_identity_and_entrypoint_boundary() -> None:
    manifest = ComponentManifest.model_validate(_manifest_payload())
    assert manifest.identity.name == "vaultspec-a2a"
    assert manifest.identity.version == "1.2.3"
    assert manifest.entrypoints.gateway.kind is EntrypointKind.GATEWAY
    assert manifest.entrypoints.standalone_mcp.kind is EntrypointKind.STANDALONE_MCP


def test_relative_command_accepts_bounded_runtime_segments() -> None:
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
def test_manifest_rejects_crossed_entrypoint_kinds(
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


def test_committed_schema_snapshot_exactly_matches_production_exporter() -> None:
    exported = export_component_manifest_schema()
    assert exported.endswith("\n")
    assert _SCHEMA_SNAPSHOT.read_text(encoding="utf-8") == exported
    assert json.loads(exported) == component_manifest_schema()


def test_exported_schema_carries_entrypoint_path_bounds() -> None:
    schema = cast("dict[str, Any]", component_manifest_schema())
    assert set(schema["properties"]) == {"identity", "entrypoints"}
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


def test_manifest_rejects_extra_fields() -> None:
    payload = _manifest_payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        ComponentManifest.model_validate(payload)


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
