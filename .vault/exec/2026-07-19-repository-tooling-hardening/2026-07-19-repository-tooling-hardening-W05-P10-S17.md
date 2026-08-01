---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:5b2c4fd5f4a173e27fd9dbc5bfb8a7a2bf779046ef9bd701ca9ed1db75a12956'
step_id: 'S17'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Schedule production JSCPD clone detection as a named advisory hosted-CI result.

## Scope

- `.github/workflows/test.yml`

## Description

- Added one named production clone-detection workflow step.
- Invoked only the existing advisory `just audit duplication` target.
- Kept the result independent, non-cancelling, and non-blocking.

## Outcome

Direct Actionlint and structural checks proved exactly one advisory JSCPD step after the strict sentinels. Canonical CI and its clean-base proof are unchanged. Independent review found no release blocker.

## Notes

A low feature-index lifecycle finding is queued in the audit. Clone reports remain investigation leads and do not join `lint all`.
