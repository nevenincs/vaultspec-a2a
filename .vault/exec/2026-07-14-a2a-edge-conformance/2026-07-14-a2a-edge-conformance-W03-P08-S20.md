---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-19'
step_id: 'S20'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Drive a vaultspec-solo-coder run that produces a research document as propose then submit, confirm human visibility in the dashboard review lane, and record proposal and changeset ids in thread state

## Scope

- `src/vaultspec_a2a/team/presets/teams/`
- `src/vaultspec_a2a/service_tests/`

## Description

- Build a per-run stdio MCP bridge subprocess that reconstructs the run's engine dispatch from its environment and serves the engine catalog's propose and read tools over stdio, reusing the transport-agnostic tool-spec and dispatch core from the served bridge.
- Extend the worker tool binding to carry the engine origin and run id, add a stdio config builder, and make the worker prefer the stdio transport when those engine facts are present.
- Force eager MCP tool loading for bridged runs so the deferred-tool path cannot hide the bridged schemas, scoped to bridged runs only.
- Prove the bridge end to end without the CLI: a real MCP client lists and calls tools through the running bridge against the live engine, and a debug startup marker confirms the bridge spawns and serves inside the real headless CLI session.
- Drive real headless solo-coder turns against the live engine across every registration channel to locate whether the bridged tools reach the model.

## Outcome

The stdio authoring bridge is complete and verified at two independent layers: the MCP protocol layer (a real client performs list and call through the bridge to the engine) and operational inside the real headless CLI session (a startup marker shows the CLI spawned the bridge and it served all seven catalog tools, under both the session-injected and workspace-config channels).

The end-to-end proof that the solo-coder agent itself calls propose then submit is DEFERRED, blocked by an external limitation that was fully characterized across a complete registration matrix. The pinned stack tested is Claude CLI 2.1.210 and the ACP adapter 0.23.1 (both latest at time of test, per the owner directive to run bleeding edge). On that stack, MCP servers provided at the workspace or session level connect, pass approval, spawn, and serve their tools, yet the model is only ever shown the servers registered in the user-global home configuration. Every matrix cell was exercised with a real spend turn: session-injected over HTTP and over stdio; workspace config registration with name approval over HTTP and over stdio with eager loading. All served their tools; none surfaced to the model. Only the user-global servers surfaced, and project policy forbids writing to the user-global configuration.

Token hygiene held throughout: the workspace config file carried only environment-variable references for the machine bearer and actor token, expanded by the CLI from its own process environment at spawn, so no token was ever written to disk. Zero filesystem writes to the vault occurred across every run.

## Notes

- Root cause is an external CLI or adapter limitation, not this repository's code; it persists on the latest CLI and adapter. The differentiator is user-global registration scope, not transport, not session versus config, and not tool search.
- A debug-gated startup marker was left in the bridge module; it is inert unless an environment variable points it at a writable path and it never emits tokens.
- The implementation, its unit tests, two live service tests, and the adapter version bump live on branch feature/stdio-authoring-bridge (commits edacf1f, d9c8f99, b3748c4). Merge-back and the final done-or-defer disposition are owner decisions.

## CLOSURE (2026-07-19) - agent-authored changeset proven live; closed together with S18

The deferred end-to-end proof is now GREEN, deterministic, on the canonical
driver `service_tests/test_s20_solo_coder_bridge_live.py` (engine-side
unforgeable assertion; narration never asserted). Final runs `pw7-1784410892`
and `pw7-1784411858` (the latter on the merged/handover state: a2a `1406d1c`
= dual-path normalizer + driver op-mode; engine catalog branch tip
`2e7980ce8c`):

- `cs:<run_id>:bridge` changeset landed WITH real content in
  `/authoring/v1/proposals`, status=draft (the human-visible review lane),
  operation_count>0, session_id set - the coder constructed a valid
  `create_proposal` (create_document / provisional_create / whole_document)
  from the engine-inlined served schema, including the correct
  `kind=provisional_create` selection and `collision_status` enum.
- The full chain this run exercises, each layer previously proven in
  isolation: DSL-to-JSON-Schema normalization (registration), run-ws
  projection (surfacing), ancestor-walking deny-pin (ambient-leak closure,
  listener-grade zero connections), dispatch-side proposal-lifecycle id
  injection (one engine session per run via the submitter's constant
  create_session key; session_id/changeset_id/expected_revision never in the
  model contract), engine catalog content inlining (task #44 both halves),
  and the declared-mode handshake (driver sets engine
  operation-mode=autonomous per the pw7 AUTO-lane precedent, so the mutating
  propose auto-approves INTO review while apply stays human-gated).
- Zero `.vault` filesystem writes (driver before/after snapshot delta empty);
  placeholder-only projected `.mcp.json`; real-engine `deny_unknown_fields`
  validation enforced and satisfied.
- Follow-ups recorded, not blockers: production autonomous dispatch should
  set the engine operation-mode at run start when `req.autonomous`
  (architect question); the engine catalog branch (`engine-catalog-inline`
  through `2e7980ce8c`) and the role-key fix (`412519a59d`) are owed a
  dashboard-side landing; projection-collision remedy for real-project run
  workspaces (see the S18 record closure).
