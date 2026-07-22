---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S51'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove unauthenticated HTTP liveness exposes only the minimal alive or not-alive signal and authenticated readiness responses carry process and product identity plus cold-to-execution state

## Scope

- `src/vaultspec_a2a/desktop_tests/test_readiness_model.py`

## Description

- Certify the readiness model end to end against a real armed gateway over real
  loopback HTTP. Seed the dashboard-created attach and ownership credential files,
  seat a valid database through the real migration entrypoint in a separate
  process, then boot the production gateway armed over that app home with the
  worker held cold.
- Assert the unauthenticated liveness body byte-for-byte as the minimal alive
  signal and confirm no process, product, or state token leaks across the
  unauthenticated boundary.
- Assert the readiness facts are reachable only with the attach credential, that
  the authenticated projection carries process and product identity, and that a
  cold, startable worker reads as gateway-ready with run admission deferred - the
  cold rung of the cold-to-execution ladder - on both the authenticated liveness
  surface and the service-state verb, with a consistent process identity across
  both.

## Outcome

`ruff` and `ty` pass on the test. The certification passes: 1 passed. It drives
real subprocesses and real HTTP with no mock, monkeypatch, stub, skip, or expected
failure. The desktop baseline passes with the new test included: 338 passed, 1
skipped. The api suite (321 passed) and control suite (97 passed) remain green from
the preceding Steps and are unaffected by this test-only addition.

## Notes

Follow-up closing a review finding: the certification now byte-asserts the
minimal liveness body on every ungated surface - both the top-level probe and the
aggregate probe - so a regression that re-adds a disclosed field cannot pass a
substring-only scan. No incidents. The gateway process identity is asserted
present and consistent
across both authenticated surfaces rather than equal to the spawn handle: a Windows
virtual environment interpreter is a launcher stub whose real child process carries
a different identifier, so binding the assertion to the launcher handle would be
false. The one baseline skip is a POSIX-only credential permission case owned by a
separate Step, not introduced here. All five readiness facts are served from the
single authority; this Step adds only the certifying test.
