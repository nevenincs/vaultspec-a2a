---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:8cb4fe06990a57906faaa11d8f4b078504f07d5cb6bb73bf76e26a04dc20f4d6'
step_id: 'S02'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Certify the landed desktop singleton credential and owned-process prerequisites without treating them as proof of worker pairing identity

## Scope

- `.vault/exec`
- `.vault/audit`
- `src/vaultspec_a2a/desktop_tests`

## Description

- Certified that the armed desktop profile's prerequisites hold against a real
  serve: the runtime singleton is held, and every credential plane is
  owner-restricted.
- Certified the limit the Step's wording insists on, by starting a REAL second
  production worker outside any gateway spawn holding the same gateway-minted
  IPC credential over the same application home.
- Verified the certification discriminates, by mutating the worker's pairing
  defaults to a non-blank value and confirming it fails.

## Outcome

Closed. The prerequisites hold, and - the part that matters - holding them is
shown NOT to establish pairing identity. Three things that are easy to conflate
are separated with evidence:

The credential does not identify: the stranger answers the authenticated probe
200 and refuses the unauthenticated one 401, exactly as the gateway's own worker
does, so possession of the prerequisite secret is satisfied by a worker this
gateway never started. The addressing does not identify: both workers report a
byte-identical declared target, so the legacy comparison cannot separate them at
all. Only reported pairing evidence identifies.

The stranger is a genuine production worker rather than an adversary stand-in,
which is what makes the negative result meaningful - it is not that a fake fails
to convince, but that a real one cannot.

## Notes

Commit `35cfe5a6`. Executed by a dispatched agent; closure rests on the
orchestrator's own reading and an independent mutation run, because the agent
delivered no report.

One inaccuracy recorded rather than corrected in place: the test's docstring
says the mutation makes the verdict "flip to an adoptable verdict". It does not.
Blank evidence is UNIDENTIFIED and any non-matching value is FOREIGN, and the
spawn path refuses both identically, so the mutation degrades evidence quality
rather than the security outcome. The test is correct and asserts the right
thing; only its stated rationale overreaches, and a reader trusting that
sentence would wrongly conclude the mutation is exploitable.
