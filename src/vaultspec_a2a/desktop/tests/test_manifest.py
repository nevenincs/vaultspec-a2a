"""Real-wheel behavior tests for the desktop component-manifest emitter."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import shutil
import subprocess
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from .. import (
    CANONICAL_JSON_VERSION,
    component_manifest_canonical_bytes,
    component_manifest_digest,
)
from ..contract import (
    ACP_VERSION_PIN,
    CPYTHON_VERSION_PIN,
    NODEJS_VERSION_PIN,
    ApiVersionRange,
    ComponentAssetKind,
    ComponentManifest,
    DigestAlgorithm,
    EntrypointKind,
    GatewayEntrypoint,
    StandaloneMcpEntrypoint,
    TargetTriple,
)
from ..manifest import (
    AssetSource,
    ManifestEmissionError,
    emit_component_manifest,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_FIXTURES = Path(__file__).with_name("fixtures")
_API_RANGE = ApiVersionRange(minimum="v1", maximum="v1")


@dataclass(frozen=True, slots=True)
class WheelEvidence:
    path: Path
    project: dict[str, object]


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        rendered = subprocess.list2cmdline(command)
        raise AssertionError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> WheelEvidence:
    """Build the exact working-tree distribution once for S11 evidence."""
    uv = shutil.which("uv")
    assert uv is not None, "uv is required to build the production wheel"
    output = tmp_path_factory.mktemp("s11-real-wheel")
    _run(
        [uv, "build", "--wheel", "--out-dir", str(output), "--no-sources"],
        cwd=_PROJECT_ROOT,
    )
    wheels = tuple(output.glob("vaultspec_a2a-*.whl"))
    assert len(wheels) == 1, wheels
    project_document = tomllib.loads(
        (_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return WheelEvidence(
        path=wheels[0],
        project=cast("dict[str, object]", project_document["project"]),
    )


def _source_closure(root: Path, wheel: Path) -> tuple[AssetSource, ...]:
    """Create opaque source artifacts around the one production wheel authority."""
    root.mkdir(parents=True, exist_ok=True)
    sources = (
        AssetSource(
            kind=ComponentAssetKind.PYTHON_RUNTIME,
            path=root / "cpython-source.zip",
            version=CPYTHON_VERSION_PIN,
            license="PSF-2.0",
        ),
        AssetSource(
            kind=ComponentAssetKind.A2A_DISTRIBUTION,
            path=wheel,
        ),
        AssetSource(
            kind=ComponentAssetKind.NODE_RUNTIME,
            path=root / "node-source.zip",
            version=NODEJS_VERSION_PIN,
            license="MIT",
        ),
        AssetSource(
            kind=ComponentAssetKind.ACP_ADAPTER,
            path=root / "acp-source.tgz",
            version=ACP_VERSION_PIN,
            license="Apache-2.0",
        ),
    )
    for source in sources:
        if source.kind is not ComponentAssetKind.A2A_DISTRIBUTION:
            source.path.write_bytes(f"source:{source.kind.value}".encode())
    return sources


def _emit(
    wheel: Path,
    root: Path,
    *,
    target: TargetTriple = TargetTriple.LINUX_X86_64,
    assets: tuple[AssetSource, ...] | None = None,
    uv_lock: Path | None = None,
    package_lock: Path | None = None,
) -> ComponentManifest:
    return emit_component_manifest(
        target=target,
        api_versions=_API_RANGE,
        assets=_source_closure(root / "sources", wheel) if assets is None else assets,
        uv_lock_path=_PROJECT_ROOT / "uv.lock" if uv_lock is None else uv_lock,
        package_lock_path=(
            _PROJECT_ROOT / "package-lock.json"
            if package_lock is None
            else package_lock
        ),
    )


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def test_emitter_derives_identity_entrypoints_and_digest_from_exact_built_wheel(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    manifest = _emit(built_wheel.path, tmp_path)
    scripts = cast("dict[str, str]", built_wheel.project["scripts"])

    assert manifest.identity.name == built_wheel.project["name"]
    assert manifest.identity.version == built_wheel.project["version"]
    assert manifest.compatibility.migration_range.base == "0001"
    assert manifest.compatibility.migration_range.head == "0008"
    assert manifest.entrypoints.gateway == GatewayEntrypoint(
        kind=EntrypointKind.GATEWAY,
        console_script="vaultspec-a2a",
        reference=scripts["vaultspec-a2a"],
        relative_command=("bin", "vaultspec-a2a"),
    )
    assert manifest.entrypoints.standalone_mcp == StandaloneMcpEntrypoint(
        kind=EntrypointKind.STANDALONE_MCP,
        console_script="vaultspec-a2a-mcp",
        reference=scripts["vaultspec-a2a-mcp"],
        relative_command=("bin", "vaultspec-a2a-mcp"),
    )

    assets = {asset.kind: asset for asset in manifest.assets}
    wheel_asset = assets[ComponentAssetKind.A2A_DISTRIBUTION]
    assert wheel_asset.version == manifest.identity.version
    assert wheel_asset.license == built_wheel.project["license"] == "MIT"
    assert wheel_asset.digest == _sha256(built_wheel.path)
    assert [asset.kind.value for asset in manifest.assets] == sorted(
        kind.value for kind in ComponentAssetKind
    )


def test_windows_commands_are_typed_and_capsule_relative(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    manifest = _emit(
        built_wheel.path,
        tmp_path,
        target=TargetTriple.WINDOWS_X86_64,
    )
    assert isinstance(manifest.entrypoints.gateway, GatewayEntrypoint)
    assert isinstance(manifest.entrypoints.standalone_mcp, StandaloneMcpEntrypoint)
    assert manifest.entrypoints.gateway.relative_command == (
        "Scripts",
        "vaultspec-a2a.exe",
    )
    assert manifest.entrypoints.standalone_mcp.relative_command == (
        "Scripts",
        "vaultspec-a2a-mcp.exe",
    )


def test_emission_and_canonical_bytes_are_deterministic(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    sources = tuple(reversed(_source_closure(tmp_path / "sources", built_wheel.path)))
    first = _emit(built_wheel.path, tmp_path / "one", assets=sources)
    second = _emit(built_wheel.path, tmp_path / "two", assets=sources)

    assert first == second
    assert component_manifest_canonical_bytes(
        first
    ) == component_manifest_canonical_bytes(second)
    assert component_manifest_digest(first) == component_manifest_digest(second)


def test_source_closure_cardinality_and_pins_fail_before_file_io(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "must-not-be-opened.whl"
    incomplete = (
        AssetSource(
            kind=ComponentAssetKind.A2A_DISTRIBUTION,
            path=absent,
        ),
    )
    with pytest.raises(ManifestEmissionError, match="exactly four sources"):
        _emit(absent, tmp_path / "incomplete", assets=incomplete)

    unpinned = (
        AssetSource(
            kind=ComponentAssetKind.A2A_DISTRIBUTION,
            path=absent,
        ),
        AssetSource(
            kind=ComponentAssetKind.PYTHON_RUNTIME,
            path=absent,
            version=CPYTHON_VERSION_PIN,
            license="PSF-2.0",
        ),
        AssetSource(
            kind=ComponentAssetKind.NODE_RUNTIME,
            path=absent,
            version="24",
            license="MIT",
        ),
        AssetSource(
            kind=ComponentAssetKind.ACP_ADAPTER,
            path=absent,
            version=ACP_VERSION_PIN,
            license="Apache-2.0",
        ),
    )
    with pytest.raises(ManifestEmissionError, match="pinned to 22"):
        _emit(absent, tmp_path / "unpinned", assets=unpinned)


@pytest.mark.parametrize(
    ("version", "license_expression"),
    (("999.0", None), (None, "MIT")),
)
def test_a2a_identity_facts_are_not_caller_supplied(
    tmp_path: Path,
    version: str | None,
    license_expression: str | None,
) -> None:
    absent = tmp_path / "must-not-be-opened.whl"
    sources = list(_source_closure(tmp_path / "sources", absent))
    source = sources[1]
    sources[1] = AssetSource(
        kind=source.kind,
        path=source.path,
        version=version,
        license=license_expression,
    )
    with pytest.raises(ManifestEmissionError, match="derive from wheel METADATA"):
        _emit(absent, tmp_path, assets=tuple(sources))


def _wheel_with_duplicate_gateway(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as original:
        entrypoint_members = tuple(
            info
            for info in original.infolist()
            if info.filename.endswith(".dist-info/entry_points.txt")
        )
        assert len(entrypoint_members) == 1, entrypoint_members
        entrypoint_name = entrypoint_members[0].filename
        with zipfile.ZipFile(destination, "w") as altered:
            for info in original.infolist():
                payload = original.read(info)
                if info.filename == entrypoint_name:
                    payload += b"\nvaultspec-a2a = duplicate.module:main\n"
                altered.writestr(info, payload)


def _wheel_with_wrong_mcp_reference(source: Path, destination: Path) -> None:
    expected = b"vaultspec-a2a-mcp = vaultspec_a2a.protocols.mcp.__main__:main"
    replacement = b"vaultspec-a2a-mcp = unrelated.module:main"
    replaced = False
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as altered,
    ):
        for info in original.infolist():
            payload = original.read(info)
            if info.filename.endswith(".dist-info/entry_points.txt"):
                assert payload.count(expected) == 1, payload
                payload = payload.replace(expected, replacement, 1)
                replaced = True
            altered.writestr(info, payload)
    assert replaced


def _wheel_with_metadata_header(
    source: Path,
    destination: Path,
    header: str,
    value: str,
) -> None:
    replaced = False
    marker = f"{header}: ".encode()
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as altered,
    ):
        for info in original.infolist():
            payload = original.read(info)
            if info.filename.endswith(".dist-info/METADATA"):
                lines = payload.splitlines(keepends=True)
                matching = tuple(
                    index for index, line in enumerate(lines) if line.startswith(marker)
                )
                assert len(matching) == 1, matching
                line_ending = b"\r\n" if lines[matching[0]].endswith(b"\r\n") else b"\n"
                lines[matching[0]] = marker + value.encode() + line_ending
                payload = b"".join(lines)
                replaced = True
            altered.writestr(info, payload)
    assert replaced


def _wheel_with_mixed_dist_info_roots(source: Path, destination: Path) -> None:
    moved = False
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as altered,
    ):
        for info in original.infolist():
            payload = original.read(info)
            name = info.filename
            if name.endswith(".dist-info/entry_points.txt"):
                name = "mixed_identity-9.9.9.dist-info/entry_points.txt"
                moved = True
            altered.writestr(name, payload)
    assert moved


def _wheel_with_misnamed_dist_info_root(source: Path, destination: Path) -> None:
    renamed = 0
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as altered,
    ):
        for info in original.infolist():
            payload = original.read(info)
            name = info.filename
            if len(Path(name).parts) == 2 and Path(name).parts[0].endswith(
                ".dist-info"
            ):
                name = f"wrong_name-9.9.9.dist-info/{Path(name).parts[1]}"
                renamed += 1
            altered.writestr(name, payload)
    assert renamed >= 3


def _wheel_without_migrations(source: Path, destination: Path) -> None:
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as altered,
    ):
        for info in original.infolist():
            if not info.filename.startswith("vaultspec_a2a/database/migrations/"):
                altered.writestr(info, original.read(info))


def _wheel_with_migration_traversal(source: Path, destination: Path) -> None:
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as altered,
    ):
        for info in original.infolist():
            altered.writestr(info, original.read(info))
        altered.writestr(
            "vaultspec_a2a/database/migrations/../outside.py",
            b"revision = 'outside'\ndown_revision = None\n",
        )


def _wheel_with_added_migration(
    source: Path,
    destination: Path,
    relative_name: str,
) -> None:
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as altered,
    ):
        for info in original.infolist():
            altered.writestr(info, original.read(info))
        altered.writestr(
            f"vaultspec_a2a/database/migrations/{relative_name}",
            b"revision = 'outside'\ndown_revision = '0007'\n",
        )


def _wheel_with_case_colliding_migration(source: Path, destination: Path) -> None:
    added = False
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as altered,
    ):
        for info in original.infolist():
            payload = original.read(info)
            altered.writestr(info, payload)
            if (
                not added
                and "/migrations/versions/" in info.filename
                and info.filename.endswith(".py")
            ):
                prefix, relative = info.filename.split("/migrations/", 1)
                altered.writestr(f"{prefix}/migrations/{relative.upper()}", payload)
                added = True
    assert added


def _wheel_with_broken_migration(
    source: Path,
    destination: Path,
    payload: bytes,
) -> None:
    replaced = False
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(destination, "w") as altered,
    ):
        for info in original.infolist():
            member_payload = original.read(info)
            if info.filename.endswith(
                "/migrations/versions/0007_authoring_event_cursor.py"
            ):
                member_payload = payload
                replaced = True
            altered.writestr(info, member_payload)
    assert replaced


def test_duplicate_required_console_script_is_rejected_before_collapse(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate-entrypoint.whl"
    _wheel_with_duplicate_gateway(built_wheel.path, duplicate)
    with pytest.raises(ManifestEmissionError, match="declares duplicates"):
        _emit(duplicate, tmp_path)


def test_required_console_script_reference_is_fail_closed(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    altered = tmp_path / "wrong-mcp-reference.whl"
    _wheel_with_wrong_mcp_reference(built_wheel.path, altered)
    with pytest.raises(ManifestEmissionError, match="unexpected reference"):
        _emit(altered, tmp_path)


def test_dist_info_documents_must_share_one_root(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    mixed = tmp_path / "mixed-dist-info-roots.whl"
    _wheel_with_mixed_dist_info_roots(built_wheel.path, mixed)
    with pytest.raises(ManifestEmissionError, match="share one root"):
        _emit(mixed, tmp_path)


def test_dist_info_root_must_match_metadata_identity(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    misnamed = tmp_path / "misnamed-dist-info-root.whl"
    _wheel_with_misnamed_dist_info_root(built_wheel.path, misnamed)
    with pytest.raises(ManifestEmissionError, match="does not match METADATA"):
        _emit(misnamed, tmp_path)


@pytest.mark.parametrize(
    ("header", "value"),
    (("Version", "v" * 65), ("License-Expression", "L" * 129)),
)
def test_wheel_metadata_component_strings_are_bounded_before_materialization(
    built_wheel: WheelEvidence,
    tmp_path: Path,
    header: str,
    value: str,
) -> None:
    malformed = tmp_path / f"overlong-{header.casefold()}.whl"
    _wheel_with_metadata_header(built_wheel.path, malformed, header, value)
    with pytest.raises(
        ManifestEmissionError,
        match="A2A wheel METADATA component facts are invalid",
    ):
        _emit(malformed, tmp_path)


def test_migration_archive_traversal_is_rejected(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    unsafe = tmp_path / "migration-traversal.whl"
    _wheel_with_migration_traversal(built_wheel.path, unsafe)
    with pytest.raises(ManifestEmissionError, match="unsafe archive path"):
        _emit(unsafe, tmp_path)


@pytest.mark.parametrize(
    "relative_name",
    (
        "versions/CON.py",
        "versions/evil:stream.py",
        f"versions/{'x' * 129}.py",
    ),
)
def test_nonportable_migration_members_are_rejected(
    built_wheel: WheelEvidence,
    tmp_path: Path,
    relative_name: str,
) -> None:
    malicious = tmp_path / "nonportable-migration.whl"
    _wheel_with_added_migration(built_wheel.path, malicious, relative_name)
    with pytest.raises(ManifestEmissionError, match="non-portable path"):
        _emit(malicious, tmp_path)


def test_migration_path_depth_is_bounded(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    malicious = tmp_path / "deep-migration.whl"
    relative_name = "/".join((*(["level"] * 17), "revision.py"))
    _wheel_with_added_migration(built_wheel.path, malicious, relative_name)
    with pytest.raises(ManifestEmissionError, match="depth bound"):
        _emit(malicious, tmp_path)


def test_case_colliding_migration_members_are_rejected(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    collision = tmp_path / "migration-case-collision.whl"
    _wheel_with_case_colliding_migration(built_wheel.path, collision)
    with pytest.raises(ManifestEmissionError, match="colliding portable paths"):
        _emit(collision, tmp_path)


@pytest.mark.parametrize(
    "payload",
    (b"def broken(:\n", b"raise RuntimeError('private migration detail')\n"),
)
def test_malformed_migration_modules_are_normalized(
    built_wheel: WheelEvidence,
    tmp_path: Path,
    payload: bytes,
) -> None:
    malformed = tmp_path / "malformed-migration.whl"
    _wheel_with_broken_migration(built_wheel.path, malformed, payload)
    with pytest.raises(ManifestEmissionError, match="migration graph") as error:
        _emit(malformed, tmp_path)
    assert str(tmp_path) not in str(error.value)
    assert "private migration detail" not in str(error.value)


def test_runtime_types_are_rejected_before_artifact_access(tmp_path: Path) -> None:
    absent = tmp_path / "must-not-be-opened"
    sources = _source_closure(tmp_path / "sources", absent)

    invalid_member = list(sources)
    invalid_member[0] = cast("Any", object())
    with pytest.raises(ManifestEmissionError, match="must be AssetSource"):
        _emit(absent, tmp_path, assets=cast("Any", invalid_member))

    with pytest.raises(ManifestEmissionError, match="target must be"):
        emit_component_manifest(
            target=cast("Any", "x86_64-unknown-linux-gnu"),
            api_versions=_API_RANGE,
            assets=sources,
            uv_lock_path=absent,
            package_lock_path=absent,
        )
    with pytest.raises(ManifestEmissionError, match="api_versions must be"):
        emit_component_manifest(
            target=TargetTriple.LINUX_X86_64,
            api_versions=cast("Any", {"minimum": "v1", "maximum": "v1"}),
            assets=sources,
            uv_lock_path=absent,
            package_lock_path=absent,
        )
    with pytest.raises(ManifestEmissionError, match="digest_algorithm must be"):
        emit_component_manifest(
            target=TargetTriple.LINUX_X86_64,
            api_versions=_API_RANGE,
            assets=sources,
            uv_lock_path=absent,
            package_lock_path=absent,
            digest_algorithm=cast("Any", "sha256"),
        )
    with pytest.raises(ManifestEmissionError, match="lock paths must be Path"):
        emit_component_manifest(
            target=TargetTriple.LINUX_X86_64,
            api_versions=_API_RANGE,
            assets=sources,
            uv_lock_path=cast("Any", "uv.lock"),
            package_lock_path=absent,
        )


def test_source_strings_are_bounded_before_artifact_access(tmp_path: Path) -> None:
    absent = tmp_path / "must-not-be-opened"
    sources = list(_source_closure(tmp_path / "sources", absent))
    acp = sources[3]
    sources[3] = AssetSource(
        kind=acp.kind,
        path=acp.path,
        version=acp.version,
        license="x" * 129,
    )
    with pytest.raises(ManifestEmissionError, match="source strings are invalid"):
        _emit(absent, tmp_path, assets=tuple(sources))


def test_asset_paths_must_resolve_to_ordinary_regular_files(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "directory-source"
    directory.mkdir()
    sources = list(_source_closure(tmp_path / "sources", built_wheel.path))
    python_source = sources[0]
    sources[0] = AssetSource(
        kind=python_source.kind,
        path=directory,
        version=python_source.version,
        license=python_source.license,
    )
    with pytest.raises(ManifestEmissionError, match="regular file"):
        _emit(built_wheel.path, tmp_path / "directory", assets=tuple(sources))

    special = tmp_path / "NUL"
    sources[0] = AssetSource(
        kind=python_source.kind,
        path=special,
        version=python_source.version,
        license=python_source.license,
    )
    with pytest.raises(ManifestEmissionError, match="regular file"):
        _emit(built_wheel.path, tmp_path / "special", assets=tuple(sources))


def test_lock_paths_must_resolve_to_ordinary_regular_files(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "lock-directory"
    directory.mkdir()
    with pytest.raises(ManifestEmissionError, match=r"uv lock.*regular file"):
        _emit(built_wheel.path, tmp_path, uv_lock=directory)


def test_expected_input_failures_are_path_safe_manifest_errors(
    built_wheel: WheelEvidence,
    tmp_path: Path,
) -> None:
    corrupt_wheel = tmp_path / "private-wheel-name.whl"
    corrupt_wheel.write_bytes(b"not a zip")
    with pytest.raises(ManifestEmissionError) as corrupt:
        _emit(corrupt_wheel, tmp_path / "corrupt")
    assert str(tmp_path) not in str(corrupt.value)

    sources = list(_source_closure(tmp_path / "sources", built_wheel.path))
    missing = tmp_path / "private-source-name.zip"
    sources[0] = AssetSource(
        kind=ComponentAssetKind.PYTHON_RUNTIME,
        path=missing,
        version=CPYTHON_VERSION_PIN,
        license="PSF-2.0",
    )
    with pytest.raises(ManifestEmissionError) as unreadable:
        _emit(built_wheel.path, tmp_path / "missing", assets=tuple(sources))
    assert str(tmp_path) not in str(unreadable.value)

    no_migrations = tmp_path / "private-no-migrations.whl"
    _wheel_without_migrations(built_wheel.path, no_migrations)
    with pytest.raises(ManifestEmissionError, match="migration tree") as migration:
        _emit(no_migrations, tmp_path / "migration")
    assert str(tmp_path) not in str(migration.value)


def test_canonical_json_v1_matches_cross_language_golden_vector() -> None:
    encoded = (
        (_FIXTURES / "component-manifest-canonical-v1.b64")
        .read_text(encoding="ascii")
        .strip()
    )
    golden_bytes = base64.b64decode(encoded, validate=True)
    expected_digest = (
        (_FIXTURES / "component-manifest-canonical-v1.sha256")
        .read_text(encoding="ascii")
        .strip()
    )
    manifest = ComponentManifest.model_validate_json(golden_bytes)

    assert CANONICAL_JSON_VERSION == "vaultspec-canonical-json-v1"
    assert not golden_bytes.startswith(b"\xef\xbb\xbf")
    assert not golden_bytes.endswith(b"\n")
    assert (
        expected_digest
        == "aab76059c36377168ff370d1531e525f26628e1919c157a035873c1665113368"
    )
    assert component_manifest_canonical_bytes(manifest) == golden_bytes
    assert component_manifest_digest(manifest) == expected_digest
    parsed = json.loads(golden_bytes)
    assert parsed["assets"][1]["license"] == 'LicenseRef-café-"quoted"-\\path'
    assert parsed["identity"]["version"] == parsed["assets"][0]["version"]

    digest_signature = inspect.signature(component_manifest_digest)
    assert tuple(digest_signature.parameters) == ("manifest",)
    with pytest.raises(TypeError):
        digest_signature.bind(manifest, algorithm=DigestAlgorithm.SHA256)
