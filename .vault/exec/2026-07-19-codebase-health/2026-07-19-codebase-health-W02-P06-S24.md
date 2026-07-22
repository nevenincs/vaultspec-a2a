---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S24'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Authenticate the progress stream and enforce global connection limits before principal lookup

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/dependencies.py`

## Description

- Establish whether the stream verb is already authenticated before adding
  anything.
- Add the global connection limit that was absent, decided from process-local
  state ahead of the thread lookup.
- Add the setting that bounds it, with a positive default.
- Add tests covering the bound, the override, the count it reads, and the
  ordering of the refusal.

## Outcome

Authentication was already in place. The versioned router carries the attach dependency, so
every route beneath it including the stream verb refuses an unauthenticated caller, and an
existing suite already asserts that for the stream path specifically. Adding a second check
would have been change without effect.

The connection limit was genuinely absent, and that is the half worth having. Authentication
stops a stranger opening a stream; it does not stop an authenticated caller opening ten
thousand. Each subscriber holds a bounded queue and a delivery path, so an unbounded count
is a resource-exhaustion surface behind a valid bearer.

The refusal is decided before the thread lookup. That ordering is the point rather than an
optimisation: a flood large enough to exhaust queues would multiply the database round trip
too, so the limit must be answerable from process-local state alone. A test proves the
ordering by passing a null session and asserting the service-unavailable rather than an
attribute error.

Zero disables the limit, which is an operator choice rather than the default; the default is
two hundred fifty-six.

Gates: `ruff check src/` clean, `ty check src/` clean, api and streaming suites report four
hundred fifteen passed.

## Notes

I added a subscriber count that already existed, and the linter caught the redefinition
immediately. That is the second time in this session I have written something the tree
already had, after a duplicate request digest. Both times the omission was the same: I did
not search before writing. The duplicate was removed and the surviving method's docstring
carries the reasoning instead, so the improvement survived without the duplication.

The step's title names two things and only one needed doing. Verifying the first before
building the second is what kept this from becoming a redundant authentication check layered
over a working one.
