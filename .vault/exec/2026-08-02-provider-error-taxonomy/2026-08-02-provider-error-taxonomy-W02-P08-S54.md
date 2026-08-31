---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:629078dd19f562b4c9c689eb55ef120d900d89b8603fb10b6966a458182292de'
step_id: 'S54'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Add one localized message key per condition member

## Scope

- `frontend/src/localization/catalogAgentKeys.ts`

## Description

- One key per member, plus one for the served human account.
- Classify every key in the role whose policy REQUIRES an actionable recovery
  clause.

## Outcome

Landed. The role classification is the load-bearing choice: it is the one role
whose policy demands a remedy rather than a restatement, so a member cannot ship
with copy that merely describes the refusal back to the reader. The vocabulary
exists because the REMEDIES differ; copy that only renames the fault would
discard exactly the information the campaign recovered.

A defect was introduced and caught here, and it is the most instructive event of
the phase. The first wording for the credential member told the reader to sign in
again - pointing at a screen this product does not have, since provenance is
ambient rather than gated by a login. A vocabulary guard failed it. Only the
whole-tree declared run caught it; no scoped run would have, and it reads
perfectly plausibly in review.

## Notes

Corrected in a follow-on commit to name the credential an operator actually
replaces. The general lesson is that copy can be internally coherent and still
describe a product that does not exist.
