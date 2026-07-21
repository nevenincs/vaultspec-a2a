---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S06'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Attach a retention declaration to each artifact-creating seam in the lifecycle package

## Scope

- `src/vaultspec_a2a/lifecycle/discovery.py`

## Description

- Declare the two artifacts this module leaves on disk: the discovery record and
  the handoff credential beside it.
- Express both roots as path expressions rather than resolved paths so they stay
  true under the armed desktop profile, which reseats the home.
- State the enforcement honestly in the mechanism text, naming the crash exposure
  rather than implying a reaper that does not exist.
- Expose the declarations individually and as a module-level collection, and add
  all three to the module's public exports.
- Confirm the new import introduces no cycle by loading the collection in a real
  interpreter.

## Outcome

Both artifacts are declared and the collection loads. The discovery record and the
credential are each session-scoped in intent, and the module now exports the pair
alongside the individual declarations.

The mechanism text is the substance of this Step. The discovery record states that it is
removed on a clean exit and explicitly not on a crash, so a stale record can outlive its
gateway indefinitely. That is the exact condition an earlier Step proved had occurred: a
record written before the credential feature existed was still resident two days later
and would be read as a live gateway with no bearer. Declaring the gap keeps it visible
until a Step closes it, rather than letting a comfortable-sounding mechanism imply it is
handled.

Gates: `ruff check` and `ty check` both report all checks passed on the changed module,
and the declarations load cleanly in a real interpreter with no import cycle.

## Notes

The artifacts package imports nothing from the rest of the service, which is what makes
it safe to import from a module as low in the stack as discovery. That property is load
bearing for the remaining adoption Steps and should not be relaxed; this repository has
already had one import-cycle crash caused by a facade reaching sideways.

The credential's declaration is deliberately session-scoped rather than permanent even
though nothing removes it on a crash. Recording intent and enforcement as separate facts
is the point: the disposition says what should happen, the mechanism says what actually
does, and the difference between them is the work still owed.
