---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove desktop state remains app-home-seated across launch-directory changes and capsule relocation

## Scope

- `src/vaultspec_a2a/desktop_tests/test_profile_paths.py`

## Description

- Add a real-artifact certification gate that builds a real application home and a
  real capsule tree, then constructs the production settings through its
  environment seam.
- Prove armed mutable-state derivation (database, checkpoint, workspace, A2A home)
  is byte-identical under two different real working directories, and that the
  seated paths live under the application home, never the launch directory.
- Prove relocating the immutable capsule directory leaves the app-home-derived
  mutable-state layout unchanged while the capsule assets root tracks the move.
- Prove a launch-directory-relative application home is refused when arming, both
  at the profile authority and through settings construction.
- Prove unarmed construction keeps its pre-existing launch-relative database path,
  which tracks the working directory as before.

## Outcome

Desktop mutable state is certified to anchor to the explicit application home. The
armed database, checkpoint, workspace, and A2A-home paths are invariant across
real working-directory changes and across a real capsule relocation, and a
relative application home is refused fail-loud. Unarmed construction is unchanged:
its database path remains launch-relative, confirming the seating is strictly
profile-scoped. The gate uses no fake, mock, stub, patch, monkeypatch, skip, or
expected failure, and always restores the working directory.

## Notes

- Capsule realism: the profile validates the installed-runtime assets (the bundled
  Node executable and ACP adapter entry) the provider factory resolves, and those
  exact files are written on disk through the factory path authorities. A full
  base closure with real CPython, Node.js, and ACP archives requires network
  downloads and is certified by the target-capsule build and verifier gates
  (S13/S14); this gate certifies path seating, not artifact bytes.
- The settings database path resolves the database URL at property-access time, so
  the unarmed launch-relative paths are read inside each working directory before
  restoration; the armed paths are absolute and therefore working-directory
  independent.
