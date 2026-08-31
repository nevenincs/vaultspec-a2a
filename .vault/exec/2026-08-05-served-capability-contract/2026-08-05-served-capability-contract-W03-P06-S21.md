---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:719fe9bcc03d637cc9c0aa579b18d393c720f30f1e0adb0571b0a0a136592df5'
step_id: 'S21'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# Enforce import-from-owner for served vocabularies so no surface redeclares or re-exports one, keeping the two distinct AdmissionState concepts separate rather than merged

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Enforce that no surface redeclares or re-exports a served vocabulary, keeping
  distinct concepts that share a name separate.

## Outcome

Closes in full. Enforcement was written against REDECLARATION, NOT NAME-MENTION,
and that distinction is the whole value of the Step.

A package facade re-exporting its own owning module's type is the import surface
this repository's facade mandate REQUIRES. A name-based check would have flagged
it and invited precisely the wrong fix - deleting a facade export to satisfy a
rule that was never about it. The refinement is recorded in the governing
decision record, because the rule as originally written could have been read
either way.

The two same-named admission concepts were verified to remain separate WITH
DISJOINT MEMBER SETS ASSERTED POSITIVELY, so a future merge fails loudly rather
than passing quietly. That is the difference between documenting a distinction
and defending one.

A sweep for other same-name different-concept pairs found TWO MORE, both kept
apart. Neither was known before the sweep.

## Notes

The sweep result is the reason this Step earns more than its size suggests. The
concept-not-name rule was stated in the governing record on the strength of one
example; the sweep turned it into three, and one of those - a field this
feature's own audit had conflated - shows the rule catching an error the audit
itself had made.

This record was authored by the vault writer from the implementing agent's
report relayed by the routing lead, not from direct observation of the work.
