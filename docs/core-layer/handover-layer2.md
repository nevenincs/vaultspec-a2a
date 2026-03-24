# Layer 2 Entry Point Decomposition — Handover

## Prerequisite

Merge PR #3 (`feature/core-layer` → `main`) first. It delivers a fully
isolated Layer 1 (425 tests, zero infrastructure imports). Branch off
`main` after merge.

## What Layer 1 delivered

Layer 1 packages (`thread/`, `context/`, `team/`, `graph/`,
`lifecycle/`, `domain_config.py`) and Layer 1.5 (`streaming/`) are
clean. Zero imports from `api/`, `database/`, `providers/`,
`telemetry/`, `control/`, `worker/`, `utils/`. The aggregator is
decomposed into 6 sub-modules. Domain events replace wire-protocol
events. Telemetry is injected via protocol hooks.

Key artefacts:

- `.vault/adr/2026-03-23-core-layer-boundary-adr.md` — Layer model
- `.vault/audit/2026-03-24-core-layer-boundary-audit.md` — Section 2
  has full Layer 2 findings
- `src/vaultspec_a2a/README.md` — Living architecture doc

## The problem: Layer 2 is fat

Layer 2 should be thin adapters — translate external protocols into
Layer 1 calls. Currently it contains business logic, inline class
definitions, and monolithic files.

### Files that need breaking up

| File | Lines | Issues |
|------|-------|--------|
| `api/endpoints.py` | 1,883 | Domain projection logic, thread-lifecycle orchestration, thread-creation policy. Should be service-layer calls into Layer 1. |
| `api/app.py` | 1,507 | Inline `WorkerCircuitBreaker`, `LazyWorkerSpawner`, `WorkerWatchdog` class definitions. WS dispatch factory duplication. |
| `api/websocket.py` | 719 | Borderline. `ConnectionManager` is clean. WS dispatch factories wired from `app.py` are the problem. |
| `worker/executor.py` | 983 | LangGraph lifecycle ownership is legitimate. Imports shared IPC types from `api/schemas/internal` — inverted dependency. |
| `cli/_team.py` | 825 | Needs audit for business logic leakage. |

### Structural violations found in Layer 1 audit

- `worker/executor.py` imports `DispatchRequest` and projection
  payloads from `api/schemas/internal` — worker depends on api's
  schema namespace. These shared IPC types should live in a neutral
  location (`protocols/` or `ipc/`).

- `api/endpoints.py` contains ~200 lines of domain projection logic
  (`_enrich_snapshot_from_state`), thread-lifecycle orchestration
  sequences repeated in every write-path handler, and thread-creation
  policy logic (`_process_metadata`) that belongs in Layer 1.

- `api/app.py` defines 3 classes inline (CircuitBreaker, Spawner,
  Watchdog) that are reusable infrastructure — they belong in
  `control/` or a new `infra/` package.

- Thread-status guard logic is duplicated between REST handlers and WS
  dispatch factories.

## Mandatory reading before starting

1. `.vault/adr/2026-03-23-core-layer-boundary-adr.md` — Layer model
2. `.vault/audit/2026-03-24-core-layer-boundary-audit.md` — Section 2
   (Entry Point Thinness) has the full findings
3. `src/vaultspec_a2a/README.md` — Living architecture doc with layer
   definitions
4. `.vault/research/2026-03-23-core-layer-boundary-research.md` —
   original boundary research methodology (apply same to Layer 2)

## Rules (non-negotiable, learned from Layer 1 PR)

- **No backwards-compat shims.** When moving code, update all
  consumers. Old import paths break loudly.
- **No deferral.** If the plan says decompose a module, decompose it.
  Do not move it as-is and call it done.
- **Stay in scope.** Layer 2 PR touches `api/`, `worker/`, `cli/`,
  and shared IPC types. Do not report or fix Layer 1 or Layer 3
  issues.
- **Modules over 1,000 lines must be split** into focused sub-modules
  (`foo/bar.py`, `foo/baz.py`). No monoliths.
- **No re-export shims.** One canonical import path per symbol.
- **Test for each phase.** Each phase must preserve a green test suite.
- **No mocks, stubs, fakes, patches, skips.** Real tests only.
- **Commit after every phase.** Push to the draft PR continuously.
- **Code review after every phase.** Do not batch reviews.

## Mandatory pipeline — follow this exactly

You MUST use the vaultspec pipeline skills in this order. Do not skip
steps. Do not combine steps. Each step produces a persisted artefact
in `.vault/`.

### Phase 1: Research

Invoke `vaultspec-research`. Use parallel sub-agents:

- **Agent 1 — `vaultspec-researcher`**: Static analysis of `api/`
  module. Map every function in `endpoints.py` and `app.py`. Classify
  each as "protocol translation" (belongs in Layer 2) or "business
  logic" (must move to Layer 1). Count lines per category.

- **Agent 2 — `vaultspec-researcher`**: Static analysis of `worker/`
  and `cli/` modules. Same classification. Map the IPC type
  dependency: which types in `api/schemas/internal.py` are used by
  `worker/`, and what neutral location they should move to.

- **Agent 3 — `vaultspec-code-reference`**: Audit the 3 inline
  classes in `app.py` (`WorkerCircuitBreaker`, `LazyWorkerSpawner`,
  `WorkerWatchdog`). Document their interfaces, dependencies, and
  where they should live.

Persist findings to `.vault/research/`.

### Phase 2: ADR

Invoke `vaultspec-adr`. Use `vaultspec-writer` agent. The ADR must
reference the research findings and decide:

- Where business logic from `endpoints.py` moves (new Layer 1 service
  module? existing Layer 1 package?)
- Where the 3 inline classes from `app.py` move
- Where shared IPC types move (out of `api/schemas/internal`)
- How `endpoints.py` (1,883 lines) splits into sub-modules
- How `app.py` (1,507 lines) splits into sub-modules
- How `executor.py` (983 lines) splits

Present to user for approval. Do NOT proceed without explicit sign-off.

### Phase 3: Plan

Invoke `vaultspec-write-plan`. Use `vaultspec-writer` agent. The plan
must:

- Reference the approved ADR
- Define phases with dependency ordering
- Identify parallelizable phases
- Include per-phase verification gates
- Track progress (update between execution runs)

Present to user for approval.

### Phase 4: Execute

Invoke `vaultspec-execute`. Use parallel sub-agents with executor
personas (`vaultspec-standard-executor` or `vaultspec-high-executor`
for complex phases).

- Instruct each executor to read the plan and start at their assigned
  phase
- Each executor writes a step record to `.vault/exec/`
- Commit and push after every completed phase
- Do NOT batch multiple phases into one commit

### Phase 5: Review

Invoke `vaultspec-code-review` after EVERY phase (not after the whole
plan). Use `vaultspec-code-reviewer` agent persona.

- Reviewer reads the ADR and plan
- Reviewer verifies the phase against the plan's tasks
- Reviewer checks for boundary violations, re-export shims, business
  logic leakage
- If CRITICAL or HIGH findings: fix before next phase
- Persist review to `.vault/audit/`

### Phase 6: Final validation

After all phases complete:

- Run the boundary audit prompt (in `docs/core-layer/`) against
  Layer 2
- Verify: each entry point file < 500 lines
- Verify: zero business logic in route handlers (protocol translation
  only)
- Verify: no entry point cross-imports (api ↛ cli, worker ↛ api
  except shared IPC types in neutral location)
- Verify: full test suite green

## Test baseline

Run before starting to establish what passes:

```bash
pytest src/vaultspec_a2a/ -q --tb=no \
  --ignore=src/vaultspec_a2a/database/tests/test_migrations.py \
  --ignore=src/vaultspec_a2a/providers/tests/test_factory.py \
  --ignore=src/vaultspec_a2a/graph/tests/test_compiler.py \
  -m "not live and not requires_vidaimock and not requires_jaeger"
```

Expected: ~977 pass. The `test_factory.py` and `test_compiler.py`
failures are pre-existing (missing ACP npm dependency).

## Scope boundary

This PR touches: `api/`, `worker/`, `cli/`, shared IPC types.

This PR does NOT touch: `thread/`, `context/`, `team/`, `graph/`,
`streaming/`, `lifecycle/`, `domain_config.py`, `database/`,
`providers/`, `telemetry/`, `docker/`, `Dockerfile`.

If you find issues in Layer 1 or Layer 3 during the work, note them
in a separate `.vault/research/` document. Do not fix them in this PR.
