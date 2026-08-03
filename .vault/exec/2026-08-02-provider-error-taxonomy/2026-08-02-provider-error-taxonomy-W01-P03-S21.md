---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:55a6ad0051c8959799f677e7fa2c46704a26933df3f94fb6950bbf069d24b391'
step_id: 'S21'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Declare the condition on the domain snapshot dataclass

## Scope

- `src/vaultspec_a2a/api/schemas/snapshots.py`

## Description

- Declare the condition on the wire snapshot model beside the reason.

## Outcome

One field, and the whole point is which side of a seam it sits on. The
projection between the domain snapshot and this model is a validating
conversion, and it DROPS any field this model does not name - silently, without
raising, and without any signal that a value went missing. That is exactly how
the failure reason was lost once already, after it had been persisted correctly.

Naming the condition on both sides is what stops it following. A value that is
persisted, carried as far as this seam, and then quietly discarded is
indistinguishable from one that was never recorded at all - and the whole
campaign is about not being in that position.

## Notes

None.
