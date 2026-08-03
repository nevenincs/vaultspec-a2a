---
tags:
  - '#plan'
  - '#current-project-binding'
date: '2026-08-03'
modified: '2026-08-03'
body_hash: 'sha256:f9a130e4d9d6452c3856e2049d8ce660d1dafe3948824e3fd036653276b6eb23'
tier: L2
related:
  - '[[2026-08-03-current-project-binding-adr]]'
  - '[[2026-08-03-current-project-binding-research]]'
---

# `current-project-binding` plan

## Steps

### Phase `P01` - contain the live cross-project escapes

Both high-severity findings are reachable today on autonomous document runs, and neither depends on work outside this repository. This phase closes them at the enforcement points the orchestrator already owns, accepting a defensive check that a later phase makes redundant.

- [ ] `P01.S01` - carry the bound project into the permission layer so a refusal has an authority to compare against; `src/vaultspec_a2a/providers/_acp_types.py`.
- [ ] `P01.S02` - refuse a tool call whose arguments name a project other than the one the run is bound to; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.
- [ ] `P01.S03` - replace the autonomous blanket-approve fallback with an exact-name read allowlist on the claude family; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.
- [ ] `P01.S04` - apply the same exact-name read allowlist to the gemini backend, which today falls through to blanket approval; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.
- [ ] `P01.S05` - prove a cross-project read is refused by driving a real search call naming a second workspace; `src/vaultspec_a2a/providers/tests/test_project_confinement.py`.
- [ ] `P01.S06` - prove an undeclared server verb is refused rather than auto-approved under autonomy; `src/vaultspec_a2a/providers/tests/test_project_confinement.py`.

### Phase `P02` - make the active project a run-bound identity

Enforcement needs something to enforce against. This phase mints the project once at admission in one canonical form, carries it explicitly, and moves pinning to the registry and launch seams so the previous phase's check stops being the only thing holding.

- [ ] `P02.S07` - mint the active project once at admission in one canonical form; `src/vaultspec_a2a/control/thread_service.py`.
- [ ] `P02.S08` - carry the minted project across dispatch instead of the raw path string; `src/vaultspec_a2a/ipc/schemas.py`.
- [ ] `P02.S09` - resolve the resolved-versus-stored spelling split so one workspace yields one graph cache entry; `src/vaultspec_a2a/worker/graph_lifecycle.py`.
- [x] `P02.S10` - declare a third trust axis on every registry entry stating whether it is root-pinnable; `src/vaultspec_a2a/providers/_acp_mcp.py`.
- [x] `P02.S11` - refuse composition of a server that cannot be pinned rather than surfacing it unpinned; `src/vaultspec_a2a/providers/_acp_mcp.py`.
- [x] `P02.S12` - add the per-run pinning seam that carries the project to a pinnable server, separate from the frozen registry; `src/vaultspec_a2a/providers/_acp_mcp.py`.
- [x] `P02.S13` - prove a pinned server receives the bound project and an unpinnable one refuses composition; `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py`.
- [ ] `P02.S20` - populate the documented but never written workspace root on graph input so the state key stops being dead capability; `src/vaultspec_a2a/worker/graph_lifecycle.py`.
- [ ] `P02.S21` - pass the bound project into harness server composition at the worker node site; `src/vaultspec_a2a/graph/nodes/worker.py`.
- [ ] `P02.S22` - pass the bound project into harness server composition at the research graph site; `src/vaultspec_a2a/graph/compiler.py`.
- [ ] `P02.S23` - hoist a pinned server declared environment into the spawn environment on the strict claude lane; `src/vaultspec_a2a/providers/acp_chat_model.py`.
- [ ] `P02.S24` - prove a pinned server project reaches the spawned child rather than only the registry spec; `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py`.
- [ ] `P02.S25` - pass the bound project into codex harness spec rendering where the model carries names across the seam; `src/vaultspec_a2a/providers/codex_chat_model.py`.

### Phase `P03` - reconcile the remaining identity gaps

The places where project identity is lost, assumed, or implied but absent: the authoring write channel bound to engine-global state, crash recovery that dispatches without a project, and harness surfaces verified but never consumed.

- [ ] `P03.S14` - carry the bound project on the authoring session rather than a literal scope constant; `src/vaultspec_a2a/authoring/submitter.py`.
- [ ] `P03.S15` - prove a session is never reused across projects so every proposal inherits a session scope that is the bound project; `src/vaultspec_a2a/authoring/session.py`.
- [ ] `P03.S16` - refuse an absent project early and typed in crash recovery, matching the follow-up path; `src/vaultspec_a2a/control/direct_control_recovery.py`.
- [ ] `P03.S17` - reconcile harness verification with the surface a run actually consumes; `src/vaultspec_a2a/context/harness.py`.
- [ ] `P03.S18` - prove the authoring session carries the bound project in the engine own scope spelling and that proposals inherit it; `src/vaultspec_a2a/authoring/tests/test_authoring_scope_binding.py`.
- [ ] `P03.S19` - prove crash recovery refuses a thread whose stored metadata names no project; `src/vaultspec_a2a/control/tests/test_direct_control_recovery.py`.
