---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S29'
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
     The S29 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Prove interrupted snapshot or restore never exposes a partially committed group and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_snapshot_recovery.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove interrupted snapshot or restore never exposes a partially committed group

## Scope

- `src/vaultspec_a2a/desktop_tests/test_snapshot_recovery.py`

## Description

- Add a certification that an interrupted snapshot or restore never exposes a
  partially committed group, constructing on real files the exact intermediate
  on-disk states each defined stage boundary leaves, using the module's own
  descriptor and marker layout.
- Prove a capture interrupted after the captured stores are written but before the
  group descriptor commits is invisible: it is absent from the snapshot listing
  and fails inspection.
- Prove a restore interrupted after the quiesced marker is written but before the
  first store is restored is detected via the marker, refuses a fresh restore, and
  rolls forward on resume to return both stores to the captured content.
- Prove a restore interrupted between the two stores -- a genuine half-restored
  pair on disk (primary restored, checkpoint still mutated) -- is never reported
  healthy: the durable marker flags it and a fresh restore is refused, and resume
  converges the checkpoint too, clearing the marker.
- Prove a restore interrupted after the last store but before the marker clears is
  still detected and resumes idempotently to a consistent group.
- Prove an uninterrupted snapshot and restore leaves no pending marker and a
  digest-consistent authoritative group.

## Outcome

Interrupted snapshot and restore are certified never to expose a partially
committed or half-restored group: every stage-boundary crash state is detectable
and recovers to a consistent group. `ruff` and `ty` pass; all five certification
cases pass.

## Notes

- Recovery is roll-forward: because the committed snapshot is the immutable source
  of truth, resuming an interrupted restore re-restores every member idempotently
  and always converges to the captured content; there is no marker-clearing path
  that could leave a half pair looking healthy.
