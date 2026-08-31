---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-24'
modified: '2026-08-02'
body_hash: 'sha256:1c53fc255774c20fe22b87a68dcad1f7f1441c1c5507537cd669a76988908be6'
step_id: 'S95'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove authenticated two-gateway one-worker pairing with real processes

## Scope

- `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`

## Description

- Decide and record the profile-split enforcement policy (armed = verdict
  authority; unarmed = legacy signal) in the codebase-health decision record.
- Wire the classifier and eviction authorization into every adoption seam of
  the worker manager; thread the spawner generation through.
- Prove the two-gateway one-worker topology with two complete armed gateways
  over separate migrated application homes sharing one worker port: gateway A
  spawns and owns its real worker (prepare 201); gateway B's demand is
  refused (503, not execution-ready).

## Outcome

Proven with real processes. B never adopts and never evicts: A's worker
still answers on the port after B's attempt, and B's log carries a
provenance-shaped refusal. The proof surfaced a second, earlier fail-closed
layer: A's worker rejects B's health probe outright (401) because the
worker-IPC credential is application-home-scoped, so a foreign gateway
cannot even read the pairing evidence - defence in depth ahead of the
classifier.

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
