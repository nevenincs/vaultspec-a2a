---
tags:
  - '#audit'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:ed0bbb29be687fe5f50f35cf73faf57f7c9f25eceb23e895fe232e9907c98c78'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
  - "[[2026-08-02-provider-error-taxonomy-adr]]"
---
# `provider-error-taxonomy` audit: `provider error taxonomy rolling audit`

## Scope

The campaign's rolling finding log. It covers the whole condition chain - the
per-lane resolvers, the worker wrapper and its cause preservation, the stash and
settle path, the durable column and its projection onto run-status, the retry
classifier bound to the condition, and the served admission surface that decides
which lanes can produce one at all.

Opened late, on the day the live refusal proof closed. Findings raised earlier in
the campaign were recorded on their own Step Records; from here they accumulate
here so that debt discovered but not yet owned stays visible in one place rather
than being distributed across sixty execution records.

## Findings

### live-refusal-reason-names-a-retry-step | medium | On non-429 refusals the human-readable failure reason names a retry step rather than the refusal

Observed live on the codex lane against a real refusing endpoint. A `401` and a
`402` both produced the CORRECT typed condition (`unauthenticated` and
`credits_exhausted`), but the free-text reason carried on the same run-status
response read `Reconnecting... 1/5`. Only the `429` path carried its status into
the message. The typed value is right in all three cases, which is the thesis of
this campaign working exactly as intended - classification does not depend on the
prose - but a client that renders the reason verbatim beside the condition will
show a correct badge next to a misleading sentence. The defect is in what the
lane's protocol error is holding at the moment the wrapper reads it, not in the
resolver.

### mock-failure-tool-advertises-a-failure-it-does-not-produce | medium | A harness tool declares a failure mode it cannot actually raise

Carried forward from earlier in the campaign. The advertised behaviour and the
implemented behaviour disagree, so anything reasoning from the declaration is
reasoning from a claim rather than a capability.

### provider-session-error-is-dead-in-the-never-retry-tuple | low | A never-retry entry names an exception the path can no longer raise

The tuple still lists a session error type that the current lane code does not
produce, so the entry protects nothing. Harmless today and misleading tomorrow:
it reads as evidence that the case was considered and handled.

### backoff-is-shorter-than-a-real-rate-limit-reset | medium | The retry schedule cannot outlast a genuine throttle window

`throttled` is classified retryable, but the schedule exhausts well inside the
reset interval a real provider advertises. The run therefore fails with a
correct, retryable condition after retrying in a window where success was never
possible. Correct classification, wasted attempts.

### infrastructure-axis-has-no-vocabulary | low | Conditions describe the provider, so an infrastructure fault has nowhere honest to land

The vocabulary is closed around what a provider says. A fault on the path to the
provider that is not a transport failure has no member that fits and degrades to
the floor. Recorded as a gap in reach, not as a bug in the mapping.

### admission-table-is-hand-edited-and-nothing-runtime-writes-it | low | Lane admission cannot be earned by running a turn, by design

Not a defect, recorded so it is not rediscovered as one. The served-lane
admission declaration is a deny-by-default literal keyed by provider and
execution mode. Running a successful turn on a lane does not admit it; a human
attests the evidence and edits the declaration. Any future work that finds itself
wanting to edit that table to make a test pass has misread the rule.

## Recommendations

Carry the provider's own refusal text into the reason on the non-429 codex paths,
so the sentence a client renders agrees with the condition beside it. This is a
change to what the wrapper captures, and it must not become a change to how the
condition is derived - the reason is for a human, the discriminator decides.

Bound the retry schedule by what the lane's refusal actually advertises rather
than by a fixed ladder, so a retryable throttle either waits long enough to
succeed or declines to retry at all. Retrying inside a window that cannot succeed
is worse than not retrying, because it delays the truthful terminal.

Remove the dead never-retry entry rather than leaving it as apparent coverage.

The infrastructure-axis gap needs a decision before it needs code: either the
vocabulary grows a member for faults on the path to a provider, or the contract
states plainly that it describes providers only and something else carries
infrastructure. A follow-on decision record should make that choice; it is not
settled here.
