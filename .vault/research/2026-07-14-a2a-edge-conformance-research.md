---
tags:
  - '#research'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-a2a-edge-conformance-reference]]"
---

# `a2a-edge-conformance` research: `repo functional-reality survey grounding the edge adoption`

What is the actual, verified state of this repository as of 2026-07-14, and
where does it diverge from the dashboard research's description of it? The
answer shapes the adoption ADR's evidentiary posture and the plan's opening
phase. Conclusion of the evidence picture: the standalone layer is verified
healthy (imports, test collection, headless gateway boot), the integrated
layer (worker IPC, real agent turns) remains unverified, exactly one
agent-reachable vault write exists (the task-queue tool), and general
document authoring for in-graph agents was never built - the write seam is
greenfield, not a swap.

## Findings

### The contract itself is external and frozen

The mission, mandates, workstreams, API surfaces, and acceptance criteria are
mirrored in the related reference document and are not restated here.

### Functional reality check: standalone layer verified, integrated layer open

Verified live (2026-07-14): `import vaultspec_a2a` succeeds; pytest collects
1165 of 1176 tests with zero collection errors (the 11 remainder carry the
`service` marker and are correctly deselected by the default profile);
`pytest -m unit -q` passes 536 tests with zero failures in 8s; the gateway
boots headless via `vaultspec_a2a.api.app:create_app` under uvicorn -
Alembic migrations auto-run on SQLite, `/health` returns 200 with
`postgres_required: false` and the sqlite fallback active. A rag-led
duplication hunt came back negative: projection/snapshot logic is
single-homed, with no near-duplicate modules; the empty top-level `core/`,
`cli/`, `bin/`, `tests/` orphans have zero inbound references. The
presumed-broken posture is disproven for this layer. Still unverified, and
therefore the plan's opening verification gate: the worker process and
gateway-worker dispatch over IPC (`worker/app.py` is a standalone FastAPI
app the gateway calls; the booted gateway reported
`worker_connected`/`worker_spawned` false because it was started alone) and
a real end-to-end agent turn (mock-tape presets exist for exactly this).

### The write seam is the ACP filesystem RPC, plus one task-queue tool

The dominant agent write path is not a tool list: spawned coding CLIs
(Claude Code/Gemini driven via `acp_chat_model` and the ACP subprocess
layer) author ALL files - including `.vault/` documents - through the
generic `fs/write_text_file` JSON-RPC method handled at
`providers/_acp_rpc_handlers.py:198` (`on_fs_write_text_file`), under a
`sandbox_path()`-resolved root with a global git mutex. Removing
agent-reachable vault writes therefore concretely means a path policy at
this single chokepoint we own, with two candidate shapes: structured denial
mirroring the engine's `forbidden_actor` semantics (actionable, steers the
agent to the authoring tools) versus silent exclusion of `.vault` from
`sandbox_path` resolution.

The second, minor write path is the in-graph tool
`graph/tools/task_queue.py` (156 lines, wired into `graph/nodes/worker.py`
via `create_mark_task_complete_tool`): it reads and writes a bespoke
markdown table at `.vault/plan/{feature_tag}-queue.md` by string
replacement, outside vaultspec-core owning verbs. `graph/tools/__init__.py`
is otherwise empty. The worker loop depends on this queue, so the
conformance question is relocation of its storage, not deletion of the
capability.

Tool grants are transport-level, not preset-level: no preset TOML declares
tools (presets configure topology, provider, permissions, persona only).
Exposing engine authoring tools to agents therefore means surfacing them at
the transport layer - as MCP tools served into the ACP subprocess session
(the repo has a real `protocols/mcp` server) or by bridging the engine's
served `/v1/agent-tools` catalog into the session. Beyond the read/control
MCP tools (discovery, messaging, thread_lifecycle, thread_query), general
document authoring for in-graph agents was never implemented (historically
host-side vaultspec-core). The authoring-API client and catalog binding are
new construction; there is no existing seam whose call sites can simply be
re-pointed.

### Not duplication; but the CLI surface is gone

Filename collisions across `api/schemas`, `control/`, `worker/`, `thread/`
are per-layer facades with verified distinct responsibilities, matching the
repo's facade mandate. Top-level `core/`, `cli/`, `tests/`, `bin/` are empty
leftovers of intentional refactors (PR #3 decomposition; live-test deletion
`7d3f1ef`) holding only stale `__pycache__`. The only script entrypoint
today is `vaultspec-mcp`; no `vaultspec-a2a` CLI exists, while the brief
declares the headless surface as CLI + engine-facing REST/SSE + health - the
ADR must decide whether to re-establish a CLI or declare it out of scope as
a cross-repo contract note.

### Structure matches the dashboard survey; health is unverified

Package line counts (scout survey 2026-07-14): api 11.6k, control 6.3k,
providers 4.4k, graph 4.3k, database 4.2k, streaming 3.8k, thread 3.4k,
worker 2.9k, protocols 2.9k, context 2.2k, service_tests 1.6k, workspace
1.3k, team 1.3k, telemetry 1.1k, utils 1k, lifecycle 0.5k, ipc 0.2k.
`tests/`, `core/`, `cli/`, `bin/` at the top level are empty placeholders.
Last substantive commit is three months old (2026-04-06, PR #38); nothing
since verifies the package imports, tests collect, or services boot. The
dashboard research's "substantial, current, tested" framing is structural
observation, not functional verification.

### Deletion targets and their blast radius

- UI: `src/ui/` (Vite/React SPA) is mounted by FastAPI at `api/app.py:309`
  behind `settings.ui_build_dir`; UI dependencies live in both the root
  `package.json` and `src/ui/package.json`; the Justfile carries
  `_dev-service-*-ui` and `_dev-code-check-ui` recipes.
- Google-A2A stub: `src/vaultspec_a2a/protocols/a2a/` is a dead 3-line stub
  with ZERO importers (deletion-manifest verification, 2026-07-14,
  correcting this survey's earlier claim: the apparent `protocols.a2a`
  hits in `graph/compiler.py`, graph tests, and six `streaming/*.py`
  files were a name collision with `graph/protocols.py`, an unrelated
  typing.Protocol module that must not be touched).

### Reusable assets confirmed present (pending verification)

Five real team presets in `team/presets/teams/`: vaultspec-solo-coder,
vaultspec-adaptive-coder (default per `control/worker_management.py:116`),
vaultspec-iterative-coder, vaultspec-structured-coder,
vaultspec-continuous-audit; plus 8 mock-* test presets with recorded tapes.
Agent personas: vaultspec-{analyst,coder,planner,reviewer,supervisor} + 7
mocks. Role-phase gating in `team/team_config.py`. The existing `/api`
surface (health, cancel, messages, permissions, team status, teams list,
thread state, thread SSE stream, thread CRUD, admin shutdown) is a close
structural cousin of the contract's five verbs.

### Boot and hygiene hazards for the plan

- Startup runs `settings.validate_postgres_requirement()` (`api/app.py`);
  headless SQLite boot must be preserved.
- Runtime state (data/, runtime/, tmp/) was moved out of `.vault/` on
  2026-07-03 into `.vault-local-state-moved-20260703/` because vaultspec
  firmware rejects unsupported directories in `.vault/`;
  `control/worker_management.py:73` still references `.vault/runtime` -
  path reconciliation is open work.
- Uncommitted vaultspec housekeeping sits in the worktree: managed
  `.gitignore` block, new vault pre-commit hooks, `vaultspec-rag[mcp]` and
  `torch` added to `pyproject.toml` with a cu130 index.
- Test infrastructure: rust-style per-package `tests/` subdirs plus
  `src/vaultspec_a2a/tests/` (evals/suites); pytest defaults to
  `-m "not service"` (Docker tests opt-in), asyncio strict, 300s timeout.
  Marker-taxonomy anomaly: `pytest -m unit -q` and `pytest -m core -q`
  return identical results (536 passed / 640 deselected each) - the
  core/middleware/unit/service markers may not partition the suite; audit
  before trusting marker-based triage.

### Still open after the reality check

Live worker-gateway dispatch over IPC and one real end-to-end agent turn
(mock tapes suffice as evidence). These are the plan's opening verification
gate; the salvage-vs-rebuild fallback hinges only on these remaining items.

## Sources

- `Y:/code/vaultspec-dashboard-worktrees/main/.vault/reference/2026-07-14-a2a-orchestration-edge-reference.md`
- `Y:/code/vaultspec-dashboard-worktrees/main/.vault/adr/2026-07-14-a2a-orchestration-edge-adr.md`
- `Y:/code/vaultspec-dashboard-worktrees/main/.vault/research/2026-07-14-a2a-orchestration-edge-research.md`
- Scout survey of this repo, 2026-07-14 (session artifact): `api/app.py:309`,
  `control/worker_management.py:73`, `control/worker_management.py:116`,
  `team/team_config.py`, `src/vaultspec_a2a/protocols/mcp/tools/`,
  `team/presets/teams/`, `pyproject.toml`, `Justfile`,
  `.vault-local-state-moved-20260703/README.txt`, commit `7b2c5f3`.
