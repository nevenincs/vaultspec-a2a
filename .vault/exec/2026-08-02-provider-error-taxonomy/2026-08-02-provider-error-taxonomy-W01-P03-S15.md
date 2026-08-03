---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:892cda9135ae94a1c0b36903c94e7985fd2d19393d22bbb111ba87e85d9e4586'
step_id: 'S15'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Declare the provider condition column on the thread model

## Scope

- `src/vaultspec_a2a/database/models.py`

## Description

- Declare the provider condition column beside the durable failure reason.

## Outcome

The typed counterpart to the reason text: the reason says what happened, the
condition says what the reader should do about it. Kept nullable with no default
and no back-fill, because a run that failed before the column existed genuinely
carries no classification and writing one for it would assert we classified runs
we never observed.

The not-null-on-new-failures invariant lives at the write sites rather than in
the schema, deliberately. A database constraint would turn a classification bug
into a write crash that loses the run outcome altogether, which is worse than
persisting an honest floor value.

## Notes

Landed as one commit with the migration and the repository write. Splitting them
would have left the ORM expecting a column the database lacks, so the
intermediate commits could not have run.
