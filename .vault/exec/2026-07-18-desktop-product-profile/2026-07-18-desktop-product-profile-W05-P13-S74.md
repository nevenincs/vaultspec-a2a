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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S74 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Prove migration rollback consistency restore tamper detection and immutable-file verification from real capsule state and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_artifact_state_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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

REVISION REQUIRED. Code reviewer ran the service suite; tests failed as part of the 4-failed run. `ruff check` and `ty check` are clean; baseline passes.

Failures diagnosed:
1. `test_snapshot_inspect_verifies_integrity`: snapshot captured-copy files are named `{store}.db` (not `*.snap`); the tamper glob produced an empty list so the fail-closed half never executed.
2. `gateway_env()` used `dict(os.environ)` instead of `clean_env()`.

## Notes

Step unchecked and revision in progress. The snapshot filename convention is `{store.value}.db` per `SnapshotGroupSpecification.snapshot_filename`.
