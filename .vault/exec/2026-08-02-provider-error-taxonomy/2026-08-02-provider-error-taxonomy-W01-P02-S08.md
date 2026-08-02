---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0eac3f9d50644e809668faf97f9e81989c4e45b85fb2c6febe2680ed8ffb35dd'
step_id: 'S08'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Map the Codex error info variants onto the vocabulary

## Scope

- `src/vaultspec_a2a/providers/conditions.py`

## Description

- Regenerate the app-server protocol schema from the installed binary and take
  the variant list from it rather than from any prior write-up.
- Add a table for the eleven bare categorical variants and a second for the five
  single-key object variants, each entry commented where the choice is not
  self-evident.
- Add a table for the HTTP status the object variants forward, and prefer it over
  the variant's own condition when present, since a status means the provider
  answered rather than that the connection failed.
- Add a total resolver for the discriminator and a second for the whole turn
  error, neither of which consults the message text.
- Expose the set of explicitly mapped variants so coverage can assert the
  installed schema is fully decided rather than partly falling through.

## Outcome

This lane carries more than the ACP lane does, and the mapping now reflects that
instead of levelling it down.

| variant | condition |
| --- | --- |
| unauthorized | unauthenticated |
| usageLimitExceeded | usage exhausted |
| sessionBudgetExceeded | budget exhausted |
| serverOverloaded | provider overloaded |
| badRequest | invalid request |
| contextWindowExceeded | invalid request |
| cyberPolicy | invalid request |
| internalServerError | unknown |
| threadRollbackFailed | unknown |
| sandboxError | unknown |
| other | unknown |
| httpConnectionFailed | network unreachable |
| responseStreamConnectionFailed | network unreachable |
| responseStreamDisconnected | network unreachable |
| responseTooManyFailedAttempts | unknown |
| activeTurnNotSteerable | invalid request |

| forwarded status | condition |
| --- | --- |
| 401, 403 | unauthenticated |
| 402 | credits exhausted |
| 429 | throttled |
| 400, 404, 413, 422 | invalid request |

Three members of the vocabulary are reachable ONLY through this lane, which is
what the governing decision meant by admitting a distinction that at least one
lane can make. The usage member is emitted here because the wire names an
exhausted usage allowance in its own right, where the ACP lane must collapse the
same situation into throttled. The budget member is emitted here because the
wire names a session budget, which is a ceiling the caller set. The unreachable
member is emitted here because three variants name a connection or stream
failure; no ACP discriminator says anything about reachability at all.

A correction to the record the plan was written against, found by regenerating
the schema rather than trusting a list: the installed app-server declares
SIXTEEN variants, not the nine previously written down. Two further categorical
variants and three further object variants exist - a thread rollback failure, a
sandbox failure, two more response-stream failures, and a retry-limit variant.
All five would have fallen through unmapped.

A second correction matters more, because it changes what this lane can honestly
claim. The type that separates a rate-limit refusal from a credits or usage
depletion does NOT appear on the error path at all; it hangs off the account
rate-limit snapshot, a channel this repository does not subscribe to. So the
categorical vocabulary here has no rate member, and the only honest route to
throttled on this lane is a forwarded 429 on one of the object variants. The
lane still separates usage exhaustion from throttling - just through two
different fields rather than two sibling variants.

Cross-checked directly against the regenerated schema: sixteen variants
declared, sixteen mapped, nothing unmapped and nothing mapped that the schema
does not declare. The resolvers were additionally exercised over both shapes,
the status refinement, an unrecognised variant, an unrecognised status, a
non-string key, and a turn error with no discriminator at all.

Verified with `ruff format`, `ruff check src`, and whole-tree `ty check` (clean).

## Notes

Server-side statuses are deliberately absent from the status table, so a 500 or
503 falls back to the variant's own condition or to the floor. The lane names
overload explicitly when it means it, and inferring overload from a 5xx would put
a wait-and-retry remedy in front of a client on evidence the wire never gave.
The cost is that a genuinely transient upstream fault reports as unknown; the
lane's own retry hint, attached two Steps from here, is the honest carrier for
that and is why inferring it was not necessary.

The policy-refusal variant maps to the invalid-request member, which is a
judgement. No member describes a policy decision, and the alternative was the
floor; the invalid member was chosen because its remedy - change the request - is
the one that actually applies. A reader who expects that member to mean a
malformed request will find this entry surprising.

The two local-machinery variants, a failed thread rollback and a sandbox
failure, map to the floor rather than to any provider condition. They are the
app-server's own failures and say nothing about the provider, so any other
member would be a statement about a system that was not involved.

One typing wrinkle is recorded because it recurs in this codebase: narrowing an
untyped payload with an isinstance check against the bare dict type leaves the
key type uninhabited, so subscripting it is rejected. The object-variant lookup
therefore builds a string-keyed view first. That also settled the ordering
question for free - the declared table is iterated rather than the payload, so a
malformed frame carrying several keys resolves the same way every time.

The schema was generated into a scratch directory and is not committed, matching
how the research treated it. It is regenerable in one command from the installed
binary, and the coverage two Steps from here regenerates it rather than reading a
checked-in copy that could drift from what executes.
