---
tags:
  - '#audit'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:5bb91be6f481bb11f75e8083e8613cae8a1b3f6b78a2cabfe553870308360859'
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

### live-refusal-reason-names-a-retry-step | RESOLVED | Fixed, and it was concealing a second defect

Closed on 2026-08-03 and re-verified live on all three armed refusals. The cause
was not in the wording: the turn loop raised on the FIRST error notification it
saw, including ones where the lane had said it was about to try again, so it
cancelled a retry the provider was already performing and reported the attempt's
own wording as the outcome. The flag stating that intent was already parsed and
carried; it was simply never consulted.

Waiting for the terminal frame then exposed the defect underneath. It produced a
truthful message and a WORSE condition - a live `402` dropped from
`credits_exhausted` to the floor member - because the app-server's error union
splits in two: a few variants are objects forwarding the provider's HTTP status,
and the rest are bare strings with no payload. A refusal routinely ends on a
payload-free one. The original code had been reading the right status off the
wrong frame and getting the right answer by luck.

Both are kept now: message from the frame that ended the turn, condition falling
back to what an earlier attempt actually forwarded, and only as a fallback so a
self-classifying terminal frame is never overridden. Checked against the schema
the installed binary generates: all sixteen declared variants are mapped and none
is stale, so the floor member was correct behaviour on incomplete evidence rather
than a missing table entry - which is why the fix retains evidence instead of
adding a mapping.

A behaviour worth recording separately: the endpoint logged NINE provider attempts
on the fixed run where it had logged one before. The lane's own retry schedule had
been cancelled by the first notice for as long as this code has existed.

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

### verification-brief-omitted-a-gate-that-crosses-package-boundaries | medium | A module-size gate scanning one language lives in another language's package, so a single-surface phase never runs it

Found by one executing agent flagging a red gate in another's lane, not by either
phase's own verification. The consuming repository's module-size gate is a script
in the frontend package, and it scans the engine's source as well at a hard
ceiling with nothing grandfathered. An engine-only phase that runs only the
language-native commands therefore cannot see it, and one landed a file over the
ceiling.

The defect is in the brief rather than in the execution: the verification list
named the language-native commands and stopped. Recorded here because the general
shape recurs - a gate whose home package does not match the surface it governs is
invisible to anyone reasoning about verification by surface.

### vocabulary-is-declared-in-three-places | low | Two of the three copies are gated against each other; the third was not

The closed vocabulary now exists as an enum here, a constant in the consuming
engine's shared contract module, and a constant in the consuming frontend. The
first two are gated in both directions by a source-reading agreement assertion.
The frontend copy was ungated and could drift from both; closing that leg is
assigned. Worth stating plainly that three declarations is the cost of two
process boundaries, not an accident to be refactored away - each side needs the
list at its own compile time.

### oversize-modules-outside-this-campaign | low | Two provider modules exceed the repository's module ceiling, neither touched by this work

Surfaced while checking this campaign's own files for compliance after the gate
finding above. Both predate this work and belong to other lanes; recorded so the
observation is not lost, not claimed as this campaign's to fix.

### catalog-read-budget-is-shorter-than-cold-discovery | high | The consumer times out listing providers on a cold workspace, and a retry hides it

Found by driving the cross-repository path by hand rather than by reading code.
The consuming engine budgets the provider-catalog verb with its FAST READ ceiling
of fifteen seconds, on the stated reasoning that a listing read is quick. This
side does not treat it as a listing read: a cold catalog enumerates lanes by
actually consulting the provider tooling. Measured on this host, a cold
enumeration took 16.3 seconds and the engine returned a timeout; the immediately
following call returned in well under a second from cache.

The two sides therefore disagree about what this verb COSTS, not about what it
returns. That disagreement is worse than a plain timeout because the failure is
self-concealing: the attempt that fails also warms the cache, so a human who
retries sees it work and a test that calls twice never sees it at all. The first
provider listing on any cold workspace is the one that fails, which is exactly
the moment a person is trying to choose a lane.

Consequence for this campaign specifically: a run cannot be started through the
consumer without a catalog selection, so on a cold workspace the product cannot
reach a provider lane at all - and therefore cannot surface a provider condition,
which is the capability this campaign exists to deliver.

The margin also makes this worse than the numbers suggest. 16.3 against 15 is not
a comfortable overrun to tune away; a slower host, a colder cache, or one more
served lane widens it, while a warm host hides it entirely.

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
