---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S36'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Validate dashboard-created attach and ownership files and create a distinct gateway-owned worker IPC credential with platform ACL checks

## Scope

- `src/vaultspec_a2a/desktop/credentials.py`

## Description

- Add `src/vaultspec_a2a/desktop/_platform_acl.py` as the single cross-platform
  owner-restriction authority: POSIX mode-bit and Windows discretionary
  access-control-list restrict, verify, harden, and is-owner-restricted helpers.
- Add `src/vaultspec_a2a/desktop/credentials.py` modelling the three disjoint
  credential planes: validate the dashboard-created attach and ownership files
  fail-closed (regular non-link file, owner-restriction, bounded size, token
  format) and mint the gateway-owned worker interprocess-communication secret
  per boot under the same owner-restriction guarantee.
- Rewire `src/vaultspec_a2a/lifecycle/discovery.py` to consume the shared ACL
  authority, deleting its private native Windows ACL copies so both the
  discovery credential and the split desktop credentials share one authority.
- Certify the authority with real files in
  `src/vaultspec_a2a/desktop/tests/test_credentials.py`.

## Outcome

- Modified: `src/vaultspec_a2a/lifecycle/discovery.py`.
- Created: `src/vaultspec_a2a/desktop/_platform_acl.py`,
  `src/vaultspec_a2a/desktop/credentials.py`,
  `src/vaultspec_a2a/desktop/tests/test_credentials.py`.
- Typed fail-closed errors (`CredentialError`); no credential value reaches a
  message, log, or exception argument.
- The Windows access-control-list check closes the prior Windows descriptor
  enforcement gap: the strongest real check available stdlib-only is the
  private-DACL predicate (current user, SYSTEM, administrators; no inherited
  entries), the same guarantee the discovery credential already enforces.

## Notes

- Pre-existing vs added: the native Windows ACL machinery pre-existed inside
  the runtime discovery module; this Step promotes it to a shared authority and
  adds the credential plane split on top. No parallel ACL implementation now
  exists.
- Gates: ruff and ty clean on all touched files; the new credential suite and
  the discovery suite both pass. The POSIX permission-bit rejection case is the
  only skip on Windows, as it asserts a POSIX-only mode.
