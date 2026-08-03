---
tags:
  - '#audit'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:f450c67bf1893895b85c6e4f6c21f749fd06916422ad108a3bb9e921ef510053'
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

### verification-brief-substituted-a-hand-copied-list-for-the-declared-gate | CORRECTED, medium | The gate was never hidden; it was simply not invoked

CORRECTION. This entry previously claimed the module-size gate was invisible to
an engine phase because it lives in the frontend package. That was WRONG, and the
truth is less comfortable. The repository's gate table declares the engine lint
target as formatting, a workspace-wide lint with warnings fatal, AND the module
scanner. Invoking the declared engine gate has always run all three. Nothing was
hidden.

What actually happened is that the verification brief hand-listed language-native
commands instead of naming the declared entry point. That is the same failure the
repository's own continuous-integration configuration warns about in its header:
a gate reimplemented elsewhere cannot be verified to match the gate it claims to
mirror, and calling the same entry point is the only thing that can. The brief
reimplemented the gate in prose and reproduced the outcome exactly.

The remedy is therefore NOT to add the missing command to a list - that would
repeat the mistake with a longer list. It is that a phase runs the declared gate
entry point, and a brief names that entry point rather than enumerating what it
happens to contain.

A second consequence surfaced with the correction: the hand-copied lint was also
WEAKER than the declared one, scoped to a single crate's library target with
warnings non-fatal, where the declared gate is workspace-wide across all targets
with warnings fatal. A hand-copied gate does not merely risk omitting a check; it
silently relaxes the ones it does include.

### declared-engine-test-gate-has-not-run-on-this-host | medium | Every engine result on this machine is a scoped subset of the declared gate

The declared engine test gate is a workspace-wide run. It was deliberately not
run here, because building the integration binaries exhausts the linker on this
platform, and every engine number reported during this campaign is therefore a
scoped subset. The subset is real evidence and it is green; it is simply not the
gate. Recorded so that no one later reads those counts as the declared gate
having passed. It runs on the project's own continuous-integration runners.

### frontend-has-no-engine-free-test-tier | medium | Every frontend test spawns a live engine, so no one can verify frontend work independently

The frontend test configuration applies the live-engine global setup to the WHOLE
suite, so even a single component test spawns a real engine process. There is no
unit tier to fall back to. The setup does attach instead of spawning when an
existing service is named, but the configuration also states that all files share
one engine with mutable state - so attaching points every test at whatever
engine is offered and mutates it.

The practical consequence is a verification monopoly: frontend work can only be
verified by whoever currently holds an engine, and a second party cannot
independently confirm it without either fighting for ports or mutating the first
party's stack. That is a structural obstacle to review, not a preference.

### no-git-hooks-installed-in-this-worktree | low | Every commit in this campaign was ungated locally

The consuming repository declares pre-commit hooks, and none are installed in the
worktree this campaign worked in - only the shipped samples are present. Every
commit made here, by every party, went in without local gating, and continuous
integration is the first thing that will see any of it.

Deliberately NOT remedied mid-campaign. Installing them now would begin stamping
another writer's in-flight documents on every commit, which is a known deadlock
in this tree, and it is a repository configuration decision that belongs to the
owner rather than to a phase executing inside it.

### vocabulary-is-declared-in-three-places | RESOLVED | All three copies are now gated, and the third gate found a trap the first two did not

RESOLVED. The third leg is gated: the consuming frontend now reads the engine's
declaration off disk - a plain relative read, no environment variable, no skip
branch, running in the ordinary tier - and requires equality member for member
and in order.

That gate found a hazard neither of the first two had to face, and it is worth
recording as a general lesson. The engine's contract module states the nine
spellings TWICE: once as the declaration, and again as the literal its own
pinning test holds the declaration against. A reader anchored on "an array of
string literals" could bind to the second copy, and would then go green on
precisely the drift that matters - one of the two edited and the other not. The
gate anchors on the DECLARATION specifically, and drives a synthetic source where
the two disagree to prove the anchoring holds.

The generalisable point: when a source file states the same fact twice, a
source-reading gate must name WHICH statement is authoritative, or it can end up
comparing a copy against itself.

Both failure directions were drilled by mutating the consuming side and reading
the real message, and non-vacuity was established four ways rather than asserted,
including printing the members actually extracted from the real file.

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

### catalog-read-budget-is-shorter-than-cold-discovery | RESOLVED, was high | The consumer timed out listing providers on a cold workspace, and a retry hid it

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

RESOLVED. The catalog verb now carries its own discovery budget on the consuming
side, sized against the measured cold cost AND against the emitting side's own
per-read ceiling, so the consumer no longer gives up while the emitter is still
inside one bounded read. The premise was confirmed from the emitting side's
source rather than from one host's timings: lanes are enumerated concurrently by
spawning each lane's tooling, and the five-minute catalog cache matches the
observed sixteen-seconds-then-nothing exactly. The emitting side needed no change
- its behaviour was correct and the consumer was wrong about the cost.

Two design points worth keeping. The shared fast-read budget was deliberately not
widened, because it also governs verbs that genuinely are fast reads, and the
guarding test asserts those remain equal to each other so that the tempting wrong
fix fails. And a hung lane is still not covered, by design and by comment: a
browser-facing verb cannot wait on a startup ceiling measured in minutes.

Consequence for this campaign specifically: a run cannot be started through the
consumer without a catalog selection, so on a cold workspace the product cannot
reach a provider lane at all - and therefore cannot surface a provider condition,
which is the capability this campaign exists to deliver.

The margin also makes this worse than the numbers suggest. 16.3 against 15 is not
a comfortable overrun to tune away; a slower host, a colder cache, or one more
served lane widens it, while a warm host hides it entirely.

### consuming-surface-independently-read-and-the-central-property-holds | VERIFIED CLEAN | No presentation path depends on the opaque prose

An adversarial read by a party who did not write the surface, commissioned
because that repository's test tier has no engine-free mode and the author's own
run was therefore the only execution evidence in existence. Two load-bearing
claims were then re-verified a third time, independently:

- The ONLY production read of the prose field on that surface renders it and
  branches on nothing. Every comparison, match and membership operator was
  searched against that field and its relay sibling; none exists. One unrelated
  subsystem does branch on a similarly-named field, and predates this work.
- The render coverage is asserted against the vocabulary itself by equality
  INCLUDING ORDER, not by sampling, so a member cannot ship unrendered. Remedies
  are asserted pairwise distinct.

The coverage test also survives the specific attack it exists to stop. A
hypothetical prose check for the word "credit" resolves the WRONG member on at
least two rows, because one member's copy says "out of credit" while another
member's says "no credit left". The contradicting reasons are real contradictions
rather than decorative, so a future prose check fails rather than passes.

All three remedy pairs that must not collapse are genuinely distinct: payment
versus a self-imposed ceiling, waiting versus a plan change, the path to the
provider versus the provider answering that it is over capacity. Two transient
members share a recovery CLAUSE while differing in diagnosis, which is a decision
rather than an accident and is recorded as one.

### consuming-authoring-record-does-not-model-the-classification | low | A second surface's wire type omits both the reason and the classification

The consuming repository's authoring run record mirrors the engine's run record
but models neither the human reason nor the classification. Pre-existing for the
reason - it never modelled it - and widened by this campaign, which added a
second unmodelled field. NOT on the delivered path: the refusal presentation
reads the orchestration status, not this record. The consequence is that the
authoring surface cannot see a classification, not that anything shipped is
broken.

### consuming-settlement-payload-cannot-report-a-classification | low, latent | The browser could not report a classification if it settled a failed run

The settlement payload type lacks the field. Latent rather than live: the hook
that would send it has no component caller and is driven only by a test, so
nothing in the product settles runs from the browser today. Worth closing when
something does.

### truncation-of-provider-prose-is-unexercised-and-splits-surrogate-pairs | low | A reason ending in an emoji truncates to a replacement character

The refusal detail truncates at a character ceiling that no test reaches, since
every fixture reason is short - so a broken truncation would pass. The cut is by
UTF-16 code unit, so a reason ending mid-surrogate-pair renders a replacement
character. Provider prose is plausible emoji-carrying text, which is what lifts
this above theoretical.

### floor-member-applies-to-records-predating-the-field | low, confirm-not-defect | Historical failed runs now render as reporting no cause

Absence is correctly kept distinct from the floor member at the adapter, and
deliberately becomes the floor at the view for a failed run. The consequence is
that every failed run recorded BEFORE the field existed now presents as having
reported no cause. That reading is honest - those runs genuinely have no recorded
classification - and is recorded here as intended rather than as a defect, so a
later reader does not mistake it for a migration gap.

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
