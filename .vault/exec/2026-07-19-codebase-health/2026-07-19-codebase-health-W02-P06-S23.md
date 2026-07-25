---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S23'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Transform gateway events through the positive DTO while excluding prompts documents artifacts edit diffs and raw provider payloads

## Scope

- `src/vaultspec_a2a/streaming/aggregator.py`
- `src/vaultspec_a2a/streaming/transformer.py`

## Description

- Projected relayed run events through the positive progress allowlist at the
  producer, so identity and metadata survive and bodies do not.

## Outcome

Closed. A positive allowlist is the right shape here rather than a denylist of
forbidden keys: a new field added upstream defaults to excluded instead of
leaking until someone notices it.

## Notes

Commit `a1b45662`.
