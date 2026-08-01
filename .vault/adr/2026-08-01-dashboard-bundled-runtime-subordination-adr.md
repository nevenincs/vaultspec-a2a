---
tags:
  - "#adr"
  - "#dashboard-bundled-runtime"
date: '2026-08-01'
related:
  - "[[2026-07-24-dashboard-bundled-runtime-adr]]"
  - "[[2026-07-21-capsule-install-layout-adr]]"
  - '[[2026-08-01-dashboard-bundled-runtime-consumer-record-correction-reference]]'
supersedes:
  - '2026-07-24-dashboard-bundled-runtime-adr'
modified: '2026-08-01'
body_schema: 'body-v1'
---
# `dashboard-bundled-runtime` adr: `the dashboard is the authority; a2a supplies what it requires` | (**status:** `accepted`)

## Problem Statement

This repository decided on 2026-07-24 that it is a dashboard-bundled runtime
rather than an installable product, and retired the capsule apparatus on the
stated ground that it served no consumer and that the dashboard did not want to
interpret this repository's internal layout.

That ground was asserted here, about a consumer, without the consumer's
agreement. The consuming project's decision record says the opposite and still
does: five of its records covering product provisioning, distribution trust,
generation authority, provisioning authority and archive materialization are all
accepted, and all of them depend on the capsule. Its own plan carries an open,
unticked step to reconcile its release-set contract against this repository's
record — the reconciliation that would have caught the disagreement was never
performed by either side.

The result is two accepted decision records that contradict each other across a
repository boundary, with retirement work already under way on the strength of
the wrong one. A decision is needed about which record governs, not about which
implementation is nicer.

## Considerations

- The consuming project is the product; this repository is a runtime it embeds.
  Consumption is one-directional and there is no other consumer.
- A supplier cannot establish, on its own authority, that its consumer does not
  need something the consumer's accepted records require.
- The disagreement is invisible from either repository's source: both sides are
  internally consistent, and only reading the other side's decisions reveals it.
- Retirement is destructive and asymmetric. Removing a required surface breaks a
  consumer immediately; keeping an unused one costs maintenance.

## Considered options

- **The consuming project's records bind; this repository supplies what they
  require — chosen.** Matches the actual dependency direction and leaves the
  authority with the side that owns the product surface.
- **This repository's 2026-07-24 record stands — rejected.** It rests on a claim
  about the consumer that the consumer contradicts, so its premise fails
  regardless of the merits of the design it proposes.
- **Leave both records accepted and reconcile per change — rejected.** That is
  the state that produced this conflict, and it defers the same decision to
  whoever next touches the boundary, with less context than is available now.

## Constraints

- The consuming project's requirements are read-only inputs here. Where they name
  an entrypoint, a manifest or a layout, this repository conforms rather than
  negotiating in code.
- The 2026-07-24 record cannot simply be deleted: work has already been committed
  against it, including removal of a standalone protocol entrypoint. Superseding
  it records why the direction reversed and prevents the same conclusion being
  rederived from source alone.
- Conformance must be verified against the consumer's records, not inferred from
  its test fixtures. A fixture naming an entrypoint is evidence of intent, not a
  specification, and at least one such fixture currently names entrypoints that
  do not exist here.

## Implementation

The 2026-07-24 record is superseded by this one. The capsule apparatus and its
manifest are retained as a supplied surface rather than retired, and the
retirement work in flight against them is stopped.

Conformance is then established in one direction: read the consuming project's
accepted records, enumerate what they require this repository to provide, and
supply exactly that. Where the consumer names an entrypoint this repository does
not expose, the entrypoint is added here; the consumer is not edited to match
what this repository happens to have.

The manifest gains a producer. Its absence is what allowed both sides to drift
undetected — a declared contract that nothing emits cannot disagree with reality
loudly enough to be noticed.

## Rationale

The deciding fact is the dependency direction, and it is not a matter of taste.
This repository is consumed by the other; nothing consumes it independently. A
supplier that unilaterally withdraws a surface its only consumer's accepted
records require is not simplifying, it is breaking the product it exists to
serve.

The 2026-07-24 record fails on its own premise rather than on its reasoning. Its
argument is sound if the capsule serves no consumer; the consumer's records say
it does. That is why this supersedes rather than merely amends: the conclusion
does not survive the correction to its input.

## Consequences

The capsule surface stays and acquires an owner, which costs maintenance this
repository had already decided to stop paying. That cost is now known to be the
price of a requirement rather than the residue of an abandoned design.

Work already committed against the superseded record must be re-examined,
specifically the removal of the standalone protocol entrypoint. Some of it may be
correct on independent grounds; none of it can be justified by the superseded
record any longer.

The wider pathway this opens is that cross-repository decisions need a
reconciliation step that actually runs. Both projects had one written down and
neither performed it, and every consequence here followed from that omission
rather than from any individual technical judgement.
