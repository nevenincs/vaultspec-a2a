---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S18'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Fetch and snapshot the engine /v1/agent-tools catalog at run start and bridge it into the agent session as MCP tools, routing execution through the engine execute endpoint under the calling role's token

## Scope

- `src/vaultspec_a2a/authoring/`
- `src/vaultspec_a2a/protocols/mcp/tools/`

## Description

Bridged the engine's served agent-tool catalog into the run, per ADR R4. A catalog module fetches and snapshots the catalog once per run, mirroring each tool's name, input schema, risk tier, and permission requirement rather than assuming a one-to-one mapping to wire routes. Tool execution routes back through the engine's run-scoped execute endpoint as a command envelope wrapping the agent-tool call, under the calling role's actor token; the envelope shape was confirmed against the engine source. The session now captures the engine run id from the start-turn receipt so execute has a run to target. A bridge helper maps a snapshot to MCP tool specifications, preserving the engine risk tier and permission requirement for the session wiring to honour; only the catalog's tools are surfaced, so the agent gets propose and read tools and no vault-write path.

- Created: `src/vaultspec_a2a/authoring/catalog.py`, `src/vaultspec_a2a/authoring/tests/test_catalog_unit.py`, `src/vaultspec_a2a/protocols/mcp/tools/authoring_bridge.py`
- Modified: `src/vaultspec_a2a/authoring/session.py`, `src/vaultspec_a2a/authoring/__init__.py`, `src/vaultspec_a2a/authoring/tests/test_live_engine.py`

## Outcome

Committed 5f1a1ca. Verified live against the engine: start-turn mints the run id, the catalog fetch returns the seven-tool schema, and a run-scoped execute of the read-only search-graph tool returns a dispatched disposition with eligibility allowed. The command discriminator for execute is the tool's own command. 43 mock-free unit tests plus 9 service-marked live tests pass; ruff, format, and ty all clean. Binding these specs into the ACP subprocess session and the worker node is S19.

## Notes

The run-scoped execute path needs an active run, so its live proof chains start-turn to obtain the run id before executing. The engine owns permission gating: mutating tools carry a human-approval requirement, so a business denial returns as a value rather than an error.

## Surfacing-channel re-arm and live proof (2026-07-17, executor-service)

The pinned CLI surfaces only user-global home-config MCP servers, so the per-run authoring bridge this step built was connected-but-never-surfaced in production (the S20 deferral recorded below). The surfacing admission channel now lands and is proven live.

### What landed (code)

- `config_home_authoring_entry` in `providers/_acp_authoring.py`: a shape-guarded selector that admits ONLY the run's own stdio bridge (name `vaultspec-authoring`, args exactly `["-m", <AUTHORING_STDIO_MODULE>]`) into the isolated `CLAUDE_CONFIG_DIR` home as a user-scope stdio server whose env is ALL `${VAULTSPEC_AUTHORING_*}` placeholders, returning atomically the name-to-real-value map hoisted into the CLI spawn env. Composed at the `acp_chat_model` spawn seam alongside the read-only harness registry. The registry trust root is untouched and never sees the bridge. Full design and the boundary are in the `2026-07-17-tool-cores-adr` amendment.
- Real-seam tests, including a real-subprocess composition test driving the production `AcpChatModel` spawn: the on-disk `.claude.json` carries only the `${VAR}` placeholders while the real bearer rides the spawn env, so the zero-secret-on-disk contract holds through the production path.

### Live proof (attached dashboard engine, both lanes)

Against the live engine (catalog of 7 tools: read_context, search_graph, propose_changeset, validate_proposal, request_approval, cancel, request_apply), a binding built in-harness (standing in for the not-yet-existing S20 production construction site) drove a real CLI through the production spawn seam:

- Surfacing config correct on BOTH lanes: the production spawn logged the isolated home "surfacing 1 server(s)", the bridge written as a user-scope stdio server, placeholder-only env, no real token on disk, and zero agent-origin `.vault` writes.
- `${VAR}` expansion works on BOTH the Z.ai vendored 0.59.0 binary AND the system `claude.exe` (Claude lane, model claude-4.6-sonnet): the bridge subprocess spawned and served all 7 tools, which is only possible if the CLI expanded the placeholders to the real engine values at parse time. An engine-side logging reverse-proxy captured the bridge's catalog `GET /authoring/v1/agent-tools`.

### Open finding: bridge tools not exposed to the model (model-independent)

The bridge SERVER connects but its TOOLS are never exposed in-session, so no invocation and no engine `execute` POST occur. Real Claude reported verbatim that the server "reported as connected via WaitForMcpServers, but the tool itself is not exposed in this session" (repeated calls returned "No such tool available"); GLM-4.7 likewise never received it (it fell back to Z.ai built-in tools). This is NOT a lane limit and NOT a surfacing-config bug:

- Control: the fast rag server's tool DID reach GLM through the IDENTICAL direct harness (a real "not a vaultspec project" server error came back), and tool-cores `2026-07-17-tool-cores-P03-S17` proved rag end-to-end on the Z.ai lane. Rag works, the bridge does not, same home mechanism, so the failure is bridge-specific.
- Leading cause: bridge cold-start latency. Measured launch-to-serving is 7.5s, of which the `vaultspec_a2a.authoring` import is 6.21s and the catalog fetch only about 0.05s against the warm local engine; rag's uvx launch is under 1s. "Connected but tools not exposed" is the slow-MCP-server signature: the CLI captures the session tool set before the bridge's tools/list, gated behind the heavy import, lands. This is a leading candidate grounded in the timing and rag contrast, not a certainty about the CLI internals.
- Candidate remedy (S20 scope, not implemented here): hand the worker's per-run catalog snapshot to the bridge so tools/list serves immediately with the engine fetch deferred to execution time (this also closes the independent catalog re-fetch drift window at `authoring_stdio.py`), and slim the bridge import path so the heavy authoring-package init is off the startup critical path.

### Dependency and close-together posture

This step wired the bridge MECHANISM only; there is still no production construction site for the `AuthoringToolBinding` (per S19's own correction note), so a real preset run never builds one. That production wiring is the S20 substance, tracked separately. Per this row's own re-arm criterion to close S18 and S20 together, S18's checkbox waits for S20 regardless: the surfacing channel proven here is the prerequisite, and the live model-exposure proof belongs to the S20 solo-coder run once both the binding-construction site and the bridge tool-exposure fix land.

## Tool-exposure root cause SETTLED + fix (2026-07-18, executor-service-3) — interim, no closure claim

The "bridge SERVER connects but its TOOLS are never exposed" open finding above is now root-caused and fixed. This is an honest interim state: the fix is validated at the tool-surfacing layer but the full S20 engine-side changeset proof is not yet green (it is being driven separately), so no S18/S20 closure is claimed here.

The two hypotheses carried into this session were both refuted. Adapter `${VAR}` non-expansion: refuted — the "Live proof" section above already showed the bridge spawning and serving all 7 tools with real engine values, which is only possible if the CLI expanded the placeholders. Autonomous flag not reaching the worker node: refuted — `autonomous=True` propagates intact end to end (`_run_start` body -> `gateway.py:183` -> `resolve_autonomous(True)=True` -> `DispatchRequest.autonomous` -> `graph_lifecycle` keeps `req.autonomous` on a fresh run; the cache override only fires on a preset-less resume -> `compile_team_graph(autonomous=True)`), so `allowed_tools` populates and `ENABLE_TOOL_SEARCH=0` is set.

The real cause is a timing race against the CLI. Discriminated stack-free against the pinned claude 2.1.214 (isolated `CLAUDE_CONFIG_DIR` home + a trivial stdio MCP server, a marker file recording spawn/serve as unforgeable evidence, no engine needed): a fast stdio server's tool is invoked by the model under `ENABLE_TOOL_SEARCH=0`; a server that sleeps 2s or 8s before serving is reported UNAVAILABLE even though its marker shows it DID serve — its tools simply never enter the session. The pinned CLI has a hard ~1.3-2s MCP-server-READY window at session start; `ENABLE_TOOL_SEARCH=0` only controls eager-vs-deferred indexing of tools that made it into that window, it does not extend the window. This exactly matches the differential the coherent-stack run observed (fast `uvx` `vaultspec-core` stdio surfaces to GLM; the slow authoring bridge does not) and the `pw7-1784348007` zero-changeset signature.

Why the bridge was slow: importing `vaultspec_a2a.protocols.mcp.authoring_stdio` ran the package `__init__` chain (`protocols/__init__` -> `from .mcp import mcp` -> `protocols/mcp/__init__` -> `from .server import mcp`), eagerly pulling the FastMCP server + `thread_lifecycle` + langgraph/langchain stack the bridge never uses (~1.35s warm, ~7.5s cold with the langgraph tree scanned on a cold cache). Fix: resolve the package-level `mcp` attribute lazily (PEP 562 `__getattr__`) in both `protocols` and `protocols.mcp`, matching the existing graph-package lazy-init precedent. Launch-to-serving drops to ~0.85s warm and the real bridge tool now surfaces to the model deterministically through the production spawn shape. Committed `7cb2b55` on branch `fix/bridge-coldstart-lazy-mcp-init` (additive, held for review). Durable constraint: any per-run stdio MCP entrypoint must serve `tools/list` well under ~1.3s or its tools silently vanish — import-chain weight in an MCP entrypoint is a correctness constraint, not a perf nicety.

## Re-probe of the full remedy chain (2026-07-18, executor-service-3) — interim RED, new projection-collision signature, no closure

Re-ran the purpose-built S20 probe (`service_tests/test_s20_solo_coder_bridge_live.py::test_solo_coder_invokes_bridged_authoring_tool_midturn`) against a freshly bounced resident on current HEAD `ece867e`, carrying the whole landed remedy chain (lazy MCP init `7cb2b55`, run-ws `.mcp.json` projection `f1b63d4`/`54969f1`, spawn-inside-cleanup `7cad8b6`, schema normalization `db7400a`, oneOf invocability `4c393c8`, dispatch-side proposal-lifecycle id injection `acfc66d`). Pre-step verified: doctor `stale_resident:false`/exit 0, fresh gateway-owned worker with correct `gateway_url` provenance, engine reachable, `VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true` and `VAULTSPEC_ENGINE_SERVICE_JSON` pinned at boot.

Verdict: RED, exposure still UNPROVEN — but the blocker has moved DOWNSTREAM of the cold-start race fixed above, to a new signature. The run (`pw7-1784409828`) dispatched, the coder worker started, and the worker died in `graph/nodes/worker.py` with a `WorkerExecutionError` whose direct cause is:

`ProjectionRefusedError: refusing to overwrite a foreign .mcp.json at Y:\code\vaultspec-dashboard-worktrees\main\.mcp.json: it lacks the '_vaultspec_projection' projection marker`.

Root of the new signature: the run-ws projection (`providers/_acp_project_mcp.py::project_declared_mcp`) writes the bridged authoring surface to `{run_workspace}/.mcp.json`. For an authoring-bridge run the workspace resolves to the ENGINE's workspace — the acceptance harness sets `workspace_root = vault_root.parent` (`test_pw7_acceptance.py`), i.e. the engine's real project root — and that root carries a real, git-tracked `.mcp.json` (the dashboard project's own dev MCP config: vaultspec-core, figma, playwright, vaultspec-rag; dated well before this run, no projection marker). The collision guard correctly refuses to clobber the foreign file, so the bridged `.mcp.json` is never projected, the CLI is never launched with the authoring surface, no `propose_changeset` is invoked, and no `cs:pw7-1784409828:*` changeset appears in `GET /authoring/v1/proposals` — the test's unforgeable assertion fails on an empty changeset set. This is NOT a lane/credential gate (Claude was never reached), NOT the cold-start timing race (that fix holds: the bridge is fast now), and NOT tools-not-exposed-in-session (projection never ran).

Assessment: this is a real remedy-chain gap, not a probe artifact. Projecting the bridge into the run-workspace ROOT collides with the near-universal presence of a project `.mcp.json` whenever the run workspace is a real vaultspec project (both this repo and the engine's carry one). The collision guard is doing its job — protecting a user file — so the fix belongs on the projection side, not the guard. Candidate remedies (S20 scope, NOT implemented here): project into an isolated per-run scratch cwd distinct from the rule-scoping workspace_root, or MERGE the bridge entry into an existing `.mcp.json` (adding only the marked bridge server alongside the user's servers and removing only the marked addition on cleanup) rather than refusing the whole write. Not forced here (would require mutating another repo's committed `.mcp.json`, an invalid environment change); reported honestly instead.

S18/S20 remain OPEN — no closure. The close-together posture is unchanged: S20's engine-changeset proof cannot go green until the bridged surface actually reaches the CLI in a real authoring-bridge run, which this projection collision now blocks. Re-arm criterion extended: the next S20 probe must run after the projection-collision remedy lands (isolated cwd or merge strategy), not merely on the next CLI/adapter release.

## CLOSURE (2026-07-19) - surfacing proven live end to end; closed together with S20

The projection-collision RED above was the last interim state. The remedy chain
completed and the close-together criterion is now met on live evidence:

- Surfacing channel final shape: the per-run PROJECTED run-workspace
  `.mcp.json` (providers/_acp_project_mcp.py, signed with the
  `_vaultspec_projection` marker) is the load-bearing surfacing channel on the
  adapter path; the isolated config home provides ambient suppression, the
  ancestor-walking deny-pin, and the `enabledMcpjsonServers` allowlist; the
  session-injected and home-`mcpServers` copies remain written as upstream
  re-arm watches. Decision recorded as the 2026-07-18 amendment in
  `[[2026-07-17-tool-cores-adr]]`.
- Live proof (final green runs `pw7-1784410892` and `pw7-1784411858`, the
  latter on the exact merged/handover state: a2a `1406d1c`, engine catalog
  branch tip `2e7980ce8c`): the projected bridge spec served, the coder
  natively invoked `mcp__vaultspec-authoring__read_context` (engine receipt:
  dispatched, allowed, read_only) and `propose_changeset`; served-schema
  captures prove BOTH normalizer paths live (oneOf-DSL translation against
  the pre-inline engine, standard top-level JSON Schema pass-through against
  the inlined engine). Placeholder-only `.mcp.json` on disk; planted ancestor
  collision and `evil-writer` listeners recorded zero connections.
- Carry-forward (open, production hardening, not an S18 gap): projecting into
  a run workspace that is itself a real vaultspec project collides with its
  committed `.mcp.json` (the guard correctly refuses; run `pw7-1784409828`).
  Green runs used clean scratch engine workspaces. Remedy candidates recorded
  above (isolated per-run cwd or marked-entry merge); owed before real-project
  workspaces are used for bridged runs.
