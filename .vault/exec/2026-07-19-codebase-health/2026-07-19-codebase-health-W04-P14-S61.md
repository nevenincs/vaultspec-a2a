---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S61'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Remove the unowned acceptance_gate_reason export and its export-only tests

## Scope

- `src/vaultspec_a2a/providers/model_profiles.py, tests`

## Description

- Remove the accessor and its module export entry.
- Restate the assertion that used it against the constant production actually appends.

## Outcome

The accessor is gone. Its test survives, restated.

The step's premise needed correction. The test was not export-only: it asserts the gate reason appears in the computed ineligibility reasons, which is real behaviour. The accessor existed so that assertion would not hard-code the string. Removing both would have dropped the assertion; removing the accessor and hard-coding the literal would have created exactly the duplicated expectation the accessor was avoiding.

The test now imports the module constant that the production path appends, so the assertion still compares against one source of truth.

## Notes

The trade is that a test now reads a module-private name. That is preferable to a public function with no production caller, which advertises a supported contract this service does not have, and preferable to a copied literal that would silently pass if production changed its wording.
