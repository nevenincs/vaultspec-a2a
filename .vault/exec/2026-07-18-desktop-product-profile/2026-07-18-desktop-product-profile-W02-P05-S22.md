---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S22'
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
     The S22 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Implement the staged-generation Alembic SDD-backfill and checkpoint migration entrypoint with bounded machine-readable results and ## Scope

- `src/vaultspec_a2a/desktop/migration.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement the staged-generation Alembic SDD-backfill and checkpoint migration entrypoint with bounded machine-readable results

## Scope

- `src/vaultspec_a2a/desktop/migration.py`

## Description

- Add a new `migration` module with the staged-generation entrypoint that takes a
  descriptor path, loads and validates the one-time transaction, and on success
  marks it durably consumed.
- Refuse any live or locked target: probe both the primary and checkpoint stores
  with a zero busy-timeout immediate transaction before mutating either, raising a
  typed store-locked error rather than blocking.
- Run the three mutations desktop boot refuses, in order and against the
  descriptor's own stores only: the Alembic upgrade to the packaged head, the
  checkpointer schema setup with WAL, and the SDD backfill.
- Return a strict, JSON-serialisable result model with per-store outcomes,
  from/to revisions, backfilled row count, duration, and, on failure, the bounded
  failing stage plus the exception class name only, so no free-form internals or
  store contents leak. No network access occurs.

## Outcome

The dashboard external updater now has one dedicated, transactional migration
entrypoint that ordinary boot never touches. Proven against real SQLite stores: a
fresh application home migrates the primary database to head, initialises the
checkpointer, backfills SDD, and durably consumes the transaction; replaying a
consumed descriptor is refused at the descriptor stage; a store held under a real
write lock is refused at the lock stage and left unconsumed; and a descriptor with
a wrong migration range is refused up front. New tests 4/4 green; touched files
pass ruff and ty.

## Notes

None.
