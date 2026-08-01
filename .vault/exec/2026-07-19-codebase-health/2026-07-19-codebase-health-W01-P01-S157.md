---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:f3361bd629001c92a993401efb79c1de6d931e1a04b2bf6fcfd3dd3c597f2929'
step_id: 'S157'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove Compose provenance mismatch fails closed without eviction with real processes

## Scope

- `src/vaultspec_a2a/service_tests/test_compose_profile_regression.py`

## Description

- Drove a real Compose-band provenance mismatch against the same pairing
  classifier.
- Asserted the spawn refuses loudly and that no eviction is attempted against an
  occupant this gateway cannot prove it owns.

## Outcome

Closed. Failing closed is only half the property; the other half is that a
foreign or unidentified occupant is left alone. It may be serving someone
else's runs, and silence about ownership is not evidence of it.

## Notes

Commit `56cc6d96`, carrying a `Refs:` trailer. Same evidence basis as `S156` -
verified from the landed test rather than from an agent's report.
