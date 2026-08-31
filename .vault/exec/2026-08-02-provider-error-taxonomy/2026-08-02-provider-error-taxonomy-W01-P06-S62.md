---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:c3851ce7ae7ef444f69353123e2d5fbba946df9962cbf37c6eb699f4d33fbbcb'
step_id: 'S62'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Gate the shared condition vocabulary against the engine's declaration so a new member cannot ship one-sided

## Scope

- `src/vaultspec_a2a/api/tests/test_engine_edge_bounds_agreement.py`

## Description

- Parse the consuming engine's declared condition vocabulary out of its source.
- Assert it equals this side's enum member for member, in declaration order.
- Explain in the failure text which direction of drift costs what, so the gate
  tells whoever trips it what to do rather than only that something differs.

## Outcome

Raised by the engine phase, not by this side. The consuming engine validates an
incoming condition against its own copy of the vocabulary and REFUSES a value it
does not recognise, at the write boundary. That choice is right - loud beats
silent, and silently storing an unmodeled value would recreate the exact failure
this whole campaign exists to undo - but it creates a release ordering that
nothing enforced: teach the engine first, or the day this side emits a new member
the engine does not lose one field, it refuses to settle that run at all.

The gate was nearly free because of where the engine put the declaration. It
lives in the shared contract module whose stated purpose is names that must agree
across the repository boundary, and this side ALREADY reads that exact file to
pin the clarification bounds and the role ceiling. So this is a fourth assertion
in an existing gate rather than a new mechanism.

Reverse drift is asserted too, and is worth stating because it is the direction
that looks harmless. A member the engine accepts and this side never emits is a
remediation affordance no user can ever reach - and it will read as implemented
in every review of either repository, because both sides name it.

## Notes

Reads the engine's source rather than calling a running engine, for the same
reason the sibling assertions do: the declaration is the contract, while a
running engine reports only what one build happens to carry. When the engine tree
is not on disk the gate skips naming what is missing, since a vocabulary that
cannot be read is not one this side can claim agreement with.

Order is compared rather than set membership. The two sides are one enumerated
vocabulary, and normalising before comparing would hide a reordering that a
positional consumer could care about.

Proven non-vacuous by reading the values it extracts: nine members, matching this
side exactly. A gate that silently skipped, or that matched an empty tuple
against an empty tuple, would pass just as green - so the extraction was checked
directly rather than inferred from the assertion passing.
