---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-24'
modified: '2026-08-02'
body_hash: 'sha256:144d1c77f88a5c9265303c877884b3b84dac4263cb4512008368f5d5a8723994'
step_id: 'S154'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove blank worker pairing never authorizes adoption with real processes

## Scope

- `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`

## Description

- Boot a real armed gateway with the worker port held by a stranger
  process reporting explicitly blank ``paired_gateway_lifetime`` and
  ``worker_generation``.
- Drive an authenticated prepare and observe the admission surface.

## Outcome

Proven: blank evidence classifies UNIDENTIFIED and the prepare refuses
503; the squatter survives with only health probes in its log; the refusal
is loud in the gateway log. Silence is no longer read as ownership.

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
