---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:ad8614d16ca18a47e46dbc72751b7699f0d7ee9a1dd30c43cab62cb0e55875b2'
step_id: 'S159'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove bounded token deltas with a real authenticated stream client

## Scope

- `tests/streaming`
- `tests/api`

## Description

- Proved the token delta stays bounded through a real authenticated stream
  client.

## Outcome

Closed. The bounded delta is the one content-bearing field the allowlist keeps,
so it is the field most worth pinning: exclusion elsewhere is worthless if the
permitted channel is itself unbounded.

## Notes

Commit `f7e67f04`. Same scope-path note as the sibling proof Steps.

The sibling Step `S160` remains OPEN rather than being closed alongside this
one. It requires global AND per-principal quotas, and only the global half is
proven - authentication is a single shared attach credential, so there is no
principal to key the other half on. Closing it needs a decision on caller
identity, recorded in the audit as
`per-principal-stream-quotas-have-no-principal`.
