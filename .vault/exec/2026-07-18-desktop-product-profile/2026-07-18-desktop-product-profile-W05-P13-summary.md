---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` `W05.P13` summary

Phase P13's local certification legs (S72 through S75) are closed: a
real-process installed-capsule harness plus fourteen service-marked gates
proving offline install, relocation, cold readiness, lazy worker, provider
execution through the supported workspace-preset seam, state lifecycle with
tamper detection, and ownership boundaries. The five per-target capsule
closure rows (S76 through S80) remain open: they execute on hosted runners
and await the repository owner publishing the workflow. Review initially
FAILED the phase — the gates had never run green — and passed only after a
full revision and a reproducibility fix, independently re-run green three
times.

- Created: `src/vaultspec_a2a/desktop_tests/harness.py`,
  `src/vaultspec_a2a/desktop_tests/test_artifact_install.py`,
  `src/vaultspec_a2a/desktop_tests/test_artifact_state_lifecycle.py`,
  `src/vaultspec_a2a/desktop_tests/test_artifact_ownership_lifecycle.py`

## Description

The harness builds the real wheel with its locked base closure, installs it
into clean environments, seeds credentials and certification presets, and
relocates and inspects installed capsules as real child processes. The
install gate proves offline installation, relocation with state
independence, the cold readiness model, single-flight lazy worker startup,
and provider execution — with the certification preset supplied through the
real workspace-preset override mechanism because the product wheel
deliberately excludes mock presets, and real external-CLI execution honestly
reported as gated. The state gate drives the real migration and snapshot
commands to prove migration to head, rollback, atomic consistency restore,
real byte-flip tamper detection against the wheel record, and
snapshot-inspect integrity gating. The ownership gate proves unauthenticated
and wrong-capability rejection, owner-only shutdown, drain with worker
reaping, and data-preserving removal that keeps databases, credential files,
and the discovery record intact.

Review history is part of this phase's record: the first submission checked
rows on gates that had never executed (four failed on first real run — a
structural wheel-versus-preset contradiction, a wrong snapshot-file glob, a
greenwashed removal proof, and unwired isolation helpers); the revision
resolved all five findings and a second review run exposed a load-induced
timeout flake, fixed by raising auth-probe timeouts to the established
class. The final trio is reproducibly green across two executor runs and an
independent lead run.

## Tests

Fourteen service-marked certification tests pass reproducibly (three
consecutive full-trio runs: 14 passed each, roughly 110 to 116 seconds), and
the thirty-two non-service desktop gates stay green with no regression. No
fakes, mocks, stubs, patches, monkeypatches, skips, or expected failures
beyond the disclosed in-process mock provider at the uninstalled-CLI seam;
the certification preset rides the real workspace-override load path the
production gateway serves.
