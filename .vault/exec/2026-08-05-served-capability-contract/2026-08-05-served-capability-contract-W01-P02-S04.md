---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:5af27f89b6b6c002daf948624d95751f8f08d35d7aab761c6eac9ae7a41dc8f9'
step_id: 'S04'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F16 safety half - refuse to report a document-authoring run completed with empty degradation when it produced no artifact, the silent green being a separate defect from the missing proposal

## Scope

- `src/vaultspec_a2a/control/run_start_policy.py`

## Description

- Surface a document-authoring run that completed while producing no artifact,
  as a degraded reason on the run snapshot.

## Outcome

Closes in full. The predicate was chosen BEFORE the code was written and checked
live against the real bundled presets: it keys on the worker persona ROLE, not
on topology, and was confirmed to answer true for the document editor, false for
the solo coder, true for the research chain.

A harness-flag predicate was considered and REJECTED, and the reason is the
useful part: the solo coder also arms the authoring bridge, so gating on that
flag would have false-positived every empty coder run. That is the same
topology-versus-role confusion recorded elsewhere in this feature's audit,
caught here before it shipped rather than after.

Two deliberate narrowings. The new marker does NOT touch the repair or execution
readiness fields - it sets snapshot completeness false and appends one degraded
reason, nothing more - which respects the constraint that those fields were not
this Step's to change. And the preset predicate fails closed to false on any
configuration or validation error, so it can never raise into a run-status read.

The subtler one, worth preserving: the check runs ONLY when the checkpoint
loaded. Asserting emptiness on an unread snapshot would report "unread" as
"produced nothing" - manufacturing exactly the class of false statement this
Step exists to remove.

VERIFIED AS A FIX. The two source files were stashed and the suite re-run,
failing with the expected reason absent from the degraded list; unstashed, it
passes. Three preservation guards accompany it, and the second is the one that
matters: a completed document-editor run that DID propose is not flagged; a
completed solo-coder run with empty identifiers is not flagged, which is what
proves the ROLE predicate rather than the harness flag is doing the work; and a
still-running document-editor run is not flagged. 78 tests across every existing
consumer pass unchanged.

## Notes

A CROSS-REPOSITORY OBLIGATION THIS STEP CANNOT DISCHARGE: a consumer rendering
only the run status still shows green after this fix. Surfacing the degraded
reason is the consuming repository's obligation, and the finding is not fully
closed until it does.

Two honest limitations were disclosed by the author and are recorded as findings
in this feature's audit rather than left in a report: the check is scoped to the
literal completed status and excludes archived, and the preset predicate resolves
bundled definitions only, so a workspace override is invisible to it. Both were
rated low by their author and neither is asserted as a live gap.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.
