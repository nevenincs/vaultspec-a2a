---
tags:
  - '#plan'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-17'
tier: L3
related:
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-reference]]'
  - '[[2026-07-14-a2a-edge-conformance-research]]'
  - '[[2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference]]'
  - '[[2026-07-14-a2a-edge-conformance-worktree-reconciliation-audit]]'
---

# `a2a-edge-conformance` plan

## Wave `W01` - Salvage verification and hygiene

Close the remaining functional unknowns (worker-gateway IPC dispatch, one real agent turn) and clean the worktree so all later work stands on verified ground. Rag-first discovery applies to every step.

### Phase `W01.P01` - Verification gate

Prove the integrated layer live: worker-gateway IPC dispatch and one real end-to-end agent turn on mock tapes; audit the pytest marker taxonomy. Salvage status is granted only on this evidence.

- [x] `W01.P01.S01` - Boot gateway and worker together and prove live IPC dispatch (worker_connected true, a message round-trips), fixing whatever blocks it; `src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/worker/app.py, src/vaultspec_a2a/api/app.py`.
- [x] `W01.P01.S02` - Execute one full agent turn end-to-end on a mock-tape preset and capture the evidence in the step record; `src/vaultspec_a2a/team/presets/, src/vaultspec_a2a/graph/`.
- [x] `W01.P01.S03` - Audit pytest marker partitioning (unit/core/middleware/service select identical sets today) and repair marker assignments so selections partition the suite; `pyproject.toml, src/vaultspec_a2a/**/tests/`.
- [x] `W01.P01.S33` - Audit the agent/tool provisioning mechanism with live evidence: how a session is constructed, the subprocess spawned, the chat-model adapter bound, and tools actually surfaced to the agent (ACP session wiring, subprocess management, chat-model adapter, provider factory), recording what is proven versus presumed; `src/vaultspec_a2a/providers/_acp_session.py, src/vaultspec_a2a/providers/_subprocess.py, src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/factory.py`.

### Phase `W01.P02` - Worktree and runtime-path hygiene

Commit the pending vaultspec housekeeping, remove dead top-level orphans, and relocate all runtime state out of .vault/ to the machine-global home, repointing code that still expects the old paths.

- [x] `W01.P02.S04` - Review and commit the pending vaultspec housekeeping (managed .gitignore block, vault pre-commit hooks, vaultspec-rag and torch additions) as a standalone commit; `.gitignore, .pre-commit-config.yaml, pyproject.toml, uv.lock`.
- [x] `W01.P02.S05` - Relocate runtime state (graph cache, logs, tmp, queues) to the machine-global A2A home, repoint the .vault/runtime reference rag-first-discovering any other stale path consumers, and discard the parked .vault-local-state-moved-20260703 directory (user decision 2026-07-14: discard, not restore). Land this before S01 if the IPC check trips over the stale path; `src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/infra/, .vault-local-state-moved-20260703/`.
- [x] `W01.P02.S06` - Delete the empty orphan top-level packages (core, cli, tests, bin) and their stale caches after confirming zero inbound references via rag and grep; `src/vaultspec_a2a/core/, src/vaultspec_a2a/cli/, src/vaultspec_a2a/tests/, src/vaultspec_a2a/bin/`.

### Phase `W01.P15` - Git-state reconciliation

Resolve every unmerged branch, worktree, stash, and orphan identified by the reconciliation audit before W02 touches overlapping files. Branch -17 merges or is consciously superseded per the pending owner decision; all discards require the pending owner cleanup authorization.

- [x] `W01.P15.S34` - Review-merge feature/integration-testing-smoke-tests-api-veri-17 in full per the owner decision of 2026-07-14: run the full test baseline before and after, merge with a merge commit (squash and rebase are disabled), and review the diff against current architecture during the merge; `this step blocks W02; `this step blocks W02 and must not proceed before the decision lands; `src/vaultspec_a2a/graph/tools/task_queue.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/streaming/, src/vaultspec_a2a/control/thread_service.py`.
- [x] `W01.P15.S35` - Spot-check feature/entry-point-layer conftest and vowel-counter test diffs for novel coverage, harvesting anything of value into the step record before the branch is deleted; `conftest.py, src/vaultspec_a2a/**/tests/`.
- [x] `W01.P15.S36` - Execute the owner-authorized LOCAL cleanup of 2026-07-14 (destructive): remove the three merged worktrees and angry-jemison, drop all four pre-restructure stashes, delete feature/control-layer and feature/entry-point-layer locally, and remove the orphaned feature-ui-integration-wire-regen-28 directory; `NO remote deletions (origin/claude/* stay), and feature/ci-resolve-vaultspec-core-dep-23 stays untouched pending W02.P03; `defer feature/ci-resolve-vaultspec-core-dep-23 until W02.P03 lands; `git worktrees, git stashes, git branches`.

## Wave `W02` - Deletion mandates and write-seam closure

Execute dashboard ADR D7 deletions (UI, Google-A2A stub) and close every agent-reachable vault write: path-policy denial at the ACP filesystem RPC chokepoint and task-queue relocation out of the vault.

### Phase `W02.P03` - Frontend deletion

Remove src/ui, its static mounting, routes, build steps, recipes, and dev dependencies; A2A is headless.

- [x] `W02.P03.S07` - Delete src/ui entirely, remove the FastAPI static mount and ui_build_dir setting, and rag-first sweep for every route or handler that exists only for the UI; `src/ui/, src/vaultspec_a2a/api/app.py, src/vaultspec_a2a/api/settings`.
- [x] `W02.P03.S08` - Remove UI build steps, dev dependencies, and recipes from the root package.json, Justfile, CI, and pre-commit, and delete the UI contract-validation gate; `package.json, Justfile, .github/workflows/, .pre-commit-config.yaml`.
- [x] `W02.P03.S09` - Run the full default test profile and boot the gateway headless to prove the deletion left no dangling imports or routes; `src/vaultspec_a2a/api/`.

### Phase `W02.P04` - Google-A2A stub deletion and dead-reference sweep

Delete protocols/a2a and scrub every stale protocols.a2a symbol reference; ACP and REST/SSE are the declared transports.

- [x] `W02.P04.S10` - Delete the zero-importer protocol stubs after re-verifying zero importers rag-first at execution time: src/vaultspec_a2a/protocols/a2a/ (dead 3-line stub) and src/vaultspec_a2a/protocols/adapter/ (second 3-line stub, adopted-audit finding); `confirm the parent protocols __init__ needs no change; do NOT touch graph/protocols.py, an unrelated typing.Protocol module whose name collides. Authorized rider on W02's first hygiene commit (W01 review ruling): remove the source-deleted providers/probes/ husk (pycache and empty tests cache only); `src/vaultspec_a2a/protocols/a2a/, src/vaultspec_a2a/protocols/adapter/, src/vaultspec_a2a/providers/probes/`.

### Phase `W02.P05` - Vault write-seam closure

Deny .vault/** writes at the ACP fs RPC chokepoint with a structured forbidden_actor-style denial, and move the worker task queue from the vault markdown table into the A2A database.

- [x] `W02.P05.S11` - Implement the .vault/** deny policy at the ACP fs write RPC handler returning a structured forbidden_actor-style denial that names the authoring tools, leaving reads untouched; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.
- [x] `W02.P05.S12` - Write adversarial mock-free tests for the deny policy covering direct, traversal, symlink, relative-path, and case-variant attempts against a live handler; `src/vaultspec_a2a/providers/tests/`.
- [x] `W02.P05.S13` - Move the worker task queue from the .vault/plan markdown table into the A2A database (new Alembic migration), preserve mark-task-complete semantics, and delete the markdown read-write path; `src/vaultspec_a2a/graph/tools/task_queue.py, src/vaultspec_a2a/database/, src/vaultspec_a2a/graph/nodes/worker.py`.
- [x] `W02.P05.S14` - Prove with live tests that a full mock-tape run performs zero .vault/ writes while the queue and worker loop still function; `src/vaultspec_a2a/graph/tests/, src/vaultspec_a2a/service_tests/`.

## Wave `W03` - Authoring client and solo-coder proof

Greenfield construction of the engine authoring-API client and served-tool-catalog bridge, proven by a solo-coder run producing a research document end-to-end: propose, submit, visible in the dashboard review lane.

### Phase `W03.P06` - Authoring package

Build src/vaultspec_a2a/authoring: loopback httpx client, envelope and tiers decoding, idempotency-key derivation, session lifecycle, proposal verbs. Real tests against a live loopback engine.

- [x] `W03.P06.S15` - Build the authoring package skeleton: loopback httpx client with machine-bearer plus per-actor auth, shared-envelope and tiers decoding, denial-as-value handling keyed on denial_kind; `src/vaultspec_a2a/authoring/`.
- [x] `W03.P06.S16` - Implement session lifecycle (create authoring_session per run, turns, id cross-referencing into thread state) and proposal verbs (create, append, replace, submit, snapshot, conflicts, provenance, rebase) with idempotency keys derived from stable run-local material; `src/vaultspec_a2a/authoring/, src/vaultspec_a2a/thread/`.
- [x] `W03.P06.S17` - Write live mock-free integration tests against a loopback dashboard engine covering the envelope, denials, idempotent replay, and whole-document proposal shapes; `src/vaultspec_a2a/authoring/tests/`.

### Phase `W03.P07` - Served tool-catalog bridge

Fetch and snapshot /v1/agent-tools per run and bridge the catalog into the agent session through the protocols/mcp server, executing via the engine under the calling role's token.

- [ ] `W03.P07.S18` - Fetch and snapshot the engine /v1/agent-tools catalog at run start and bridge it into the agent session as MCP tools, routing execution through the engine execute endpoint under the calling role's token. RESUMPTION STATE (2026-07-15 audit): the mechanism is BUILT and PROVEN at the protocol layer (S19 is checked; `the audit's s20-deferral-ruling records the stdio bridge as operational in real headless CLI sessions - spawned, all seven catalog tools served, both registration channels, both transports). This checkbox stays open on SUBSTANCE, not code: the pinned CLI (2.1.210, adapter 0.23.1) never surfaces non-user-global MCP servers to the model (matches upstream issues 40314, 57033), so an agent never actually sees the bridged tools in production. Re-arm criterion: re-run the S20 matrix probe on each CLI/adapter release; close S18/S20 together when surfacing lands. Evidence: `.vault/audit/2026-07-15-a2a-edge-conformance-w03-review-audit.md` (s20-deferral-ruling finding).; `src/vaultspec_a2a/authoring/, src/vaultspec_a2a/protocols/mcp/tools/`.
- [x] `W03.P07.S19` - Wire the bridged tools into the ACP subprocess session and the worker node so spawned CLI agents see propose and read tools but no vault write path, proven by live tests against the engine and a real subprocess; `src/vaultspec_a2a/providers/, src/vaultspec_a2a/graph/nodes/worker.py`.

### Phase `W03.P08` - Solo-coder end-to-end proof

A vaultspec-solo-coder run produces a research document as a proposed changeset: propose, submit, human-visible in the dashboard review lane, with zero .vault/ writes anywhere in the run.

- [ ] `W03.P08.S20` - Drive a vaultspec-solo-coder run that produces a research document as propose then submit, confirm human visibility in the dashboard review lane, and record proposal and changeset ids in thread state. RESUMPTION STATE (2026-07-15 audit): blocked on the same upstream CLI tool-search surfacing gap as S18 (dashboard-observed proposal proof needs the agent to actually reach the bridged propose tool, which the pinned CLI does not currently surface). The audit ruled this open correctly, not a missed step - two named backstops: (1) re-arm and re-probe on every CLI/adapter release, and (2) W05.P14 (S31) cannot pass without this proof, so the PROGRAM does not close until resolved. Evidence: the s20-deferral-ruling finding in .vault/audit/2026-07-15-a2a-edge-conformance-w03-review-audit.md; `(2) W05.P14 (S31) cannot pass without this proof, so the PROGRAM does not close until resolved. Evidence: `.vault/audit/2026-07-15-a2a-edge-conformance-w03-review-audit.md` (s20-deferral-ruling finding).; `src/vaultspec_a2a/team/presets/teams/, src/vaultspec_a2a/service_tests/`.
- [x] `W03.P08.S21` - Assert zero .vault/ filesystem writes across the whole proof run via filesystem watch or audit and capture the evidence in the step record; `src/vaultspec_a2a/service_tests/`.

## Wave `W04` - Actor tokens and the five-verb gateway

Accept the engine-provisioned per-role token bundle at run-start, thread tokens to owning workers without logging or sharing, and expose the five stable versioned verbs the engine pass-through forwards; restore the minimal operator CLI.

### Phase `W04.P09` - Token-bundle intake and threading

run-start accepts the engine-provisioned per-role actor token bundle; each token lives only in its owning worker's runtime state, is never checkpointed or logged, and is dropped at run end.

- [x] `W04.P09.S22` - Accept the per-role actor token bundle on run-start, hold each token in worker-scoped runtime state only (never checkpointed, never logged, redacted from any payload logging), inject per worker, drop at run end; `src/vaultspec_a2a/api/, src/vaultspec_a2a/control/, src/vaultspec_a2a/worker/`.
- [x] `W04.P09.S23` - Write live tests proving token isolation per role, absence from checkpoints and logs, and disposal at run end; `src/vaultspec_a2a/worker/tests/, src/vaultspec_a2a/control/tests/`.

### Phase `W04.P10` - Five-verb gateway surface

Reshape the existing /api surface into versioned run-start, run-status, run-cancel, presets-list, and service-state endpoints; SSE frames become versioned, bounded, droppable; run-status is the recovery read.

- [x] `W04.P10.S24` - Reshape the gateway into the five versioned verbs (run-start, run-status, run-cancel, presets-list, service-state), designing run-status as the authoritative recovery snapshot with topology position, per-role state, and produced proposal ids; `src/vaultspec_a2a/api/`.
- [x] `W04.P10.S25` - Version and bound the SSE progress frames (droppable, non-authoritative) and cover the five verbs plus stream with live gateway tests replacing the deleted UI contract coverage; `src/vaultspec_a2a/streaming/, src/vaultspec_a2a/api/tests/`.

### Phase `W04.P11` - Operator CLI restoration

Restore a minimal vaultspec-a2a CLI as a thin client of the five-verb surface: serve, doctor, presets, run start/status/cancel. No second code path.

- [x] `W04.P11.S26` - Restore the vaultspec-a2a operator CLI as a thin client of the five-verb surface (serve, doctor, presets, run start/status/cancel) with a console-script entrypoint and live tests; `src/vaultspec_a2a/cli/, pyproject.toml`.

## Wave `W05` - Discovery contract, ADR dispositions, full-team acceptance

Publish the machine-global discovery and heartbeat contract, ratify local ADR supersessions and amendments, and run a full multi-role team preset to the acceptance criteria, flagging the dashboard composition re-arm.

### Phase `W05.P12` - Discovery and heartbeat contract

Publish machine-global service.json with pid, port, and heartbeat plus the ungated health endpoint reporting ready and live pid, satisfying the engine's attach-never-own predicate.

- [x] `W05.P12.S27` - Publish and heartbeat the machine-global service discovery file with pid and port from the resident gateway, expose the ungated health endpoint reporting ready plus live pid, and amend service lifecycle handling for attach-never-own; `src/vaultspec_a2a/lifecycle/, src/vaultspec_a2a/api/`.
- [x] `W05.P12.S28` - Write live tests for discovery freshness, stale-pid detection, single-resident-service semantics, and health-while-degraded; `src/vaultspec_a2a/lifecycle/tests/`.

### Phase `W05.P13` - Local ADR dispositions and documentation

Ratify the supersession map through the owning ADR verbs, amend preserved records, and rewrite the README and project docs to the headless mission.

- [x] `W05.P13.S29` - Ratify local ADR dispositions through the owning ADR verbs (supersede UI-serving records, amend protocol, queue, gating, and module-hierarchy records) per the conformance ADR supersession map; `.vault/adr/`.
- [x] `W05.P13.S30` - Rewrite README and project documentation to the headless orchestration-sibling mission, removing every UI and Google-A2A claim; `README.md, docs/`.

### Phase `W05.P14` - Full-team run and acceptance verification

Run a multi-role team preset through the engine pass-through and verify every acceptance criterion; flag the dashboard multiagent-composition re-arm as a cross-repo event.

- [ ] `W05.P14.S31` - Run a full multi-role team preset through the engine pass-through, verify each brief acceptance criterion including mid-run kill honesty and restart recovery from run-status, and record evidence. RESUMPTION STATE (2026-07-15 audit): HARD-BLOCKED on S20 per the audit's own ruling (W05.P14 cannot pass without the dashboard-observed proposal proof) - do not attempt this step until S18/S20's upstream CLI surfacing gap closes. Not an independent gap, resolving S20 is the unblock; `resolving S20 is the unblock.; `src/vaultspec_a2a/service_tests/, src/vaultspec_a2a/team/`.
- [x] `W05.P14.S32` - Raise the dashboard multiagent-composition re-arm as a cross-repo contract event with the first composing two-agent run as evidence; `.vault/exec/`.

### Phase `W05.P16` - Relay activation and resident-stack health

Close the two dashboard-reported blockers for Transcript live-frame wiring: the stale resident gateway at the :8000 discovery point lacking the run-stream route, and the broken worker-gateway-authoring wiring that kills every run at ingest before progress frames are emitted. Ends with a cross-repo evidence handoff proving contract-correct token, tool_call, and agent_status frames reach the engine relay.

- [ ] `W05.P16.S37` - Diagnose and fix the worker-gateway-authoring wiring defect where workers heartbeat a dead gateway port and authoring_backend_reachable is false, causing WorkerExecutionError at graph ingest (httpx.ConnectError) and INGEST_ERROR terminal frames on every run. Ground rag-first in worker_management spawn-env propagation, lifecycle manager env overlay, and registry ProcRecord re-injection. Prove with a live mock-autonomous run that reaches terminal completed while emitting token, tool_call, and agent_status frames; `src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/lifecycle/, src/vaultspec_a2a/streaming/, src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `W05.P16.S38` - Promote the current build to the machine-global :8000 discovery point (restart the resident gateway so its OpenAPI serves the run-stream route) and add a doctor staleness check that detects a resident serving an older route set than the installed source, so a stale resident is diagnosable instead of silently 404ing the engine relay; `src/vaultspec_a2a/lifecycle/, src/vaultspec_a2a/cli/, src/vaultspec_a2a/api/`.
- [ ] `W05.P16.S39` - Run the end-to-end D3 relay proof through the engine pass-through stream against the healthy resident stack, capture contract-correct frame evidence (envelope fields, sequence, replay) in the step record, and raise the cross-repo re-arm event to the dashboard team mirroring the S32 pattern; `src/vaultspec_a2a/service_tests/, .vault/exec/`.

## Description

Bring this repository into conformance with the frozen dashboard edge
contract as adopted by the governing ADR: verify the salvageable core, then
execute the deletion mandates (frontend, Google-A2A stub), close every
agent-reachable vault write at the ACP filesystem chokepoint, build the
engine authoring-API client and served-tool-catalog bridge greenfield, prove
one solo-coder run end-to-end as a reviewable dashboard proposal, accept and
thread engine-provisioned per-role actor tokens, expose the five-verb
gateway with a minimal operator CLI, publish the machine-global discovery
and heartbeat contract, ratify the local ADR supersession map, and close
with a full multi-role acceptance run.

This is plan 1 of a program, and the owner expects the program to take more
than one plan: the project is unproven and may contain shadows, duplicated
code, and an untested agent/tool provisioning mechanism. Audit findings from
the verification gate and later waves spawn successor plans rather than
inflating this one; this plan's scope is fixed at the steps below. Per the
governing ADR's owner qualifier, local standards, conventions, and prior
ADRs are inputs to verify, never authorities - any step relying on one must
validate it first.

Approved for execution by the owner on 2026-07-14. Decisions recorded at
approval: the parked runtime-state directory is discarded, not restored
(S05); a live loopback dashboard engine will be available for W03 and
later; W01 honors the S05-before-S01 sequencing caveat from
Parallelization.

**Resumability state (2026-07-15 audit):** Executor-of-record: unassigned (W01-W04 and most of W05 are committed and complete). Current frontier: W03.P08.S20 (dashboard-observed solo-coder proposal proof), hard-blocked upstream on the pinned CLI's MCP tool-search surfacing gap (issues 40314, 57033) per `.vault/audit/2026-07-15-a2a-edge-conformance-w03-review-audit.md`'s s20-deferral-ruling; W05.P14.S31 is transitively blocked on S20. A cold resume should re-run the S20 matrix probe against the current CLI/adapter release before attempting either step - do not re-derive the blocker from scratch, it is fully recorded in S18/S20/S31's own row text and the cited audit.

## Parallelization

W01.P01 and W01.P02 can run in parallel (verification touches runtime
behaviour, hygiene touches worktree and paths), except S05 (runtime-path
relocation) should land before S01 if the IPC check trips over the stale
`.vault/runtime` path. W01.P15 (git-state reconciliation) is independent of
P01/P02 and can run alongside them, but S34 (the branch -17 decision) hard-
blocks all of W02: it rewrites the very files P04/P05 will edit. S36's bulk
discard is destructive and waits for the owner's cleanup authorization; it
does not block anything else. Within W02, P03 (UI) and P04 (stub) are
parallel-safe: disjoint file sets; P05 should follow P04 because the
streaming sweep and the deny-policy tests touch neighbouring provider code.
W03 is strictly sequential (P06 client, then P07 bridge, then P08 proof);
each phase consumes the previous one's surface. In W04, P09 (tokens) and
P10 (five verbs) overlap on run-start and should be executed by one agent or
serialized; P11 (CLI) can start once P10's endpoint shapes are stable. W05
phases are independent of each other but all depend on W04 completing; P14
must run last. One coding agent per phase is the sensible dispatch unit;
nothing below phase level should be split across agents.

## Verification

Mission success is the brief's acceptance criteria, verified live and
honestly - tests can be cheated, so each criterion demands observable
evidence, not green checkmarks:

- A pipeline run started through the engine pass-through produces documents
  that appear ONLY as reviewable proposals in the dashboard review lane,
  each attributed to its per-role actor. Evidence: a human sees the proposal
  in the dashboard UI (P08 solo, P14 full team); proposal ids recorded in
  thread state match the engine's records.
- Nothing in any run writes to a `.vault/` path. Evidence: filesystem
  watch/audit across the whole run (S21), plus the adversarial deny-policy
  suite (S12) exercising a live handler.
- Killing A2A mid-run degrades the dashboard honestly (tiers) and a
  restarted A2A resumes or reports the run from run-status. Evidence: the
  S31 kill/restart drill, observed from the dashboard side.
- The repository contains no UI code, no Google-A2A stub, no engine import,
  and no agent-reachable filesystem write into a vault. Evidence: tree
  inspection, import-graph check, and the deny-policy suite.
- Tokens never leak: no token string appears in logs, checkpoints, or
  crash output. Evidence: S23's live isolation tests plus a log scan during
  the P08/P14 runs.

Known honesty limits: W03 and later phases require a live dashboard engine
on loopback (the owner confirmed availability at approval) - if it is ever
absent, the integration tests MUST be reported as not-run, never simulated
with test doubles. SSE relay frames are non-authoritative by contract;
their loss is not a test failure. Unit-level green does not certify the
edge: only the P08 and P14 end-to-end runs, observed from the dashboard,
certify conformance.

Program note: verification here covers THIS plan's steps only. W01 audit
findings (provisioning mechanism, shadows, duplication) that exceed this
plan's fixed scope are success when RECORDED and handed to successor plans,
not when fixed here. Completing all 33 steps does not close the program;
it closes plan 1.
