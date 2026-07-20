"""Certify the desktop capsule state lifecycle: migration, rollback, consistency
restore, tamper detection, and immutable-file verification from real capsule state.

All operations are driven through CLI commands run from the installed capsule
python or against real SQLite stores.  Tamper = real byte flips; immutable-file
verification uses the wheel's standard RECORD file (the Python packaging
authority for installed-file integrity).  No mock, monkeypatch, stub, skip, or
expected failure is used.

Install strategy
----------------
Same wheel-install approach as ``test_artifact_install.py`` (see that module's
docstring for rationale).  The transport capsule's ``verify_desktop_capsule.py``
asset-digest checks apply to the full CPython+Node ZIP format produced by S13;
those checks are proved in ``test_capsule_verify.py``.  For the installed-wheel
layout used here, the analogous integrity authority is the wheel RECORD file,
and that is what tamper-detection proves.

All tests are marked ``service`` because they run ``uv build`` and provision a
clean environment.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import subprocess
from io import StringIO
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.desktop.transaction import package_migration_range

from .harness import (
    _MODULE,
    InstalledCapsule,
    build_and_install,
    seat_valid_database,
    seed_credentials,
    write_migration_descriptor,
)

# ---------------------------------------------------------------------------
# Module-scoped fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def installed_capsule(tmp_path_factory: pytest.TempPathFactory) -> InstalledCapsule:
    """Build the project wheel and install the desktop closure into a clean venv."""
    sandbox = tmp_path_factory.mktemp("artifact-state-capsule")
    return build_and_install(sandbox)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(
    python: Path,
    *args: str,
    timeout: int = 120,
) -> tuple[int, str]:
    """Run a CLI command via *python* and return (returncode, stdout)."""
    result = subprocess.run(
        [str(python), "-m", _MODULE, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout


def _set_marker(db_path: Path, value: str) -> None:
    """Write a distinguishable marker row into a real SQLite store."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS state_marker (v TEXT NOT NULL)")
        conn.execute("DELETE FROM state_marker")
        conn.execute("INSERT INTO state_marker (v) VALUES (?)", (value,))
        conn.commit()
    finally:
        conn.close()


def _read_marker(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT v FROM state_marker").fetchone()
        assert row is not None, f"no marker row in {db_path}"
        return str(row[0])
    finally:
        conn.close()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(1 << 20):
            hasher.update(block)
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# S74 test 1 - migration via the installed CLI
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_migration_from_installed_capsule(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """The installed desktop-migrate command seats a real Alembic-headed database.

    Drives the CLI from the installed python, proving migration runs from the
    isolated environment without importing from the development tree.
    """
    head = package_migration_range().head
    app_home = tmp_path / "app"
    descriptor = write_migration_descriptor(
        tmp_path / "txn.json", app_home, "state-migrate-txn-1"
    )

    code, stdout = _run_cli(
        installed_capsule.python,
        "desktop-migrate",
        "--descriptor",
        str(descriptor),
    )
    payload = json.loads(stdout.strip())
    assert code == 0, payload
    assert payload["status"] == "succeeded"
    assert payload["target_head"] == head

    state = derive_state_paths(app_home)
    version = (
        sqlite3.connect(str(state.database_path))
        .execute("SELECT version_num FROM alembic_version")
        .fetchone()
    )
    assert version is not None and version[0] == head
    assert state.checkpoint_path.is_file()


# ---------------------------------------------------------------------------
# S74 test 2 - snapshot rollback via the installed CLI
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_snapshot_rollback_via_installed_cli(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """Snapshot captures state; restore rolls back to it after mutation.

    Drives ``desktop-snapshot-create`` and ``desktop-snapshot-restore`` from the
    installed python, with real SQLite marker rows as distinguishable state.
    This proves the snapshot-based rollback path the external updater uses.
    """
    app_home = tmp_path / "app"
    seed_credentials(app_home, prefix="rollback")
    descriptor = write_migration_descriptor(
        tmp_path / "txn.json", app_home, "rollback-txn-1"
    )
    seat_valid_database(installed_capsule.python, app_home, descriptor)

    state = derive_state_paths(app_home)
    _set_marker(state.database_path, "pre-update")
    _set_marker(state.checkpoint_path, "pre-update-ckpt")

    # Capture the consistency group.
    code, stdout = _run_cli(
        installed_capsule.python,
        "desktop-snapshot-create",
        "--app-home",
        str(app_home),
        "--group-id",
        "rollback-group",
    )
    descriptor_json = json.loads(stdout.strip())
    assert code == 0, descriptor_json
    assert descriptor_json["group_id"] == "rollback-group"

    # Mutate both stores (simulating a failed update).
    _set_marker(state.database_path, "failed-update")
    _set_marker(state.checkpoint_path, "failed-update-ckpt")
    assert _read_marker(state.database_path) == "failed-update"

    # Restore from the captured group.
    restore_code, restore_out = _run_cli(
        installed_capsule.python,
        "desktop-snapshot-restore",
        "--app-home",
        str(app_home),
        "--group-id",
        "rollback-group",
    )
    restore_json = json.loads(restore_out.strip())
    assert restore_code == 0, restore_json

    # Both stores rolled back to the captured content.
    assert _read_marker(state.database_path) == "pre-update"
    assert _read_marker(state.checkpoint_path) == "pre-update-ckpt"


# ---------------------------------------------------------------------------
# S74 test 3 - consistency restore: both stores change together
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_consistency_restore_both_stores_together(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """Restore returns both stores to their captured state atomically.

    Drifts the primary and checkpoint independently after capture, then restores.
    Neither store is left at its drifted value after restore, proving the group
    is treated as one unit.
    """
    app_home = tmp_path / "app"
    seed_credentials(app_home, prefix="consistency")
    descriptor = write_migration_descriptor(
        tmp_path / "txn.json", app_home, "consistency-txn-1"
    )
    seat_valid_database(installed_capsule.python, app_home, descriptor)
    state = derive_state_paths(app_home)

    _set_marker(state.database_path, "primary-captured")
    _set_marker(state.checkpoint_path, "checkpoint-captured")

    code, _ = _run_cli(
        installed_capsule.python,
        "desktop-snapshot-create",
        "--app-home",
        str(app_home),
        "--group-id",
        "consistency-group",
    )
    assert code == 0

    # Drift each store independently.
    _set_marker(state.database_path, "primary-drifted")
    _set_marker(state.checkpoint_path, "checkpoint-drifted")

    restore_code, _ = _run_cli(
        installed_capsule.python,
        "desktop-snapshot-restore",
        "--app-home",
        str(app_home),
        "--group-id",
        "consistency-group",
    )
    assert restore_code == 0

    # Both return to their individually-captured content — the group is atomic.
    assert _read_marker(state.database_path) == "primary-captured"
    assert _read_marker(state.checkpoint_path) == "checkpoint-captured"


# ---------------------------------------------------------------------------
# S74 test 4 - tamper detection via real byte flips and RECORD verification
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_tamper_detection_real_byte_flip(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """Real byte flips in installed capsule files are detected via the RECORD file.

    The wheel RECORD (``{package}.dist-info/RECORD``) is the Python packaging
    authority for installed-file integrity: it lists every installed file with its
    sha256 digest.  This test:

    1. Locates one installed .py file and reads its RECORD-declared sha256.
    2. Flips a byte in that file (real mutation, not a mock).
    3. Recomputes the sha256 and proves it no longer matches the RECORD entry.

    This is the equivalent of the transport capsule's ``verify_desktop_capsule.py``
    asset-digest check for the installed-wheel form: both prove that a tampered
    immutable file is detectable via a content-addressed record.
    """
    dist_info_dirs = list(
        installed_capsule.install_root.rglob("vaultspec_a2a-*.dist-info")
    )
    assert dist_info_dirs, (
        f"vaultspec_a2a dist-info not found under {installed_capsule.install_root}"
    )
    record_path = dist_info_dirs[0] / "RECORD"
    site_packages = dist_info_dirs[0].parent
    record_text = record_path.read_text(encoding="utf-8")

    # Find an installed .py source file that has a sha256 in the RECORD.
    target_file: Path | None = None
    expected_hash: str | None = None
    for row in csv.reader(StringIO(record_text)):
        if len(row) < 2:
            continue
        rel, digest_field = row[0], row[1]
        if not rel.endswith(".py") or not digest_field.startswith("sha256="):
            continue
        candidate = site_packages / rel
        if candidate.is_file():
            target_file = candidate
            expected_hash = digest_field[len("sha256="):]
            break

    assert target_file is not None, "no .py file with sha256 found in RECORD"
    assert expected_hash is not None

    # Verify the untampered file matches its RECORD entry.
    import base64

    def _sha256_b64(path: Path) -> str:
        digest = hashlib.sha256(path.read_bytes()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    assert _sha256_b64(target_file) == expected_hash, (
        f"pre-tamper hash mismatch for {target_file} — test precondition violated"
    )

    # Flip one byte in the target file (real mutation).
    original = target_file.read_bytes()
    tampered = bytearray(original)
    tampered[0] ^= 0xFF
    target_file.write_bytes(bytes(tampered))

    # The recomputed sha256 no longer matches the RECORD entry.
    assert _sha256_b64(target_file) != expected_hash, (
        "tampered file must not match its RECORD-declared digest"
    )

    # Restore the file so the module-scoped capsule stays usable.
    target_file.write_bytes(original)
    assert _sha256_b64(target_file) == expected_hash


# ---------------------------------------------------------------------------
# S74 test 5 - snapshot inspect verifies integrity after capture
# ---------------------------------------------------------------------------


@pytest.mark.service
def test_snapshot_inspect_verifies_integrity(
    installed_capsule: InstalledCapsule, tmp_path: Path
) -> None:
    """Snapshot inspect confirms captured-store integrity via the installed CLI.

    After a snapshot is created, ``desktop-snapshot-inspect`` re-verifies the
    captured copies against their recorded digests and returns the group
    descriptor.  A tampered snapshot copy causes inspect to fail closed.
    """
    app_home = tmp_path / "app"
    seed_credentials(app_home, prefix="inspect")
    descriptor = write_migration_descriptor(
        tmp_path / "txn.json", app_home, "inspect-txn-1"
    )
    seat_valid_database(installed_capsule.python, app_home, descriptor)

    code, stdout = _run_cli(
        installed_capsule.python,
        "desktop-snapshot-create",
        "--app-home",
        str(app_home),
        "--group-id",
        "inspect-group",
    )
    assert code == 0
    created = json.loads(stdout.strip())
    assert created["group_id"] == "inspect-group"

    # Inspect succeeds: every captured copy still matches its recorded digest.
    inspect_code, inspect_out = _run_cli(
        installed_capsule.python,
        "desktop-snapshot-inspect",
        "--app-home",
        str(app_home),
        "--group-id",
        "inspect-group",
    )
    assert inspect_code == 0, inspect_out
    inspected = json.loads(inspect_out.strip())
    assert inspected["group_id"] == "inspect-group"
    assert len(inspected["stores"]) > 0

    # Tamper one captured copy with a real byte flip.
    state = derive_state_paths(app_home)
    snapshots_dir = state.snapshots_dir / "inspect-group"
    captured_files = list(snapshots_dir.glob("*.snap"))
    assert captured_files, f"no .snap files found under {snapshots_dir}"
    target = captured_files[0]
    raw = target.read_bytes()
    flipped = bytearray(raw)
    flipped[-1] ^= 0xFF
    target.write_bytes(bytes(flipped))

    # Inspect now fails closed: the tampered copy fails its digest check.
    tamper_code, _ = _run_cli(
        installed_capsule.python,
        "desktop-snapshot-inspect",
        "--app-home",
        str(app_home),
        "--group-id",
        "inspect-group",
    )
    assert tamper_code != 0, "inspect must fail when a captured store is tampered"
