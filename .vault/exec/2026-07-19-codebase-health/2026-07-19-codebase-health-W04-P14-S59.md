---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S59'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Remove the unowned AcpProtocolError export and its export-only tests

## Scope

- `src/vaultspec_a2a/providers/acp_exceptions.py, tests`

## Description

- Remove the exception, its module export entry, and its providers-facade
  re-export.
- Drop it from the parametrized subclass test, keeping the three live siblings.
- Restate the cross-catch test against a surviving pair rather than deleting it.

## Outcome

The exception is gone from the module, its exports, and the package facade, and the test
file no longer imports it.

The cross-catch test needed care rather than deletion. It proved that one sibling exception
is not caught by another, using the removed exception as its subject. That property is real
and still worth asserting, so the test was restated against two surviving siblings instead
of being removed with its subject. Deleting it would have silently dropped coverage of a
behaviour unrelated to the symbol being retired.

Gates: `ruff check src/` clean, `ty check src/` clean, three hundred forty passed across the
affected suites.

## Notes

The parametrized subclass test kept its remaining three cases and lost only the removed
entry, so the formatting-inheritance behaviour it covers is still exercised.
