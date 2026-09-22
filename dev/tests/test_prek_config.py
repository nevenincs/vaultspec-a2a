"""Guards for the repository-owned read-only prek validation boundary."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _hooks() -> list[dict[str, object]]:
    """Load every hook from the real repository-owned prek configuration."""
    config = tomllib.loads((ROOT / "prek.toml").read_text(encoding="utf-8"))
    return [
        hook for repository in config["repos"] for hook in repository.get("hooks", [])
    ]


def test_vaultspec_validation_hooks_are_read_only() -> None:
    """Keep repair commands out of the default validation pipeline."""
    hooks = _hooks()
    managed_ids = {
        "vault-fix",
        "vault-sanitize-annotations",
        "check-provider-artifacts",
        "spec-check",
    }
    vaultspec_entries: dict[str, str] = {}
    for hook in hooks:
        entry = hook.get("entry")
        hook_id = hook.get("id")
        if not isinstance(entry, str) or hook_id not in managed_ids:
            continue
        assert isinstance(hook_id, str)
        vaultspec_entries[hook_id] = entry

    assert vaultspec_entries["vault-sanitize-annotations"] == (
        "uv run --no-sync python dev/vault_annotations_gate.py"
    )
    assert all(
        marker not in entry
        for entry in vaultspec_entries.values()
        for marker in ("sanitize", "--fix", "spec sync --execute")
    )

    justfile = (ROOT / "Justfile").read_text(encoding="utf-8")
    assert "vault-sanitize:\n    {{core}} vault sanitize annotations" in justfile


def _write_fixture(root: Path, *, with_annotation: bool) -> Path:
    """Create a minimal real Core workspace and return its document path."""
    (root / ".vaultspec").mkdir()
    (root / ".vaultspec" / "workspace.json").write_text(
        '{\n  "packages": {"vaultspec-core": {"install_mode": "dev"}},\n'
        '  "schema_version": "2.2"\n}\n',
        encoding="utf-8",
    )
    document = root / ".vault" / "adr" / "fixture.md"
    document.parent.mkdir(parents=True)
    annotation = "<!-- generated template note -->\n" if with_annotation else ""
    document.write_bytes(
        (
            "---\n"
            "title: Annotation gate fixture\n"
            "tags: [adr, annotation-gate]\n"
            "---\n"
            f"{annotation}"
            "# Fixture\n"
        ).encode()
    )
    return document


def _snapshot_files(root: Path) -> dict[Path, bytes]:
    """Return all fixture bytes so a read-only run cannot hide a write."""
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _run_gate(target: Path) -> subprocess.CompletedProcess[str]:
    """Run the repository hook wrapper against an isolated workspace."""
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "dev" / "vault_annotations_gate.py"),
            "--target",
            str(target),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_annotation_gate_accepts_clean_fixture_without_writes(tmp_path: Path) -> None:
    """A clean Core result passes and leaves every fixture byte unchanged."""
    document = _write_fixture(tmp_path, with_annotation=False)
    before = _snapshot_files(tmp_path)

    result = _run_gate(tmp_path)

    assert result.returncode == 0, result.stderr
    assert _snapshot_files(tmp_path) == before
    assert document.read_bytes() == before[document.relative_to(tmp_path)]


def test_annotation_gate_rejects_bad_fixture_without_writes(tmp_path: Path) -> None:
    """A Core warning becomes a failing gate without allowing any write."""
    document = _write_fixture(tmp_path, with_annotation=True)
    before = _snapshot_files(tmp_path)

    result = _run_gate(tmp_path)

    assert result.returncode == 1, result.stderr
    assert '"total":1' in result.stdout
    assert "Template annotations remain" in result.stdout
    assert _snapshot_files(tmp_path) == before
    assert document.read_bytes() == before[document.relative_to(tmp_path)]
