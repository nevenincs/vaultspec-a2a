---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S70'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove attach-control-authenticated terminal callback retry rejects worker IPC and unrelated credentials while status reconciliation revokes exactly one run-scoped lease without raw tokens

## Scope

- `src/vaultspec_a2a/desktop_tests/test_terminal_settlement.py`

## Description

- Add a real test-hosted dashboard settlement receiver - a threaded HTTP server in
  the test process modelling the dashboard endpoint - that authenticates callbacks
  with the attach-control credential, transiently rejects the first authenticated
  attempt to force a retry, and revokes the named lease on acceptance.
- Prove, against a real armed gateway that runs a mock run to a durable terminal
  state, that the emitted settlement authenticates with the attach-control
  credential and never the worker interprocess-communication secret (read from the
  gateway's own credential directory for the negative comparison).
- Prove the callback body carries only the run and its non-secret lease identity
  plus the terminal status, and that the run's actor token never appears in any
  attempt.
- Prove delivery is retried (at least two attempts observed) and the run's lease is
  revoked exactly once.
- Prove the settlement plane rejects a real minted worker interprocess-communication
  secret and an unrelated credential with 401 and accepts only the attach-control
  credential, confirming the two credential planes are distinct files and secrets.

## Outcome

Two real-behavior tests pass (2 passed in ~20s): the armed-gateway terminal
settlement proof and the credential-plane rejection proof. The settlement callback
is observed authenticating with attach-control, never worker IPC; its body carries
only non-secret identities with no actor token; delivery retries a transient
rejection and the lease is revoked exactly once. Lint, format, and type checks
pass. This Step adds only tests, so the api, control, and worker suites are
unchanged from the prior Step and the new tests join the desktop baseline.

## Notes

The receiver's ``log_message`` override matches the standard-library signature
exactly (parameter name ``format``) to satisfy the type checker's override
compatibility rule, following the established pattern in the existing worker and
authoring HTTP-server test doubles. The worker interprocess-communication secret
used in the rejection proof is minted through production code, guaranteeing it is a
genuine, distinct credential value rather than a fabricated string.
