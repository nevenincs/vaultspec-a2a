---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S14'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Export the child session record out of the isolated config home before teardown

## Scope

- `src/vaultspec_a2a/providers/_acp_config_home.py`

## Description

- Copy the transcript, history, and todo state out of the per-run config home
  before teardown removes it.
- Copy rather than move, so a preservation failure can never cost the caller its
  teardown.
- Bound the archive with oldest-first eviction, and declare the new artifact
  through the retention vocabulary.
- Break eviction ties on name so records preserved inside one filesystem
  timestamp tick evict deterministically.
- Add tests covering survival past teardown, the nothing-to-preserve case, an
  absent home, and the eviction bound.

## Outcome

The agent's own account of a run now survives the home it was written in. Four tests
pass, including one that preserves past the cap and asserts the three oldest records
were evicted while the newest survives.

The bound is the part that made this defensible. An uncapped transcript archive would
have traded a small leak for a larger one, which is precisely the failure the governing
decision exists to prevent, so the artifact is declared as size-bounded with
oldest-first eviction as its stated mechanism rather than being written and forgotten.

Preservation is best-effort throughout. An absent home, a home with nothing to preserve,
and a copy that fails all return without raising, because a run that cannot preserve is
better than a run that crashes trying to.

Gates: `ruff check` and `ty check` report all checks passed, and the combined provider
and artifacts suites report thirty-four passed.

## Notes

The eviction tiebreaker was added after the test passed, not because it failed. Sorting
purely on modification time is unstable when several records land inside one filesystem
timestamp tick, which is realistic when a run preserves in quick succession; the test
would have flaked rather than failed honestly. Name now breaks the tie.

This Step writes the preservation function but does not call it. Nothing in the spawn
path invokes it yet, so no run currently preserves anything - the following Step owns
that wiring. Until then this is capability without effect, and saying so matters more
than the Step reading as complete.

The archive root is expressed in the declaration as living under the runtime directory,
but the function takes its destination from the caller. Whether the caller passes the
declared root is unverified here and belongs with the wiring Step.
