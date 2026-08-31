---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:ed372e1df10e0a0c95edbd33ac06468fdf0583d81ad94a1de818792a8a9933bc'
step_id: 'S17'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# Capture the value set each candidate vocabulary actually serves from live payloads and prove containment in its proposed enumeration, which gates every narrowing in this Wave

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Capture the value set each candidate vocabulary actually serves and prove
  containment before any narrowing.

## Outcome

Closes in full. Eleven vocabularies were captured from live payloads AND from a
code sweep of every write site - the second half matters, because a live capture
alone samples only what happened to be produced. Ten were proven and declared.

THREE WERE HONESTLY LEFT OPEN WITH REASONS, and that is the substance of this
Step rather than a shortfall. The provider identifier carries two concepts and
narrowing it would fault a deliberately-handled read path. The run degradation
reasons had a member added by a CONCURRENT WRITER mid-flight - narrowing an hour
earlier would have returned a server error on run-status the moment that writer
landed. The service degradation reasons are prose with an interpolated member,
so not a vocabulary at all.

Containment was proven by RE-VALIDATING ACTUAL PAYLOADS THROUGH THE NARROWED
MODELS - every one of the six real run payloads, the twenty-preset listing and
the service payload parsed - rather than by comparing value sets. A set
comparison would have missed shape errors that a parse catches.

VERIFICATION IS NEITHER PRESERVATION NOR A FIX, AND THE AUTHOR SOLVED THAT
PROPERLY. A new suite has no before-state, so passing proves nothing about
whether it discriminates. Three enumeration members were MUTATED and the suite
proven to fail across the capture check, the model-replay check and the producer
sweep, then reverted and re-verified. That is a vacuity proof, and it is the
correct answer to "how do I know a new test is not vacuous".

The 1031 and 414 passing tests are labelled by their author as "passes with the
change" - explicitly NOT a measured before-and-after.

## Notes

The concurrent-writer case is the strongest available evidence for the
subset-proof requirement in this feature's vocabulary decision. That clause was
written a day earlier on general reasoning, and it caught a real breaking change
in flight rather than a hypothetical one.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.
