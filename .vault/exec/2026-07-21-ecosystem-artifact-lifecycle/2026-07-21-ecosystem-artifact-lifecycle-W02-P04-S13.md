---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S13'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Add a test that forces a write failure and asserts no temporary file survives

## Scope

- `src/vaultspec_a2a/lifecycle/tests/test_atomic_write.py`

## Description

- Drive the helper against real files and assert on directory contents afterwards,
  producing every failure from genuinely unwritable or occupied filesystem state
  rather than from patched behaviour.
- Cover the success path, a republish, a missing destination directory, a rename
  that cannot succeed, a non-operating-system failure mid-write, and the
  process-keyed temporary name.
- Verify by mutation that the cleanup is what the residue assertions measure.

## Outcome

Six tests pass. The mutation check removed the temporary-file cleanup and failed exactly
the two residue tests while the other four continued to pass, so those assertions measure
the guarantee rather than restating it.

Two tests were rewritten after failing for the wrong reason, and the correction is the
substantive part of this Step. Both originally forced failure through a string subclass
whose conversion raised, which never fired: writing a string subclass to a file uses its
buffer directly and never calls the conversion. The tests were failing because the
mechanism was wrong, not because the helper was. They were replaced with real failure
modes: an unpaired surrogate that genuinely cannot encode as UTF-8, and a directory
occupying the exact temporary name so the write cannot open it.

## Notes

The rewrite is a reminder that a red test is only evidence once its mechanism is
understood. Had the originals been left red and the helper adjusted to satisfy them, the
result would have been production code shaped by a test that never exercised the path it
claimed to.

The non-operating-system failure case is the one that justifies catching every exception
type in the helper rather than only operating-system errors. An encode failure raises a
value error after the temporary file already exists, so a narrower handler would leak
there. That case is now pinned by a test.

Coverage of a genuine process interruption is absent. Asserting on a real interrupt would
require driving a subprocess and killing it mid-publication, which is worth doing and is
not done here; the handler covers the case by construction but no test proves it.
