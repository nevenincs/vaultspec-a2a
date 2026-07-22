"""Production preparation orchestration, proven against the real pinned inputs.

The source-fact loader is proven offline against the actual committed
pinned-inputs document for every target: the facts it derives from each pinned
url are round-tripped through the real ``author_source_descriptors`` so a fact
is proven only when the descriptor authority accepts it, never asserted against
this module's own output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vaultspec_a2a.desktop.artifacts import ArchiveKind, ComponentAssetKind
from vaultspec_a2a.desktop.capsule_descriptor import author_source_descriptors
from vaultspec_a2a.desktop.capsule_input_authoring import (
    BuiltDistribution,
    CapsuleInputAuthoringError,
    build_a2a_distribution_wheel,
)
from vaultspec_a2a.desktop.capsule_preparation import (
    derive_project_wheel_artifact,
    load_source_inputs,
)
from vaultspec_a2a.desktop.contract import TargetTriple

_REPO_ROOT = Path(__file__).resolve().parents[4]

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
