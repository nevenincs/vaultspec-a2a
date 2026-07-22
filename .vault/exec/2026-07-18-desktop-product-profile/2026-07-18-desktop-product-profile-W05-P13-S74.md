---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S74'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove migration rollback consistency restore tamper detection and immutable-file verification from real capsule state

## Scope

- `src/vaultspec_a2a/desktop_tests/test_artifact_state_lifecycle.py`

## Description

- Created `src/vaultspec_a2a/desktop_tests/test_artifact_state_lifecycle.py` with five `@pytest.mark.service` tests and a module-scoped `installed_capsule` fixture.
- `test_migration_from_installed_capsule`: runs `desktop-migrate` CLI against a clean app home and reads the alembic version via SQLite to confirm head revision.
- `test_snapshot_rollback_via_installed_cli`: creates a snapshot group, mutates a SQLite marker, restores, and asserts the marker returns to the pre-mutation value.
- `test_consistency_restore_both_stores_together`: creates snapshot, mutates both primary and checkpoint databases, restores, verifies both are rolled back atomically.
- `test_tamper_detection_real_byte_flip`: reads the wheel RECORD sha256 for an installed `.py` file, flips one byte, recomputes the hash, and asserts it does not match; restores the original byte.
- `test_snapshot_inspect_verifies_integrity`: calls `desktop-snapshot-inspect` on a clean snapshot (expects 0 exit) and on a tampered `.snap` file (expects non-zero exit).

## Outcome

Service gate: **14 passed, 0 failed** — run 1: 115.75s, run 2: 115.54s (two consecutive runs, 2026-07-20). `ruff check` clean, `ty check` clean, baseline (32 non-service) passes.

Revision history:
- Round 1 fixes: snapshot tamper glob `*.snap` → `*.db`; `gateway_env()` uses `clean_env()`.
- Round 2 fix (flake): auth-plane probe timeouts raised to 30.0s across all three test files.

## Notes

Tamper detection uses the Python wheel RECORD file (sha256 digests for all installed files) as the integrity authority for the installed-wheel form; the transport capsule format's `verify_desktop_capsule.py` asset-digest check is proved separately in `test_capsule_verify.py`.  Snapshot captured-copy files follow the `{store.value}.db` naming convention from `snapshot.py`.
