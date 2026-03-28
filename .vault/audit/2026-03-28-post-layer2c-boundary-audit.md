---
tags:
  - '#audit'
  - '#database-layer'
date: '2026-03-28'
related:
  - '[[2026-03-28-database-layer-adr]]'
  - '[[2026-03-28-post-layer2b-boundary-audit]]'
  - '[[2026-03-27-domain-logic-extraction-adr]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
---

# post-layer-2c full-stack boundary audit

Full-stack audit of the vaultspec-a2a codebase after Layer 2c (PR #11).
Covers all layer isolation goals from PRs #2 through #11.

## Audit Results

### Layer 1 Independence: PASS

Zero upward imports from `thread/`, `graph/`, `context/`, `lifecycle/`,
`streaming/`, `team/`, `workspace/`, `utils/`, `domain_config.py` to any
Layer 2 package. Layer 1 is independently importable without running
services.

### Entry Point Isolation: PASS

Zero cross-imports between `api/`, `cli/`, `worker/`. Each entry point
imports only from Layer 1 and Layer 2 infrastructure services.

### control/ -> api/ Boundary: PASS

Zero imports from `api/` in any `control/` module (excluding tests).
This was the primary target of PR #9 (D-12 dependency inversion) and
remains clean after Layer 2c service extraction.

### utils/ Independence: PASS

Zero imports from `control/` or `api/` in `utils/`. Parameter injection
pattern from PR #9 (D-09) holds.

### ipc/ Independence: PASS

Zero imports from `control/` in `ipc/`. The `settings` coupling was
removed in Layer 2c (D-06). `DispatchRequest.recursion_limit` is now a
required field.

### database.crud Elimination: PASS

Zero references to `database.crud` anywhere in codebase. The re-export
hub has been deleted. All 17 consumer files import from the facade
(`database`) or specific repository modules.

### Service Function Isolation: PASS

All 4 service modules (`thread_service.py`, `permission_service.py`,
`message_service.py`, `cancel_service.py`):
- Zero imports from `api/`
- Zero `db.commit()` calls (route handlers own commit)
- Zero `HTTPException` usage (return result dataclasses)
- Zero direct `settings` imports (receive `recursion_limit` as parameter)
- All use `safe_dispatch()` (no raw exception handling)

### Route Handler Thinness: PASS

| Route | Lines | Status |
|-------|-------|--------|
| `admin.py` | 15 | Thin |
| `cancel.py` | 63 | Thin (service delegate) |
| `health.py` | 82 | Thin |
| `permissions.py` | 83 | Thin (service delegate) |
| `messages.py` | 92 | Thin (service delegate) |
| `teams.py` | 102 | Thin |
| `thread_state.py` | 157 | Thin (projection delegate) |
| `threads.py` | 321 | 5 endpoints, all thin |

### File Size Violations: 2 REMAINING (deferred)

| File | Lines | Status |
|------|-------|--------|
| `providers/acp_chat_model.py` | 1,821 | DEFERRED to Layer 2d |
| `protocols/mcp/server.py` | 1,045 | DEFERRED to Layer 2d |
| `control/verify.py` | 894 | OK (under threshold) |
| `api/websocket.py` | 719 | OK |
| `control/config.py` | 632 | OK (god-object concern tracked) |
| `control/worker_management.py` | 604 | OK |

## Layer 2a ADR Decisions — All 11 DONE

- D-01: IPC types to `ipc/` — DONE
- D-02: Infrastructure to `control/` — DONE
- D-03: Dispatch consolidation — DONE
- D-04: Projection to `control/` — DONE
- D-05: Event handlers to `control/` — DONE
- D-06: Health consolidation — DONE
- D-07: Split `endpoints.py` into `routes/` — DONE
- D-08: Slim `app.py` — DONE
- D-09: Split `executor.py` into 3 modules — DONE
- D-10: Extract `cli/_renderers.py` — DONE
- D-11: Fix `cli/_agent.py` filesystem bypass — DONE

## Layer 2b ADR Decisions — All 12 DONE

- D-01 through D-12: All implemented and verified in PR #9

## Layer 2c ADR Decisions — All 7 DONE

- D-01: Repository naming — DONE
- D-02: CRUD hub elimination — DONE
- D-03: Terminal status constants — DONE
- D-04: Service function extraction — DONE
- D-05: Dispatch helper — DONE
- D-06: IPC decoupling — DONE
- D-07: Repair transitions — DONE

## Outstanding Items for Layer 2d

- Split `providers/acp_chat_model.py` (1,821L) into focused sub-modules
  (ACP protocol, subprocess management, LangChain interface)
- Split `protocols/mcp/server.py` (1,045L) into per-domain handler
  modules; adopt `control/` service functions
- `control/config.py` settings god-object — reduce 34-file import
  footprint by having modules import `DomainConfig` directly where only
  behavioral knobs are needed (Layer 3 candidate)

## Post-Layer 2b Audit Finding Resolution

| Finding | Severity | Status |
|---------|----------|--------|
| Route handler orchestration leakage | Moderate | RESOLVED (Layer 2c D-04) |
| Direct DB calls in handlers | Moderate | RESOLVED (heavy handlers delegate to services) |
| Settings god object | Moderate | PARTIALLY_RESOLVED (ipc decoupled; 34-file footprint remains) |
| `acp_chat_model.py` over 1,000L | Moderate | DEFERRED to Layer 2d |
| `ipc/schemas.py` settings import | Minor | RESOLVED (Layer 2c D-06) |
| `mcp/server.py` over 1,000L | Minor | DEFERRED to Layer 2d |
| Missing `.dockerignore` | Minor | DEFERRED to Layer 3 |
