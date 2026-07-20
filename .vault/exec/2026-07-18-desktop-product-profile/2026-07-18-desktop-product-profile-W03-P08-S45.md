---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S45'
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
     The S45 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Read owner-scoped credential files for operator calls without accepting secret command-line arguments and ## Scope

- `src/vaultspec_a2a/cli/main.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Read owner-scoped credential files for operator calls without accepting secret command-line arguments

## Scope

- `src/vaultspec_a2a/cli/main.py`

## Description

- Source operator authentication from the owner-scoped attach credential file
  under the armed desktop profile: the operator request path reads the same
  dashboard-created attach credential the gateway reads, restricted to loopback
  targets, before falling through to the resident discovery token.
- Audit the operator command surface: no option accepts a secret value; the only
  credential-shaped flag is a file-path reference, certified by walking the whole
  command tree.

## Outcome

- Modified: `src/vaultspec_a2a/cli/main.py`.
- Created: `src/vaultspec_a2a/cli/tests/test_operator_credentials.py`.
- Pre-existing vs added: the operator already reused a directly configured token
  and the loopback discovery token; this Step inserts the owner-scoped attach file
  as the armed-desktop source and adds the no-secret-argument audit. No secret CLI
  argument existed before or after.

## Notes

- Gates: ruff and ty clean; the operator-credential suite and the full CLI
  non-service suite (43 passed) pass.
