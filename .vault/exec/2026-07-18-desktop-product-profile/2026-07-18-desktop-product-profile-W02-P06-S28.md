---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S28'
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
     The S28 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Prove primary and checkpoint databases restore together from a real consistency group and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_snapshot_group.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove primary and checkpoint databases restore together from a real consistency group

## Scope

- `src/vaultspec_a2a/desktop_tests/test_snapshot_group.py`

## Description

- Add a certification that the primary and checkpoint databases restore together
  from a real consistency group, driving production code end to end with no test
  doubles.
- Build the group for real: migrate a fresh application home through the
  production staged-generation migration entrypoint, producing a real
  Alembic-headed primary database and a real WAL-mode LangGraph checkpoint
  database with the state-driven-development state backfilled.
- Write distinguishable marker content into both real stores, capture the group,
  and assert the committed descriptor is authoritative over both members (both
  present, primary's recorded Alembic revision equals the packaged head, non-zero
  sizes).
- Mutate both stores away from the captured content, restore the group, and prove
  by querying the real SQLite files that both members return to the captured
  content together; assert the real migrated schema (primary Alembic head,
  checkpoint `checkpoints` table) survived the round trip, and re-inspect to
  confirm the captured copies still verify by digest under the authoritative
  descriptor.
- Add a second case mutating only one member and proving the group restore is
  all-or-nothing: both members return to the captured content, never a mixed
  pair.

## Outcome

The primary and checkpoint databases are certified to snapshot and restore as one
receipt-verifiable consistency group against real migrated SQLite stores. `ruff`
and `ty` pass; both certification cases pass.

## Notes

- The group is built in-process through the production migration entrypoint rather
  than a full wheel install, so the certification runs in the ordinary desktop
  baseline (it is not `service`-marked) while still exercising the real Alembic
  upgrade, real checkpointer setup, and real SDD backfill.
