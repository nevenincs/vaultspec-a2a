---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S77'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Build a deterministic real-process fixture that launches an authenticated gateway worker provider and real persistence stores

## Scope

- `src/vaultspec_a2a/acceptance`
- `tests/acceptance`

## Description

- Built the certification harness: the real migrate entrypoint seats the
  database, and a production gateway is spawned armed with the desktop profile
  so it owns and spawns its own worker, with readiness retry around the bind.

## Outcome

Closed. The harness boots the real stack rather than an approximation - the
12-15s setup times in every certification that uses it are real process starts,
not fixture overhead.

The provider backend is the deterministic tape-replay service, which is a real
HTTP service rather than a mock object, and the harness states plainly that a
live model provider is not required to certify a provider-INDEPENDENT gateway
contract. That distinction is what keeps the certifications meaningful without
making them depend on an external model.

## Notes

The suite landed under `src/vaultspec_a2a/acceptance` rather than the `tests/`
path the Step names, because the project's configured test paths would never
collect a tree outside them. The wheel build excludes the new package, so the
harness ships with neither the product nor the frozen binary.
