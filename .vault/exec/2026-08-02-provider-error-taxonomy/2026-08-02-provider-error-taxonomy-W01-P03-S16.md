---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:2f1ef9546f78b00409ab0c041533fd31d76c957437bc884e7155ba045fce98ba'
step_id: 'S16'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Add the provider condition migration revision

## Scope

- `src/vaultspec_a2a/database/migrations/versions`
- `src/vaultspec_a2a/database/tests/test_migrations.py`

## Description

- Add the additive nullable column revision on top of the control-action lease head.
- Advance the four head assertions that pin the expected revision.

## Outcome

Verified forward on a real SQLite database rather than by inspection: alembic
reported `Running upgrade 0012 -> 0013`. The column is an unconstrained string
rather than a native enum, because the vocabulary is a wire contract shared with
a second repository and is additive-only - a new member must never require a
schema migration before it can be stored.

The head assertions were advanced rather than rewritten to derive the head from
the script directory. Deriving it would have been more robust to the next
migration and strictly weaker: pinning is what forces each new revision to be
acknowledged by a human instead of changing the head silently.

## Notes

Two `upgrade(cfg, "0012")` calls were deliberately left alone - they exercise the
lease migration specifically and are not head assertions.
