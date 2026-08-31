---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:aea5e10e45e34bac98f4d346f49e5bae06aeee9b19569ccbfe97ef75b054cc10'
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

STEP REOPENED after this record was first written. The implementation below
landed and its verification stands as described, but the Step is NOT complete:
a later finding proved the check false-positives on every completed run of the
lane it was built for.

The proposal and changeset id fields it keys on are populated only by the
research chain's submitter path. The document-editor lane tracks its ids in a
session object whose accessor has ZERO PRODUCTION CALLERS, so those fields are
structurally empty on that lane whether the run succeeded or not. The check
built to catch a silent success on the document editor now fires on the document
editor's SUCCESS CASE - a false positive replacing the false negative.

The companion negative test is vacuous for the same reason: it seeds the ids
directly into the fixture, which is a state no real document-editor execution
reaches. The seeded shape is not fabricated - it is exactly what the OTHER lane
produces - which is why the vacuity was invisible when it was written.

One remedy direction is explicitly RULED OUT: narrowing the predicate to fire
only where the write path is currently wired would silently restore the original
blind spot on the document-editor lane, which is the lane the incident was
about. That is a regression dressed as a fix.

The record below describes what landed and how it was verified. It is retained
unchanged because the work and its proof were sound - what was wrong was the
assumption that both lanes populate those fields.

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
