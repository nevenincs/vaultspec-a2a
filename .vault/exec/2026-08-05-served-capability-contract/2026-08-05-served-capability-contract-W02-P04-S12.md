---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:f89afa3f63b117c3721fef033b141442389f45923b7a467813b58acb2d5052a0'
step_id: 'S12'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F11 DONE in commit 1022ba08 - the five underscore-prefixed snapshot models were renamed and exported, the parity test updated, and zero underscore-prefixed schemas remain in the published contract, verified against the committed artifact

## Scope

- `src/vaultspec_a2a/api/schemas/snapshots.py`

## Description

- Rename five snapshot models out of the private underscore namespace and add
  them to the module's public export list.
- Update the parity test that guards the published contract against the schema
  set.

## Outcome

Closed. The five models were being published in the contract's schema
components with leading underscores, on the clarification and permission
surfaces - the human-in-the-loop path. Underscore-leading names are invalid or
mangled identifiers in most code generation targets, so a generated client
either failed or produced mangled class names on exactly the surfaces a human
operator depends on.

Verified against the COMMITTED ARTIFACT rather than the working tree: zero
underscore-prefixed schemas remain in the published contract. Checking the tree
would have proved only that the source changed, not that the artifact a client
consumes did.

No served byte changed. Schema component keys name types in the contract
document; they never appear in a payload, so this is a rename of published type
identifiers rather than a wire change.

## Notes

The Step originally attributed this to the gateway schema module. That was
wrong: the models live in the snapshots schema module, and the Step has been
corrected. Leaving the wrong attribution would have set a trap for the next
reader.

Their public siblings in the same module already carried plain names, which is
what establishes the underscore as an oversight rather than a deliberate
privacy boundary being breached.

This record was authored by the vault writer from the implementing agent's
report, not from direct observation of the work.
