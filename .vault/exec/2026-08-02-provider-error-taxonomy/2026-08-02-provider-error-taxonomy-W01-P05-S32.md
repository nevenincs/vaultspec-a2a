---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:3788846ece0a4a3c9417967df40231b928a870417709162d37c9d7f355119a06'
step_id: 'S32'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Pass the dispatch failure reason from permission resume

## Scope

- `src/vaultspec_a2a/control/permission_service.py`

## Description

- Pass the dispatch outcome's own detail as the durable failure reason on permission resume.

## Outcome

Same shape as the run-creation site, with one difference worth stating: this path
fails the thread to INPUT_REQUIRED rather than FAILED, because a permission
resume that could not be delivered leaves the run still parked on its question
rather than dead. The reason is recorded on that transition all the same, so a
reloading panel can say why the answer did not take.

## Notes

This file is concurrently owned by the control-action lease migration. The edit
was confined to the existing failure arm and took none of that work; the
previously-failing applied-stamp test in this area now passes, having been fixed
by its own author.
