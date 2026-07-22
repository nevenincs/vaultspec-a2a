---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S63'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Define prepare and commit variants bounded required-role output reservation identity lease identity and terminal settlement under run-start

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Add a `RunStage` enumeration (`start`, `prepare`, `commit`) to the versioned
  gateway wire models so the split desktop admission protocol rides the single
  existing run-start verb; `start` is the default so every pre-existing caller
  keeps its one-shot contract unchanged.
- Extend the run-start request with a `stage` selector and an optional
  reservation identity, and replace the message field-validator with a
  stage-aware model-validator: `start` and `commit` still refuse an empty prompt,
  `prepare` refuses any actor tokens or reservation id, and `commit` requires the
  reservation it binds.
- Add bounded `ReservationId` and `LeaseId` path-safe identity aliases: the
  server-minted reservation handle and the non-secret, run-scoped lease handle
  the dashboard revokes at settlement. Neither is ever a bearer.
- Add the prepare-stage response carrying the reservation identity, the bounded
  validated required-role set the later commit must cover, the hard expiry, and
  the three readiness facts explaining a deferred or blocked admission.
- Add the commit-stage response carrying the created run and its non-secret lease
  identity, and the terminal-settlement callback body carrying only the run and
  lease identities plus the terminal status - never a token or the worker
  interprocess-communication secret.

## Outcome

The gateway schema surface now expresses the two-stage prepare/commit admission
protocol and the authenticated terminal-settlement callback without growing the
verb set. A focused round-trip probe confirmed back-compatible direct start,
empty-message refusal on start and commit, token and reservation refusal on
prepare, and the reservation requirement on commit. Lint, format, and type checks
pass on the file, and the full `api`, `control`, and `worker` suites remain green
(517 passed, 8 deselected), proving no existing run-start caller regressed.

## Notes

No durable behavior changed in this Step; it defines the contract the reservation
broker, route wiring, settlement emitter, and their proofs consume in the
following Steps. The message field relaxed from mandatory to stage-conditional,
so the non-empty guarantee now lives in the model-validator rather than the field
constraint.
