---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:6eaf28e2b33c6686a387fe70695076ea78dc056e06f8d7cbc1658bc8ea75f3b5'
step_id: 'S14'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Correct the cognitive-complexity command scope so it measures only production sources on every supported host.

## Scope

- `dev/toolchain.py`
- `pyproject.toml`

## Description

- Replaced repeated Complexipy exclusions with one comma-separated target-local exclusion argument.
- Added direct and nested test-tier and cache patterns without changing the shared configured threshold.
- Kept the audit complexity target unchanged and queued its separate label drift.

## Outcome

The full production command completed in 9.2 seconds and identified 196 production source headings with no test-tier or cache paths. It remains red only for the existing production cognitive-complexity backlog. Ruff, formatting, and diff checks passed, and independent review found no blocker.

## Notes

The audit complexity description does not match its broad package command. It is recorded as a medium deferred audit finding rather than changed outside this step's scope.
