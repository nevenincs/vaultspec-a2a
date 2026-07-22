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
