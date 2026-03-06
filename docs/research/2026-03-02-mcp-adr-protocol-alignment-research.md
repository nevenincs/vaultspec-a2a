---
name: 'MCP ADR Protocol Alignment'
date: 2026-03-02
type: research
summary: 'Gap analysis between MCP tool surface and ADR-mandated operations. Prioritized recommendations for MCP additions.'
maturity: 70
feature: mcp-surface-alignment
---

# Research: MCP Surface Alignment with ADR-Mandated Operations

**Date**: 2026-03-02
**Status**: Complete
**Requested by**: team-lead (Task 4)
**Builds on**:

- `docs/adrs/011-frontend-backend-contract.md` (wire contract)
- `docs/adrs/012-agent-definition-schema.md` (agent config)
- `docs/adrs/013-team-composition-topology.md` (team config)
- `docs/research/2026-02-25-mcp-tasks-a2a-compliance-research.md` (MCP/A2A protocol)
- `docs/audits/2026-03-02-mcp-surface-audit.md` (MCP audit findings)

---

## 1. Current MCP Tool Surface

The MCP server (`src/vaultspec_a2a/protocols/mcp/server.py`) exposes exactly **3 tools**:

| Tool                | REST Proxy                        | Purpose                            |
| ------------------- | --------------------------------- | ---------------------------------- |
| `start_thread`      | `POST /api/threads`               | Create thread with autonomous=True |
| `get_thread_status` | `GET /api/threads/{id}/state`     | Poll status + message count        |
| `send_message`      | `POST /api/threads/{id}/messages` | Follow-up message                  |

All tools are thin HTTP proxies to the REST API. No WebSocket integration.

---

## 2. ADR-Mandated Operations Not Reachable via MCP

### 2.1 From ADR-011 (Wire Contract) — REST Endpoints

ADR-011 §2.2 defines 6 REST endpoints. MCP coverage:

| Endpoint                         | MCP Tool            | Gap?                                                          |
| -------------------------------- | ------------------- | ------------------------------------------------------------- |
| `POST /threads`                  | `start_thread`      | Partial — forces `autonomous=True`, no `workspace_root` param |
| `GET /threads`                   | **MISSING**         | No tool to list threads                                       |
| `GET /threads/{id}/state`        | `get_thread_status` | Partial — returns human text, not structured data             |
| `POST /threads/{id}/messages`    | `send_message`      | OK                                                            |
| `GET /team/status`               | **MISSING**         | No tool to query team/agent health                            |
| `POST /permissions/{id}/respond` | **MISSING**         | No tool to respond to permission requests                     |

**Missing tools: 3 of 6 endpoints have no MCP equivalent.**

### 2.2 From ADR-013 (Team Composition) — Team Management

ADR-013 §6 defines the team presets endpoint:

| Endpoint     | MCP Tool    | Gap?                                   |
| ------------ | ----------- | -------------------------------------- |
| `GET /teams` | **MISSING** | No tool to list available team presets |

An IDE user cannot discover what team presets are available without hardcoded knowledge.

### 2.3 From ADR-012 (Agent Definition) — Agent Inspection

ADR-012 defines agent TOML configs with workspace override capability. No MCP tools exist to:

- List available agent definitions (preset + workspace)
- Inspect an agent's config (persona, capabilities, model binding)
- Validate a workspace agent TOML before use

### 2.4 From ADR-014 (Thread Metadata) — Context Injection

The thread metadata system (`GET /threads/{id}/metadata`) has no MCP tool.
An IDE cannot query or set the workspace root or context refs for a thread.

---

## 3. A2A Protocol Requirements for MCP (from Research Doc)

The MCP/A2A compliance research (`2026-02-25-mcp-tasks-a2a-compliance-research.md`)
identified the following operations that a CLI/IDE must reach:

### 3.1 Core Task Management (A2A §4)

| A2A Operation             | Current MCP         | Gap                                  |
| ------------------------- | ------------------- | ------------------------------------ |
| SendMessage (create task) | `start_thread`      | Covered (with caveats)               |
| SendMessage (follow-up)   | `send_message`      | Covered                              |
| GetTask (poll status)     | `get_thread_status` | Partial — no structured agent status |
| CancelTask                | **MISSING**         | No way to cancel a running thread    |

### 3.2 Interrupted States (A2A §2.2)

| A2A State           | MCP Coverage   | Gap                                                    |
| ------------------- | -------------- | ------------------------------------------------------ |
| `INPUT_REQUIRED`    | Not exposed    | MCP user has no way to see pending permission requests |
| `AUTH_REQUIRED`     | Not applicable | Not implemented in vaultspec                           |
| Permission response | **MISSING**    | `POST /permissions/{id}/respond` has no MCP tool       |

The research recommended (§5.4) a stable-MCP tool surface of:

```text
team/delegate  → start_thread (exists)
team/status    → MISSING (should expose team agent statuses)
team/artifacts → MISSING (should expose thread artifacts/files)
team/respond   → MISSING (should wrap permission response)
team/cancel    → MISSING (should cancel running thread)
```

---

## 4. MCP Audit Findings Status (MCP-01 through MCP-07)

From `docs/audits/2026-03-02-mcp-surface-audit.md` and task tracker:

| ID     | Severity | Finding                                               | Status                  |
| ------ | -------- | ----------------------------------------------------- | ----------------------- |
| MCP-01 | MEDIUM   | No input size cap on `initial_message`                | **RESOLVED** (Task #78) |
| MCP-02 | MEDIUM   | Preset glob at import; missing directory logs WARNING | **RESOLVED** (Task #79) |
| MCP-03 | MEDIUM   | Raw API errors leak in 409/422 responses              | **RESOLVED** (Task #80) |
| MCP-04 | LOW      | Checkpoint ID exposed in output                       | **RESOLVED** (Task #81) |
| MCP-05 | LOW      | New `AsyncClient` per call                            | **RESOLVED** (Task #82) |
| MCP-06 | LOW      | Misleading code comment in `_ws_url_from_api_base`    | **RESOLVED** (Task #83) |
| MCP-07 | INFO     | Hardcoded preset list in docstring                    | **RESOLVED** (Task #84) |

**All 7 audit findings are resolved.** The current MCP surface is clean from a
correctness/security standpoint. The remaining gaps are **functional** (missing
tools), not quality issues.

---

## 5. Prioritized Recommendations

### Priority 1 — CRITICAL: Operations Required for Usable IDE Integration

These are required for a CLI/IDE to manage vaultspec teams without
falling back to raw HTTP calls.

| #   | Tool Name           | Wraps                                 | Rationale                                                                                                                                                                                             |
| --- | ------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | `list_threads`      | `GET /api/threads`                    | IDE must list active/recent threads to resume work. Without this, users must remember thread IDs. ADR-011 §2.2 mandates this endpoint.                                                                |
| R2  | `list_team_presets` | `GET /api/teams`                      | IDE must discover available presets before calling `start_thread`. Currently presets are opaque. ADR-013 §6 mandates this endpoint.                                                                   |
| R3  | `cancel_thread`     | `POST /api/threads/{id}/cancel` (new) | A2A requires CancelTask. An IDE must be able to abort a runaway thread. Research §5.4 lists this as mandatory. **Note**: the REST endpoint itself does not yet exist — both REST and MCP tool needed. |

### Priority 2 — HIGH: Operations Required for Non-Autonomous Mode

These are required to use vaultspec in interactive (non-autonomous) mode
from an IDE, where agents request human permission.

| #   | Tool Name                 | Wraps                                | Rationale                                                                                                                                                                       |
| --- | ------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R4  | `respond_to_permission`   | `POST /api/permissions/{id}/respond` | The only way to unblock a graph waiting on `interrupt()`. Without this, non-autonomous threads hang forever. ADR-011 §2.2 mandates this.                                        |
| R5  | `get_pending_permissions` | New query endpoint                   | IDE needs to discover which threads have pending permission requests. Currently only available via WebSocket `PermissionRequestEvent`. A REST query endpoint is needed for MCP. |

### Priority 3 — MEDIUM: Operations for Full Team Management

These enable complete TOML-driven team management from IDE.

| #   | Tool Name           | Wraps                        | Rationale                                                                                                                            |
| --- | ------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| R6  | `get_team_status`   | `GET /api/team/status`       | Shows real-time agent lifecycle states. ADR-011 §2.2 mandates this endpoint. Useful for monitoring long-running threads.             |
| R7  | `get_thread_detail` | Enhanced `get_thread_status` | Current tool returns 4 lines of text. Should return structured data: agent statuses, current plan, last message preview, error info. |

### Priority 4 — LOW: Nice-to-Have Inspection Tools

| #   | Tool Name              | Wraps        | Rationale                                                                                            |
| --- | ---------------------- | ------------ | ---------------------------------------------------------------------------------------------------- |
| R8  | `list_agents`          | New endpoint | List available agent definitions (preset + workspace). Useful for IDE agent picker but not blocking. |
| R9  | `get_thread_artifacts` | New endpoint | Return file changes/artifacts from a completed thread. Research §5.4 recommended `team/artifacts`.   |

### Priority 5 — DEFERRED: MCP Experimental Tasks

The research (§5.4) recommended building on stable MCP tools first, with
experimental MCP tasks as an optional enhancement. This remains the correct
strategy:

- `start_thread` could optionally return an MCP task ID if the client supports it
- Elicitation could replace `respond_to_permission` for clients that support it
- Polling via MCP task protocol could replace `get_thread_status`

**Do not build on experimental MCP tasks until Claude CLI confirms support.**

---

## 6. `start_thread` Parameter Gaps

The current `start_thread` tool hardcodes `autonomous=True` and does not
accept `workspace_root`. For full ADR compliance:

| Parameter         | Current                                      | Should Be                                      |
| ----------------- | -------------------------------------------- | ---------------------------------------------- |
| `autonomous`      | Hardcoded `True`                             | Optional param, default `True`                 |
| `workspace_root`  | Not passed                                   | Optional param for context injection (ADR-014) |
| `team_preset`     | Optional, default `vaultspec-adaptive-coder` | OK                                             |
| `initial_message` | Required, 32k cap                            | OK                                             |

Adding `autonomous` as a parameter enables non-autonomous mode from IDE,
which unlocks R4/R5 permission flow. Adding `workspace_root` enables
context injection per ADR-014.

---

## 7. Summary

| Category                    | Count    | Details                                                              |
| --------------------------- | -------- | -------------------------------------------------------------------- |
| ADR-mandated REST endpoints | 6        | ADR-011 §2.2                                                         |
| Currently exposed via MCP   | 3        | start_thread, get_thread_status, send_message                        |
| Missing (functional gap)    | 3        | list_threads, team_status, permission_respond                        |
| Additional recommended      | 6        | list_presets, cancel, pending_permissions, detail, agents, artifacts |
| Audit findings (MCP-01..07) | 7        | All resolved                                                         |
| Experimental MCP tasks      | Deferred | Wait for CLI support confirmation                                    |

**The MCP surface covers 50% of ADR-mandated REST operations.** The three
missing tools (R1, R2, R3) should be the immediate sprint target. R4/R5
are required before non-autonomous mode can be used from IDE.
