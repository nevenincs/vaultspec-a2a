---
tags:
  - '#reference'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
related: []
---

# `a2a-edge-conformance` reference: `frozen dashboard edge contract, a2a side`

Mirror of the frozen cross-repo contract this repository conforms to, restated
from the A2A side. Sources (dashboard repo, read in full 2026-07-14):
`Y:/code/vaultspec-dashboard-worktrees/main/.vault/reference/2026-07-14-a2a-orchestration-edge-reference.md`
(the dev-team brief), the accepted edge ADR
`.vault/adr/2026-07-14-a2a-orchestration-edge-adr.md` (decisions D1-D8), and its
grounding research. The dashboard surface is FROZEN; any change to the edge is
a reviewed cross-repo contract event raised to the dashboard owners, never a
unilateral refactor.

## Summary

### Mission

This repo becomes a headless orchestration sibling of the dashboard engine.
LangGraph teams keep running the Research -> ADR -> Plan -> Exec -> Audit
pipeline over team presets, but every document an agent produces becomes a
proposed changeset on the engine's authoring API (`/authoring/v1/`), reviewed
and applied by a human in the dashboard. Agents never write `.vault/` files
(the engine denies agent direct writes as `forbidden_actor`). The dashboard
frontend never calls this service; the engine fronts it through a whitelisted
`/ops/a2a/{verb}` pass-through.

### Functional-reality posture (local amendment to the brief's framing)

The dashboard research describes this repo as a "substantial, current, tested
core". We do NOT take that at face value. Working assumptions until proven
otherwise by a verification gate: the codebase may be non-functional
(duplication, dead code, tests that do not collect or do not exercise real
services), and the agent-side vault-authoring tools were never implemented.
Workstream 1 is therefore greenfield construction of the authoring-API client
and served-tool-catalog binding, not a swap of a working seam. "Preserve the
core" reads as "salvage, verify, and harden the core."

### The write seam (Workstream 1 - authoring-API client)

Engine origin is loopback HTTP; auth is machine bearer plus per-actor token;
every response arrives in the shared envelope with a `tiers` block.

- Sessions: one `authoring_session` per run via `/v1/sessions` and
  `/v1/sessions/{id}/turns`; LangGraph `thread_id`/`run_id` are associated with
  it and the Vaultspec ids stored in thread state as references.
- Proposals: `/v1/proposals`, `/v1/proposals/{changeset_id}/append|replace`,
  `submit`, plus `snapshot`, `conflicts`, `provenance`, `rebase`.
- Served tool plane (preferred over hand-rolled request builders):
  `/v1/agent-tools` catalog, `/v1/agent-tools/prepare`,
  `/v1/agent-tools/{tool_call_id}/permission-decision`,
  `/v1/runs/{run_id}/agent-tools/execute`. The catalog is versioned with the
  engine and advertises only what runs.
- Interrupts/resume: `/v1/runs/{run_id}/resume`, `/v1/runs/{run_id}/cancel`,
  `/v1/interrupts/{interrupt_id}/resume` - resume by interrupt id, never
  positional order.
- Idempotency: every mutating command carries an idempotency key derived from
  stable run-local material (never timestamps); LangGraph interrupt replay
  re-runs the interrupted node and the engine deduplicates on the key.
- Whole-document operations only (section operations are deferred
  engine-side). New documents are whole-document creations; the engine
  scaffolds and validates frontmatter, filenames, and templates - agents never
  author them.
- Approval is never ours: self-approval is banned engine-side keyed on
  changeset origin. A denial envelope is a value, not an error - read
  `denial_kind`.

### Identity (Workstream 2 - tokens)

The engine's brokered `run-start` provisions one actor per pipeline role
(researcher, analyst, planner, executor, reviewer, supervisor) and passes
per-actor tokens in the start payload. Rules: each token lives only in the
worker it belongs to; never shared across roles; never logged (nor the start
payload verbatim); dropped at run end. This repo never mints tokens.

### Engine-facing control surface (Workstream 3 - five verbs)

The engine forwards exactly five verbs; endpoints must be stable and
versioned:

- `run-start`: preset id + prompt/message + target feature tag + actor token
  bundle; returns run/thread id and echoes the Vaultspec session id.
- `run-status`: authoritative recovery snapshot (topology position, per-role
  state, produced proposal ids) - sufficient for a client that saw nothing
  else to render the run.
- `run-cancel`: idempotent cancel by run id.
- `presets-list`: enumerate team presets with plain-language names.
- `service-state`: health/doctor rollup.

Progress streaming (node transitions, agent turns, bounded token frames) is
relayed by the engine as a non-authoritative SSE channel; frames are
versioned, bounded, and droppable. Durable truth is `run-status` plus the
engine's authoring events.

### Lifecycle and discovery (Workstream 4)

Machine-global discovery contract so the engine's attach-never-own predicate
applies verbatim: a service discovery file in a machine-global home location
(rag precedent: `~/.vaultspec-rag/service.json`; ours is the A2A equivalent)
carrying pid, port, and heartbeat, plus an ungated health endpoint reporting
ready + live pid. One resident service per machine.

### State-ownership fence

This repo owns orchestration state only: threads, runs, checkpoints,
task-queue entries, its own database, retry policy, topology, presets,
providers. The engine owns all document state: changesets, proposals,
approvals, preimages, receipts, audit. Vaultspec ids are stored here as
references; LangGraph ids live engine-side as provenance. No second document
ledger here.

### Reads

The read-only, token-budgeted `.vault/` mount stays for corpus context
(compatible with engine read-and-infer). Anything about in-flight work -
proposal snapshots, changeset status, conflicts, review state - is read from
the authoring API, never reconstructed from the filesystem.

### Deletion mandates (dashboard ADR D7)

- `src/ui/` (React/Vite, ~14.8k lines) and every UI-serving route, build step,
  and dev dependency that exists only for it.
- The Google-A2A protocol stub `src/vaultspec_a2a/protocols/a2a/`; "a2a"
  survives as a project label; declared transports are ACP and REST/SSE.
- Every agent-reachable file-write tool that can touch a `.vault/` path.
- No cross-imports in either direction; the edge is loopback HTTP only.

Salvage targets (verify before trusting): `src/vaultspec_a2a/graph/`
(compiler, nodes, task queue), `team/` (presets, role-phase gating),
`providers/` (ACP stack), `thread/`, `context/`.

### Local ADR supersession map

New-contract impact on this repo's own decision corpus (dispositions to be
ratified in the conformance ADR):

- Superseded outright by the edge contract: `adr-018` react-tailwind-figma
  migration, `adr-9` frontend-backend contract, and the 2026-04-05
  contract-validation ADR (CI contract gate with custom WS codegen) - all
  exist for the deleted UI. `adr-4` event-aggregation server-side replay is
  superseded where it serves the UI; its event model is replaced by the
  engine-relayed SSE split.
- Amended: `adr-3` protocol-bridging-translation and `adr-6`
  protocol-ecosystem-bridge lose the Google-A2A transport ambition (ACP +
  REST/SSE remain); `adr-16` blackboard-content-mounting and `adr-18`/
  `adr-019` (contextual anchoring, teamstate enrichment) remain valid for
  READS but any write-side artifact production they imply now routes through
  the authoring API; `adr-19` phase-artifact-gates now gates on proposal
  existence via the authoring API rather than on files appearing in
  `.vault/`; `adr-20` plan-approval-interrupt maps onto engine interrupts and
  human review in the dashboard lane; `adr-7` tech-stack-deployment and
  `adr-009` approved-module-hierarchy drop the UI stack and the `src/ui/`
  and `protocols/a2a/` entries from the approved layout (rag-confirmed both
  records carry them).
- Preserved (subject to salvage verification): `adr-008` orchestration
  topology, `adr-11` team-composition topology, `adr-17` persistent task
  queue, `adr-25` worker-process architecture, `adr-29` postgres dual
  backend, `adr-2` llm-context-provider abstraction, `adr-038` control-layer
  CLI/justfile separation, `adr-039` service-lifecycle architecture (the
  local half of the new discovery contract), and the layer-boundary series
  (core-layer, entry-point, domain-logic, database-layer, service-layer).
