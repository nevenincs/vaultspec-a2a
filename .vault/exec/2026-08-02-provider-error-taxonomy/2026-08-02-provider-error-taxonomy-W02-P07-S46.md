---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:6b1085c03b225f34bc65fa242fbd83d426bb6720ed23d4912ae94f9b570bc1ae'
step_id: 'S46'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Declare the provider condition on the run record type

## Scope

- `engine/crates/vaultspec-api/src/authoring/session/types.rs`

## Description

- Add the optional condition field to the run record beside the existing failure
  reason, matching its serialization treatment so every recorded run already on
  disk still deserializes.
- Add the receiving field to the complete-run request, without which the store
  has no way to be told the value at all.

## Outcome

Landed. The field mirrors the failure reason it sits beside, which is the right
shape for a reason no one queries: the source-of-truth record carries it and the
runs table needs no column.

One premise this Step was briefed with turned out to be FALSE, and the executor
disproved it rather than accepting it. The brief asserted that the serde default
attribute was load-bearing under the record's deny-unknown-fields setting. A
mutation probe removing the attribute left the old-record read passing:
deny-unknown-fields governs fields that are PRESENT and unexpected, while an
absent optional field already deserializes to none. The attribute is retained for
consistency with the optional fields around it, and the field's own comment now
states what actually holds rather than repeating the claim.

Worth recording because the same wrong claim sits on two neighbouring fields'
comments. They were left alone as outside this phase, so the repository still
carries the belief in two places.

## Notes

The receiving field on the complete-run request was outside the Step's named
scope and was added anyway, correctly: a declared field with no path to reach the
store is a field that cannot be set, and shipping one would have been the dead
capability this campaign exists to eliminate.
