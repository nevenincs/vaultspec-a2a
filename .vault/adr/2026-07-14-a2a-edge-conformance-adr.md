---
tags:
  - "#adr"
  - "#a2a-edge-conformance"
date: '2026-07-14'
related:
  - "[[2026-07-14-a2a-edge-conformance-reference]]"
  - "[[2026-07-14-a2a-edge-conformance-research]]"
  - "[[2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference]]"
supersedes:
  - '2026-02-28-react-tailwind-figma-migration-adr'
  - '2026-02-26-frontend-backend-contract-adr'
  - '2026-04-05-contract-validation-adr'
modified: '2026-07-15'
---
# `a2a-edge-conformance` adr: `adopting the dashboard edge contract under a salvage-and-verify posture` | (**status:** `accepted`)

## Problem Statement

The dashboard has frozen the cross-repo edge (its edge ADR, decisions D1-D8)
and issued a dev-team brief this repo must conform to; both are mirrored in
`2026-07-14-a2a-edge-conformance-reference`. This record decides how THIS
repository adopts that contract: which local decisions the contract
supersedes or amends, what implementation shape the repo-side conformance
work takes, and under what evidentiary posture the "reusable core" is
treated. A decision is needed now because no in-flight plan exists, the last
substantive work predates the contract by three months, and every subsequent
plan must derive from this record.

## Considerations

- The dashboard surface is frozen; conformance work is unilateral only on
  this side of the HTTP edge (`2026-07-14-a2a-edge-conformance-reference`).
- Functional-reality posture, refined by evidence: the standalone layer is
  verified healthy (clean import, 1165-test collection, 536 unit tests
  passing, headless SQLite gateway boot); the integrated layer
  (worker-gateway IPC dispatch, a real agent turn, the agent/tool
  provisioning mechanism) remains unverified and gates the plan
  (`2026-07-14-a2a-edge-conformance-research`).
- Owner's qualifier (2026-07-14, recorded at acceptance): EVERYTHING in this
  repo is fluid and suspect until tested - including the repo's own
  standards, conventions, and prior ADR corpus, which the owner rates as
  "somewhat incorrect". Local ADRs and conventions are inputs to verify,
  never authorities; only the frozen dashboard contract and this record are
  binding without re-validation.
- The agent write seam is a single chokepoint we own: the ACP
  `fs/write_text_file` RPC handler in `providers/_acp_rpc_handlers.py`,
  through which spawned coding CLIs author all files under a sandbox root -
  plus one in-graph task-queue tool writing a markdown table under
  `.vault/plan/`. General document authoring for in-graph agents was never
  built; Workstream 1 is greenfield.
- Tool grants are transport-level, not preset-level: presets declare
  topology/provider/permissions/persona only, so authoring tools must be
  surfaced at the transport layer, not in preset TOML.
- No `vaultspec-a2a` CLI entrypoint exists today (only `vaultspec-mcp`),
  while the brief declares the headless surface as CLI + engine-facing
  REST/SSE + health.
- The five existing real presets include `vaultspec-solo-coder` (the W2
  proof vehicle) with `vaultspec-adaptive-coder` as the configured default
  in `control/worker_management.py`; gating lives in `team/team_config.py`.
- The existing `/api` surface (threads, teams, health, SSE stream, cancel,
  messages, permissions) is a close cousin of the five-verb contract; the
  gateway work is reshaping, not invention.
- The Google-A2A stub has zero importers (manifest-verified); the earlier
  dead-reference-sweep concern was a name collision with
  `graph/protocols.py`, an unrelated typing.Protocol module that stays.
- The UI is mounted by FastAPI (`api/app.py`) behind `settings.ui_build_dir`;
  UI deps live in both the root `package.json` and `src/ui/package.json`;
  Justfile carries UI recipes. Local `adr-9`, `adr-018`, and the 2026-04-05
  contract-validation ADR exist for that UI.
- Worktree hygiene: vaultspec housekeeping is uncommitted, and runtime state
  was moved out of `.vault/` on 2026-07-03 while
  `control/worker_management.py` still references `.vault/runtime`.
- Startup enforces `settings.validate_postgres_requirement()` - headless
  boot must remain possible with the SQLite default.

## Considered options

- **Adopt-and-conform under salvage-and-verify (CHOSEN).** Keep the repo,
  verify the core before trusting it, build the write seam greenfield.
  Preserves presets/topology/queue investment while refusing unverified
  claims about their health.
- **Adopt-and-conform trusting the dashboard survey.** Rejected: the
  "substantial, current, tested" framing is external and three months stale;
  building the write seam atop an unverified runtime risks debugging two
  unknowns at once.
- **Fresh thin orchestrator cherry-picking this repo.** Held as fallback
  (mirrors the dashboard ADR's own fallback) if the verification gate shows
  the core does not salvage economically; not preferred while presets,
  queue, and providers lift cleanly.

## Constraints

- Frontier deps: `langgraph 1.x`, ACP (`@zed-industries/claude-agent-acp`)
  - both fast-moving; the engine fences event-shape drift via versioned
  schemas, and this repo must do the same on its SSE frames.
- The engine's served tool catalog (`/v1/agent-tools`) is versioned with the
  engine; binding to it couples our worker tools to a surface we do not
  control - by design. Hand-rolled request builders would trade that for
  silent drift instead.
- Whole-document proposal shapes only (engine-side section-operations
  deferral); nothing here may assume sub-document operations.
- Actor tokens exist only inside a run's lifetime and only in the owning
  worker; logging or persistence of tokens is prohibited.
- No engine import may ever enter this dependency graph; the edge is
  loopback HTTP.

## Implementation

Repo-side decisions (the dashboard's D1-D8 are adopted verbatim and not
restated):

- **R1 - Verification gate before conformance work.** The narrowed salvage
  audit is the first executable phase of any plan under this record: prove
  live worker-gateway dispatch over IPC and one real end-to-end agent turn
  (mock-tape presets are acceptable evidence), and audit the pytest marker
  taxonomy (unit/core/middleware/service selections currently do not
  partition the suite) so later marker-based triage is trustworthy.
  The gate extends to the agent/tool provisioning mechanism (the ACP
  session wiring: session construction, subprocess management, chat-model
  adapter, provider factory), presumed untested until live evidence exists.
  Standalone-layer health is already verified
  (`2026-07-14-a2a-edge-conformance-research`). Failures are fixed or the
  component is declared non-salvageable and the fallback re-evaluated.
  Per the owner's qualifier, the gate's spirit generalizes: any step that
  relies on a local standard, convention, or prior ADR must validate it
  before depending on it.
- **R2 - Vault-write denial at the ACP filesystem chokepoint.** The
  `fs/write_text_file` handler (and any sibling fs-mutation RPCs) enforces a
  path policy denying `.vault/**`: a structured, actionable denial
  mirroring the engine's `forbidden_actor` semantics exactly as wired - a
  value-typed result (the engine returns HTTP 200 with `data.denial_kind`
  in snake_case beside a human-readable `eligibility.reason`, never a
  transport error; see
  `2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference`) - naming
  the authoring tools as the correct path, rather than silent exclusion
  from `sandbox_path` resolution. Silent exclusion was rejected: an unexplained write failure
  leaves the CLI agent retrying or corrupting its plan, while a structured
  denial steers it. Reads through the ACP fs surface remain permitted
  (dashboard D4). The denial policy gets adversarial tests (traversal,
  symlink, relative-path attempts).
- **R3 - Authoring client placement.** A new `src/vaultspec_a2a/authoring/`
  package owns the engine edge: httpx-based loopback client, envelope/tiers
  decoding, idempotency-key derivation (stable run-local material), session
  lifecycle, proposal verbs, and the served-tool-catalog binding. No other
  package speaks to the engine directly. The client speaks the engine's
  exact wire grammar
  (`2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference`): dual
  auth headers (machine bearer plus `x-authoring-actor-token`), every
  mutating call wrapped in the CommandEnvelope with the idempotency key as
  a BODY field (`{api_version, command, idempotency_key, payload}` - the
  sole exception being the bare actor-tokens bootstrap route), the
  `expected_revision` fence threaded through every draft mutation, the
  160-byte restricted-charset id rules enforced client-side, and the two
  denial vocabularies distinguished: typed HTTP errors for
  transport/identity, 200-value `denial_kind` results for business
  denials.
- **R4 - Tool exposure: engine catalog bridged into the agent session.**
  Because tool grants are transport-level, engine authoring tools reach
  agents by bridging the engine's served `/v1/agent-tools` catalog into the
  agent-facing tool surface at session start: the catalog is fetched per
  run, snapshotted, and its tools surfaced to the spawned CLI session by
  our own per-run MCP bridge process; the bridge's agent-facing transport
  is an orchestration-internal choice (D5) - stdio where the pinned CLI
  cannot consume local HTTP MCP servers headlessly (the verified adapter
  limitation, upstream issues 40314 and 57033), HTTP where it can - and is
  NEVER part of the frozen edge: every mutating tool call executes through
  `/v1/runs/{run_id}/agent-tools/execute` over loopback HTTP under the
  calling role's token, regardless of the agent-side hop. The bridge
  process carries the R7 token discipline: it holds only the calling
  role's token, per run, never logged, dropped at run end (owner decision
  2026-07-14 adopting the stdio bridge). Hand-rolled request builders are rejected
  (silent drift against an engine-versioned surface); a preset-level tool
  list is rejected (presets do not carry tools). Refinement (2026-07-14,
  owner-authorized on the first live bridged turn; causal claim CORRECTED
  same day): headless runs must not double-gate bridged authoring tools
  behind a local permission layer - the authoritative human gate for
  proposals is the engine's review lane (self-approval banned engine-side,
  origin-keyed), mirroring the dashboard operation-modes principle that
  autonomy is a recorded policy, never a bypass of the ledgered write
  path. Mechanism, root cause confirmed in the `claude-agent-acp` source:
  the ACP-layer prompt was NEVER the blocker - the RPC handler already
  auto-selects the allow option when no permission callback is configured
  (the autonomous case), and zero permission requests reached it on the
  failing turn. The operative gate is the spawned CLI's OWN permission
  mode: the adapter resolves `default | acceptEdits | bypassPermissions`,
  the session layer never set any mode, so headless runs sat in
  prompt-required `default` where mutating MCP tools are never invokable
  (read tools pass as auto-permitted; Claude gates internally, emitting
  zero tool calls and zero ACP permission requests). The operative
  decision is therefore how the orchestrator configures the spawned CLI's
  permission surface for autonomous runs, least-privilege preference
  order (specialist-confirmed against the CLI's documented permission
  model, where a tool without a matching allow rule is declined
  internally and silently): an exact-name allowlist of
  `mcp__<server>__<tool>` rules from the catalog snapshot (the CLI's
  allowedTools / permissions.allow surface; wildcards exist but are not
  used), `bypassPermissions` prohibited, optionally `dontAsk` mode as a
  hard-deny for unlisted tools where the pinned ACP adapter threads it -
  autonomous presets only, human-in-the-loop presets unchanged, the
  granted surface logged per run. Unchanged rationale either way: the engine review lane is the
  authoritative human gate, and the R2 deny policy independently protects
  the vault under ANY permission mode. The W03 review verifies the
  implementation against these constraints. Gate-narrowing ruling
  (2026-07-15, RATIFIED by the owner the same day at the
  production-wiring plan approval): the graph-submitter mechanism (the
  adr-authoring-orchestration amendment, PW3/PW6) delivers
  dashboard-observed, per-role-attributed proposals WITHOUT the CLI tool
  path, so a completed production research-to-ADR run closes the
  SUBSTANCE of the brief's first acceptance criterion; the S20
  solo-coder MCP-bridge proof narrows from program-blocking gate to
  upstream watch item (re-run the matrix probe on CLI/adapter releases;
  close S20 when surfacing lands).
- **R5 - Task queue leaves the vault.** The worker task queue is
  orchestration state (dashboard D5: ours), so its storage moves from the
  bespoke markdown table under `.vault/plan/` into A2A's own database
  alongside threads/checkpoints; the existing queue schema decision
  (`adr-17`) is amended accordingly. The capability is preserved; only its
  home changes. Any human-facing queue visibility later rides `run-status`,
  never vault files. Refinement (2026-07-14, on the executor's finding
  that no population path ever existed in code - rows were historically
  authored externally as a vault artifact):
  - **Population source: the planner role emits queue rows run-locally**
    (option b). The planner node that proposes the plan document through
    the authoring API also registers its execution-facing task
    decomposition as rows in the A2A database. Rejected: carrying a task
    list in the `run-start` payload (option a) - that changes the frozen
    verb shape, a cross-repo contract event, and would move plan content
    across the orchestration edge; ingesting from the engine plan document
    at run startup (option c) - plan CONTENT is the engine's document, and
    coupling queue construction to snapshot parsing rebuilds a document
    reader the fence says we must not own. The document linkage is by
    REFERENCE instead: each row stores the plan proposal's Vaultspec ids,
    and the existing phase gate (per the R12 re-target of the
    phase-artifact-gates record) verifies through the authoring API that
    the plan proposal was approved before the exec phase consumes the
    queue. Fence-clean: content stays engine-side, execution state stays
    ours, approval stays human.
  - **Schema (migration 0006)**: one table, rows owned by a thread -
    `id` (uuid hex pk), `thread_id` (FK, cascade delete), `feature_tag`
    (validated as in the merged traversal guard), `position` (int,
    unique per thread, sole ordering authority), `task_key` (stable
    per-thread row identity the mark-complete tool addresses),
    `description` (the task's action text), `status` (bounded enum:
    `pending | in_progress | completed | failed`), nullable Vaultspec
    references `plan_changeset_id` and `plan_step_key` (D5 references,
    never content), `created_at`/`updated_at`. The execution cursor
    (`current_task_id`) stays in TeamState where it lives today - it is
    graph state, not queue state. Mark-complete becomes an idempotent
    status transition (completing a completed row is a no-op, matching
    the engine's replay discipline).
  - **Context injection preserved**: `vault_reader`'s queue view is
    format-stable - the current row plus the next two pending by
    `position`, rendered as the same table text the markdown path
    injected, so prompts and recorded tapes are unaffected; only the
    backing store changes from file parse to repository query.
  - **Interim population**: until the planner wiring lands (full-team
    wave), rows enter through the internal repository/service API only -
    used by tests and future gateway internals; no agent-reachable
    population path exists, preserving R2's closure.
- **R6 - Gateway reshaping, not new service.** The five verbs map onto the
  existing FastAPI app: `run-start` -> reshaped thread-create+message flow
  accepting the actor-token bundle; `run-status` -> reshaped thread-state
  read designed as a recovery snapshot; `run-cancel` -> existing cancel made
  idempotent; `presets-list` -> existing teams listing; `service-state` ->
  health/doctor rollup. Endpoint shapes are versioned; UI static mounting
  and every UI-only route are removed. Shapes are designed against the
  engine's pass-through template
  (`2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference`): the
  engine whitelists verbs and 403s unknown ones before I/O, validates args
  field-by-field with bounded types, forwards our envelope verbatim inside
  its tiers envelope, degrades to a tier block (never 5xx) when we are
  down, and caps calls at 8 MiB / 120s - so our responses must be bounded,
  self-describing, and safe to wrap verbatim.
- **R7 - Token-bundle threading.** The `run-start` payload's per-role tokens
  are held in worker-scoped runtime state (never checkpointed, never
  logged), injected into the authoring client per worker, and dropped at run
  end. Supervisor holds its own token; roles never share.
- **R8 - Discovery contract and runtime paths.** A machine-global
  `~/.vaultspec-a2a/service.json` (rag precedent) written by the resident
  gateway service, adopting the rag contract's exact field and freshness
  semantics
  (`2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference`):
  `port` required; optional `pid`, `service_token`, and `last_heartbeat`
  (ms-epoch integer or ISO-8601 string); producer refreshes every 15s,
  consumers treat >120s as stale; stale or malformed reads as Crashed
  (attach-never-own), and only Absent licenses a start. Hot-path discovery
  is filesystem-only; the ungated health endpoint reporting ready + live
  pid is probed by lifecycle callers only, and `status == "ready"` is the
  sole liveness predicate. `adr-039` service-lifecycle architecture is
  amended, not replaced, to add the discovery file. The design is
  validated by a live specimen: recon found a stale engine discovery file
  (plausible "ready" state, dead pid, 20-hour-old heartbeat) that would
  have misdirected any file-trusting client - exactly the Crashed case
  attach-never-own exists for
  (`2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference`). All A2A runtime state (graph cache, logs, queues, tmp)
  relocates out of `.vault/` into the same machine-global home - vaultspec
  firmware rejects foreign directories inside `.vault/`, and
  `control/worker_management.py` still points at the old `.vault/runtime`
  path; the parked `.vault-local-state-moved-20260703/` contents are
  restored there or discarded.
- **R9 - CLI surface re-established, minimally.** The brief's declared
  surface is CLI + engine-facing REST/SSE + health, but no `vaultspec-a2a`
  entrypoint exists. A minimal operator CLI (serve, doctor/service-state,
  presets-list, run-start/status/cancel against the local gateway) is
  restored as a thin client of the same five-verb surface - no second code
  path. Anything beyond operator parity with the five verbs is out of
  scope.
- **R10 - Gateway/worker split retained.** The split (gateway FastAPI +
  spawned worker process) is kept as-is through conformance; simplification
  is out of scope until after the acceptance criteria pass.
- **R11 - Rag-led discovery is the working method.** The repo is presumed
  semantically misorganised; identifier names and directory layout are not
  trusted as a map. All discovery during conformance work - code and vault -
  leads with vaultspec-rag semantic search (`--type code` for source,
  `--type vault` with a doc-type filter for decisions), with grep reserved
  for exact-symbol confirmation. Every plan step that involves locating code
  or decisions must instruct rag-first discovery explicitly. Per the
  owner's qualifier this extends beyond location to trust: what a local
  document or convention claims about the code is a hypothesis to test
  against the code itself, never a fact to build on.
- **R12 - Local ADR dispositions.** As enumerated in the supersession map of
  `2026-07-14-a2a-edge-conformance-reference`: UI-serving ADRs superseded;
  protocol ADRs amended to drop Google-A2A; read-mount and gating ADRs
  amended to route artifact production through the authoring API; `adr-17`
  amended per R5; topology, worker-process, database, provider, and
  layer-boundary ADRs preserved subject to R1 verification. "Preserved" is
  provisional under the owner's qualifier: every preserved record remains
  suspect until a step has tested its claims, and dispositions may be
  revised on audit evidence without reopening this record.

## Rationale

Salvage-and-verify wins because both alternatives fail a knockout: trusting
the external survey builds the contract's most security-sensitive code
(token handling, write seam) on an unverified runtime, and a fresh
orchestrator discards the preset/topology/queue investment the dashboard
chose this repo for. The posture has already paid for itself: the
verification pass it demanded disproved "presumed broken" for the standalone
layer, located the real write seam at a single ACP RPC chokepoint rather
than a diffuse tool inventory, and narrowed the remaining risk to
worker-gateway dispatch and one live agent turn. The greenfield finding (no
in-graph authoring tool exists) removes the "swap" framing entirely: since
Workstream 1 is new construction either way, the only question is what
runtime it lands on, and R1 answers that with evidence instead of
assumption. Structured denial at the chokepoint (R2) is preferred over
silent exclusion because the engine's own denial contract treats denials as
readable values - agents are steered, not stranded. Binding to the served
tool catalog (R4) follows the brief's own preference and keeps tool shapes
versioned with the engine that owns them.

## Consequences

- Every document an agent produces becomes a human-reviewed proposal in the
  dashboard lane; this repo's agents lose all direct vault mutation,
  including through their coding-CLI file tools, enforced by the `.vault/**`
  path policy at the ACP filesystem RPC chokepoint.
- The verification gate adds an upfront phase before any visible
  conformance progress, but converts the unknown-unknowns of a stale repo
  into a checklist and preserves the fallback decision point.
- Binding worker tools to the engine catalog means engine upgrades can
  change our tool surface mid-run; run-start snapshots the catalog per run
  to fence this.
- The five-verb gateway makes the existing richer `/api` surface (thread
  metadata, permissions, messages) internal-only; anything the dashboard
  needs beyond the five verbs is a cross-repo contract event, not a local
  addition.
- Two repos now hold halves of one contract; the mirrored reference must be
  kept in sync with the dashboard's brief, and drift between them is itself
  a defect.
- Deleting the UI and its contract-validation CI gate removes the repo's
  only end-to-end consumer of the SSE surface; the plan must replace that
  coverage with gateway-level tests or the streaming layer regresses
  silently.
