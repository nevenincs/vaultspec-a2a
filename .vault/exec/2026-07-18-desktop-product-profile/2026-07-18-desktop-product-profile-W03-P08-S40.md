---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S40'
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
     The S40 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Require attach authentication on dashboard product APIs while leaving minimal liveness ungated and ## Scope

- `src/vaultspec_a2a/api/routes/__init__.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Require attach authentication on dashboard product APIs while leaving minimal liveness ungated

## Scope

- `src/vaultspec_a2a/api/routes/__init__.py`

## Description

- Apply the attach gate to every dashboard product router in the route
  registration helper, leaving the aggregate readiness probe ungated as the
  minimal-liveness surface.
- Certify over real HTTP that a product API rejects an unauthenticated caller
  and that the minimal top-level liveness probe answers without a credential.

## Outcome

- Modified: `src/vaultspec_a2a/api/routes/__init__.py`.
- Created: `src/vaultspec_a2a/api/tests/test_product_api_auth.py`.
- Pre-existing vs added: this follows the owner's precedent of gating the
  versioned edge with the same attach dependency; here it is extended to the
  product surface. Existing product-API tests run through the test-only bypass
  and are unaffected (full `api` suite green).

## Notes

- The minimal liveness surface is the top-level liveness probe, which stays
  ungated; the aggregate readiness probe requires live service state and its
  authenticated split is refined in a later readiness Step.
- Gates: ruff clean; the focused product-auth suite and the full
  `src/vaultspec_a2a/api` suite (308 passed) both pass.
