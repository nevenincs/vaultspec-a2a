---
tags:
  - '#plan'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_hash: 'sha256:d8e8862103fa7e229ad26ebb5c5387a4b11a478a08be0398326dcc0baaa4be82'
tier: L3
related:
  - '[[2026-08-05-served-capability-contract-canonical-vocabulary-adr]]'
  - '[[2026-08-05-served-capability-contract-research]]'
---
# `served-capability-contract` plan

## Description

Triages every finding in the feature's gateway contract audit through to
closure. The audit is a LIVING record and this plan grows with it: new findings
are triaged into new Steps appended at the next free identifier, and no existing
identifier is ever renumbered or reused. A Step that turns out to be unnecessary
is retired in place rather than removed and backfilled.

Every Step names the audit finding it closes by its stable `F` number. A Step
carrying no `F` number is either a prerequisite the audit implies without
recording (the value capture in `W03.P05`), a decision the vocabulary record
deferred (`W04.P07`), or a finding that surfaced after its owner reported and
still needs an audit number assigned (`W01.P02.S06`).

The governing decision is the canonical-vocabulary record in `related:`. Note
its deliberate scope limit: it governs a served value's DOMAIN and explicitly
does NOT claim the findings where a correctly typed field carries an untrue
value. `W03` executes that record; `W04` handles what it ruled out of scope, and
opens the separate transition decision those findings need. Closing `W03` must
not be read as closing F17, F20, or F22.

**The breaking and additive split, which sequences this plan more than severity
does.** `W02` is additive and unilateral - it only describes behaviour already
on the wire, so it can land at any time. `W05` is breaking: every Step changes
what a served field MEANS or removes it, the edge contract with the consuming
repository is frozen, and none of it may land unilaterally. `W05.P10`'s F9 Step
is the one most likely to be mishandled: it merely executes an already-ruled
amendment and needs no new decision, but it removes fields the dashboard
consumes today, so "already ruled" must not be read as "safe to land alone".
`W03`'s narrowings are breaking for the same reason and are gated behind the
value capture in `W03.P05`.

**Work in flight, represented rather than specified.** Every Step in `W02.P03`
is already dispatched to another agent and is tracked here only so it can be
taken off the board when its owner reports. Do not re-specify or re-execute
them. Separately, the worker and gateway pairing fix landed as commit
`00a84258` and is not carried as a Step at all.

## Steps

## Wave `W01` - prove and repair the core authoring path

The product's primary function reports success while delivering nothing (audit F16). Nothing else on this plan matters if a completed document run cannot produce an applyable artifact, so this Wave diagnoses before it fixes and closes both halves: the missing proposal and the silent green that hid it.

### Phase `W01.P01` - diagnose before fixing

Two hypotheses must be settled in code before any fix is chosen, because both remedies branch on the answer.

- [ ] `W01.P01.S01` - F16/F7 branch point - confirm in code whether the engine authoring bridge and proposal submission are gated on the preset authoring_capability value, and record the answer before any fix because both remedies depend on it; `src/vaultspec_a2a/worker/graph_lifecycle.py`.
- [ ] `W01.P01.S02` - F22 - diagnose why the flagship research_adr chain stalled with no graph event for over 90s after emitting one proposal, including whether the ingest-stall watchdog kills healthy runs and serves a false reason; `src/vaultspec_a2a/worker/graph_lifecycle.py`.

### Phase `W01.P02` - close the false green

Restore the missing artifact and remove the silent success that concealed it; either alone leaves the next failure looking identical.

- [ ] `W01.P02.S03` - F16 - make the document editor submit its authored output as an engine proposal so the review lane has something to apply; `src/vaultspec_a2a/authoring/submitter.py`.
- [ ] `W01.P02.S04` - F16 safety half - refuse to report a document-authoring run completed with empty degradation when it produced no artifact, the silent green being a separate defect from the missing proposal; `src/vaultspec_a2a/control/run_start_policy.py`.
- [ ] `W01.P02.S05` - F21 - gate authored document content on structural validity before submission so the review lane never receives a document with duplicated sections; `src/vaultspec_a2a/authoring/submitter.py`.
- [ ] `W01.P02.S06` - Restore the review lane end to end so an approved proposal becomes a file on disk, and assign this an audit finding number when its owner reports the evidence; `src/vaultspec_a2a/authoring/submitter.py`.

## Wave `W02` - additive contract corrections

Findings whose remedy only ADDS description of behaviour that already exists on the wire. These are unilateral on this side of the frozen edge and need no cross-repository coordination, so they may land in any order and in parallel with every other Wave.

### Phase `W02.P03` - corrections in flight

Work already dispatched to other agents, represented here for tracking only. Do not re-specify or re-execute; close each Step when its owner reports.

- [ ] `W02.P03.S07` - F1 correction half IN FLIGHT with agent contract-audit - correct the stale streaming route and the false claim that legacy api routes remain; `docs/a2a-edge-conformance-verb-mapping.md`.
- [ ] `W02.P03.S08` - F14 IN FLIGHT with agent contract-audit - correct the module docstring that claims three topology types where four are dispatched; `src/vaultspec_a2a/graph/compiler.py`.
- [ ] `W02.P03.S09` - F3 IN FLIGHT with agent contract-audit - declare an HTTPBearer security scheme, apply it to the versioned and admin surfaces, drop the hand-rolled authorization parameter and declare 401 responses; `src/vaultspec_a2a/api/app.py`.
- [ ] `W02.P03.S10` - F1 guide half IN FLIGHT with agent contract-audit - publish a client-facing API guide covering auth, discovery and the run lifecycle; `docs/index.rst`.

### Phase `W02.P04` - residual additive findings

Mechanical contract corrections with no owner yet, each independent of the others.

- [ ] `W02.P04.S11` - F10 - add a discriminator to the four-way run-start response union, or split it by route, and document the reservation lifecycle; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W02.P04.S12` - F11 - rename the five underscore-prefixed snapshot models that leak into the published contract and break code generation; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W02.P04.S13` - F13 - serve topology structure on the preset so a frontend can render what a preset will do rather than only its name; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W02.P04.S14` - F15 - route startup failures through the structured logger before exit, populate the process registry log path consistently and reap the stale duplicate port records; `src/vaultspec_a2a/lifecycle`.
- [ ] `W02.P04.S15` - F15 unowned gap - decide and record whether every error is guaranteed to reach the structured log, which no document in the corpus currently guarantees; `docs/operations.rst`.
- [ ] `W02.P04.S16` - Document the OpenAPI artifact regeneration command, which exists only inside the test file that enforces it; `docs/development.rst`.

## Wave `W03` - canonical vocabulary

Executes the canonical-vocabulary decision across the served surface: one declaration per concept, emit sites deriving rather than restating, and every narrowing subset-proved against live payloads before it lands. Depends on W01 only for the capability field, whose remedy branches on W01's gating verification.

### Phase `W03.P05` - prove the value sets

Every narrowing is a breaking change unless the live value set is provably contained in the proposed enumeration; the capture comes first and gates the rest of the Wave.

- [ ] `W03.P05.S17` - Capture the value set each candidate vocabulary actually serves from live payloads and prove containment in its proposed enumeration, which gates every narrowing in this Wave; `src/vaultspec_a2a/api/schemas/gateway.py`.

### Phase `W03.P06` - declare and derive

Give each served vocabulary one owning declaration and make every emit site derive from it.

- [ ] `W03.P06.S18` - F23 shape one - serve the TopologyType enumeration that already exists in code instead of a bare string, and reconcile provider_id with the typed Provider enumeration served beside it; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W03.P06.S19` - F23 shape two - declare owning enumerations for the vocabularies that have none, covering origin, repair_status, execution_readiness, provider_condition, worker_status, semantic_status, semantic_phase, replay_status and the degraded_reasons members; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W03.P06.S20` - F7 - correct the document editor authoring_capability and populate supported_capabilities across presets, gated on the S01 verification because the remedy branches on it; `src/vaultspec_a2a/team/team_config.py`.
- [ ] `W03.P06.S21` - Enforce import-from-owner for served vocabularies so no surface redeclares or re-exports one, keeping the two distinct AdmissionState concepts separate rather than merged; `src/vaultspec_a2a/api/schemas/gateway.py`.

## Wave `W04` - truthful run projection and the live interaction surface

Findings where a correctly typed field still carries an untrue value, plus the streaming and interaction surface the audit could not exercise live. These are state and transition defects that the vocabulary decision explicitly rules OUT of scope, so this Wave opens the transition contract they need before fixing them piecemeal.

### Phase `W04.P07` - rule the transition contract

The vocabulary decision governs a value's domain, never whether a written value is true. These findings need a decision on terminal states and the obligation to reach them.

- [ ] `W04.P07.S22` - Author the transition-contract decision the vocabulary record ruled out of scope, defining terminal state sets, the writer obliged to reach them and reconciliation for states that never do; `.vault/adr`.

### Phase `W04.P08` - repair the run projection

Fix the projections that serve untrue values on completed and failed runs.

- [ ] `W04.P08.S23` - F17 - advance tool-call status to a terminal value and populate locations and content, so a completed run stops showing perpetually pending operations; `src/vaultspec_a2a/api/event_adapter.py`.
- [ ] `W04.P08.S24` - F18 and F8 - scope the agents projection to the run topology so a one-worker pipeline stops reporting an eight-agent roster, and back the team-status active runs with the same projection the runs listing uses; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W04.P08.S25` - F20 - define what reconciling means, how long it may persist and how a run leaves it, then provide the recovery path a stranded run currently lacks; `src/vaultspec_a2a/control/run_discovery_service.py`.
- [ ] `W04.P08.S26` - F22 - stop serving healthy on every structured health field of a failed run, so a frontend gating on machine-readable fields is not forced to parse prose; `src/vaultspec_a2a/api/routes/gateway.py`.

### Phase `W04.P09` - drive and specify the live surface

The audit could not exercise this surface. It must be driven live before it can be documented honestly, and it carries a known defect to fix while there.

- [ ] `W04.P09.S27` - Drive the streaming and interaction surface live and specify it - event taxonomy, frame schema, reconnect protocol and terminal semantics - across the stream, history, messages and both respond routes, and fix F19 where last_sequence is zero on a completed run; `src/vaultspec_a2a/api/routes/gateway.py`.

## Wave `W05` - breaking semantics requiring dashboard coordination

Findings that change what a served field MEANS, or remove it. The edge contract is frozen, so every Step here lands in lockstep with the consuming repository and none may be taken unilaterally - including the one that merely executes an already-ruled amendment.

### Phase `W05.P10` - coordinate the breaking set

Each Step changes what a served field means and requires agreement with the consuming repository before it lands.

- [ ] `W05.P10.S28` - F2 BREAKING - either retire the eligible flag and profiles from the preset listing consistently with the catalog amendment, or redefine eligible as runnable-given-a-valid-selection and scope each reason to the preset it applies to; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W05.P10.S29` - F4 BREAKING - separate product presets from certification fixtures on the served surface by a declared classification rather than a name prefix, so a frontend can request product-only; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W05.P10.S30` - F5 BREAKING - reconcile eligible_providers with the catalog admission predicate so the two discovery surfaces cannot disagree about which providers are usable; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W05.P10.S31` - F6 BREAKING - rule whether an unreachable authoring backend degrades the service, then define the readiness vocabulary and stop serving a worker check that reports ok beside a disconnected worker; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W05.P10.S32` - F9 BREAKING but ALREADY RULED - remove the empty roles and assignments from run-status per the catalog amendment, which needs no new decision yet still removes fields the dashboard consumes today; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W05.P10.S33` - F12 BREAKING - make workspace_root consistent between the two sibling discovery routes, either by requiring it or by disclosing that no workspace resolved; `src/vaultspec_a2a/api/routes/gateway.py`.

## Parallelization

Waves are sequenced by default, but this plan deliberately relaxes that in one
direction: `W02` is additive and unilateral and may run concurrently with every
other Wave, including its own in-flight Phase. `W01` gates nothing structurally
but should lead on priority - it is the only Wave addressing a defect that
makes the product report success while delivering nothing.

Two real dependencies exist and are not negotiable. `W03.P06`'s capability Step
is gated on `W01.P01.S01`, because the remedy branches on whether the authoring
path is gated on that value. Every narrowing in `W03.P06` is gated on
`W03.P05`, because a narrowing without a proven value set is an unverified
breaking change.

`W05` is internally parallel - its Steps touch different fields - but each
requires its own agreement with the consuming repository, so throughput is
bounded by coordination rather than by engineering.

## Verification

The plan is complete when every Step is closed AND every finding in the feature
audit is either closed by a Step or explicitly owned elsewhere with that
ownership recorded in the audit.

Per-Step, closure requires the finding's remedy verified against the surface
that carried the defect - for a served-contract finding, a live payload showing
the corrected value, not a passing unit test alone. Three Steps carry a stricter
bar. `W01.P01.S01` closes only on a code-read answer, never on the correlation
that motivated it. `W03.P05` closes only on a captured value set with proven
containment. `W04.P09` closes only on a live subscription, because the audit
records that surface as unexercised and it cannot be documented honestly from
the specification alone.

No Step in `W05`, and no narrowing in `W03.P06`, may be marked closed on the
strength of a change landed in this repository alone.
