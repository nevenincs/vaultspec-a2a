---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
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
