---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:2a07bd5f14d288ffb350d7ef6ad1841bbcbfd50829ae72cbb701c1f0d5fde07c'
step_id: 'S177'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Classify credential values out of the plain-start replay fingerprint and stamp each persisted fingerprint with the rule that computed it

## Scope

- `src/vaultspec_a2a/api/run_admission.py`
- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Exclude credential values from the plain-start replay fingerprint while leaving the staged commit binding strict.
- Stamp every persisted fingerprint with the rule that computed it so older runs compare under their own rule.
- Give the credential dimension real coverage, which it never had.

## Outcome

Implemented and gated. The plain-start fingerprint previously folded the credential bundle
into the identity of the work, so a client retrying with the same run identifier and
freshly minted short-lived credentials was refused - which is precisely the
lost-acknowledgement recovery that client-supplied idempotency exists to serve. Credential
values are now classified out on that path, using the same named-exclusion mechanics the
module already applies rather than a second mechanism. The engine bearer needs no separate
entry because it lives inside the bundle, and a test asserts that independently so a
future refactor lifting it to a top-level field fails loudly instead of silently restoring
the defect.

The staged commit binding is untouched and remains strict. Its retry window binds an
already-minted bundle, and a rotated commit retry is refused there by design at the
credential-binding boundary - a deliberate refusal rather than an impossibility, which is
the stronger reason to leave it alone.

Persisted fingerprints now carry the rule that produced them. Raw credentials are never
stored, so an older fingerprint cannot be recomputed; without a marker, a byte-identical
replay of a pre-change run would have been refused spuriously. An unseparated stored value
reads as the older rule, and an unrecognised marker reports no match rather than guessing -
refusing to replay a run whose identity was never verified is the safe direction.

One repair reached both call sites for free: an earlier change had lifted the replay
identity comparison into a single helper shared by the sequential path and the
insert-race branch, so one edit to that helper covered both. That was verified rather
than assumed.

Verification: the interface and control suites pass 586 tests with no failures; lint and
formatting are clean; the whole-tree type gate adds nothing to the pre-existing set. A
mutation probe flipping the current rule back to the credential-sensitive one fails four
tests including the live one, so the coverage is not vacuous.

## Notes

The brief for this work asked for an existing token-sensitive conflict test to be
INVERTED rather than deleted. On inspection that test conflicted on the prompt and carried
no credential bundle at all, and a tree-wide search found nothing anywhere asserting
credential sensitivity - so there was no coverage to invert and none to retire. The
dimension was simply untested. It now is: a retry carrying a rotated bundle replays and
returns the original run, a retry that also changes a behaviour-affecting field is still
refused, exactly one dispatch occurs and it carries the ORIGINAL credential, and the
original body still replays. The correction to the brief came from the implementer
checking rather than complying, which is the behaviour worth recording.

The old-rule comparison is proven against a fingerprint recomputed from the SPECIFICATION
inside the test rather than from the production exclusion tables, so a future edit to
those tables cannot redefine the old rule and green-wash the guarantee.

One consequence is flagged rather than buried: because the insert-race branch shares the
helper, a commit body losing an insert race now resolves credential-free where it was
previously credential-sensitive. It is reachable only across two processes against one
store, since commits are serialized per run identifier in-process, and any subsequent
retry still meets the strict durable binding. Threading a second rule through that path
would have meant inventing the second mechanism this work exists to avoid.


Reviewed PASS WITH FINDINGS - no critical, no high. The review reproduced the
implementer's mutation probe independently, added a second probe on the edge wiring that
the implementer had not run, and confirmed five of six self-reported claims exactly as
stated.

The sixth did not hold, and it is the most useful result here: the test guarding the
fail-closed behaviour on an unrecognised rule marker DID NOT DISCRIMINATE. It fed the
guard a digest computed under the current rule, but a fail-open implementation returns the
same answer for that input, because a credential-free digest never equals a
credential-sensitive one. The assertion held against both the correct and the defective
implementation. Proven by mutation: replacing the refusal with a silent fallback left the
file fully green, while a run written by a newer process would then replay on a guess -
exactly what the guard exists to prevent.

Repaired as a test-only change: the assertion now uses a fingerprint the fallback rule
would actually match, and a positive control was added first, so every refusal is
attributable to the MARKER being refused rather than to a digest that happens to disagree.
Both original assertions were kept rather than traded away. The repair was then proven to
discriminate - the tightened test fails against the fail-open mutant while the originals
still pass against it - with the probe applied only to a copy outside the repository and
the production file verified untouched afterwards.

Four low findings are queued rather than fixed here: the frozen historical rule reads its
exclusions from a live table rather than a frozen copy, the exclusion is one notch wider
than the decision record's literal words, the engine-bearer guard covers the bearer leaving
the bundle but not a second bearer being added beside it, and a docstring claims a
constant-time comparison that two earlier return paths bypass.
