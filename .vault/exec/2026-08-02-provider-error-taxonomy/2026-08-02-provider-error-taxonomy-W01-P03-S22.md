---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:22a3c5ffe111165ec044929a042188d91bc5e1f91db38eea1e189a04e5c91bec'
step_id: 'S22'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Declare the condition on the run-status response schema

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Declare the condition on the run-status response beside the failure reason.

## Outcome

This response is where the condition becomes authoritative. The repository's
disclosure discipline is already settled for the pending questionnaire on the
same model: durable state answers the reload, and a relay frame is a
non-authoritative nudge to come and read it. The condition follows that rule
unchanged, and it has to - the error frame carrying it is droppable, so a client
that reloaded, or that never received the frame, has no other source.

Typed as an optional string rather than the enum. The field is a wire contract
consumed by a second repository which validates the value against its own copy
of the closed vocabulary; serving a strict enum here would turn a member that
repository has not adopted yet into a serialization failure on OUR side, when
the honest outcome is for it to receive a value it can decide about. The set is
additive-only by decision, so a reader can rely on old members never changing
meaning.

None for a run that never failed, and for one whose failure predates the durable
column - both are honest absences rather than defects.

## Notes

None.
