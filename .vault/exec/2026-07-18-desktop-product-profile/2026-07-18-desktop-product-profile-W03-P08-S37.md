---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S37'
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
     The S37 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Model distinct attach credential worker IPC credential and receipt-bound lifecycle capability references and ## Scope

- `src/vaultspec_a2a/control/config.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Model distinct attach credential worker IPC credential and receipt-bound lifecycle capability references

## Scope

- `src/vaultspec_a2a/control/config.py`

## Description

- Add a `desktop_credential_paths` property to the composed settings that, when
  the desktop profile is armed, derives the three credential file references
  (attach control, receipt-bound ownership capability, worker interprocess
  communication) through the desktop path and credential authorities.
- Return `None` while unarmed and import the desktop credential package lazily so
  the Compose and development import surface and behaviour are byte-for-byte
  unchanged.
- Certify the arming, path derivation, distinctness, app-home seating, and unarmed
  no-import invariant with real settings construction.

## Outcome

- Modified: `src/vaultspec_a2a/control/config.py`.
- Created: `src/vaultspec_a2a/control/tests/test_desktop_credential_references.py`.
- Pre-existing vs added: the owner's landed auth already models the env-configured
  `gateway_service_token` and `internal_token` for the Compose profile; this Step
  adds only the armed-desktop file-reference derivation beside them without altering
  the unarmed path.

## Notes

- Gates: ruff and ty clean; the new reference suite and the full
  `src/vaultspec_a2a/api` suite pass (294 passed).
