---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S05'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Define the retention disposition vocabulary and the declaration record type

## Scope

- `src/vaultspec_a2a/artifacts/retention.py`

## Description

- Add an artifacts package following the repository's facade convention, exposing
  the declaration types from the package root and keeping the implementation in a
  leaf module.
- Define a deliberately small disposition vocabulary covering size-bounded,
  age-bounded, session-scoped, and permanent lifetimes.
- Define an immutable declaration carrying the artifact name, its root as a path
  expression rather than a resolved path, the owning component, the disposition,
  and the mechanism that enforces it.
- Refuse a permanent declaration with no stated reason, and refuse a reason on a
  non-permanent one because that field would never be read.
- Refuse any blank required field.
- Add tests that execute each refusal rather than asserting on the happy path alone.

## Outcome

The vocabulary and the declaration exist and validate. Nine tests pass, covering the
accepted bounded case, both directions of the permanence-reason rule, each of the four
blank-field refusals individually, and a sweep asserting every vocabulary member both
constructs and reports its own boundedness correctly.

Gates on the new package: `ruff check` clean, `ruff format` applied, `ty check` reported
all checks passed, and the package suite reports nine passed.

The type checker initially rejected two constructs in the tests, and both were fixed at
the root rather than suppressed. A helper that splatted an untyped dictionary into the
constructor was replaced with an explicitly typed keyword signature. An immutability
test was removed outright rather than silenced: it asserted that a frozen dataclass
refuses attribute assignment, which exercises the standard library rather than anything
written here.

## Notes

The declaration is inert by design and deletes nothing. That is a deliberate constraint
from the governing decision, which rejected a central janitor because a janitor knows
only the targets it was told about, and every leak the sweep found was an artifact
nothing had told a janitor about. Nothing in this package should later acquire the
authority to remove files.

Two properties are asserted here that the rest of the plan depends on. The root is
recorded as a path expression rather than a resolved path, so a declaration stays true
across hosts and across the armed desktop profile that reseats the home. And permanence
is representable rather than forbidden, because some artifacts genuinely should outlive
every process that reads them; the requirement is only that the choice be stated.

This Step defines the vocabulary and nothing adopts it yet. The declaration is
unreferenced production code until the following Steps attach it to real seams, which is
a real if temporary cost and is recorded rather than glossed. The blast radius of that
adoption is unknown until the first seam is wired, because no seam currently has a place
to put a declaration.
