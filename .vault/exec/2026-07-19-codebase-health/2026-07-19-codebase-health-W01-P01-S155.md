---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-24'
modified: '2026-08-02'
body_hash: 'sha256:004c57b16eb7b98cbc0c42ed83767233cef4603ca89a024da32c7f120b19702c'
step_id: 'S155'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove unauthenticated legacy readiness never authorizes adoption with real processes

## Scope

- `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`

## Description

- Boot a real armed gateway with the worker port held by a stranger
  process echoing this gateway's ``gateway_url`` - the exact legacy readiness
  signal the retired policy adopted on - while carrying no pairing evidence.
- Drive an authenticated prepare and observe the admission surface.

## Outcome

Proven: the echoed URL no longer authorizes adoption - the verdict is
UNIDENTIFIED, the prepare refuses 503, the squatter survives with only
health probes logged. This is the direct proof that the weaker signal was
demoted from authority to irrelevance under the armed profile.

## Notes

The enforcement this proof required did not exist when the Step was
authored: the audit's authenticated-pairing-verdict-not-enforced finding
established the classifier was dead code. The 2026-07-24 codebase-health
decision record made the profile-split policy call, and the enforcement
landed with these proofs in one commit - the verdict now governs the
readiness/adoption gate, the armed pre-spawn occupancy gate, the
non-auto-spawn attach, the post-spawn fallback, and the watchdog's
external-worker fallback, with the spawner's generation threaded into every
call.
