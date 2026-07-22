---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S20'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Read one project checkpoint tuple and derive all run-status fields from that immutable snapshot

## Scope

- `src/vaultspec_a2a/control/thread_state_service.py`

## Description

- Count the checkpoint reads a single run-status response performs.
- Extract the field derivations as pure functions over an already-read tuple.
- Add one shared reader and route the run-status path through it.
- Keep the existing async readers working for their other callers.

## Outcome

One run-status response performed three checkpoint reads. The state builder, the authoring
ids, and the semantic context each opened the checkpoint for themselves, so a run advancing
between reads produced a response carrying a status from one moment and a position from
another.

That is worse than staleness. A stale but coherent answer describes a real past state; a
mixed one describes a state the run was never in, and a consumer cannot tell the difference
from the payload.

The parse is now a pure derivation over a tuple, and the run-status path reads once and
derives every field from that snapshot. The two async readers remain for callers that
genuinely want their own read, and now delegate to the same derivations rather than
repeating the parse, so the duplicated channel-values extraction is gone as well.

Five tests cover the derivations, including that neither mutates the snapshot they share -
two derivations over one tuple is exactly where an in-place parse would corrupt the second.

Gates: `ruff check src/` clean, `ty check src/` clean, control and api suites report four
hundred thirty-one passed with six deselected.

## Notes

My first tests spelled the channel names by hand and two failed. The code was right; the
names were guessed. Importing the module's own constants fixed it and left the tests
stronger than intended, because a rename now breaks them rather than silently turning every
assertion into "field absent" while still passing.

The type checker caught a shadowed name in the route. The variable holding the composed
thread state was already called ``snapshot``, and the checkpoint tuple reused it - a
collision that would have passed lint and failed at runtime on the first attribute access.
