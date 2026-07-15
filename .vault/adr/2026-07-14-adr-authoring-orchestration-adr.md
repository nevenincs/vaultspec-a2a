---
tags:
  - '#adr'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-15'
related:
  - "[[2026-07-14-document-authoring-orchestration-audit]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - '[[2026-07-14-adr-authoring-orchestration-research]]'
---
# `adr-authoring-orchestration` adr: `phase-machine topology, document personas, and external-verdict gates for research-to-ADR authoring` | (**status:** `accepted`)

## Problem Statement

The engine must orchestrate agents that research a problem and author an ADR through dashboard proposals - the hardest document-authoring shape and the owner-designated first intent (2026-07-14 scope directive: vault documents only; coding out of scope). The current graph layer cannot express it: no fan-out stage, no generalized per-phase human gate, no path for an out-of-run reviewer verdict to re-enter a run, and the persona set is coding-shaped. Grounding: `2026-07-14-adr-authoring-orchestration-research`.

## Considerations

- Diverge-stage fan-out has no topology today; LangGraph Send is the native primitive (research, fan-out finding).
- Resumed nodes re-run from their start; gates must be deterministic pre-interrupt, and proposal submits are replay-safe via authoring idempotency keys (research, gate finding).
- The engine's review-lane verdict stream exists and is authoritative; only the a2a subscriber is missing (research, outer-loop finding).
- `validation_errors` reducer and `authoring_*_ids` correlation fields already exist in TeamState (research, inner-loop finding).
- Owner directive retires coder/code-reviewer personas from this mission (research, persona finding).

## Considered options

- **Extend star with prompt-driven phases.** Rejected: phase discipline as LLM convention is the audited failure mode - gates must be graph structure, not supervisor prose.
- **One-off research_adr hardcoded chain.** Rejected: the curation family and later plan-authoring need the same fan-out/gate/subscriber primitives; a bespoke chain forks them.
- **Phase-machine topology built from reusable primitives (chosen):** a new topology type composed of a Send-based fan-out stage, a synthesis stage with an inner review loop, and a generalized phase-gate node, plus a run-external verdict subscriber. Primitives are individually testable and reused by curation.
- **Poll the engine from inside a running node instead of interrupt-and-park.** Rejected: burns a live node/task for the full human latency window, defeats checkpoint durability, and dies with the process; interrupt+resume is the framework-supported park.

## Constraints

- Depends on the W03 authoring client and tool bridge (landed: S15-S19) and on the engine's events/recovery surfaces (verified live, but the subscriber's cursor persistence across gateway restarts must be designed - recovery snapshot is the documented fallback).
- LangGraph Send is new to this codebase (no in-repo precedent; framework-documented, `langgraph==1.2.2` installed).
- The ADR-021 drain-pattern regression and compile-time-only `vault_index` must be fixed first or the phase machine cannot observe its own outputs.
- Plan-Step ID allocation across the edge remains open (RS-1(a) in the gap audit) - out of scope here; this ADR covers research and ADR documents only.

## Implementation

Five layers, all in the graph/team/control packages:

- **State**: a `research_findings` append-reducer field accumulating per-thread findings (claim, locators, source thread); `vault_index` refresh on every mount pass so gates and mounts see newly produced documents.
- **Fan-out**: a Send-based diverge stage - a dispatch node emits one Send per research thread (thread spec from team config), researcher workers append findings, a join point feeds synthesis.
- **Phase gate**: generalize the `plan_approval` pattern (commit `f5f650d`) into a gate-node factory parameterized by phase: deterministic pre-interrupt propose+submit via the authoring client (idempotent), `interrupt({proposal_id, phase})`, resume payload is the verdict; Rejected/RequestChanges routes to the phase's writer with reviewer notes appended to `validation_errors`.
- **Verdict subscriber**: a control-layer consumer of the engine's `/authoring/v1/events` SSE (recovery-snapshot fallback) that correlates lifecycle events to parked threads via `authoring_proposal_ids` and issues `Command(resume=verdict)`; cursor persisted in the a2a database.
- **Personas and team**: researcher, synthesist, adr-author, doc-reviewer TOML personas (read+web for researchers; propose/validate for writers; never request_apply), a `vaultspec-adr-research` team preset on the new topology, and the writer sentinel pattern for machine-checkable stage completion. Coder-shaped presets are left untouched but are no longer the mission surface.

## Rationale

Every load-bearing claim is verified rather than assumed: the replay rule and Send are framework-documented; the engine's verdict stream and idempotency reservation were read from engine source; the gate pattern is already committed and tested. Composing reusable primitives (fan-out, gate, subscriber) wins over a bespoke chain because the very next workload (vault curation) is the same primitives minus synthesis - the knockout criterion is reuse across the document-authoring family. Structural gates over prompt convention is the direct lesson of the audited ADR-023/024 drift.

## Consequences

- Gains: the first end-to-end document-authoring capability; human judgment mechanically enforced at every phase; curation becomes a composition exercise; the two remaining audited graph defects get fixed as prerequisites.
- Difficulties: Send introduces parallel-branch checkpoint semantics new to this codebase (multiple interrupts per superstep need id-keyed resume maps); subscriber correctness across gateway restarts rests on cursor persistence + recovery reconciliation; reviewer-note quality directly bounds revise-loop convergence.
- Opens: plan-document authoring as a third phase later; per-phase tool-policy narrowing via the served catalog; retirement path for coding presets.
- Supersession posture: this record governs document-authoring orchestration going forward; ADR-012/013 (agent schema, team composition) remain governing for config mechanics and will be amended, not superseded, when the persona set lands.

## Amendment - production wiring (2026-07-15)

Concretizes this record for the dashboard team's production handover
(requirements and verified reality:
`2026-07-15-adr-authoring-orchestration-handover-reference`). The topology
decisions above are unchanged; this amendment decides the production
construction layer. Rag-led grounding confirmed the seams: the gate
consumes an injected submitter Protocol (`graph/nodes/phase_gate.py:53`),
`compile_team_graph` already accepts `proposal_submitter`
(`graph/compiler.py:303`), and the worker lifecycle call site
(`worker/graph_lifecycle.py:251-263`) never passes it - the topology is
correctly fail-closed dead code until this amendment's work lands.

- **PW1 - Production submitter lives in the authoring package.** A
  concrete `authoring/submitter.py` class implements the Protocol
  (async call taking state and phase, returning the proposal id) backed
  by `AuthoringSession`: create-or-resume the run's session,
  whole-document create/populate operations, validate, submit. Every
  mutating call derives its idempotency key from stable run-local
  material - thread id, phase, document kind, revision cycle - never
  timestamps; denials decode as values. The submitter reads the calling
  role's token from `RunTokenStore` at call time and holds no token
  itself, so restart-resumed runs re-resolve identity correctly (the
  conformance R7 lifecycle intact).
- **PW2 - The worker lifecycle is the single construction site.**
  `worker/graph_lifecycle.py` builds the `AuthoringSession` factory, the
  production submitter, and any `AuthoringToolBinding` from run-start
  facts (engine origin via discovery or explicit config, run id, token
  bundle) and passes `proposal_submitter=` into `compile_team_graph` for
  `research_adr` presets. Construction with missing prerequisites fails
  closed at build time with typed errors; a run that cannot author never
  starts vague.
- **PW3 - Two tool-exposure mechanisms, deliberately split.** The
  GRAPH-SUBMITTER path (in-process `AuthoringSession` calls from gate
  nodes) is the production mechanism for document topologies - it is
  deterministic, replay-exact, and NOT blocked by the upstream CLI
  MCP-surfacing limitation. The MCP BRIDGE (conformance R4) remains the
  agent-initiated tool path for CLI-coder presets and stays behind the
  upstream re-arm watch. Routing gate submits through the bridge is
  rejected: a subprocess hop on a path that must be deterministic and
  idempotent before `interrupt()`.
- **PW4 - Fail-closed taxonomy and state discipline.** One typed error
  family in the authoring package - engine unavailable, actor identity
  missing, submitter unconfigured, role configuration invalid,
  credentials missing - each actionable, surfaced as a truthful run
  failure state, never a silent skip. LangGraph state carries ONLY
  Rust-backend identifiers (authoring session id, changeset ids,
  proposal ids in the existing correlation fields); no document content,
  no tokens; product-facing status speaks role/phase vocabulary, never
  internal node names. In-flight reconciliation (2026-07-15): the
  product vocabulary is CONCRETIZED by the edge plan-2 semantic
  authoring-phase projection (starting, researching,
  synthesizing_research, reviewing_research, awaiting_research_decision,
  writing_adr, reviewing_adr, awaiting_adr_decision, completed, failed,
  cancelled, recovery_required) - single-homed there; this record does
  not define a second enum. The fail-closed posture is two composed
  layers decided independently and deliberately kept: the gateway's
  pre-dispatch run-start eligibility refusals (missing/unloadable
  preset, empty prompt, absent target feature for document presets,
  token bundle not covering the preset's required roles - typed 422s)
  refuse BEFORE dispatch, and PW2's construction-site errors fail
  closed AFTER dispatch for anything that slips past or degrades
  mid-lifecycle; neither replaces the other.
- **PW5 - Verification standard and documentation integrity.** The
  handover's verification requirements are the plan extension's
  Verification verbatim (no stub submitter, no graph-shape-only tests;
  live loopback engine; park durability, verdict resume including
  revision routing, restart correlation, replay-without-duplicates,
  zero vault writes, truthful unavailability). The S06 record is
  confirmed honest (structural spine, live proof deferred to P04.S10);
  the W03 S19/S20 binding-assembly deferral is reconciled in the plan
  rather than re-claimed. The five-verb gateway, model-profile
  selection, and product discovery remain separate issue domains.
- **PW6 - Effect on the conformance program's open gate.** Completing
  P04.S10 with a dashboard-observed research and ADR proposal closes
  the SUBSTANCE of the conformance brief's first acceptance criterion
  (documents appear only as reviewable proposals, attributed to
  per-role actors, zero vault writes) through the contract-blessed
  graph-submitter mechanism. The MCP-bridge-specific solo-coder proof
  (S20) stays open as a watch item on the upstream limitation, no
  longer program-blocking. This ruling is recorded on the conformance
  ADR as well and was RATIFIED by the owner on 2026-07-15 at the
  production-wiring plan approval.
- **PW7 - Headless acceptance contract with a per-gate verdict-policy
  axis (owner mandate, 2026-07-15).** The loop must be testable with
  tangible results and NO frontend: given a prompt, the result is N
  markdown documents. The contract: run-start (prompt, target feature,
  actor-token bundle) -> agent collaboration -> parked proposals ->
  verdicts driven PROGRAMMATICALLY over the engine's HTTP review surface
  (review-queue -> claim -> decisions -> apply) -> assertion that N
  documents MATERIALIZED on disk under `.vault/` (count, expected stems,
  frontmatter validity). For `research_adr`, N = 2 (research + ADR).
  Contract-legitimacy reading, verified against the wire reference and
  engine shapes: `ActorKind` admits `human` and `system` classes; actor
  tokens mint against any registered actor; the review surface is plain
  authoring-API HTTP; and the self-approval ban is ORIGIN-keyed - it
  binds the proposing agent actor, not the reviewer class - so a
  registered human- or system-class test actor deciding an agent-origin
  approval over HTTP is the normal review flow driven without a GUI, not
  a bypass. The dashboard review lane remains available to WATCH; no
  test may REQUIRE it.
  Verdict-policy axis (per gate, not per run): (a) AUTO - a
  system/test-class actor approves immediately per recorded policy; the
  TESTING default: prompt in, N documents out, zero waits; (b) HUMAN -
  parked until a real dashboard or API verdict; the PRODUCTION default
  for real authorship; (c) MIXED - per-gate choice (e.g. auto research
  gate, human ADR gate). Grounding: the dashboard operation-modes ADR's
  invariant, already quoted in the conformance research - one lifecycle
  (proposed -> approved -> applying -> applied) in EVERY mode; autonomy
  is a recorded approval-policy bundle with a system-actor approver,
  never a bypass arc. AUTO therefore approves ON the ledger by a
  different actor class; nothing skips proposal, validation, approval,
  or apply.
  Policy ownership: the ENGINE owns approval-policy declaration (its
  operation-modes surface - `/v1/mode` exists on the wire; its exact
  semantics and whether approval-policy bundles are engageable from a
  sibling are a follow-on check); A2A carries only a per-gate verdict-
  policy SELECTOR - in the harness now, optionally as a preset/run-start
  flag later (cross-repo contract event if it rides run-start). Until
  the engine-side engagement is settled, AUTO executes as
  harness-driven system-actor decisions over the review surface, which
  honors the same invariant.
  Harness reuse: the finale's driver is built as the STANDING acceptance
  harness - parameterized over prompt, preset, expected document count
  and stems, and per-gate verdict policy - not a one-off; successor
  plans (curation, plan-authoring) reuse it. Single-home note: the edge
  plan-2 evidence battery (its P03.S06) covers gateway behaviour and
  composes with this harness; the document-materialization loop
  assertion lives HERE.
