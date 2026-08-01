---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:6d473109faa5631817abd8a369b1f0d965085f5ef0026ec012d920c2b091f38c'
step_id: 'S171'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Certify authenticated status behavior through the supported public surface

## Scope

- `tests/acceptance/test_dashboard_contract.py`

## Description

- Certified that status returns a coherent snapshot for a real run and a real
  404 for an unrelated run id.

## Outcome

Closed. The certification discriminates on snapshot SHAPE, which is independent
of how a run eventually ends: the run id, the topology preset, and the per-role
identity all match what was launched, the status parses through the production
status enum rather than a copied literal, and the checkpoint cursor is a real
integer. A blanket 200, an empty body, or a snapshot for the wrong run cannot
satisfy it.

## Notes

The test name reads as an either/or, which is usually the shape of an assertion
that accepts whatever it is given. It is not one here - both branches are
asserted, the coherent snapshot for a real run AND the 404 for an absent one.
The name is worth tightening; the assertions are sound.
