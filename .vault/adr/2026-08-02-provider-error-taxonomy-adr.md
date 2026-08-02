---
tags:
  - '#adr'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0776fb2bc5e7929d8b6a345d70109cbcd98a01719ce1ea9e50b5492180939e72'
related:
  - "[[2026-08-02-provider-error-taxonomy-research]]"
---

# `provider-error-taxonomy` adr: `typed provider conditions on the failure surface` | (**status:** `accepted`)

## Problem Statement

A failed run tells a client nothing about why it failed. Eight provider
conditions - unreachable, overloaded, unauthenticated, throttled, out of credits,
past a spend floor, inside an exhausted usage window, and genuinely unknown -
each demand a different user action, and all eight currently render identically.

A decision is needed now because the dashboard is being wired to this surface
under its own accepted records, and because `2026-08-02-provider-error-taxonomy-research`
establishes that the failure is not an absent vocabulary but a destroyed one:
every served lane already puts a machine-readable discriminator on the wire, one
of which is already parsed into a Python attribute with zero readers. Without a
decision the next consumer will do what the existing web-grounding test already
does - substring-match prose - and that pattern will set.

The record must also settle a boundary the research surfaced and the original
question did not anticipate: some runs terminate with no reason at all, so a
condition vocabulary alone would leave the worst cases still blank.

## Considerations

- Classification is discarded, not missing: the worker-node wrapper and ingest's
  non-`__cause__`-walking summarizer are the two loss points, per
  `2026-08-02-provider-error-taxonomy-research`.
- Only three lanes are served (CLAUDE, CODEX, ZAI); typing unserved lanes is
  speculative work, per the same research and the standing
  `no-unproven-providers-in-served-profiles` rule.
- The lanes do not carry equal information: Codex separates throttling from
  usage-window exhaustion, the ACP lane cannot. Any uniform eight-member
  vocabulary would force one lane to assert a distinction its wire lacks.
- `recoverable` currently classifies which `except` branch caught the exception,
  not retryability, and is live-only on a droppable channel.
- A dead typed vocabulary (`ErrorSeverity`, `RecoveryAction`) already exists with
  zero production readers; adding a second without addressing the first repeats
  the failure.
- The repo's established disclosure discipline - authoritative state on
  `run-status`, relay frames as non-authoritative nudges - is set by
  `clarifications-are-typed-interrupts` and applies unchanged here.
- The consumer validates a failure reason at 500 bytes; the emitting frame is
  capped at 512 characters.
- The dashboard's accepted records impose no taxonomy but do ask for a scripted
  failure scenario, per `2026-08-02-provider-error-taxonomy-research`.

## Considered options

- **Central string classification.** One function sniffing the flattened reason
  for known substrings. Rejected: it is exactly what the live web-grounding test
  does today, it re-derives a structured value the lane already held, and it
  breaks whenever a vendor edits prose.
- **Adopt the existing `ErrorSeverity` / `RecoveryAction` pair.** Rejected: they
  model severity and remediation, not condition - the wrong axis - and they have
  lain unread since introduction, so adopting them answers neither what the
  condition is nor why this vocabulary would fare differently.
- **Forward the provider's raw error payload to the client.** Rejected:
  unbounded, vendor-shaped, and a disclosure hazard; it also pushes
  classification onto every consumer, which is how two clients come to disagree.
- **Per-lane mapping into one closed condition enum (chosen).** Each lane owns a
  pure function from its own wire discriminator to a shared vocabulary; the
  vocabulary admits only distinctions at least one served lane can actually make,
  and a lane that cannot make a distinction maps to the coarser member rather
  than guessing.

## Constraints

- The ACP lane cannot separate throttling from usage-window exhaustion: the CLI's
  429 handler assigns one kind to both and consumes the distinguishing header
  internally. This is a hard information limit, not an implementation gap.
- A reset time is available on Codex and only opportunistically on the ACP lane,
  via a pre-failure notification that is emitted conditionally and may never
  arrive. No design may promise a reset time uniformly.
- ZAI's discriminator fidelity is UNVERIFIED and is the likeliest route to a
  false claim: the adapter derives some kinds by matching English vendor prose
  that an Anthropic-compatible endpoint need not reproduce. ZAI typing is
  therefore gated on live evidence rather than assumed from the shared adapter.
- Parent-feature stability is adequate: the frame catalog, the durable
  `failure_reason` column, and `run-status` projection are all shipped and
  exercised; this work extends them rather than depending on anything in flight.
- The condition vocabulary is a wire contract consumed by a second repository, so
  it is additive-only once accepted.

## Implementation

Five layers, ordered so each de-risks the next.

**Preserve the cause.** The worker-node wrapper stops discarding the provider
exception's identity, and the ingest summarizer walks the `__cause__` chain.
These two changes alone restore a truthful free-text reason, and they are
prerequisites for anything typed - without them there is nothing left at the
reporting site to classify.

**Classify at the lane.** A new domain module declares a closed `ProviderCondition`
vocabulary. Each served lane owns a pure, separately testable mapping from its own
wire discriminator into it: the ACP lane from `data.errorKind` plus the JSON-RPC
code, the Codex lane from `codexErrorInfo` and its HTTP-status-bearing variants.
Mapping is total - an unrecognized discriminator yields the unknown member, never
an exception and never a silent drop. The vocabulary admits only distinctions a
served lane can make; where the ACP lane cannot separate throttling from window
exhaustion it maps to the coarser throttled member, and the finer member is
emitted only by a lane whose wire carries it.

**Carry the condition durably.** The condition becomes the `error` frame's `code`
- reusing the existing catalogued field rather than widening the frame - and is
additionally persisted alongside the failure reason and projected onto
`run-status`, because a reloading client must recover it and the relay is
droppable. This follows the disclosure discipline already set for clarifications:
`run-status` is authoritative, the frame is a nudge.

**Make recoverability a consequence, not a guess.** `recoverable` is derived from
the condition rather than from the catch site, and the same classification binds
the existing node retry policy so that the conditions which should retry actually
do, under the backoff already configured. Where a lane supplies a retry hint
directly, that hint is preferred over inference.

**Close the blank terminals.** Every path that drives a run to a failed state
records a condition; the unknown member is the floor, and a null condition on a
failed run becomes an invariant violation rather than a normal outcome. This
covers the dispatch-level failures that today write nothing, and the executor
paths that emit no terminal at all. The reconnect replay frame carries the
condition, and terminal frames are made non-droppable relative to token chunks.

The dead `ErrorSeverity` and `RecoveryAction` enums, and the never-raised
`ProviderSessionError`, are removed in the same campaign rather than left beside
the new vocabulary.

Frontend work follows in the same campaign and consumes only the typed condition:
the panel maps each member to its distinct user action and never parses the
reason string.

## Rationale

The knockout is that per-lane mapping is the only option that does not
manufacture information. The research establishes that the discriminators already
cross the wire and are discarded; recovering them is strictly cheaper than
inferring them, and unlike string classification it cannot silently break when a
vendor rewords a message. Central classification and raw-payload forwarding both
fail the same test from opposite directions - one re-derives what was already
known, the other refuses to derive anything and pushes the problem to every
consumer.

Admitting only distinctions a served lane can make is what keeps the vocabulary
honest. The alternative - a tidy eight-member enum mirroring the original
question - would require the ACP lane to assert a throttled-versus-exhausted
distinction its wire does not carry, which is precisely the class of false claim
the `no-unproven-providers-in-served-profiles` rule exists to prevent. Coarser on
one lane and finer on another is the truthful shape.

Deriving `recoverable` from the condition rather than the catch site is what
turns the taxonomy from a label into a contract: it makes the flag mean the same
thing to the retry policy and to the client, and it fixes the current inversion
where the two canonically retryable conditions are the ones reported permanent.

Closing the blank terminals is included rather than deferred because the feature's
value is conditional on it. A taxonomy that classifies only the runs which already
report something would leave the worst failures - the ones where a client sees a
bare `failed`, or a thread stuck running forever - exactly as opaque as before.

## Consequences

The frontend gains a stable, machine-readable reason to branch on, and can offer
the right remediation per condition instead of one generic failure. Retry becomes
correct for transient provider faults, which should visibly reduce spurious
failures on overload. Diagnosis stops depending on worker logs, because the
provider's own message survives to the client.

Honestly framed, the gains are uneven across lanes. Codex users get the finest
classification, including credit balances and reset times; ACP users get six
conditions and a coarser throttled member with no reliable reset time. That
asymmetry is visible in the product, and the panel must not imply a precision the
lane lacks.

The wire contract now spans two repositories, so vocabulary changes become
coordinated releases rather than local edits; the additive-only constraint is the
cost of that. Removing the dead enums touches the public thread package surface.
And the blank-terminal work reaches into dispatch, executor, and streaming paths
well beyond the provider adapters, which is real blast radius: the campaign is
larger than the original question implied, and the plan must sequence the
cause-preservation and blank-terminal layers first so that value lands even if
later layers slip.

The ZAI gate is a live dependency: until a real error is captured on that lane,
its typing is provisional and the plan must carry the probe as an early,
blocking step rather than an assumption.
