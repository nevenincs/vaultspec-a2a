---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S34'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove two real desktop gateway processes cannot own or overwrite one app home

## Scope

- `src/vaultspec_a2a/desktop_tests/test_runtime_singleton.py`

## Description

- Add a real-process certification that spawns child interpreters running the
  production desktop ownership surface: acquire the runtime singleton over an
  explicit application home (as the serve path does before bind), then publish
  the versioned discovery record.
- Prove a second gateway against the same application home fails loud at
  acquisition (non-zero exit carrying the conflict classification) and never
  reaches discovery publication, so the first gateway's record is byte-for-byte
  intact after the failed contender.
- Prove that after the first gateway is really killed its runtime singleton
  reads STALE, and a same-owner restart reclaims the home through stale
  classification and republishes its own discovery record.
- Certify ownership through the published discovery and singleton records — the
  real gateway process identity — never the launch handle, since desktop-serve
  re-execs a fresh interpreter whose launcher pid differs from the gateway's.

## Outcome

Two real desktop gateways cannot own or overwrite one application home, and an
owner-matching restart after a real kill recovers cleanly. Gates: `ruff` clean;
`pytest src/vaultspec_a2a/desktop_tests/test_runtime_singleton.py -q` 2 passed.

## Notes

The certification drives the singleton-then-publish serve surface directly
rather than booting a full Uvicorn gateway, which would require a real capsule
and database; this is the "minimal real desktop-serve path against real app
homes" the Step contemplates and exercises the exact ordering the gateway uses.
Full attach authentication and the gateway's own publication of this record land
in `W03.P08`.
