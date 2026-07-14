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
