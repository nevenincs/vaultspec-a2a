---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S17'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Define a canonical run-start fingerprint over every behavior-affecting request field

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/control/run_start_policy.py`

## Description

- Enumerate the request fields whose value changes what a run does, and record
  why each excluded field is excluded.
- Digest them canonically so the value depends on the fields rather than on
  dictionary ordering or formatting.
- Add tests binding the enumeration to the real schema.

## Outcome

Corrected after the fact, and the correction is the substance of this record.

The first implementation was a duplicate and has been withdrawn. A canonical request
digest already existed on the admission path, wired into the prepare-commit binding and
into release, and it was not found before a second one was written - in a Step belonging to
a plan whose subject is removing duplicated behaviour. The duplicate is deleted.

What survived is the part that had value: the enumeration is now explicit on the existing
digest, with each exclusion carrying its reason, and tests bind those names to the schema.

The digest distinguishes a retry from a changed intention. Two requests
that would produce the same run share a digest; any difference in what the run would do
produces a different one.

Exclusions are named rather than derived. The stage and the reservation id identify the
request rather than describe the work: a prepare and its own commit differ on both while
driving one run, so including them would make the staged path conflict with itself. A
prepare additionally excludes the prompt and the tokens, because it carries neither yet.

The run id IS included, contrary to what the withdrawn implementation assumed. That is
harmless for both uses: a replay is looked up by run id before its digest is compared, and
a prepare and its commit share one. The behaviour is now asserted rather than assumed, so a
future reader weighing whether to exclude it sees the current answer stated.

The enumeration is explicit rather than derived from the model, and that is the load-bearing
choice. Deriving it would fold a newly added field in silently, making previously valid
replays conflict; excluding new fields by default would let a behaviour change replay as
identical. Both failures are quiet, so a person classifies each field and a test asserts
every named field still exists on the schema - a rename would otherwise drop a field out of
the digest without a word.

Thirteen tests cover it, including one case per behaviour-affecting field, an assertion
that a prepare digest ignores the prompt so a commit can still bind to it, and one binding
the excluded names to the schema so a rename cannot silently stop excluding a field.

Gates: `ruff check src/` clean, `ty check src/` clean, control suite reports one hundred
forty-two passed with six deselected.

## Notes

Searching for an existing implementation is the step that was skipped, and it is the same
discipline this session has applied repeatedly elsewhere - the ownership sweeps, the
duplicate-policy consolidations - so the omission was mine rather than a gap in the method.
The cost was bounded because the duplicate never acquired a caller, but a second digest
over the same request would have been a genuine hazard: two definitions of what makes two
runs the same, diverging silently.

This Step defines the digest and computes nothing new with it. Nothing persists it and no
route compares it yet, so replay behaviour is unchanged - that is the following Step, and
separating them keeps a pure definition reviewable before it acquires a failure mode.

The first version of the tests splatted a dictionary of mixed values into the request
constructor, which the type checker rejected because each field is precisely typed. The
same shape was rejected earlier in this session for the same reason. Overriding through the
model rather than the constructor fixes it without a suppression, and the docstring records
why, because the suppression would have hidden a genuinely wrong field name rather than a
typing inconvenience.
