---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:2322ea1c123372b2981fadb06582b0185577536be6859d4c38fe8918e3dcbc2c'
step_id: 'S47'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Validate the condition against the closed vocabulary

## Scope

- `engine/crates/vaultspec-api/src/authoring/session/validate.rs`

## Description

- Declare the accepted vocabulary once, and validate an incoming condition
  against it at the same write boundary the sibling reason is checked at.
- Refuse an unrecognised value loudly, naming the offending value and the
  accepted set.

## Outcome

Landed, with the declaration placed better than the brief specified. It lives in
the shared cross-repository contract module rather than beside the run record,
because that module's stated purpose is exactly names that must agree across the
boundary, it already holds the other bounds both sides share, and it carries a
pinning test against literals.

That placement had a consequence the executing side could not see: the emitting
repository ALREADY reads that same file to pin its clarification bounds and role
ceiling. So the declaration is not merely well-placed, it is now gated - a
separate Step added an agreement assertion on the emitting side that parses this
constant out of the source and requires it to equal the emitted enum member for
member, in order.

Refusing loudly is the right choice and worth defending. Silently storing an
unmodeled value would recreate, one layer up, the exact failure this campaign
exists to undo: a classification destroyed in transit and no one able to tell.

## Notes

The refusal creates a real release ordering - the consuming side must learn a new
member before the emitting side sends one, or that run cannot settle at all. That
obligation was reported as documented-but-unenforced, and is now enforced by the
agreement gate rather than by discipline.
