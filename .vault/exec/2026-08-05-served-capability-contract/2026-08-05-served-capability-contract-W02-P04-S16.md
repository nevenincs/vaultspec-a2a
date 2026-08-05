---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:2effa56ae196d09aaedde1469bb287cb2b1768ef2aee610bb5003cce9cbb7b96'
step_id: 'S16'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# Document the OpenAPI artifact regeneration command, which exists only inside the test file that enforces it

## Scope

- `docs/development.rst`

## Description

- Document the OpenAPI artifact regeneration command in the development guide.

## Outcome

Closed. The command existed only inside the test file that enforces it, named
in that test's own assertion failure messages. The strongest guard on this
contract surface - a test asserting full field-for-field equality between the
committed artifact and the freshly built application, plus path completeness in
both directions - rested on a command nobody outside that file was told about.

Verified by the guard's own behaviour rather than by inspection: the artifact
test FAILED before regeneration and PASSES after. That ordering does double duty
here. It confirms the documented command actually regenerates, and it proves the
guard detects change rather than passing vacuously - a test that passed in both
states would have told us nothing about either.

## Notes

This is the documentation half of an audit finding whose broader concern was
that no decision record governs the OpenAPI artifact at all; both records that
once did are superseded and the generator they mandated no longer exists. That
gap is not closed by this Step and remains open.

This record was authored by the vault writer from the implementing agent's
report, not from direct observation of the work.
