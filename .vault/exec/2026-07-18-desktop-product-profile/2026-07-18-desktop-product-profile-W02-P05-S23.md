---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S23'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Expose the internal desktop migrate command while keeping lifecycle verbs off the public run-control API

## Scope

- `src/vaultspec_a2a/cli/main.py`

## Description

- Add an internal `desktop-migrate` command to the operator CLI that takes a
  required descriptor path, runs the staged-generation migration entrypoint in a
  fresh event loop, prints the bounded machine-readable result as sorted JSON to
  stdout, and exits zero only when the migration succeeds.
- Name the command flat (`desktop-migrate`), matching the existing
  `desktop-serve` convention, and keep it off the HTTP run-control router so the
  lifecycle verb stays CLI-only.

## Outcome

The dashboard external updater can drive the staged migration through one
internal CLI verb whose JSON result and exit code reflect the outcome. Proven by
real child-process CLI runs: a fresh store migrates and the command prints a
success result and exits zero; a mismatched descriptor prints a failed result
naming the descriptor stage and exits non-zero; a missing descriptor is a usage
error; and route-signature inspection proves no run-control HTTP route carries the
migration verb. New tests 4/4 green; `desktop-serve` and provision CLI suites
16/16; touched files pass ruff and ty.

## Notes

None.
