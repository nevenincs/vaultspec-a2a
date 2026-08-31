---
tags:
  - '#adr'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:114c44e2889cc08ddd64959efea61cf2fcfd7ad2add9127fc37a6cd4499075eb'
related:
  - "[[2026-08-05-served-capability-contract-gateway-contract-audit]]"
---

# `served-capability-contract` adr: `a failure must reach the log before the process does` | (**status:** `proposed`)

## Problem Statement

Nothing in this project's decision corpus guarantees that an error reaches the
structured log. The audit established that absence by searching for it rather
than assuming it (F15), which makes this an unowned gap rather than a defect
against an existing rule.

The gap has teeth. A gateway exhausted its entire port band across ten attempts
and produced a structured log containing zero error lines, because each retry
was silent and the terminal failure reached only stderr as a traceback. Every
one of the 51 error-level records in the sampled log was an export failure to an
absent telemetry collector, so the level carried no information about the
service at all. And the denial that broke document authoring (F24) had no logger
call on its arm whatsoever - it surfaced only because an operator's prompt asked
the model to relay the tool rejection verbatim, which is a safety net that
depends on prompt wording and model compliance.

A decision is needed now because remediation has begun and would otherwise
overstate itself. Commit `2b978a35` fixed three real defects on this path, and
its own framing is the reason this record exists: it makes the guarantee TRUER
but does not ESTABLISH it - one set of call sites was fixed, not a rule. The
operator documentation must not assert a guarantee no record makes, and it
currently has nothing to cite either way.

## Considerations

- The absence was checked, not assumed: no accepted record states this
  guarantee, and the observability record that governs logging LANES is silent
  on completeness (audit F15).
- A level whose historical population is entirely deployment noise conveys
  nothing. Error meant "an unreachable collector" in 51 of 51 sampled cases
  before `2b978a35` demoted them.
- The most consequential swallowed condition in the audit had no logging
  statement at all on its path, so a rule phrased in terms of log LEVELS would
  not have caught it.
- A failure discovered only because a prompt asked a model to repeat it is not
  observability; it is coincidence with a plausible-looking output.
- The boot path is the hardest case: it fails before the machinery that would
  report the failure is necessarily up.
- This is an OPERATOR-facing surface. The served-contract records govern what a
  frontend gates on; nothing here changes a wire field.

## Considered options

**Oblige the failure path, not the log level: every terminal failure emits a
structured record before the process exits, and every swallowed condition emits
one where it is swallowed.** Chosen. It attaches the duty to the code path that
loses the information.

**Guarantee that every raised exception is logged.** Rejected: it drowns the log
in handled control flow and conflates an exception used as a signal with a
failure. It also would not have caught F24, which raised nothing.

**Rely on the process supervisor to capture standard error.** Rejected: it is
what happens today. The traceback exists but sits outside the structured log the
operator is told to read, so the two disagree about whether anything went wrong.

**Fold this into the state-truthfulness record.** Rejected, and the reasoning is
recorded because the shapes genuinely rhyme - both concern an obligation the
code does not carry, and one could argue a single record about things nothing is
responsible for producing. But the subjects differ: that record governs SERVED
STATE a frontend gates on across a frozen contract; this governs an OPERATOR
diagnostic with a different consumer, a different surface, and no wire
implications. Merging on shape similarity rather than subject identity is the
error `2026-08-04-canonical-homes-adr` warns against, and it would widen a
record whose every clause is about the served contract.

**Document the current behaviour in the operations guide instead of ruling.**
Rejected: it is the workaround posture the owner has forbidden, and there is no
stable behaviour to document.

## Constraints

- The boot path constrains the mechanism: a failure before logging is configured
  cannot be logged by the normal route, so either logging configuration precedes
  every failable boot step or the earliest steps carry their own fallback sink.
  Which of the two is an implementation choice, not a decision.
- `2b978a35` fixed the specific call sites this record generalizes from, so the
  motivating evidence is partly historical. That is a strength for the diagnosis
  and a weakness for regression testing: the original conditions no longer
  reproduce, so any test must construct them.
- Nothing here may change what a served field reports. If an operator-facing
  obligation and a served-field obligation ever conflict, the served-contract
  records govern the wire.

## Implementation

**L1 - A terminal failure emits a structured record before the process exits.**
Any path that ends the process abnormally emits a structured, machine-readable
record naming what failed and why, before it exits or re-raises to the top. A
failure that reaches only standard error, or only a traceback, has not been
reported. This settles the question the audit opened: a fatal startup path may
NOT exit without a structured record.

**L2 - A swallowed condition is recorded where it is swallowed.** Where code
declines, denies, retries, falls back, or returns a null in place of a result,
it emits a record at the point of that decision. The obligation attaches to the
SWALLOW, not to an exception, because the conditions that cost the most here
raised nothing: a permission arm answered a request with a rejection and logged
nothing, and a token lookup returned nothing on missing coverage. A retry loop
records each attempt and records exhaustion distinctly, so that "tried and
failed repeatedly" is never indistinguishable from "never ran".

**L3 - Error means the service is failing.** The error level is reserved for
conditions where this service cannot do its job. A dependency absent by
deployment configuration - a collector that is not running, an optional
integration not enabled - is a warning, because it describes the environment
rather than a fault. This gives the level a meaning a reader can act on, which
it did not have when every instance of it was an absent collector.

**L4 - Observability may not depend on a model or a prompt.** A condition is
observable through the service's own instrumentation, never only through text a
model chose to relay. Where the only witness to a failure today is model output,
that is a defect to close, not a channel to rely on. This clause exists because
the audit's most consequential finding was recovered exactly that way, and would
have stayed invisible had the prompt been worded differently.

**L5 - The guarantee is claimed only where it is enforced.** Operator
documentation may state this guarantee only for paths that satisfy L1 and L2. A
blanket claim ahead of enforcement is forbidden - the direct consequence of the
framing that prompted this record: the remediation so far makes the guarantee
truer without establishing it.

**Out of scope.** Log routing, retention, transport, and the lane structure,
which are already governed. Log formatting and field vocabulary. Whether any
particular condition IS a failure - this record governs reporting, not
classification. And every served wire field, which the served-contract records
own.

## Rationale

The knockout criterion is whether a rule would have caught the audit's actual
cases. A level-based or exception-based rule fails that test twice: the
port-band exhaustion logged nothing to raise a level about, and the authoring
denial raised no exception at all. Only an obligation attached to the swallowing
path reaches both, which is why L2 is phrased in terms of what the code DOES
rather than what it throws.

L3 earns its place from a measurement rather than from taste. A level that was
100 percent deployment noise in the sampled log is not merely noisy - it is
unusable as a filter, which is precisely how ten failed boots hid inside a log
that reported 51 errors.

L5 is the clause most likely to feel redundant and is the one the evidence most
directly demands. The remediation that motivated this record was careful to say
it had fixed call sites rather than established a rule; without L5 the
documentation would quietly convert that honesty into a guarantee, and the next
silent failure would be read as impossible rather than as unreported.

The refusal to fold this into the state-truthfulness record is argued in
Considered options rather than assumed, because the two are close enough that an
unexamined merge was the likely default.

## Consequences

- Gains: an operator can trust the structured log as the complete account of
  service failures, and the error level becomes a usable filter. F15 gains an
  owner it did not have.
- Difficulties: L2 is broad by design and will surface many quiet paths, some
  legitimately quiet; distinguishing a deliberate silent fallback from an
  accidental one is judgement that cannot be mechanized, and the first pass will
  over-report.
- Costs accepted: more log volume on retry-heavy paths, and a boot-path
  constraint that either orders logging configuration first or carries a
  fallback sink.
- Pitfall: L5 is easy to breach by accident, because documenting a guarantee is
  cheaper than enforcing one and reads the same to a user.
- Opens: once L1 and L2 hold, a test can assert that a failing path leaves a
  record, which is the first mechanical check this area has ever had.

## Open questions

- **Does logging configuration precede every failable boot step today?** L1's
  boot case depends on it and the current ordering has not been traced. Settled
  by reading the boot sequence; the answer chooses between ordering and a
  fallback sink.
- **Which swallowed conditions are deliberately silent?** L2 will surface paths
  that are quiet on purpose. Settled per path as they surface, with the
  deliberate ones recorded rather than left implicit - an undocumented
  deliberate silence is indistinguishable from the defect.
- **Can the original conditions be reproduced for regression tests?** The
  motivating call sites are fixed, so those failures no longer occur naturally.
  Settled by deciding whether constructed failure injection is worth its weight
  here, which is a testing decision rather than an architectural one.
