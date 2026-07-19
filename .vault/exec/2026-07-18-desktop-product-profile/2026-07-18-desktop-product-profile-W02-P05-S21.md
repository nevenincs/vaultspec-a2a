---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S21'
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
     The S21 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Validate the updater one-time descriptor owned state roots and compatible schema range before lifecycle mutation and ## Scope

- `src/vaultspec_a2a/desktop/transaction.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Validate the updater one-time descriptor owned state roots and compatible schema range before lifecycle mutation

## Scope

- `src/vaultspec_a2a/desktop/transaction.py`

## Description

- Add a new `transaction` module defining the typed one-time migration
  descriptor: a strict, extra-forbidding model carrying the descriptor version,
  a single-use transaction id, the explicit application home and its database and
  checkpoint paths, the staged generation identity (manifest digest plus
  component version), the claimed Alembic migration range, and a timezone-aware
  expiry instant.
- Add a fail-closed loader that reads the descriptor owner-restricted (regular
  file, size-bounded, refusing group- or world-writable modes on POSIX), parses
  and schema-validates it, proves the declared state roots equal the desktop
  profile's own derivation from the application home, proves the claimed migration
  range equals the packaged Alembic base and head, rejects expired descriptors,
  and rejects a descriptor whose durable single-use marker already exists.
- Store the single-use marker under the application home's receipts directory
  keyed by transaction id, and add an atomic consume writer that fails closed on a
  concurrent second claim.
- Expose the packaged migration range as a public helper so callers derive base
  and head from the graph rather than hardcoding them.

## Outcome

The external updater's migration authorisation is now a typed, validated,
single-use artifact. Proven by real on-disk descriptor files: a well-formed
current descriptor validates and yields its derived state and marker paths, and
relative application home, database/checkpoint root mismatch, incompatible
migration range, expiry, malformed JSON, non-regular file, and already-consumed
descriptors each raise a typed error. Consume-then-reload and double-consume both
fail closed. New tests 10/10 green; touched files pass ruff and ty.

## Notes

Windows access-control-list enforcement of descriptor ownership is deferred to the
credential-boundary work; this module enforces regular-file and POSIX
group/world-writable restrictions, and the non-regular-file rejection is proven
cross-platform.
