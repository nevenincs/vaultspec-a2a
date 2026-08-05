---
tags:
  - '#adr'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:ca2a4da9cd6c255a5c3944e1268da122b85d72c417fff02405aeab5ef6f66f71'
related:
  - "[[2026-08-05-served-capability-contract-gateway-contract-audit]]"
---

# `served-capability-contract` adr: `terminal states, obligated writers, and fields that must not contradict the run` | (**status:** `proposed`)

## Problem Statement

Served state fields carry values that are well-typed and untrue. A run reports
`completed` having produced nothing, with an empty degradation list. A failed run
reports `healthy` on every structured health field it serves. Fifteen tool calls
sit at `pending` on a finished run, one of them narrated by the model as
rejected. A run sits in a transitional state across a restart of both processes
that could move it, permanently occupying the active-run view. The findings are
F16, F22, F17, and F20.

None of these is a typing defect. `ToolCallStatus` is a closed enumeration with a
genuine terminal set and F17 happened inside it; `ThreadStatus` contains
`reconciling` as a legitimate member and F20 happened inside it. The
canonical-vocabulary record (`2026-08-05-served-capability-contract-canonical-vocabulary-adr`)
governs a value's DOMAIN and ruled these explicitly out of scope, precisely so
they would not be marked closed by work that cannot close them. This record is
the decision that scope limit deferred.

A decision is needed because the frontend gates on exactly these fields. The
audit's through-line is that the prose is honest while the typed surface lies -
and the typed surface is the machine-readable one. Every instance above would
have been caught by an obligation this contract does not currently impose.

## Considerations

- A terminal set with no obligated writer is decoration. F17's calls were
  written once at dispatch and never advanced; nothing was responsible for
  advancing them (audit F17).
- A transitional state needs an owner that can outlive the process that entered
  it. F20's run survived a restart of both the gateway and the worker with no
  path out (audit F20).
- Truthfulness is not the same obligation as terminality. F22's fields were
  terminal and wrong; the run had reached a final state and the health fields
  described a different one (audit F22).
- A diagnostic field can be accurate about its own signal and still mislead. The
  watchdog's message named "the graph" where it observed one stream, and the
  audit's own first correction of F25 wrongly called it false on the strength of
  an adjacent measurement. Both errors are instructive and neither is a lie.
- Fields whose values a human reads are already correct in every case observed;
  only the machine-readable siblings drifted. Any rule must not degrade the
  prose to match the structured fields.
- Domain and declaration questions are already ruled and are not reopened here
  (the canonical-vocabulary record, V1 through V7).
- The consuming repository observes terminal states across the frozen edge, so
  changing when a state is reached, or what is served alongside it, is not
  unilateral.

## Considered options

**Impose four obligations - terminal sets, an obligated writer, reconciliation
for abandoned transitions, and non-contradiction with the run outcome.** Chosen.
Each maps to one observed failure and each is checkable.

**Rule only the terminal sets.** Rejected: it is what the system already has.
`ToolCallStatus` declares its terminal members today and F17 still occurred,
because declaring a destination obliges no one to travel to it.

**Infer health fields from the run status at serialization time.** Rejected as
the primary mechanism: it makes the fields non-independent, so they can no
longer carry information the status does not - a run that completed but degraded
becomes inexpressible. Retained only as the fallback consistency check in T4.

**Have the reader reconcile - let clients treat prose as authoritative.**
Rejected: it inverts the contract, and the prose is not machine-readable. It is
also the workaround posture the owner has forbidden.

**Add a timeout that force-fails anything transitional.** Rejected as a general
rule: F25 is the cautionary case, where an unconditional bound killed work the
run's own configuration sanctioned. Timeouts must be derived from the run, which
is what T3 requires.

## Constraints

- Depends on nothing unbuilt. Every vocabulary this record governs already
  exists and is already typed; the obligations attach to writers that already
  run.
- The reconciliation in T3 needs durable knowledge of which transitional states
  were entered and by whom. The checkpoint and run store already carry the run;
  whether they carry enough to identify an abandoned WRITER has not been
  verified and is an open question below.
- T4 changes what is served alongside a terminal status, which the consuming
  repository parses, so it lands in lockstep per the vocabulary record's V6.
- The audit's own evidence base has a gap that bounds T3: per-event timestamps
  for the run behind F25 could not be recovered, because the database held no
  rows for that thread. A reconciliation design must not assume that history is
  always available.

## Implementation

**T1 - Every state vocabulary declares its terminal partition.** A served
vocabulary whose values describe progress declares, at its single owning
declaration, which members are TERMINAL and which are TRANSITIONAL. The
partition is part of the type, not documentation about it, and it is exhaustive:
every member is one or the other. A value that is neither is a declaration
defect.

**T2 - Every transitional state names the writer obliged to leave it.** For each
transitional member there is exactly one component responsible for advancing it,
and that responsibility is explicit rather than incidental. A transitional state
with no obligated writer may not be declared. This is the clause F17 needed: the
tool-call vocabulary had a terminal set and no one whose job it was to arrive
there.

**T3 - An abandoned transition is reconciled, never left.** When the obliged
writer cannot complete - process death, restart, an unrecoverable error - the
state is moved to a terminal value by a reconciler that does not depend on that
writer's liveness, and the terminal value records that it was reconciled rather
than reached normally. A transitional state that can outlive every process able
to advance it is a defect regardless of how it is typed.

Any bound used to decide abandonment is DERIVED FROM THE RUN, never a flat
global. The run's own declared timeouts are the authority where they exist, and
a global value serves only as a floor for runs that declare none. This is the
generalization of F25's fix, and it is stated as a rule here because the same
mistake is available to every reconciler this clause invites.

**T4 - A structured field must not contradict the run's own outcome.** Where a
served field describes health, degradation, or readiness, its value must be
consistent with the run's terminal status. A failed run may not serve `healthy`
on every health field; a completed run that produced no artifact may not serve
an empty degradation list. The obligation is CONSISTENCY, not derivation: a
field may still carry information the status does not, and a completed-but-
degraded run must remain expressible. What is forbidden is a combination that
asserts two incompatible things at once.

Consistency is enforced where the fields are assembled, not at each writer, so
that a new field cannot be added outside the check. Where a genuine combination
looks contradictory, the resolution is to make the field say what it means -
not to suppress the check.

**T5 - A diagnostic field describes what was observed, not a cause inferred from
it.** A field explaining why something happened names the signal that was
actually measured. The watchdog's message said "no event from the graph" while
observing one specific stream, which reads as "nothing happened in this run" and
misdirected diagnosis for exactly as long as anyone believed it. This clause is
narrower than truthfulness: the message was accurate about its own signal and
still wrong about the system.

**Out of scope.** Which values each vocabulary should contain, and where the
type lives - both ruled by the canonical-vocabulary record. The remediation
order, which belongs to the plan. And whether any specific run SHOULD have
failed: this record governs how state is reported, never what the orchestrator
decides.

## Rationale

The knockout criterion is that each clause must close an observed failure that
typing demonstrably did not. That test is what separates this record from the
tempting single rule "declare terminal states": F17 is the counter-example, a
closed enumeration with a correct terminal set whose members never moved. The
obligation, not the declaration, is the load-bearing part - which is why T2
exists as a separate clause and why T1 alone would be a restatement of the
status quo.

T4 is deliberately CONSISTENCY rather than derivation, and that choice is the
one most likely to be second-guessed. Deriving health from status would close
F22 immediately and would also destroy the only reason those fields exist: a run
that completes while degraded has something to say that its status cannot. A
consistency check keeps the information and forbids the contradiction, at the
cost of having to define compatibility per field.

T3's derived-bound requirement earns its place from F25 rather than from theory.
The instinct when a run hangs is to add a timeout, and F25 is what that instinct
produced: a flat ninety-second bound that killed work a preset had declared safe
for eighteen hundred. Inviting reconcilers without that constraint would
reproduce the defect at every new site.

T5 is the smallest clause and the one the audit itself violated - the first
correction of F25 called the watchdog's message false on the strength of a
measurement of a different channel. A rule that a field must describe its own
observed signal is also a rule about how findings against such fields are
argued.

## Consequences

- Gains: the four findings the vocabulary record could not claim become
  closeable, and closeable by a check rather than by inspection. A frontend can
  gate on the structured surface without cross-checking prose.
- Difficulties: T2 forces an owner to be named for transitions that currently
  have none, which will surface states nobody owns - the useful outcome, and an
  uncomfortable one. T4 requires a per-field compatibility definition, which is
  real design work and cannot be generated mechanically.
- Costs accepted: reconciled terminal values are distinguishable from naturally
  reached ones, so consumers gain a distinction they must now handle; and T4's
  check is a serialization-time cost on a hot read path.
- Pitfall: T3 invites new reconcilers, and a reconciler with a flat global bound
  is F25 rebuilt. The derived-bound clause is the guard, and it is the clause
  most likely to be skipped as an implementation detail.
- Opens: once terminal partitions are declared, the streaming surface can state
  terminal semantics rather than leaving a client to infer them - which is
  currently one of the entries the client guide cannot write.

## Open questions

- **Can an abandoned transition's obliged writer be identified from durable
  state?** T3 requires reconciliation without the writer's liveness, which
  presumes enough is persisted to know a transition was abandoned rather than
  merely slow. The audit records one run whose per-event history was absent
  entirely. Settled by inspecting what the run store and checkpoint actually
  retain for a transitional state, before any reconciler is designed.
- **What is the compatibility relation for each health field?** T4 forbids
  contradiction but the specific incompatible combinations are per-field and are
  not enumerated here. Settled field by field as the vocabularies are declared,
  and the enumeration belongs with each field's declaration rather than in this
  record.
- **Does the reconciled-versus-reached distinction cross the edge?** It changes
  what a terminal status means to a consumer that already reads it. Settled with
  the consuming repository under the mutual-reference discipline; until then, T3
  can record the distinction internally without serving it.
