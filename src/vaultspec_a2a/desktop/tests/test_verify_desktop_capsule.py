"""Prove the reworked capsule generation verifier against a real generation.

The offline unit tests exercise the verifier's pure structure check. The
service-marked end-to-end tests reuse the build stage's real-descriptor fixture
to assemble a real generation, verify it passes read-only against its pinned
inputs, and prove every integrity check fails closed under a real on-disk
tamper (a flipped closure byte, a doctored drop-audit-trail, a corrupted
archive).

No mocks, stubs, or expected failures: the generation is assembled by the real
build from real archives, and every tamper mutates real materialized bytes.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest

from vaultspec_a2a.desktop.capsule_assembly import (
    CAPSULE_ARCHIVE_OUTPUT_NAME,
    CAPSULE_ROOT,
)
from vaultspec_a2a.desktop.contract import TargetTriple
from vaultspec_a2a.desktop.tests.test_build_desktop_capsule import (
    _BUILD,
    _prepared_inputs,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

_REPO_ROOT: Final = Path(__file__).resolve().parents[4]
_VERIFY_SCRIPT: Final = _REPO_ROOT / "scripts" / "verify_desktop_capsule.py"
_TARGET: Final = TargetTriple.LINUX_X86_64


def _load_verify_module() -> ModuleType:
    """Load the standalone verifier script as an importable module by its path."""
    spec = importlib.util.spec_from_file_location(
        "verify_desktop_capsule", _VERIFY_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the module's slotted dataclass resolves its string
    # annotations through sys.modules during class creation.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_VERIFY: Final = _load_verify_module()


# ---------------------------------------------------------------------------
# Offline unit tests: structure
# ---------------------------------------------------------------------------


def test_structure_accepts_a_capsule_tree_and_its_archive(tmp_path: Path) -> None:
    (tmp_path / CAPSULE_ROOT).mkdir()
    (tmp_path / CAPSULE_ARCHIVE_OUTPUT_NAME).write_bytes(b"PK\x05\x06")
    capsule, archive = _VERIFY._check_structure(tmp_path)
    assert capsule == tmp_path / CAPSULE_ROOT
    assert archive == tmp_path / CAPSULE_ARCHIVE_OUTPUT_NAME


def test_structure_fails_closed_without_the_archive(tmp_path: Path) -> None:
    (tmp_path / CAPSULE_ROOT).mkdir()
    with pytest.raises(_VERIFY.VerificationError, match="exactly the capsule tree"):
        _VERIFY._check_structure(tmp_path)


def test_structure_fails_closed_on_an_unexpected_entry(tmp_path: Path) -> None:
    (tmp_path / CAPSULE_ROOT).mkdir()
    (tmp_path / CAPSULE_ARCHIVE_OUTPUT_NAME).write_bytes(b"PK\x05\x06")
    (tmp_path / "stray.txt").write_bytes(b"unexpected")
    with pytest.raises(_VERIFY.VerificationError, match="exactly the capsule tree"):
        _VERIFY._check_structure(tmp_path)


# ---------------------------------------------------------------------------
# Service-marked end-to-end verification against a real generation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def verifiable_generation(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[dict[str, object]]:
    """Assemble one real generation and yield the verifier's read-only inputs."""
    root = tmp_path_factory.mktemp("verify-generation")
    with _prepared_inputs(root) as (descriptor_path, digest, cache, uv, package):
        generation, _ = _BUILD._run_build(
            target=_TARGET,
            descriptor_path=descriptor_path,
            descriptor_sha256=digest,
            input_dir=cache,
            uv_lock=uv,
            package_lock=package,
            out_dir=root / "out",
            launcher_stub_donor=None,
        )
        yield {
            "target": _TARGET,
            "generation": generation,
            "descriptor_path": descriptor_path,
            "descriptor_sha256": digest,
            "input_dir": cache,
            "uv_lock": uv,
            "package_lock": package,
        }


def _verify(inputs: dict[str, object], *, generation: Path | None = None) -> Any:
    kwargs = dict(inputs)
    if generation is not None:
        kwargs["generation"] = generation
    return _VERIFY.verify_generation(**kwargs)


def _clone_generation(inputs: dict[str, object], destination: Path) -> Path:
    source = inputs["generation"]
    assert isinstance(source, Path)
    shutil.copytree(source, destination)
    return destination


@pytest.mark.service
def test_verify_accepts_a_faithful_generation(
    verifiable_generation: dict[str, object],
) -> None:
    result = _verify(verifiable_generation)
    assert result.installed_file_count > 0
    # The drop-audit-trail the build surfaced is reconciled against the
    # inventory-bound records; the click .data/scripts member is present.
    assert any(
        record["closure"] == "python" and record["reason"] == "data-scripts"
        for record in result.dropped
    )


@pytest.mark.service
def test_verify_fails_closed_on_a_flipped_closure_byte(
    verifiable_generation: dict[str, object], tmp_path: Path
) -> None:
    clone = _clone_generation(verifiable_generation, tmp_path / "gen")
    target_file = next(
        path
        for path in (clone / CAPSULE_ROOT / "runtime" / "python").rglob("*")
        if path.is_file()
    )
    data = bytearray(target_file.read_bytes())
    data[0] ^= 0xFF
    target_file.write_bytes(bytes(data))
    with pytest.raises(_VERIFY.VerificationError, match="digest does not match"):
        _verify(verifiable_generation, generation=clone)


@pytest.mark.service
def test_verify_fails_closed_on_a_doctored_drop_audit_trail(
    verifiable_generation: dict[str, object], tmp_path: Path
) -> None:
    clone = _clone_generation(verifiable_generation, tmp_path / "gen")
    evidence_path = clone / CAPSULE_ROOT / "installed-tree.cdx.json"
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    # Drop the recorded omission entirely: an unrecorded drop must fail closed.
    document["vaultspec:dropped-members"] = []
    evidence_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(_VERIFY.VerificationError, match="drop-audit-trail"):
        _verify(verifiable_generation, generation=clone)


@pytest.mark.service
def test_verify_fails_closed_on_an_extra_dropped_record(
    verifiable_generation: dict[str, object], tmp_path: Path
) -> None:
    clone = _clone_generation(verifiable_generation, tmp_path / "gen")
    evidence_path = clone / CAPSULE_ROOT / "installed-tree.cdx.json"
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    # A dropped record the inventories never declared must fail closed: the
    # evidence may not claim an omission that did not happen.
    document["vaultspec:dropped-members"] = [
        *document["vaultspec:dropped-members"],
        {
            "closure": "acp",
            "source_member": "package/.data/scripts/fabricated",
            "source_sha256": "0" * 64,
            "size": 1,
            "sha256": "1" * 64,
            "reason": "data-scripts",
        },
    ]
    evidence_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(_VERIFY.VerificationError, match="drop-audit-trail"):
        _verify(verifiable_generation, generation=clone)


@pytest.mark.service
def test_verify_fails_closed_on_a_missing_installed_file(
    verifiable_generation: dict[str, object], tmp_path: Path
) -> None:
    clone = _clone_generation(verifiable_generation, tmp_path / "gen")
    target_file = next(
        path
        for path in (clone / CAPSULE_ROOT / "runtime" / "python").rglob("*")
        if path.is_file()
    )
    target_file.unlink()
    with pytest.raises(_VERIFY.VerificationError, match="absent from the capsule tree"):
        _verify(verifiable_generation, generation=clone)


@pytest.mark.service
def test_verify_fails_closed_on_a_corrupt_archive(
    verifiable_generation: dict[str, object], tmp_path: Path
) -> None:
    clone = _clone_generation(verifiable_generation, tmp_path / "gen")
    archive = clone / CAPSULE_ARCHIVE_OUTPUT_NAME
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0xFF
    archive.write_bytes(bytes(data))
    with pytest.raises(_VERIFY.VerificationError):
        _verify(verifiable_generation, generation=clone)


@pytest.mark.service
def test_sbom_reflects_the_verified_generation(
    verifiable_generation: dict[str, object],
) -> None:
    result = _verify(verifiable_generation)
    document = _VERIFY._build_sbom(result)
    assert document["target"] == _TARGET.value
    assert {component["kind"] for component in document["components"]} == {
        "python-runtime",
        "node-runtime",
        "acp-adapter",
        "a2a-distribution",
    }
    assert document["installed_file_count"] == result.installed_file_count
    assert document["dropped_members"] == result.dropped
