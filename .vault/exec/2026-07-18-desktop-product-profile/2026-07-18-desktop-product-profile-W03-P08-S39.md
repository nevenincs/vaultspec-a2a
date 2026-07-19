---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S39'
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
     The S39 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Require the attach credential on the versioned six-member whitelist (five run-control verbs plus bounded active-run discovery) without expanding it and ## Scope

- `src/vaultspec_a2a/api/routes/gateway.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Require the attach credential on the versioned six-member whitelist (five run-control verbs plus bounded active-run discovery) without expanding it

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Reconcile the versioned gateway router onto the unified `require_attach`
  import surface, dropping the direct `auth` import so the whitelist has one
  attach gate.
- Certify over real HTTP that every reviewed whitelist member (the five control
  verbs plus bounded active-run discovery) rejects an unauthenticated caller,
  that a correct attach bearer passes the gate, and that the versioned surface
  carries exactly the reviewed members with no expansion.

## Outcome

- Modified: `src/vaultspec_a2a/api/routes/gateway.py`.
- Created: `src/vaultspec_a2a/api/tests/test_v1_attach_whitelist.py`.
- Pre-existing vs added: the owner's landed auth already applied a router-level
  attach dependency to the whole `/v1` surface, so attach enforcement on the
  whitelist pre-existed; this Step only unifies the import surface and adds the
  no-expansion and enforcement certification. The credential the gate reads is
  the attach credential, which the armed desktop profile loads from the
  dashboard-created file.

## Notes

- Gates: ruff and ty clean; the full `src/vaultspec_a2a/api` suite passes
  (308 passed) including the new whitelist certification.
