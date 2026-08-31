---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:7b31531c834754489ca0a1546beb222a41ac7578d1aec0d83eef355e5b514b33'
step_id: 'S18'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Align the failure reason bound to the consumer byte limit

## Scope

- `src/vaultspec_a2a/database/thread_repository.py`

## Description

- Express the durable failure-reason bound in encoded bytes, not characters.
- Count the truncation mark against the same budget.
- Cut on a character boundary so a stored reason is always valid text.
- Assert the bound over ASCII, multibyte, boundary-straddling and short reasons.

## Outcome

The bound was 500 CHARACTERS while the consumer that decides whether a reason is
acceptable rejects anything over 500 BYTES. The two agree only for ASCII, so a
provider message carrying a curly quote or a non-Latin script passed the local
cap and was then refused outright downstream - the run reporting nothing at all
rather than a shortened something. Measured on the cases now covered, the old
cap admitted 972 and 1201 bytes where 500 was the limit.

Capping where the reader caps is what turns a rejection into a truncation. That
is the whole benefit: no reason is lost for being long, it is merely shortened.

The truncation mark is counted against the budget in its own encoded length
rather than appended afterwards, because appending after measuring is precisely
how a cap comes to be exceeded by the mark announcing it.

Truncation cuts on a character boundary even though the budget is counted in
bytes. Slicing an encoded string mid-sequence stores bytes that are not valid
text, and a column holding half a character is worse than one holding a slightly
shorter reason. The lenient re-decode drops exactly the trailing partial
character and nothing else, because what it re-decodes was produced by encoding
a Python string and so is well formed everywhere before the cut.

Coverage measures the persisted column against the CONSUMER's number, restated
in the test rather than imported from the repository. Importing the production
constant would have made the assertions agree with whatever the code chose;
restating the requirement is what lets them disagree with it. Four cases: an
overlong ASCII reason is marked and fits, a multibyte reason fits in bytes and
not merely in characters, a budget landing inside a multi-byte character still
round-trips through a strict decode, and a short reason is stored verbatim.

## Notes

The emitting frame's own 512-character bound is untouched. It sits on a
different channel with a different reader and is not what the durable column or
its cross-repository consumer measures; changing it was not part of this Step.
