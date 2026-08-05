---
tags:
  - '#adr'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:acffc0bb9701fb2a06fc857e4b194ea76e299a8bf4c3fff9ba57e023e47cf9bb'
related:
  - "[[2026-08-05-served-capability-contract-gateway-contract-audit]]"
---

# `served-capability-contract` adr: `one declaration per served vocabulary` | (**status:** `proposed`)

## Problem Statement

A served vocabulary - a field whose values come from a fixed set - is declared
inconsistently across this contract. Roughly 32 are closed enumerations on the
wire; about 15 of the same kind are bare strings, undefined booleans, or
unconstrained string arrays. In two cases one concept is served both ways in the
same payload. The measured split and its three distinct shapes are recorded as
F23 in the audit this record cites.

A decision is needed because the split has a measurable cost to the consumer
this contract exists to serve. The audit records a frontend author who can
generate exhaustive, checked handling for the typed half of the surface and must
hand-maintain string literals for the rest, with nothing on the wire marking
which half a given field is in. A four-member enumeration exists in code and is
served as a bare string (audit F23); one vocabulary's legal values exist only in
a source comment; and the audit's F35 records a boolean that is permanently
false on one surface and true on another for the same preset - a value a client
cannot act on in either direction.

An earlier draft of this paragraph also claimed two fields carry the same
concept under different typings. That example - a provider identifier served
beside a typed provider enumeration - was MEASURED AND DOES NOT HOLD: one is the
closed set of lanes this build can run, the other is an identifier a past run
recorded, and they diverge over time by design. The correction is recorded in
audit F23. It removes an example, not the decision: the split this record
governs is measured across the surface, not inferred from that one pair.

An earlier draft of this record motivated the decision with the audit's F16, on
the hypothesis that an undeclared `authoring_capability` string was gating the
authoring path and silently disabling the product's primary function. That
hypothesis is REFUTED: F16's mechanism is F24, a bridged tool call auto-denied
at a provider permission rung, and the capability string correlated only because
it tracks which topology submits by which mechanism. The correction is recorded
here rather than removed because it bounds this decision honestly - typing was
never what was broken in F16, and this record should not be credited with
fixing it.

This record rules how served vocabularies are declared and derived. It does not
rule the capability taxonomy, the remediation order, or any individual finding's
fix.

## Considerations

- The contract is NOT uniformly stringly-typed; roughly 32 closed enumerations
  already exist and work (audit F23). The decision is about closing a split, not
  about introducing typing.
- Two of the three shapes in F23 are typing defects; the third is not. A
  properly typed `ToolCallStatus` did not prevent F17, and a properly typed
  `ThreadStatus` containing `reconciling` did not prevent F20. Typing constrains
  a value's domain and never obliges a writer to advance it.
- `AdmissionState` is declared twice for two genuinely distinct concepts (audit
  F23). `2026-08-04-canonical-homes-adr` establishes that DISTINCT verdicts are
  load-bearing and that merging them destroys properties they were written to
  hold.
- A rehoming that leaves a re-export behind has not removed the second
  declaration site (`2026-08-04-canonical-homes-adr`).
- The consuming repository renders these fields under a frozen edge contract, so
  a change to a served value's type or domain is not unilateral.
- Policy constants that gate refusal must remain code-truth and must not become
  derivable from workspace-overridable data
  (`2026-07-16-authoring-contract-adr`, binding decision (b)).
- A field a client cannot distinguish from a confident emptiness is removed
  rather than served empty (`2026-08-02-provider-model-catalog-adr`, 2026-08-03
  amendment).

## Considered options

**Own each vocabulary as one canonical type in a core module, derive every emit
site from it, and let the served schema carry the enumeration.** Chosen. Closes
shapes one and two of F23 with a rule that is mechanically checkable.

**Type everything that currently looks like a vocabulary.** Rejected: it treats
F17, F20, and F22 as typing defects when the evidence shows they occurred on
correctly typed fields, and would mark them closed while they still occur.

**Document the legal values in prose or code comments.** Rejected: this is the
status quo for `origin`, whose values live in a source comment a client cannot
read and a compiler cannot check.

**One declaration per NAME.** Rejected: it would merge the two distinct
`AdmissionState` concepts, which the canonical-homes record forbids on exactly
this ground.

**Serve every vocabulary as an open string and publish a value registry
alongside.** Rejected: it keeps generated clients unable to exhaustively handle
the surface, which is the frontend cost F23 records.

## Constraints

- Adding an enumeration to a field the dashboard already consumes NARROWS its
  domain, which is a breaking change if any served value falls outside the
  declared set. Every migration must first prove the live value set is a subset
  of the proposed enumeration, against real served payloads, before the type is
  narrowed.
- The frozen edge contract means a narrowing lands in lockstep with the
  consuming repository, never ahead of it.
- Parent stability is good: the enumerations this record generalizes from are
  accepted, shipped, and covered by an artifact-equality test. The risk is
  entirely in migration, not in the mechanism.
- The `authoring_capability` field is mis-valued on a shipped preset and its
  correction is an ordinary application of V1. It is NOT a blocked dependency:
  the hypothesis that the authoring path was gated on it is refuted (audit F24),
  so correcting the value fixes a declaration, not a behaviour.

## Implementation

**V1 - One declaration per CONCEPT, in a core module.** Every served vocabulary
is declared exactly once, as a closed string enumeration, in the core module
that owns the concept. Distinct concepts stay distinct even when they share a
name; the identity test is what the value MEANS, not what it is called. Where
two concepts genuinely collide by name, they are disambiguated at the
declaration, not merged.

**V2 - Emit sites derive; they never restate.** A layer that serves a
vocabulary value derives it from the owning type. Restating a literal at an emit
site, redeclaring a parallel type per surface, or annotating the field as a bare
string when an owning type exists is a defect, not a style preference. The
served schema carries the enumeration, so the wire and the code agree by
construction rather than by review.

**V3 - Consumers import from the owning module only.** No local alias, no
per-surface copy. A rehoming that leaves a re-export behind has not removed the
second declaration site.

REFINEMENT, from executing this clause. The rule bites on a second DECLARATION
SITE, never on a name mention. A package facade that re-exports its own owning
module's type is the import surface this repository's facade mandate REQUIRES,
and a name-based check flags it and invites exactly the wrong fix - deleting the
facade export to satisfy a rule that was never about it. Enforcement is written
against redeclaration. The distinction is the same one V1 draws between a
concept and a name, applied to the check rather than to the type.

**V4 - What is enum-worthy.** A field is a vocabulary, and must be declared,
when its values are drawn from a set the SERVICE fixes and a client is expected
to branch on. A field stays free-form when its content originates outside the
service or is meant for a human to read rather than a program to match - a
failure reason, a display name, a reviewer note, an identifier minted elsewhere.
The test is branching: if a client is expected to compare the value against a
known constant, it is a vocabulary. An unconstrained string array whose members
are drawn from a fixed set is a vocabulary in an array, not an exception.

**V5 - Booleans that carry a reason are vocabularies.** A boolean cannot express
WHY, so a field whose false case a client must explain is not a boolean. Where
the audit records an undefined boolean serving as a verdict, the remedy is a
declared vocabulary carrying the state, not a comment explaining the flag.

**V8 - One key answering two questions is resolved by SEPARATING the
derivations, never by reconciling their answers.** Where two consumers read the
same key to answer different questions, deriving each from what it actually asks
will make them DISAGREE. That disagreement is the correct outcome and producing
it is the point; prior agreement was the symptom, not the health - both were
reading a key that answered neither question properly.

The hazard this clause exists to prevent is downstream and human: a later reader
sees two derivations disagree, assumes one is broken, and aligns them - which
re-conflates the questions and re-introduces the defect the separation removed.
Each site therefore documents WHICH QUESTION IT ANSWERS and that the other
deliberately answers a different one. The documentation obligation is heaviest
at the site a debugger lands on first, because that is where the urge to make
them match is strongest.

Worked instance: whether a preset AUTHORS DOCUMENTS and whether it uses the
DIRECT WORKER-TO-ENGINE SUBMITTER are different questions. The solo document
lane authors through the bridged tool, so the true answers differ - and that
mechanism difference is precisely why one topology emitted a proposal and the
other did not.

**V6 - Migration is subset-proved and lockstepped.** Narrowing an existing field
requires, in order: a capture of the values that surface actually serves; proof
that the captured set is contained in the proposed enumeration; then the
narrowing, landed with the consuming repository. A value found outside the
proposed set is a finding to resolve, never a member to quietly admit.

**V7 - Scope limit, ruled explicitly so it is not mistaken for an omission.**
This record governs a value's DOMAIN. It does not govern whether a written value
is TRUE, and it does not oblige any writer to advance a state. The audit's F17,
F20, and F22 occurred on correctly typed fields and are out of scope here; they
need a transition contract - a defined terminal set per lifecycle, a writer
obliged to reach it, and a reconciliation for states that never do. That is a
separate decision and must not be folded into this one, or those findings will
be marked closed while still occurring.

**Out of scope.** The capability taxonomy and what each capability means; the
remediation sequence and priority, which belong to the plan; individual field
remedies, which this record constrains but does not choose.

## Rationale

The knockout criterion is that the rule must be mechanically checkable and must
not destroy distinctions the codebase was careful to draw. Deriving at the emit
site from a single owning declaration satisfies both: divergence becomes
impossible rather than merely discouraged, and the concept-not-name identity
test preserves the two `AdmissionState` meanings the canonical-homes record
protects.

The scope limit in V7 is the part of this record most worth defending. The
tempting version of this decision treats every wrong value in the audit as a
typing failure and claims all of F16, F17, F20, and F22. The evidence refuses
it: `ToolCallStatus` is exactly the closed, terminal-valued enumeration such a
ruling would prescribe, and 15 of its instances still sat at `pending` on a
finished run. Typing that field harder changes nothing. Ruling the limit
explicitly is what stops the remediation from reporting success against findings
it did not address - which is, precisely, the failure mode the audit is about.

Generalizing from the enumerations already in the contract rather than inventing
a mechanism keeps the migration risk where it belongs: in proving each live
value set, not in the pattern.

## Consequences

- Gains: a generated client can handle the whole served surface exhaustively
  rather than half of it; a wrong vocabulary value becomes a type error at the
  emit site instead of a silent wire value; the split the audit measured has one
  rule to close it.
- Difficulties: every narrowing is a breaking change requiring a value capture
  and cross-repository lockstep, so this lands as many small coordinated changes
  rather than one sweep. The `authoring_capability` remedy is additionally
  blocked on reading the gating logic.
- Costs accepted: two similarly-named types stay separate and must be
  disambiguated, which reads as duplication to anyone who has not read the
  canonical-homes record; and V7 leaves three high-severity findings explicitly
  unaddressed by this decision, which is honest rather than comfortable.
- Pitfall to watch: V6's subset proof is the whole safety of the migration, and
  it is the step most likely to be skipped because the value set "obviously"
  matches. A capture that was never taken cannot prove containment.
- Opens: the transition contract V7 defers; and, once vocabularies are declared,
  serving topology structure and capability sets becomes a matter of publishing
  types that already exist rather than inventing a discovery surface.

## Open questions

- ~~**Is the authoring path gated on `authoring_capability`?**~~ SETTLED and
  answered NO. The audit's F24 established the mechanism as a bridged tool call
  auto-denied at a provider permission rung, with the capability string
  correlating only because it tracks which topology submits by which mechanism.
  The capability field is still mis-valued and still needs correcting, but that
  is now an ordinary instance of this record's V1 rather than a blocked
  dependency.
- **Which vocabularies can be narrowed without a wire break?** Settled per field
  by V6's value capture against real served payloads; unknown until taken.
- **Does the transition contract V7 defers belong to this repository alone?**
  Terminal states are observed by the consuming repository, so the obligation
  may be cross-repository. Settled when that decision is opened.
