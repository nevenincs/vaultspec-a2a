---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e65a9354d7e13942a244ab79a2583b383b85ef69cc3cee675f0c195d233f1295'
step_id: 'S16'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Prove cross-run exclusion for undeclared tests and degraded admission of a concurrent session

## Scope

- `src/vaultspec_a2a/testing/tests/`

## Description

- Land the live proofs: two real interpreters allocating simultaneously
from one registry home, holds barrier-overlapped, get fully disjoint port
sets with zero declarations; a parked real pytest session causes a second
distributed run under a pinned four-core budget to admit itself at two
workers instead of four, read from its own report header.

## Outcome

Committed as 6bfb2a2c. Framework suite 47/47 green on a loaded box; the scheduling evidence run pins the admission budget through the sanctioned operator knob so the proof keeps its two workers under load.

## Notes

The first version of the concurrency proof lacked the barrier and reported legitimate port reuse as collision; the barrier is documented in-test because the distinction is what makes the claim meaningful.
