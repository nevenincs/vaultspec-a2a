---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:6f5d8d8f7f8747578c1f39cd79580e1cc8e5e811cfed66623b1a4c0fb02b74d8'
step_id: 'S13'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Verify the literal inventory with a Python sweep and classify every kept literal in the audit

## Scope

- `src/vaultspec_a2a`

## Description

- Re-run the Python regex inventory over `src/vaultspec_a2a` after the changes and classify every remaining literal.
- Append the port-policy-centralization finding with the full classification to the rolling audit.

## Outcome

Production: 0 runtime literals outside the canonical home (17 total occurrences remain: the home's own definitions plus docstring/help prose). Tests: no test binds a hardcoded port; kept literals are record/URL fixtures on isolated homes, render/parse assertions, band-relative scratch-band definitions, deliberate dead ports, and the conftest's non-routable OTLP sink.

## Notes

Ripgrep under-reports literals in this tree; the sweep used pathlib+re per the team-lead's verified methodology.
