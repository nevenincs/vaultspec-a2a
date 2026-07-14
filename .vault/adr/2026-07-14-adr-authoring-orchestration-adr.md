---
tags:
  - '#adr'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
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
