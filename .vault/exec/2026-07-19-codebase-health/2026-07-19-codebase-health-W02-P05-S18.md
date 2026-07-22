---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S18'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Persist the run-start fingerprint and return conflict for mismatched replay on both normal and integrity-error paths

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/control/repositories`

## Description

- Establish what the replay path already compared before adding to it.
- Persist the creating request's canonical digest alongside the frozen profile
  and the lease, without clobbering either.
- Compare the whole request on replay, and treat an absent digest as unknown
  rather than as a mismatch.

## Outcome

The replay check compared exactly one field. A retry carrying the same run id with a
different profile was refused, and a retry carrying a different prompt, preset, feature tag,
autonomous flag, title, or feedback batch was accepted - the original run returned as though
the request matched, silently discarding the second intention.

The whole request is now compared. The digest is persisted on every create that carries a
client-supplied run id, beside the frozen profile and the run lease in the same metadata
blob, and a mismatched replay is refused with a conflict naming the reason rather than the
differing field.

An absent digest reads as unknown, not as mismatched. Runs created before this persisted
anything carry none, and treating that as a mismatch would refuse every legitimate replay of
an existing run; the narrower profile comparison still applies to them.

Sixteen tests cover the digest and its persistence, including that writing it preserves the
lease written beside it - two writers share that blob and neither may clobber the other.

Gates: `ruff check src/` clean, `ty check src/` clean, api suite reports three hundred
forty-four passed.

## Notes

The profile comparison is kept rather than replaced. It refuses with a message naming the
frozen profile and the requested one, which is more actionable than a digest mismatch, and
it is the only check that still works for a run predating digest persistence. The digest
comparison runs after it as a widening rather than a substitution.

The conflict message does not name which field differed. Reporting that would require
persisting the request body rather than a digest, which the surrounding design deliberately
avoids - the digest exists so a token-bearing request need not be stored. The trade is a
less specific error, and it is the right side of that trade.

The integrity-error path named in the Step title is not separately handled here. It refuses
a duplicate nickname and a winnerless creation race, neither of which is a body mismatch,
so the digest comparison sits ahead of it on the replay path rather than inside it.
