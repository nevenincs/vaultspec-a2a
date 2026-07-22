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
