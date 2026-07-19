---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S20'
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
     The S20 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Make ordinary desktop database checkpointer and SDD initialization validate compatibility without schema mutation and ## Scope

- `src/vaultspec_a2a/database/` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Make ordinary desktop database checkpointer and SDD initialization validate compatibility without schema mutation

## Scope

- `src/vaultspec_a2a/database/`

## Description

- Add a single arming predicate `desktop_profile_armed` to the settings object as
  the one authority every schema seam branches on.
- Add a new `compatibility` module owning read-only validation: the primary
  database must sit exactly at the packaged Alembic head, the checkpointer schema
  must be present, and the SDD state fields must already be backfilled; each check
  is a synchronous SQLite read offloaded to a worker thread, and every failure
  raises `SchemaCompatibilityError` naming the offending store and the
  staged-migration remedy.
- Add a read-only `count_pending_sdd_backfill` helper beside the existing backfill
  so coherence is measured without mutating rows.
- Gate the migration runner behind a new `apply_migrations` flag on `init_db`;
  armed boot skips it and instead validates compatibility.
- Suppress the checkpointer `setup()` call in the SQLite checkpointer opener when
  the profile is armed, and gate the SDD backfill call in the gateway lifespan on
  the same predicate.
- Re-export the new public API through the database package facade.

## Outcome

Ordinary armed desktop boot performs no Alembic upgrade, no checkpointer table
creation, and no SDD backfill; it validates the seated stores and fails loud with
an actionable remedy on an empty, stale, unrecognised, or incoherent store.
Unarmed Compose and development boot is byte-for-byte unchanged. Proven by real
SQLite stores: a pre-migrated store validates with before/after `sqlite_master`
schema-dump equality, and empty, behind-head, foreign-revision, missing-checkpoint,
and SDD-incoherent stores each raise. New tests 8/8 green; `database` suite 126/126;
touched files pass ruff and ty.

## Notes

Six failures in `desktop/tests/test_capsule_archives.py` and
`test_capsule_publication_races.py` are pre-existing concurrent-session drift (a
`NameError` in `_filesystem_authority.py`), unrelated to this Step and not touched
here. The known `desktop_tests/test_dependency_closure.py` lock drift stays
ignored per the baseline command.
