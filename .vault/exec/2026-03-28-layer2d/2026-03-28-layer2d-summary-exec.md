---
tags:
  - '#exec'
  - '#layer-2d'
date: '2026-03-28'
related:
  - '[[2026-03-28-layer2d-file-size-plan]]'
  - '[[2026-03-28-layer2d-file-size-adr]]'
  - '[[2026-03-28-post-layer2d-boundary-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `layer-2d` execution summary

Resolved the two remaining file-size violations from the post-Layer 2c
boundary audit. Both monolithic modules decomposed into focused
sub-modules. All boundary checks pass. Full test suite green.

- Created: `protocols/mcp/_http.py`
- Created: `protocols/mcp/tools/thread_lifecycle.py`
- Created: `protocols/mcp/tools/thread_query.py`
- Created: `protocols/mcp/tools/discovery.py`
- Created: `protocols/mcp/tools/messaging.py`
- Created: `protocols/mcp/tools/__init__.py`
- Created: `providers/_acp_session.py`
- Created: `providers/_acp_protocol.py`
- Created: `providers/_acp_rpc_handlers.py`
- Modified: `protocols/mcp/server.py` (1,045 → 55 lines)
- Modified: `providers/acp_chat_model.py` (1,821 → 663 lines)
- Modified: `protocols/mcp/tests/test_server.py` (14 import sites updated)
- Modified: `providers/tests/test_acp_chat_model.py` (12+ test functions updated)
- Modified: `providers/tests/test_acp_security.py` (imports + free function calls)
- Modified: `src/vaultspec_a2a/README.md` (architecture doc updated)
- Created: `.vault/audit/2026-03-28-post-layer2d-boundary-audit.md`

## Description

**Track A (MCP handler decomposition):** Extracted shared `_mcp_request()`
HTTP helper eliminating 186 lines of duplicated boilerplate. Split 11
tool handlers into 4 domain-grouped modules. Slimmed `server.py` to a
55-line registration stub. HTTP loopback architecture preserved.

**Track B (ACP chat model decomposition):** Introduced `_AcpModelConfig`
frozen dataclass (17 read-only fields) and extended `_AcpSessionContext`
with session-scoped mutables. Extracted session lifecycle, JSON-RPC
protocol dispatch, and RPC handlers into free-standing module functions.
Replaced `self._runtime_log_extra` with free function across all modules.

## Tests

- `pytest -m core`: 520 passed (>= 520 target)
- `pytest -m middleware`: 574 passed (>= 574 target)
- Full `pytest`: 1,094 passed (>= 1,094 target)
- Pre-commit hooks: ruff clean
- Boundary validation: all checks pass
- Code review: Track A PASS (zero critical/high), Track B PASS after
  fixes (1 critical downgraded to high with ADR documentation)
