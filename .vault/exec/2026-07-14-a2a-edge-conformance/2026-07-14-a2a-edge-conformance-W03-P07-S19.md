---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-15'
step_id: 'S19'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Wire the bridged tools into the ACP subprocess session and the worker node so spawned CLI agents see propose and read tools but no vault write path, proven by live tests against the engine and a real subprocess

## Scope

- `src/vaultspec_a2a/providers/`
- `src/vaultspec_a2a/graph/nodes/worker.py`

## Description

Wired the engine's bridged authoring tools into the spawned CLI agent's session, per ADR R4, across two halves.

Served side: a per-run authoring MCP server built on the low-level MCP server surface (explicit list-tools and call-tool) so the catalog's dynamic tools carry their engine JSON input schemas, which the signature-derived FastMCP surface cannot express. It advertises exactly the catalog's tools and routes each call back through the engine's run-scoped execute endpoint via an injected dispatcher.

Worker side: a worker-scoped authoring binding holds the per-run catalog snapshot, the loopback server url, and both auth tokens, redacted from its representation and never placed in graph state or a checkpoint. It enforces two construction invariants — the server url must be loopback, and no surfaced tool may look like a raw filesystem write, so a drifted catalog fails loudly rather than handing an agent a write path. A builder emits the session-new mcpServers entry carrying the machine bearer and the per-actor token as headers. The worker node, when a run carries a binding and the model exposes an ACP mcp-servers surface, augments the model so the spawned CLI's session-new advertises the loopback authoring server; mock and hosted-API models are left untouched. The chat model threads mcp-servers through to session-new, and the ACP simulator records what session-new receives.

Observed advertised tool set (the seven semantic tools): read_context, search_graph, propose_changeset, validate_proposal, request_approval, cancel, request_apply — and no filesystem-write tool of any kind.

- Modified: `src/vaultspec_a2a/graph/nodes/worker.py`, `src/vaultspec_a2a/providers/acp_chat_model.py`, `src/vaultspec_a2a/graph/tests/acp_simulator.py`, `src/vaultspec_a2a/protocols/mcp/tools/authoring_bridge.py`
- Created: `src/vaultspec_a2a/providers/_acp_authoring.py`, `src/vaultspec_a2a/providers/tests/test_acp_authoring.py`, `src/vaultspec_a2a/providers/tests/test_acp_authoring_bridge.py`, `src/vaultspec_a2a/graph/tests/nodes/test_worker_authoring_wiring.py`, `src/vaultspec_a2a/protocols/mcp/tests/test_authoring_bridge.py`

## Outcome

Committed dc9d3c0 (served bridge) and 014e9a2 (worker/session wiring). Proven at three levels, all mock-free: the real MCP protocol (an in-memory connected client drives the exact list-tools/call-tool path a spawned agent uses) shows the agent sees exactly the propose and read tools and no filesystem-write tool; a real ACP-protocol subprocess simulator receives session-new carrying the authoring server plus both auth headers, and receives an empty server list when no binding is present; and a real claude-agent-acp subprocess accepts the config at session-new and connects to the live authoring MCP server at session setup. 140 unit and wiring tests plus one service-marked live subprocess test are green; ruff, format, and ty all clean.

## Notes

A live probe corrected the mcpServers HTTP entry shape: the ACP schema REQUIRES a headers array — a session-new without it is rejected with a validation error naming the missing field. The worker-side builder carries the bearer and actor tokens there. A duplicate auth-less config builder introduced in the served-bridge commit was removed in favour of the single worker-side builder, so there is no way to surface the authoring server without its auth headers. The real agent connects to the MCP server eagerly at session-new (before any prompt), so the tool-advertisement proof needs no authenticated turn or spend; the authenticated propose-then-submit turn is the S20 deliverable.

Correction note (2026-07-15, reconciled at adr-authoring-orchestration P05.S14): this step wired the binding MECHANISM only. It did not, and does not, create a production construction site for the binding — a real run never builds one, and the worker default leaves it unset. This was the explicit S20 deferral, not an omission. The production wiring amendment splits the two tool-exposure mechanisms deliberately: document topologies such as research_adr author through the in-process graph-submitter path, which needs no binding; the MCP bridge this step wired is the agent-initiated path for CLI-coder presets and stays behind the upstream re-arm watch. So the absence of a binding construction site is the correct, decided posture, not a gap to fill. The S20 leaf proof remains open as that watch item.
