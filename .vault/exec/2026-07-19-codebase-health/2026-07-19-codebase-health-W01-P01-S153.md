---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-24'
modified: '2026-08-02'
body_hash: 'sha256:30d6189f1e0402646154ab2208763f5ca214dc88040382157b68d47b822c85b4'
step_id: 'S153'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove plain worker health never authorizes adoption with real processes

## Scope

- `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`

## Description

- Boot a real armed gateway over a migrated application home with its
  private worker port held by a genuine stranger process serving plain
  ``/health`` 200 with no pairing evidence.
- Drive an authenticated prepare and observe the admission surface.

## Outcome

Proven: prepare refuses 503 (not execution-ready); the squatter process
survives untouched (no eviction) and its request log shows only health
probes (no adoption, no dispatch); the gateway log carries the loud
provenance refusal. Under the retired lenient policy this squatter would
have been adopted.

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
