---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:cba160cf97b58aa1b417e69dd0bb5c2282c891c3026666bcec5cd14deb7d9910'
step_id: 'S26'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Bind the condition to the node retry classifier

## Scope

- `src/vaultspec_a2a/graph/compiler.py`

## Description

- Import the closed condition vocabulary into the compiler.
- Declare the retryable-condition set with the reasoning for every admission and
  every exclusion recorded on the declaration itself.
- Add a condition reader that resolves the member a failure carries, or nothing.
- Add a per-exception verdict helper that answers from the condition first and
  falls through to the existing transient-type tuple only when no condition was
  resolved.
- Route both branches of the worker retry predicate - the direct exception and
  the wrapper's chained cause - through that helper.

## Outcome

The node retry policy now fires for a provider fault. It already existed, was
already attached to every worker, supervisor, researcher, synthesist, writer and
reviewer node, and already carried exponential backoff; it simply never matched,
because the predicate tested Python types and no provider exception was in the
transient tuple. A 429 or a 502 was a one-shot terminal failure by omission
rather than by decision.

Retryability is now a consequence of the resolved condition. Three members are
admitted, and they share the property that the provider refused BEFORE doing any
work, so another attempt costs a request and nothing else:

- Throttled - the wire states a rate refusal, and waiting is the remedy it names.
  This is exactly what the configured backoff does.
- Provider overloaded - reserved by the vocabulary for a discriminator that names
  overload specifically, so it is a stated "not now" rather than an inferred one.
- Network unreachable - admitted for consistency with the type axis, which
  already retries the stdlib connection errors describing the same fault.
  Excluding it would have made the two axes contradict each other on one fact: a
  bare connection refusal retried, while the identical failure typed by a lane
  did not. The member is reached only when no provider answer arrived - a
  forwarded HTTP status outranks it at the mapper - so nothing was consumed
  upstream, and a genuinely misconfigured endpoint costs two extra attempts
  before failing with the same condition it would have failed with anyway.

Five members are excluded by decision rather than by omission. Unauthenticated,
credits exhausted and budget exhausted each need a credential, a payment or a
raised ceiling, and a retry supplies none of them - it only burns quota or money.
Invalid request means the same request cannot succeed as sent. Usage exhausted
clears only when an allowance window rolls over, which no bounded backoff
outlives, so it stays excluded even though it is the near neighbour of a member
that is admitted. Unknown is the floor, reached when the wire said nothing:
retrying an unclassified failure three times with backoff turns one unexplained
failure into a slow one.

That last exclusion carries a visible asymmetry worth stating plainly. The ACP
lane cannot separate a short-term rate refusal from an exhausted usage window and
maps both to the throttled member, so on that lane an exhausted window will be
retried while the same condition on the Codex lane will not. This is the hard
information limit the vocabulary documents rather than a defect here, and the
cost of the wrong side of it is two extra refused requests.

Composition ordering was a real decision. The condition axis answers first and
outranks the type axis, because a resolved condition is the lane's own statement
about what it refused while a type match is an inference from a base class; a
future provider exception subclassing a transient type but resolving to invalid
request must not retry. The ordering also leaves the existing behaviour exactly
where it was: stdlib exceptions carry no condition, so they still reach the type
tuple unchanged, and the never-retry guard still runs outermost on both branches.

The condition is read off the attribute rather than matched against the provider
exception classes. One of those classes is private to its own adapter module, and
importing either would pull a provider implementation into the compiler - the
import cycle the providers package's lazy boundary exists to break. The value's
type is checked, so an unrelated attribute of some other type resolves to nothing
rather than to a member.

Verification: `ruff format` left the file unchanged, `ruff check src` passed,
whole-tree `ty check` reported five diagnostics, all of them pre-existing in
gateway text-bounds and run-start-digest test modules owned by another lane and
none in the graph package. The graph suite passed 306 tests, 2 deselected.

## Notes

Behavioural proof that a retryable condition actually produces repeated attempts
is the following proof Step, not this one. What landed here was verified by
driving the real predicate with a real provider exception whose condition came
from the real lane mapper, in both the bare and the wrapped shape; that is a
predicate-level check and is deliberately not the evidence the Phase closes on.

A collision is visible on this file: the cleanup Phase removes the never-raised
session-error type, which this module names in its never-retry tuple. The tuple
is untouched here, so the removal remains a clean edit against the current text.
