---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S04'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Make a tokenless discovery publication fail loudly instead of silently unlinking the credential

## Scope

- `src/vaultspec_a2a/lifecycle/discovery.py`

## Description

- Add an explicit opt-in keyword to the publication routine and refuse a
  credential-free publish without it, naming the destructive consequence in the
  error text rather than reporting a generic argument fault.
- Document on the routine why silence was the hazard: the gateway always mints a
  credential, so a tokenless call is a defect at every production call site.
- Run the suite to measure the blast radius before adapting any caller.
- Annotate the eleven credential-free call sites, all of them discovery-state
  fixtures where credentials are irrelevant, so each states its intent.
- Add a test that executes the refusal and asserts the existing record and its
  credential survive it, and a second proving the deliberate un-publish still clears
  both.

## Outcome

The routine now refuses a credential-free publish unless the caller opts in. The
refusal is proven by a test that triggers it and then asserts the healthy record still
carries its handoff reference and the credential file is unchanged, so the test
measures the protection rather than the exception type alone. The opt-in path is
proven separately, so the un-publish capability is retained rather than removed.

Blast radius was measured before adapting anything: the change failed five tests and
passed one hundred fifteen, and every failure was a credential-free fixture in the
discovery suite. No production caller was affected, which is consistent with the
previous Step's finding that exactly one production caller exists and it always
supplies a credential.

Gates: `ruff check` clean on both changed files, `ruff format` applied, `ty check`
reported all checks passed, and the discovery suite reports twelve passed. The wider
touched-area run across the lifecycle, api, and control suites was still executing when
this record was written and its totals are recorded in the Notes.

## Notes

The eleven annotated call sites are noise, and that is the intended cost. A
credential-free publish is now visible at every site that performs one instead of being
indistinguishable from an ordinary call, which is the property whose absence let an
unauthenticated record persist unnoticed for two days.

One design alternative was rejected. The refusal could have been placed at the gateway
call site rather than on the primitive, which would have left the eleven fixtures
untouched. It was rejected because the primitive is the seam that creates the artifact,
and the governing decision places enforcement there specifically so a future caller
cannot reintroduce the hazard by bypassing a higher-level check.

This Step does not address the temporary-file leak on the same routine, which remains
open and is owned by the Phase covering the shared write-and-rename helper. It also does
not remove a stale record when a gateway exits; nothing does, and that gap is what the
previous Step established as the real cause of the record examined there. No Step in
this plan currently covers it, so it is carried here as open work rather than assumed
handled.
