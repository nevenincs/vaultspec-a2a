---
tags:
  - '#adr'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:3921b1c0d7614df78ce6e0913e9cc369487d73209ecf2efdb6fc5447024569f0'
related:
  - "[[2026-08-05-served-capability-contract-research]]"
---

# `served-capability-contract` adr: `the capability a preset serves, and who routes to it` | (**status:** `proposed`)

## Problem Statement

A frontend relays a user's natural-language ask to this backend and must choose
what to run. The served contract does not carry enough to choose with: the
capability declaration is keyed to the topology type, four topologies partition
twenty presets, and one shipped document-authoring lane is consequently served
as a coding preset with no capabilities at all
(`2026-08-05-served-capability-contract-research`). Two of the four asks the
owner named have no capability of their shape anywhere in the system, and the
served list mixes certification scaffolding into the product surface under a
flag a frontend cannot use.

A decision is needed now because each of those is a question about what a
SERVED FIELD MEANS, and the consuming repository renders those fields under a
frozen edge contract. They cannot be fixed one at a time by whoever next touches
the code without a ruling on the taxonomy they all express. Three related
questions are decided here and nowhere else: what the named capabilities ARE,
what DERIVES them, and which of the owner's asks this backend commits to
serving.

Routing itself is explicitly NOT among them. The consuming repository already
ruled it, and this record's job is to make that ruling workable rather than to
revisit it.

## Considerations

- The capability declaration is served truth the dashboard renders, and it must
  extend in lockstep with what the topology delivers (the agent-flow record's
  Constraints, dashboard repository). The lockstep obligation is already
  breached on a shipped preset (research, capability-key finding).
- Roles discriminate the served preset set where topologies do not, and map to
  document kinds one-to-one (research, same finding).
- Policy constants that gate run-start refusal and token coverage are
  code-truth, never derived from workspace-overridable data
  (`2026-07-16-authoring-contract-adr`, binding decision (b)). Any capability
  mechanism must not become a back door around that.
- Every served capability terminates in a ledgered document proposal; there is
  no answer-shaped output anywhere on the wire (research, output-shape finding).
- Workspace scope is universal and correct for a project-status ask; feature
  scope is narrow and already confined to document-authoring presets (research,
  scope finding; `2026-08-03-current-project-binding-adr`).
- Schema conformance and agent-side self-validation of authored documents are
  already ruled and delivered (`2026-07-14-adr-authoring-orchestration-adr`,
  2026-07-15 refinement). Corpus-level semantic conflict is not ruled anywhere
  (research, obligations finding).
- A field a client cannot distinguish from a confident emptiness is removed
  rather than served empty (`2026-08-02-provider-model-catalog-adr`, 2026-08-03
  amendment).

## Considered options

**Key the capability to the preset's declared worker ROLES, against a code-truth
role-to-capability map.** Chosen. Distinguishes all five served document kinds,
cannot be widened by a workspace-local preset, and needs no new vocabulary.

**Keep the topology key and add a topology per capability.** Rejected: it forces
a new graph topology for every product capability, and the case that broke the
key is a document-authoring role deliberately placed on the `pipeline` topology
by the consuming repository's own D2 - a topology split would relitigate that.

**Free-text `supported_capabilities` list in each preset TOML.** Rejected: same
expressiveness, but a workspace-local preset could assert a capability nothing
backs, reintroducing exactly the workspace-mutable policy
`2026-07-16-authoring-contract-adr` refused.

**Serve an intent-routing endpoint that classifies the natural-language ask.**
Rejected as out of this repository's authority: the consuming repository's D1
rules routing to be explicit preset selection at the composer, with no layer
inferring topology from prompt text.

**Express answer-shaped asks as document proposals anyway.** Rejected: it forces
a persisted artifact into existence for an ephemeral question and makes every
summary a review-lane obligation.

**Filter certification presets by widening the existing name-prefix flag.**
Rejected: a prefix convention is what already failed, and six scaffolding
presets currently evade it. Classification must be declared, not inferred from
an identifier.

## Constraints

- The cross-repo edge is frozen. Everything ruled here that changes a RESPONSE
  BODY (the capability values, the preset filter) is unilateral on this side and
  lands without negotiation; everything that adds an OUTPUT SHAPE is a contract
  event requiring lockstep with the consuming repository and must not ship
  ahead of it.
- Parent stability is good on the load-bearing dependencies: the authoring
  contract leaf, the phase machine, the phase-gate pattern and the verdict
  subscriber are all accepted and test-covered. The zero-internal-import
  invariant of the contract leaf is a review-enforced property that any change
  landing this decision must preserve.
- The two capabilities this record admits in principle but does not serve
  depend on facts not yet established: an answer-shaped output has no wire
  today, and no preset harness carries a repository-evidence tool, whose
  admissibility under the run-bound project pin
  (`2026-08-03-current-project-binding-adr`) has not been traced.
- No verdict in the grounding rests on a completed run. The capability
  declarations ruled here are declarations about what a preset IS, not proof
  that it completes; a capability may be declared only for a lane whose
  completion has been proven live, on the same standard the served-profile
  admission rule applies to providers.

## Implementation

**R1 - The capability taxonomy.** This backend serves a closed, named set of
capabilities. Four are ADMITTED AND SERVED today: `research_document`,
`architecture_decision`, `plan_document`, and `document_edit`. Two are ADMITTED
IN PRINCIPLE AND NOT SERVED: `document_summary` (prose about an existing
document set) and `project_status` (prose about a repository's state). A
capability not on this list is not served, and adding one is an amendment to
this record.

**R2 - Capabilities derive from declared roles, not from topologies.** The
served capability set of a preset is computed from the roles its declared
workers hold, against a code-truth role-to-capability map homed alongside the
existing role and topology contract: `researcher` and `synthesist` yield
`research_document`, `adr-author` yields `architecture_decision`, `plan-author`
yields `plan_document`, `doc-editor` yields `document_edit`. The topology-keyed
derivation is replaced, not supplemented. The coarse `authoring_capability`
field follows the same source: a preset yields `document_authoring` when its
role set yields any document capability.

This does NOT reopen `2026-07-16-authoring-contract-adr`. The security
predicates it homed - which roles author, which topologies are
document-authoring, what run-start refuses on - are untouched and remain the
gate. R2 adds a product-discovery projection over the same code-truth
vocabulary. A preset composes roles the contract already knows; it cannot invent
one, so no workspace file can widen a capability claim.

**R3 - `/v1/presets` IS the routing surface, and routing is the frontend's.**
This backend serves no intent classifier and no capability endpoint. Its
obligation under the consuming repository's D1 is discharged by making the
preset listing rich enough to choose from - which is R2's whole purpose. A
future capability endpoint would be a second declaration of the same fact and is
refused on that ground.

**R4 - The scope model.** Every run is workspace-bound and none is unscoped;
workspace binding is not a limitation to route around but the correct scope for
a project-status ask, which is a question about a project. Feature binding stays
confined to document-authoring capabilities and MUST NOT be widened to the
answer-shaped ones: `document_summary` takes a document or feature target as
run input, and `project_status` takes none beyond the workspace.

**R5 - Answer-shaped capabilities need an output shape before they are served.**
`document_summary` and `project_status` are admitted as real capabilities and
are blocked on one missing decision: where a non-document answer lands on the
wire. The target shape ruled here is the run's own terminal output, disclosed on
the existing run-status and stream surfaces - NOT a document proposal, and not a
new endpoint. Because that is a contract event, neither capability may be
declared on a served preset until the consuming repository's side lands.

**R6 - Authoring obligations, split three ways.** Structural and schema validity
belongs to the ENGINE, which is the applier and the only layer where a document
lands. Agent-side conformance self-validation belongs to the RUN and is already
ruled and delivered (`2026-07-14-adr-authoring-orchestration-adr`, 2026-07-15
refinement); this record adds nothing to it. Corpus-level semantic conflict
belongs to A2A, because it owns the phase machine and holds the grounding
server, and neither of the other two layers can reach the corpus.

a2a discharges it as a GATE INPUT, not as a capability and not as an automatic
verdict: a document-authoring phase that produces a decision or a plan must
carry a prior-art recall over the existing corpus, typed and accumulated on the
same in-run evidence channel the research findings already use, and disclosed
into the phase-gate payload the human reviews. A phase whose prior-art recall is
absent is a refusal at submit time, on the same discipline as the submitter's
existing refusal of a phase whose upstream document has not materialized.
Whether a machine may also VERDICT a conflict is left open below; the
DISCLOSURE obligation does not wait on it.

**R7 - Single-lane versus team.** The discriminator is verifiability of the
output, not difficulty of the ask. A capability whose output is a claim about
the world that the user cannot cheaply check - research, decision, plan -
requires the multi-role chain with its inner review loop and human gates. A
capability whose output the user can check at a glance against a source already
in front of them - `document_edit`, `document_summary` - is single-lane.
`project_status` is single-lane WITH mandatory evidence citation: its claims are
individually checkable, so a reviewer role would add cost without adding
verification the locators do not already give.

This rules how a2a SHAPES the preset it offers. It does not touch who SELECTS
one, which the consuming repository's D1 rules and this record honours.

**R8 - Certification presets are not product capability.** A preset carries a
declared classification - product or certification - and the product preset
listing excludes certification presets by default. The classification is
declared in the preset, never inferred from its identifier; the existing
name-prefix flag is retired rather than widened, and is removed from the served
response rather than served with a value a client cannot act on.

**Out of scope.** Coding capabilities in the panel's preset list (the consuming
repository's D7 excludes coder lanes and requires a future decision to widen
them); free-form per-run model or provider override (deferred by its D3);
natural-language intent inference in any layer (refused by its D1 and by R3);
and any capability that writes to the filesystem directly, which the authoring
path forecloses.

## Rationale

The knockout criterion is expressiveness against the actual served set. The
topology key does not merely risk a future divergence - it is wrong today on a
preset the consuming repository itself mandated, and it is wrong in the
direction that matters, understating a document lane as a coding one to the
client that renders the field as truth. Any option that keeps the topology as
the key has to explain why a document-authoring role on a pipeline topology
should not be a document capability, and the only available answer is an
implementation accident.

Roles win over a free-text declaration on the same driver that decided
`2026-07-16-authoring-contract-adr`: a claim that gates what a client offers a
user must not be assertable by a file the user can edit. Deriving from roles
keeps the entire capability vocabulary inside code the contract leaf already
owns, so a workspace preset can compose capabilities but never mint one.

The split in R6 follows from where each obligation can actually be discharged
rather than from where it would be convenient. Schema validity is the engine's
because that is where the document lands; corpus conflict is a2a's because the
recall tool is mounted in a2a's runs and nowhere else. Stopping at disclosure
rather than verdict is the same discipline the provider-admission rule applies:
a semantic judgement with no demonstrated accuracy on this corpus is not
promoted to a blocking gate on the strength of expecting it to work.

R5 refuses the tempting shortcut. Serving a summary as a document proposal would
let both missing capabilities ship this week and would permanently miscast an
ephemeral answer as a durable artifact, putting every "summarize this" through a
human review lane built for documents that persist.

## Consequences

- Gains: a frontend can distinguish a document lane from a coding lane and a
  research chain from a solo editor without hardcoding preset ids; the shipped
  misdeclaration of the solo document lane is closed; the capability vocabulary
  has one home and one derivation; two capabilities the product needs are named
  and their real blockers stated rather than left as absence.
- Difficulties: R2 changes the value of a field the consuming repository already
  renders, so a preset that reported `coding` will begin reporting
  `document_authoring` - a widening, not a break, but one the consuming side
  should be told about rather than discover. R8 changes which presets appear in
  a listing, which will look like a regression to any test that counts them.
- The certification presets do not disappear; they remain discoverable to the
  acceptance harness that needs them, and only the product listing narrows.
- Pitfall: R2's role-to-capability map is a second thing that must extend when a
  role is added, and it lives next to the contract that gates security. A
  reviewer must keep the two distinguishable - widening the map is a product
  change, widening the role set is a policy change - or the map becomes a soft
  path into the hard contract.
- Opens: an answer-shaped run output would serve more than these two
  capabilities; a `vault_curation` capability composes the same primitives the
  phase machine already has; and the prior-art recall channel, once typed, is
  the natural input to any later conflict verdict.

## Open questions

- **Can corpus conflict be machine-verdicted, or only disclosed?** R6 rules the
  disclosure obligation and deliberately stops there. Settled by running a
  labelled set of known-conflicting and known-independent ADR pairs from this
  corpus through the recall-and-judge loop and measuring it; a verdict gate is
  admissible only on evidence of that kind.
- **Where does an answer-shaped output land on the wire?** R5 names the target
  shape but the field, its bounds and its disclosure on run-status are a
  cross-repo contract event. Settled by a joint decision with the consuming
  repository under the edge's mutual-reference discipline.
- **Can a `project_status` run source repository evidence at all?** No preset
  harness carries a git or repository-status tool, and whether one is admissible
  under the run-bound project pin was not traced. Settled by a registry decision
  plus a live probe proving the pin holds for such a tool.
- **Does `document_summary` need a feature-scoped read surface the doc-editor
  lane deliberately lacks?** A feature summary spans a document set, which the
  solo editing mandate forbids widening to. Settled by deciding whether the
  summary lane is a new preset with a corpus-read mandate or a widened
  doc-editor, once R5 unblocks either.
- **Should `served-presets-are-the-router` be codified as a rule here?** It is
  the one codification candidate of its record not present in this repository's
  rule directory, while its two siblings were codified. Settled by the owner:
  this record honours the ruling either way, but the asymmetry looks like an
  oversight rather than a decision.
