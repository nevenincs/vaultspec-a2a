---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S17'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Derive database checkpoint log credential discovery receipt workspace temporary-home and snapshot paths only from the explicit desktop app home

## Scope

- `src/vaultspec_a2a/control/config.py`

## Description

- Add an optional `desktop_app_home` setting bound to the
  `VAULTSPEC_DESKTOP_APP_HOME` environment variable, documented as the explicit
  mutable-state root that arms the desktop profile.
- Add an after-model validator that, when armed, delegates path derivation to the
  desktop profile's single authority and seats the A2A home, workspace root,
  database URL, and checkpoint URL under the explicit application home.
- Import the derivation authority lazily and only on the armed branch, so unarmed
  Compose and development construction never pulls the desktop package and stays
  byte-for-byte unchanged.
- Cover the seam with real construction tests: armed derivation of every mutable
  path, database-path round-trip back to the app-home seat, fail-loud rejection
  of a relative application home, and unarmed invariance of the path fields.

## Outcome

The desktop profile is armed by a single explicit setting. While unarmed, the
configuration is unchanged, including its import surface: the desktop package is
imported only when an application home is present. When armed, the database,
checkpoint, workspace, and A2A-home paths derive solely from the explicit
application home through the desktop profile's derivation authority, so no mutable
path resolves relative to the launch directory. A relative application home is
rejected at construction with an actionable, absolute-path message. The existing
capsule-assets seam is left in place and coherent: the capsule root remains the
provider factory's asset authority, distinct from the mutable application home.

## Notes

- The derived sqlite URLs use the POSIX form of the absolute state paths so the
  same URL string parses correctly through the existing URL-splitting properties
  on every target platform.
- Arming currently seats the observable database, checkpoint, workspace, and
  A2A-home settings. The remaining explicit sub-paths (logs, credentials,
  discovery, receipts, temporary homes, snapshots) are already exposed by the
  desktop profile authority and are consumed by later phases; the A2A home
  reseats the runtime-state tree beneath the application home in the meantime.
