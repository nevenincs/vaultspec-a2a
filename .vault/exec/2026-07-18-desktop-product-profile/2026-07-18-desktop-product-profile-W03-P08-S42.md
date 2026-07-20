---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S42'
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
     The S42 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Require both authenticated runtime control and receipt ownership for administrative shutdown and ## Scope

- `src/vaultspec_a2a/api/routes/admin.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Require both authenticated runtime control and receipt ownership for administrative shutdown

## Scope

- `src/vaultspec_a2a/api/routes/admin.py`

## Description

- Require both the attach credential and the receipt-bound lifecycle ownership
  capability on the administrative shutdown route, so a foreign attachment that
  can reach the product surface still cannot stop the gateway.
- Certify the two rejection paths over real HTTP: no attach is a 401, and a valid
  attach without (or with a wrong) lifecycle capability is a redacted 403.

## Outcome

- Modified: `src/vaultspec_a2a/api/routes/admin.py`.
- Created: `src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py`.
- Pre-existing vs added: attach on the admin router is inherited from the product
  gating; this Step adds the explicit receipt-ownership requirement and states
  both dependencies at the route for a security-critical endpoint.

## Notes

- The authorized 202 path terminates the process (it signals the running
  interpreter), so it is not exercised in-process; the two rejection paths fully
  prove the conjunction of attach and lifecycle capability.
- Gates: ruff and ty clean; the three real-HTTP rejection cases pass.
