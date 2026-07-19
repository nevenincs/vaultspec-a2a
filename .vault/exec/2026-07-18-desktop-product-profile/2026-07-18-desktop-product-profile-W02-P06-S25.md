---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S25'
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
     The S25 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Create temp-fsynced atomic snapshot descriptors and quiesced restore markers for every declared consistency-group store and ## Scope

- `src/vaultspec_a2a/desktop/snapshot.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Create temp-fsynced atomic snapshot descriptors and quiesced restore markers for every declared consistency-group store

## Scope

- `src/vaultspec_a2a/desktop/snapshot.py`

## Description

- Add `snapshot.py` as the single authority for capturing and restoring the
  desktop consistency group as one receipt-verifiable unit.
- Declare the group membership once in `consistency_group_members`: the primary
  Alembic-versioned database and the checkpoint database (LangGraph checkpointer
  plus state-driven-development state). Both are non-derivable, so both are
  mandatory members; the `StoreMember.derivable` flag exists so the manifest
  layer consumes one membership authority.
- Capture each store coherently through SQLite's online-backup API rather than a
  byte copy, so a WAL-resident committed frame is included and the source's
  committed content is never altered; the captured copy is checkpointed to a
  single sidecar-free file.
- Write each capture to a temp file, `fsync` it, and rename it into the group
  directory; commit the group by writing exactly one JSON descriptor
  (per-store source path, digest, size, SQLite schema cookie, and primary
  Alembic revision, plus group identity) through the same
  temp-`fsync`-atomic-rename discipline. Until the descriptor lands the snapshot
  is invisible to `inspect_snapshot` and `list_snapshots`.
- Restore under a quiesced-restore marker written before any store is touched
  and cleared only after every member is restored and flushed. A leftover marker
  is the durable signal of an interrupted restore; `restore_snapshot` refuses a
  fresh restore while one is pending and rolls forward deterministically with
  `resume=True` from the immutable captured copies.
- Refuse a live or locked store fail-closed on both capture and restore via a
  zero-timeout `BEGIN IMMEDIATE` probe; verify every restored store against its
  recorded digest so a restore that did not converge fails loud.
- Add real-store unit tests driving the production functions against real SQLite
  databases: capture and commit, WAL-resident coherence, source-content
  preservation, missing-member and live-store refusals, uncommitted-snapshot
  invisibility, tamper detection, together-restore, and interrupted-restore
  detection and roll-forward recovery.

## Outcome

`snapshot.py` delivers the temp-fsynced atomic snapshot descriptor and
quiesced-restore-marker primitive the external updater transaction consumes.
`ruff` and `ty` pass; the 14 real-store unit tests pass.

## Notes

- A small `_ensure_quiesced` SQLite lock probe is implemented locally rather than
  importing the private probe in the migration entrypoint, keeping the two
  desktop lifecycle modules independent; the shape mirrors the existing migration
  probe intentionally.
- Directory `fsync` is a no-op on Windows, where it is unsupported and atomic
  rename carries the durability; this matches the existing discovery/registry
  atomic-write convention.
- The captured group is later declared into the component manifest membership by
  the following Step; `StoreMember.derivable` is the seam for that.
