---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:654b2363f43802fe3e8a83413a4ba113f368ff934b8272afe2e2e46c7c077b19'
step_id: 'S181'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Answer the delete verb with its five distinct outcomes and carry abandoned cleanup item kinds through the service result

## Scope

- `src/vaultspec_a2a/api/routes/threads.py`
- `src/vaultspec_a2a/control/thread_service.py`

## Description

- Answer a deletion that finalized over permanently-unremovable cleanup with success carrying a versioned body.
- Carry the abandoned item kinds through the service result instead of flattening them to a flag.
- Move the cleanup-kind vocabulary to the domain enum layer so the wire schema can name it without reaching into control.
- Preserve the pre-saga lifecycle refusal, the resumable-incomplete refusal, and the absent-thread answer unchanged.

## Outcome

Implemented and gated. The delete verb now answers five distinct outcomes rather than
collapsing two of them into one bare success: an absent thread, a pre-saga lifecycle
refusal, a resumable incomplete cleanup, a deletion that finalized while stranding
external state, and a clean deletion. All five codes and their descriptions are declared
on the route, so the published contract carries the whole surface rather than only the
default. The abandoned body names the KINDS of stranded item and nothing else - no
filesystem path, ledger key, attempt count, or failure detail reaches the wire, and a test
asserts the response text contains neither the target path fragment nor the item key.

The service result no longer flattens the outcome. The finalize outcome computes a
deduplicated kind tuple read from the manifest, which is the only authority on an item's
kind since the ledger records key and state alone, and keeps manifest order so the
reported vocabulary is deterministic. The delete result carries that tuple, with the old
boolean retained as a derived property so existing readers keep working. The kind
vocabulary moved to the domain enum layer because the wire schema must name it and the
schema layer deliberately imports only domain leaves; a duplicate wire enum with a
route-side mapping was rejected as a silent drift surface for a two-member closed set.
Durable serialized values are unchanged, so nothing needs migrating, and no re-export shim
was left behind - the four importers were updated.

The abandoned case is proven end to end, not asserted by setting a flag. A real
checkpoint store over a closed connection was probed first to confirm it genuinely raises,
then three real delete passes produced refusal, refusal, and success as the saga's own
attempt ceiling abandoned the item, with a fourth request answering absent - which is
precisely why this outcome is not the resumable refusal. A second driver strands both
kinds at once through the executor's real containment refusal. A mutation check forcing
the abandoned branch dead fails exactly the two abandonment tests and no others.

Verification: the interface and control suites pass 590 tests with no failures; lint and
formatting are clean across all twelve touched files; the whole-tree type gate reports 12
diagnostics, all of them in the protocol package and none in the touched surface. The
published interface artifact was regenerated through the documented command rather than
hand-edited.

## Notes

One coverage limit is stated rather than papered over: an artifact-file abandonment was
NOT driven from a genuinely locked file, because no portable way to do it exists - an open
handle blocks removal on this platform but not on POSIX, and a read-only parent blocks it
on POSIX but not here. Rather than fork the test by platform or skip the case, that kind
is stranded through the executor's containment refusal, which fails identically on every
host and exercises the same abandonment path. Nothing was faked and no case was dropped.

The earlier decision record for this contract wrongly implied only four outcomes, omitting
the pre-saga lifecycle refusal that the route already returned. That error was corrected
in the record before implementation, and the refusal is now additionally proven to write
nothing durable - the thread row survives and no saga row is created - so it is
demonstrably a refusal before the saga rather than one of its states.
