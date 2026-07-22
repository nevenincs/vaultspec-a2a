"""Production preparation orchestration, proven against the real pinned inputs.

The source-fact loader is proven offline against the actual committed
pinned-inputs document for every target: the facts it derives from each pinned
url are round-tripped through the real ``author_source_descriptors`` so a fact
is proven only when the descriptor authority accepts it, never asserted against
this module's own output.
"""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.desktop.artifacts import (
    ArchiveKind,
    ComponentAssetKind,
    open_verified_capsule_inputs,
)
from vaultspec_a2a.desktop.capsule_descriptor import author_source_descriptors
from vaultspec_a2a.desktop.capsule_input_authoring import (
    BuiltDistribution,
    CapsuleInputAuthoringError,
    build_a2a_distribution_wheel,
)
from vaultspec_a2a.desktop.capsule_preparation import (
    derive_project_wheel_artifact,
    load_source_inputs,
    prepare_capsule_inputs,
)
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.tests._capsule_inputs import (
    _python_wheel,
    _sha256,
    _sha512_sri,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ACP_ROOT = "@agentclientprotocol/claude-agent-acp"
_SDK = "@anthropic-ai/claude-agent-sdk-win32-x64"


def _npm_tarball(
    name: str,
    version: str,
    license_expression: str,
    license_path: str,
    *,
    bin_map: dict[str, str] | None = None,
    extra: tuple[tuple[str, bytes], ...] = (),
) -> bytes:
    document: dict[str, object] = {
        "name": name,
        "version": version,
        "license": license_expression,
    }
    if bin_map is not None:
        document["bin"] = bin_map
    members = [
        ("package/package.json", json.dumps(document).encode()),
        (license_path, f"{license_expression} license text\n".encode()),
        *extra,
    ]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path, payload in members:
            info = tarfile.TarInfo(path)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
    return gzip.compress(raw.getvalue(), mtime=0)


_INPUTS_TOML = (
    Path(__file__).resolve().parents[4] / "scripts" / "desktop_capsule_inputs.toml"
)
_NODE_STEM = {
    TargetTriple.MACOS_ARM64: "node-v22.17.0-darwin-arm64",
    TargetTriple.LINUX_ARM64: "node-v22.17.0-linux-arm64",
    TargetTriple.LINUX_X86_64: "node-v22.17.0-linux-x64",
    TargetTriple.WINDOWS_X86_64: "node-v22.17.0-win-x64",
}


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_source_inputs_derive_the_pinned_release_facts(target: TargetTriple) -> None:
    inputs = load_source_inputs(_INPUTS_TOML, target)

    # Facts derived from the committed, content-verified urls (from spec, not
    # from this module's output).
    assert inputs.python.release == "3.13.5"
    assert inputs.python.build == "20250702"
    assert inputs.python.archive_kind is ArchiveKind.TAR_GZIP
    assert inputs.python.archive_root == "python"
    # CPython ships its license under lib/python3.13, not at python/LICENSE.
    assert inputs.python.license_members == ("python/lib/python3.13/LICENSE.txt",)

    assert inputs.node.release == "22.17.0"
    assert inputs.node.archive_root == _NODE_STEM[target]
    assert inputs.node.license_members == (f"{_NODE_STEM[target]}/LICENSE",)
    expected_kind = (
        ArchiveKind.ZIP
        if target is TargetTriple.WINDOWS_X86_64
        else ArchiveKind.TAR_GZIP
    )
    assert inputs.node.archive_kind is expected_kind

    assert inputs.acp.release == "0.59.0"
    assert inputs.acp.build == "npm"
    assert inputs.acp.archive_root == "package"


@pytest.mark.parametrize("target", tuple(TargetTriple))
def test_derived_facts_author_valid_source_descriptors(target: TargetTriple) -> None:
    inputs = load_source_inputs(_INPUTS_TOML, target)
    # A synthetic-but-valid distribution + ACP root SRI: the oracle is that the
    # real descriptor authority accepts the derived runtime facts.
    built = BuiltDistribution(
        path=Path("dist") / "vaultspec_a2a-0.1.0-py3-none-any.whl",
        sha256="a" * 64,
        size=1024,
        source_commit="0" * 40,
    )

    sources = author_source_descriptors(
        target=target,
        python=inputs.python.runtime_source_input(size=40_000_000),
        node=inputs.node.runtime_source_input(size=30_000_000),
        acp=inputs.acp.runtime_source_input(size=200_000),
        acp_root_integrity="sha512-" + "A" * 86 + "==",
        a2a=built,
        a2a_version="0.1.0",
        a2a_license_expression="LicenseRef-Anthropic-Commercial",
        a2a_license_members=("vaultspec_a2a-0.1.0.dist-info/licenses/LICENSE",),
        a2a_redistribution_evidence=("wheel-license",),
    )

    by_kind = {source.kind: source for source in sources}
    assert set(by_kind) == set(ComponentAssetKind)
    assert by_kind[ComponentAssetKind.PYTHON_RUNTIME].release == "3.13.5"
    assert by_kind[ComponentAssetKind.NODE_RUNTIME].release == "22.17.0"
    assert by_kind[ComponentAssetKind.ACP_ADAPTER].release == "0.59.0"
    assert by_kind[ComponentAssetKind.PYTHON_RUNTIME].target is target
    # The A2A distribution is target-neutral.
    assert by_kind[ComponentAssetKind.A2A_DISTRIBUTION].target is None


@pytest.mark.service
def test_project_wheel_artifact_derives_and_verifies(tmp_path: Path) -> None:
    import shutil

    cache = tmp_path / "cache"
    cache.mkdir()
    built = build_a2a_distribution_wheel(
        repo_root=_REPO_ROOT,
        sandbox=tmp_path / "build",
        source_date_epoch=1_700_000_000,
    )
    shutil.copyfile(built.path, cache / built.sha256)

    artifact = derive_project_wheel_artifact(
        built, cache_root=cache, target=TargetTriple.LINUX_X86_64
    )

    assert artifact.name == "vaultspec-a2a"
    assert artifact.license_expression == "MIT"
    assert artifact.license_members == (
        f"vaultspec_a2a-{artifact.version}.dist-info/licenses/LICENSE",
    )
    assert artifact.sha256 == built.sha256


@pytest.mark.service
def test_prepare_capsule_inputs_opens_through_the_real_consumer(
    tmp_path: Path,
) -> None:
    click, click_bytes = _python_wheel()
    acp_root = _npm_tarball(
        _ACP_ROOT,
        "0.59.0",
        "Apache-2.0",
        "package/LICENSE",
        bin_map={"claude-agent-acp": "dist/index.js"},
        extra=(("package/dist/index.js", b"#!/usr/bin/env node\n"),),
    )
    sdk = _npm_tarball(
        _SDK, "0.3.207", "LicenseRef-Anthropic-Commercial", "package/LICENSE.md"
    )
    acp_root_url = "https://registry.npmjs.org/claude-agent-acp-0.59.0.tgz"
    sdk_url = "https://registry.npmjs.org/claude-agent-sdk-win32-x64-0.3.207.tgz"
    py_blob, node_blob, acp_src_blob = (
        b"pinned-python-runtime\n",
        b"pinned-node-runtime\n",
        b"pinned-acp-adapter\n",
    )
    py_url = (
        "https://github.com/astral-sh/python-build-standalone/releases/download/"
        "20250702/cpython-3.13.5+20250702-x86_64-pc-windows-msvc-install_only.tar.gz"
    )
    node_url = "https://nodejs.org/dist/v22.17.0/node-v22.17.0-win-x64.zip"
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
version = "{click.version}"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [
  {{ url = "{click.url}", hash = "sha256:{click.sha256}", size = {click.size} }},
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
                    "os": ["win32"],
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

[targets.x86_64-pc-windows-msvc.python]
version = "3.13"
license = "PSF-2.0"
url = "{py_url}"
sha256 = "{_sha256(py_blob)}"

[targets.x86_64-pc-windows-msvc.node]
version = "22"
license = "MIT"
url = "{node_url}"
sha256 = "{_sha256(node_blob)}"
"""

    streams = {
        click.url: click_bytes,
        acp_root_url: acp_root,
        sdk_url: sdk,
        py_url: py_blob,
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
        TargetTriple.WINDOWS_X86_64,
        inputs_toml=inputs_path,
        uv_lock=uv_path,
        package_lock=package_path,
        repo_root=_REPO_ROOT,
        cache_root=cache,
        output_dir=tmp_path / "out",
        source_date_epoch=1_700_000_000,
        open_stream=open_stream,
    )

    assert descriptor_path.exists()
    assert digest == _sha256(descriptor_path.read_bytes())
    # Independent re-proof: the real consumer opens exactly what prepare wrote,
    # with the first-party wheel installed and no attribution record.
    with open_verified_capsule_inputs(
        descriptor_path,
        expected_descriptor_sha256=digest,
        input_dir=cache,
        uv_lock_path=uv_path,
        package_lock_path=package_path,
    ) as session:
        licensed = {record.package for record in session.python_installed.licenses}
        assert licensed == {"click"}
        assert "vaultspec-a2a" not in licensed


def test_missing_target_fails_closed(tmp_path: Path) -> None:
    document = tmp_path / "inputs.toml"
    document.write_text(
        '[acp]\nversion = "0.59.0"\nlicense = "Apache-2.0"\n'
        'url = "https://registry.npmjs.org/x/-/x-0.59.0.tgz"\nsha256 = "'
        + "a" * 64
        + '"\n[targets]\n',
        encoding="utf-8",
    )
    with pytest.raises(CapsuleInputAuthoringError, match="does not declare target"):
        load_source_inputs(document, TargetTriple.LINUX_X86_64)


def test_non_pinned_python_url_fails_closed(tmp_path: Path) -> None:
    document = tmp_path / "inputs.toml"
    document.write_text(
        '[acp]\nversion = "0.59.0"\nlicense = "Apache-2.0"\n'
        'url = "https://registry.npmjs.org/x/-/x-0.59.0.tgz"\nsha256 = "'
        + "a"
        * 64
        + '"\n\n[targets.x86_64-unknown-linux-gnu.python]\nversion = "3.13"\n'
        'license = "PSF-2.0"\nurl = "https://example.invalid/python.tar.gz"\n'
        'sha256 = "' + "b" * 64 + '"\n\n'
        '[targets.x86_64-unknown-linux-gnu.node]\nversion = "22"\nlicense = "MIT"\n'
        'url = "https://nodejs.org/dist/v22.17.0/node-v22.17.0-linux-x64.tar.gz"\n'
        'sha256 = "' + "c" * 64 + '"\n',
        encoding="utf-8",
    )
    with pytest.raises(CapsuleInputAuthoringError, match="cpython install_only"):
        load_source_inputs(document, TargetTriple.LINUX_X86_64)
