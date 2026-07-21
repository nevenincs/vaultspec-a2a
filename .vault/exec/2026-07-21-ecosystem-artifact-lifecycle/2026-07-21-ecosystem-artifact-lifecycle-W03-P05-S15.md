---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S15'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Resolve the isolated config home under the declared desktop temporary homes root

## Scope

- `src/vaultspec_a2a/desktop/profile.py`

## Description

- Add a settings accessor exposing the armed profile's temporary-homes root,
  deriving it through the desktop path authority rather than restating the layout.
- Create per-run config homes inside that root when the profile is armed, and
  leave every other profile on the operating system temporary directory.
- Fall back to the system temporary directory when the declared root cannot be
  created, so an unwritable state directory cannot stop a run.
- Add tests covering the unarmed and armed cases through the real settings object.

## Outcome

The temporary-homes root declared by the desktop profile now has a consumer. It was
previously derived, exported, and never read by anything, so a packaged install scattered
its ephemeral homes through the operating system temporary directory despite declaring a
location of its own.

The behaviour is profile-conditional by intent. An armed install keeps its homes inside
its own application home, so an uninstall can account for them and a system-wide
temporary sweep cannot remove a home out from under a live run. Development and Compose
profiles stay on the system temporary directory, where a sweep reclaiming an abandoned
home is a feature rather than a hazard.

Gates: `ruff check` and `ty check` report all checks passed, the temporary-home suite
reports two passed, and the combined provider and artifacts suites report three hundred
sixty-eight passed with ten deselected.

## Notes

The first version of these tests constructed the settings object by attribute name and
silently produced an unarmed profile, because the field arms through its environment
alias. Two tests failed for that reason rather than because the code was wrong. The
construction was corrected and the module docstring now records the trap, since anyone
writing the next test against this field will hit it.

A third test was written and then deleted rather than made to pass. It asserted the
declared root lies outside the system temporary directory, which cannot hold in this
harness because the fixture directory it builds the application home inside is itself
under the system temporary directory. The property it was reaching for - that the root
derives from the application home rather than from the temporary directory - is already
asserted by the test that compares against the path authority, so the deleted test was
both unsound and redundant.

This Step changes where homes are created but adds no reclaim for homes a crash leaves
behind. On an armed install those now accumulate inside the application home, where no
system sweep will reach them, which makes the following Step's sweeper more load bearing
than it was before this change rather than less.
