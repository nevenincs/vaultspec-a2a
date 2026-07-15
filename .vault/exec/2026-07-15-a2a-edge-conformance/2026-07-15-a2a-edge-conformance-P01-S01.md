---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S01'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

# Harden run-start: client-supplied stable run id or idempotency key with dispatch-exactly-once under retry, reject empty prompt, reject missing or unloadable preset (no silent draft on the v1 verb), require target feature for document-authoring presets, validate the token bundle covers the preset's required roles, and return initial semantic status plus eligibility

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/schemas/gateway.py`
- `src/vaultspec_a2a/control/thread_service.py`

## Description

- Added a pure run-start eligibility policy module holding the document-authoring
  predicate (research_adr topology), the required-role derivation (worker agent
  ids), and the eligibility evaluation, so the gateway route stays a thin HTTP
  translator and the policy is unit-testable against real team configs.
- Extended the run-start request schema: a mandatory non-empty preset
  (min_length), a non-empty-prompt field validator, an optional bounded target
  feature tag, and an optional client-supplied stable run id for idempotency.
- Extended the run-start response schema with an initial semantic status
  (starting) and an eligibility flag.
- Reworked the run-start endpoint: a client run id makes the verb
  dispatch-exactly-once (a retry with the same id returns the existing run
  without a second dispatch); the target feature is threaded onto the metadata so
  it reaches dispatch and the vault index.
- Loaded and validated the preset with the run's workspace context before
  dispatch, refusing a missing or unparseable preset with a 422 rather than
  creating the internal surface's non-running draft; the internal /api thread
  route keeps its draft behavior untouched.
- Refused document-authoring runs that lack a target feature or whose actor-token
  bundle does not cover every required role, with a safe reason that names the
  unmet precondition without echoing token values or prompt content.
- Added policy unit tests over the real bundled presets and a real token bundle,
  and live-socket endpoint tests for the refusal matrix (empty prompt, unknown
  preset, authoring preset without feature, incomplete token bundle) and the
  dispatch-exactly-once idempotent retry.

## Outcome

- The v1 run-start verb now refuses invalid requests before dispatch instead of
  silently drafting, honors client idempotency, and returns an initial semantic
  status plus eligibility, closing the run-start deltas from the dashboard
  handover.
- Scoped suites green: control (run_start_policy unit, 8) and api (gateway live
  refusal + idempotency, plus the full api and control suites, 255); `ruff
  check`, `ruff format`, and `ty check` clean on the changed modules.
- The internal thread-create draft path is preserved: its
  test_creates_thread_without_preset coverage still passes.

## Notes

- Token-bundle coverage is required only for document-authoring presets, which
  make authoring calls; non-authoring presets carry neither the feature nor the
  token requirement at this verb.
- The eligibility policy lives in a new control module rather than
  thread_service.py so the decision stays pure and I/O-free; the plan's
  thread_service.py scope was satisfied by the endpoint reshaping in the route
  and the metadata threading rather than a change to the service function body.
- The full semantic-phase projection is P02.S04; this Step emits only the initial
  "starting" status.
