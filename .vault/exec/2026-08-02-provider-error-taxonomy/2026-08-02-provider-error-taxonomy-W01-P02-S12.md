---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:84dd38e142ebfb344e047d9df89a00e5fc47bf154f240478a557fdefcc81c81f'
step_id: 'S12'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Prove each lane mapper is total over its installed wire vocabulary

## Scope

- `src/vaultspec_a2a/providers/tests/test_conditions.py`
- `src/vaultspec_a2a/providers/tests/_installed_vocabulary.py`

## Description

- Extend the shared installed-vocabulary reader with the ACP adapter's own
  literal error kinds, scanned from the shipped bundle, and with the Codex
  error-info variants, generated from the codex binary at call time.
- Assert per lane that every installed discriminator is decided by the mapping
  rather than reaching its member by falling through.
- Assert the inverse per lane: the mapping decides nothing the installed adapter
  cannot produce, so a stale entry cannot advertise a condition that no longer
  occurs.
- Assert totality over inputs neither mapping has seen - an unrecognised
  discriminator, an unrecognised status, a non-object frame, a non-string key,
  and an absent discriminator - all resolving to the floor without raising.
- Drive the real raise sites: the real ACP raise with the frame captured live
  from the Z.ai gateway, and the real Codex turn consumer over a real subprocess
  emitting real notification frames for the error, failed-turn, interrupted-turn
  and completed-turn cases.
- Skip naming the missing prerequisite when an installed artefact is absent, so
  an unarmed host reports the coverage unrun rather than passed.

## Outcome

Sixteen tests, all passing, and - more to the point - all demonstrated capable of
failing.

The property under test is not totality. Totality alone is close to untestable
here, because the floor guarantees every input returns a member, so an
it-returned-something assertion would pass on exactly the day a provider adds a
discriminator nobody has mapped. The property proven instead is that every
discriminator the INSTALLED adapter can emit reaches its member by decision. That
requires knowing what the installed adapter can emit, which is why the
vocabularies are read from the artefacts that execute rather than restated: the
agent SDK's shipped type declaration, the ACP adapter's own bundle, and a
protocol schema generated from the codex binary during the test run at a cost of
about 1.6 seconds.

Generating rather than committing the Codex schema is the deliberate choice. A
checked-in copy records what the protocol looked like when someone last
refreshed it, which is precisely the drift this coverage exists to detect.

The coverage was mutation-checked rather than assumed effective. Two deliberate
faults were introduced and both were caught: pointing the ACP rate-limit kind at
the finer usage member failed the test that guards the one distinction this
lane's wire cannot carry, and deleting a Codex variant from the mapping failed
the decided-by-decision test, which named the orphaned variant. The mapping was
then restored byte-identically and the suite returned to sixteen passing.

The wiring is exercised, not just the tables. A completed-turn case is included
specifically so the failure-path work cannot have quietly turned every turn into
an error - a gap the failure tests alone could not detect - and the
interrupted-turn case pins that a turn with no error object gets no invented
condition and no invented retry hint.

Verified with `ruff format`, `ruff check src`, whole-tree `ty check` (clean), and
`pytest -q -p no:randomly --timeout=180 --timeout-method=thread`: this file alone
at 16 passed in 18s, and the whole providers package at 642 passed, 2 failed, 30
deselected - both failures pre-existing and unrelated.

## Notes

Only literal error kinds are recoverable from the ACP adapter bundle. The
forwarding call sites pass a variable rather than a string, so the SDK union
covers those and the bundle scan covers the kinds the adapter mints itself. That
split is stated in the reader, because a future reader could otherwise assume the
scan alone is the whole vocabulary.

The stale-entry test is the one most likely to become a nuisance, and that is
deliberate. It fails if a provider REMOVES a discriminator, which is not a
correctness bug in the mapping. It is still worth failing on: an entry for a
condition the lane can no longer report is a false statement about the lane, and
it is how a consumer comes to ship a remediation nobody will ever see.

The Codex frames are driven through a real subprocess that emits the frames and
then sleeps, so the reader is never racing an end-of-file. The turn consumer ends
the process by raising and the client reaps the tree in the helper's teardown; no
test leaves a process behind.

Two pre-existing failures in the providers package remain untouched and are
recorded against the first Step of this Phase. Both assert a superseded contract
about the Codex config home; neither file is in this Phase's scope.
