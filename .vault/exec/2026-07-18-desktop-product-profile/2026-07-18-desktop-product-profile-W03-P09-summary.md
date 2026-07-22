---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` `W03.P09` summary

Phase P09 delivered the single desktop readiness model: liveness, gateway
readiness, worker state, provider eligibility, and run admission are separate
bounded facts served from one authority, and every unauthenticated surface on
the armed gateway discloses nothing beyond a minimal alive signal. All five
Steps (S47 through S51) are closed; independent review passed with no open
findings after the phase's sixth commit closed the last ungated aggregate
surface. With P07, P08, and P09 complete, Wave W03 — runtime identity and
authenticated readiness — is done.

- Modified: `src/vaultspec_a2a/api/schemas/gateway.py`,
  `src/vaultspec_a2a/control/health.py`, `src/vaultspec_a2a/api/app.py`,
  `src/vaultspec_a2a/api/routes/gateway.py`,
  `src/vaultspec_a2a/api/routes/health.py`
- Created: `src/vaultspec_a2a/desktop_tests/test_readiness_model.py`

## Description

S47 defined five bounded enumerated facts with a minimal liveness response
and a desktop readiness projection nested on the service-state schema. S48
implemented the single readiness authority: a valid desktop database with a
cold, startable worker reports gateway-ready without claiming execution
readiness, worker absence before demand is informational, and provider
eligibility resolves through the no-instantiation classification seam. S49
split the armed gateway's health endpoint — unauthenticated callers receive
only the minimal alive signal, while attach-authenticated callers receive
process and product identity plus the separated state ladder — behind a
constant-time gate at parity with the credential phase. S50 served the same
projection through service state with no duplicated computation. S51
certifies the model against a real armed child gateway over real HTTP,
byte-asserting the complete minimal body on both ungated surfaces and the
cold-to-execution ladder on both authenticated surfaces. The phase's final
commit extended the minimization to the aggregate health route — the last
unauthenticated surface that still disclosed worker and backend state under
the armed profile — closing the deferred credential-phase finding, while
Compose and development consumers keep the full aggregate body their
healthchecks rely on.

## Tests

The api suite (321 passed), control suite, and the real-gateway readiness
and credential-boundary certifications are green from the committed tree,
with the reviewer independently walking every armed route and confirming no
remaining unauthenticated disclosure; no fakes, mocks, stubs, patches,
monkeypatches, or expected failures, and the single platform skip is owned
by its open follow-up row. Baseline failures at review time were attributed
to a concurrent session's untracked work outside this phase.
