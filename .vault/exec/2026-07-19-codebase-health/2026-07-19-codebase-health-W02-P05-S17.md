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

The fingerprint exists and distinguishes a retry from a changed intention. Two requests
that would produce the same run share a digest; any difference in what the run would do
produces a different one.

Eight fields are included and four deliberately excluded. The stage, the reservation id and
the run id identify the request rather than describe the work - a prepare and its own
commit legitimately differ on all three while driving one run, so including them would make
the staged path conflict with itself. Actor tokens are minted per attempt by the engine, so
comparing them would make every honest retry conflict.

The enumeration is explicit rather than derived from the model, and that is the load-bearing
choice. Deriving it would fold a newly added field in silently, making previously valid
replays conflict; excluding new fields by default would let a behaviour change replay as
identical. Both failures are quiet, so a person classifies each field and a test asserts
every named field still exists on the schema - a rename would otherwise drop a field out of
the digest without a word.

Thirteen tests cover it, including one case per behaviour-affecting field and an assertion
that the identifier fields stay out.

Gates: `ruff check src/` clean, `ty check src/` clean, control suite reports one hundred
forty-two passed with six deselected.

## Notes

This Step defines the fingerprint and computes nothing with it. Nothing persists it and no
route compares it yet, so replay behaviour is unchanged - that is the following Step, and
separating them keeps a pure definition reviewable before it acquires a failure mode.

The first version of the tests splatted a dictionary of mixed values into the request
constructor, which the type checker rejected because each field is precisely typed. The
same shape was rejected earlier in this session for the same reason. Overriding through the
model rather than the constructor fixes it without a suppression, and the docstring records
why, because the suppression would have hidden a genuinely wrong field name rather than a
typing inconvenience.
