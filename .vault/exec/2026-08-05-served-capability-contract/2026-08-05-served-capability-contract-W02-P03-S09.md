---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:6b810476411b5a57dabfba155b932da62a73b47fb1941d6be381ecf8aba11a0e'
step_id: 'S09'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F3 IN FLIGHT with agent contract-audit - declare an HTTPBearer security scheme, apply it to the versioned and admin surfaces, drop the hand-rolled authorization parameter and declare 401 responses

## Scope

- `src/vaultspec_a2a/api/app.py`

## Description

- Declare the bearer scheme the contract always required, apply it to the
  versioned and administrative surfaces, drop the hand-rolled authorization
  parameter, and declare the refusal responses.

## Outcome

Closes in full. The scheme is declared and depended on from the authentication
path, sixteen gated operations carry a declared refusal response with none
missing, and the free-text authorization parameter was removed from every
versioned and administrative operation. The artifact regeneration command was
documented in the development guide.

VERIFIED WITH THE INSTRUMENT ITSELF PROVEN: the artifact test FAILED before
regeneration and PASSES after. That ordering does double duty - it confirms the
regeneration works, and it proves the guard genuinely detects change rather than
passing vacuously.

ONE VERIFICATION LIMIT, PRESERVED AS THE AUTHOR STATED IT: the 51-test
authentication suite is AFTER-ONLY. No baseline was captured before the change,
so it is an after-proof and NOT preservation evidence. Recorded because the
distinction is exactly the one this feature's audit insists on elsewhere, and
softening it here would be inconsistent.

## Notes

A REGRESSION WAS INTRODUCED AND CAUGHT BY RUNNING THE TESTS RATHER THAN
REASONING FROM SOURCE. Mounting the scheme at router level broke the worker
socket, because router-level dependencies also apply to socket routes while the
bearer resolver resolves only against a request. Four internal socket tests
failed; the fix attaches the dependency per route, with a comment recording why
it cannot move back.

The author's own counterfactual is the part worth keeping: it would otherwise
have shipped a broken worker connection behind a clean-looking contract change.
That is this feature's through-line reproducing during its own remediation, and
it is recorded as a finding in the audit for that reason.

A lint rule fired on the dependency default because the authentication module is
deliberately absent from the per-file ignore list. It was fixed by annotating
the parameter rather than by widening the ignore list - the narrower fix, and
the one that keeps the module's deliberate exclusion intact.

The carve-out this Step left - four internal routes still exposing a free-text
parameter - was closed later as its own credential plane, because folding them
under the gateway scheme would have misrepresented two different credentials as
one.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.
