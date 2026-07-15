---
tags:
  - '#audit'
  - '#layer-2d'
date: '2026-03-28'
modified: '2026-07-15'
related:
  - '[[2026-03-28-layer2d-file-size-adr]]'
  - '[[2026-03-28-layer2d-file-size-plan]]'
  - '[[2026-03-28-post-layer2c-boundary-audit]]'
---

# post-layer-2d boundary audit

Full boundary audit after Layer 2d (PR #12). Covers the two file-size
violations resolved in this PR.

## File Size Violations: RESOLVED

| File | Before | After | Status |
|------|--------|-------|--------|
| `protocols/mcp/server.py` | 1,045 | 55 | RESOLVED |
| `providers/acp_chat_model.py` | 1,821 | 663 | RESOLVED |
| `protocols/mcp/_http.py` | — | 197 | NEW |
| `protocols/mcp/tools/thread_lifecycle.py` | — | 264 | NEW |
| `protocols/mcp/tools/thread_query.py` | — | 196 | NEW |
| `protocols/mcp/tools/discovery.py` | — | 217 | NEW |
| `protocols/mcp/tools/messaging.py` | — | 69 | NEW |
| `providers/_acp_session.py` | — | 714 | NEW |
| `providers/_acp_protocol.py` | — | 325 | NEW |
| `providers/_acp_rpc_handlers.py` | — | 445 | NEW |

All files under the 1,000-line mandate.

## Layer 1 Independence: PASS

Zero upward imports from Layer 1 modules to any Layer 2 package.

## Entry Point Isolation: PASS

Zero cross-imports between `api/`, `cli/`, `worker/`, `protocols/mcp/`.

## control/ → api/ Boundary: PASS

Zero imports from `api/` in any `control/` module.

## MCP Boundary: PASS

- Zero `import httpx` in `protocols/mcp/tools/` — all HTTP via `_http.py`
- MCP standalone process model preserved (HTTP loopback)
- `server.py` is registration-only (55 lines)

## ACP Boundary: PASS

- Zero `self._runtime_log_extra` in any `providers/` file
- Zero `self._tool_calls` or `self._agent_modes` in `acp_chat_model.py`
- `_acp_protocol.py` does NOT import from `_acp_rpc_handlers`
- `_AcpModelConfig` is frozen (immutable during session)
- Session lifecycle functions return result dataclasses

## Test Baseline: PASS

| Suite | Count | Target |
|-------|-------|--------|
| `pytest -m core` | 520 | >= 520 |
| `pytest -m middleware` | 574 | >= 574 |
| Full `pytest` | 1,094 | >= 1,094 |

## Code Review Findings

Track A: PASS — zero critical/high issues. 3 medium pre-existing.
Track B: 1 critical (downgraded to high, documented in ADR), 2 high
(ADR updated), 3 medium (1 fixed, 2 ADR updated), 3 low.

## Outstanding Items

- `_last_auth_url` dual-write (ctx + self PrivateAttr) — documented
  pragmatic compromise for `authenticate()` outside `_astream`
- Settings god-object (34-file footprint) — tracked for Layer 3
- `acp_chat_model.py` at 663 lines (ADR target was < 600) — under
  the 1,000-line mandate, acceptable
