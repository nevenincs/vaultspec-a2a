---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S38'
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
     The S38 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Implement constant-time attach and lifecycle capability dependencies with redacted failures and ## Scope

- `src/vaultspec_a2a/api/dependencies.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Implement constant-time attach and lifecycle capability dependencies with redacted failures

## Scope

- `src/vaultspec_a2a/api/dependencies.py`

## Description

- Re-export the pre-existing attach-control gate through `api/dependencies.py`
  as `require_attach`, giving route modules one import surface for authentication
  without a second attach implementation.
- Add `require_lifecycle_capability`: a constant-time (`hmac.compare_digest`)
  dependency that requires the receipt-bound ownership capability header on top of
  attach, failing closed with a redacted 403 on mismatch and 503 when the runtime
  capability is unconfigured; honours the explicit test-only bypass.
- Certify both dependencies over real HTTP against a live app instance.

## Outcome

- Modified: `src/vaultspec_a2a/api/dependencies.py`.
- Created: `src/vaultspec_a2a/api/tests/test_lifecycle_capability_dependency.py`.
- Pre-existing vs added: attach authentication is the owner's landed
  constant-time bearer gate, reused verbatim; only the distinct lifecycle-capability
  gate and its header constant are added here.

## Notes

- The lifecycle capability travels in a distinct header from the attach bearer so
  the two planes never alias; loopback-only exposure keeps the raw value off any
  shared transport.
- Gates: ruff and ty clean; the six real-HTTP dependency cases pass.
