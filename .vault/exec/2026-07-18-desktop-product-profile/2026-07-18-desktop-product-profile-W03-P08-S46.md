---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S46'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove attach-control worker IPC and lifecycle credentials are non-interchangeable rejected outside their planes and absent from discovery logs and responses

## Scope

- `src/vaultspec_a2a/desktop_tests/test_credential_boundaries.py`

## Description

- Certify the three credential planes against a real armed gateway: a child
  interpreter boots the production application armed with the desktop profile
  (loading the dashboard-created attach and ownership credentials and minting the
  worker interprocess secret), publishes the versioned discovery record, and
  serves the real authentication stack over a real loopback socket.
- Prove over real HTTP that the attach, worker interprocess, and ownership
  credentials are non-interchangeable and rejected outside their planes; that no
  secret appears in the discovery record, the process logs, or any response body
  (byte-scan); that unauthenticated liveness discloses nothing; and that the
  listener is loopback-only.
- Fix a critical circular-import defect the certification exposed: with the
  desktop profile armed through the environment, the settings profile validator
  transitively imported the component-manifest and lifecycle stacks while
  `control.config` was still constructing, so the armed gateway could not boot at
  all. Make the desktop package facade resolve its contract and manifest exports
  lazily, and compute the discovery-record filename in the profile from a leaf
  constant instead of importing the lifecycle stack.

## Outcome

- Created: `src/vaultspec_a2a/desktop_tests/test_credential_boundaries.py`.
- Fixed: `src/vaultspec_a2a/desktop/__init__.py` (lazy facade),
  `src/vaultspec_a2a/desktop/profile.py` (leaf discovery-filename constant).
- Guard test added: `src/vaultspec_a2a/desktop_tests/test_profile_paths.py`
  (the profile discovery path stays in sync with the discovery authority).

## Notes

- The circular-import defect predates this phase (introduced with the armed
  settings seating); no prior test booted the gateway with the profile armed
  through the environment, so it went uncaught. The armed real-process boot in
  this certification is what surfaced it.
- Real-process evidence only: no mock, monkeypatch, stub, skip, or expected
  failure; the child is torn down in a `finally`.
- Gates: ruff and ty clean on the changed sources; the certification passes and
  the desktop suite (221 passed, 1 POSIX-only skip) is green excluding the
  separately-owned in-flight capsule/artifacts WIP
  (`test_artifacts.py`/`test_capsule_*`/`test_unpublished_generation.py` fail
  collection on an undefined `_MAX_PACKAGE_COUNT`, an open capsule row owned by
  another session, not touched here).
