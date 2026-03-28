---
tags:
  - '#audit'
  - '#layer-2d'
date: '2026-03-28'
related:
  - '[[2026-03-28-layer2d-file-size-adr]]'
  - '[[2026-03-28-layer2d-file-size-plan]]'
  - '[[2026-03-28-post-layer2d-boundary-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `layer-2d` rolling audit

Living audit document tracking post-execution findings, rough edges,
and quality concerns discovered during code review of Layer 2d.

## Cycle 1 — Post-Execution Self-Audit (2026-03-28)

Initial findings from code review immediately after execution.

### HIGH — Inconsistent handler signatures force lambda adapters

The `rpc_map` in `acp_chat_model.py` uses lambda wrappers because
RPC handler functions have 4 different signatures across 8 handlers:
- `on_request_permission(rpc_id, params, ctx, config)`
- `on_fs_read_text_file(rpc_id, params, config)` (no ctx)
- `on_terminal_kill(rpc_id, params, ctx)` (no config)
- `on_terminal_create(rpc_id, params, ctx, config)`

A uniform `(rpc_id, params, ctx, config)` signature for all handlers
would eliminate the lambda adapters.

### HIGH — `_MinimalSessionContext` is a structural fake

`test_acp_security.py` line 221 creates a minimal context class that
shadows `_AcpSessionContext` for terminal/filesystem validation tests.
The shared `ClassVar[dict]` for `terminals` could leak state across
tests.

### MEDIUM — `send_notification` is dead code

Defined in `_acp_session.py`, zero callers anywhere in the codebase.

### MEDIUM — ADR drifted from implementation

`SessionSetupResult` has 2 fields (not 6), `setup_prompt` has 4 params
(not 3), `select_auth_method_id` has 3 params (not 2). ADR was patched
post-implementation.

## Cycle 2 — Deep Codebase Audit (2026-03-28)

Five parallel audit agents covering: fakes/mocks/stubs, API signature
consistency, dead code, `_acp_session.py` split feasibility, and
`_last_auth_url` dual-write analysis.

### Fakes/Mocks/Stubs Sweep

**Codebase is remarkably clean.** Zero `MagicMock`, `AsyncMock`,
`unittest.mock.patch`, `monkeypatch`, `pytest.mark.skip`, or `xfail`
found anywhere.

| Severity | Count | Details |
|----------|-------|---------|
| HIGH | 1 | `_StubProviderFactory` + `FakeChatModel` in `graph/tests/conftest.py` — wraps LangChain's `FakeChatModel` for Layer 1 structural tests. Justified if VidaiMock integration tests cover the real provider path. |
| MEDIUM | 6 | Shadow types for LangGraph internals: `_MinimalSessionContext` (ACP security), `_MinimalNode`/`_MinimalGraph` (aggregator metadata), `_InterruptValue`/`_GraphTask`/`_GraphStateSnapshot` (aggregator interrupts), `_SilentGraph`/`_InterruptingGraph`/`_RecursingGraph` (aggregator ingest), `_WriteBuffer`/`_ReadBuffer` (probe serialisation) |
| LOW | 4 | `_InProcessGateway`/`_InProcessWorker` (real ASGI, acceptable), `_SettingsOverride` (manual settings mutation), `_noop_lifespan` (worker route tests) |

**Key risk:** All MEDIUM shadow types are duck-typed doubles for
LangGraph internal types that cannot be publicly constructed. Interface
drift would cause silent false-passes. Mitigation: add protocol-shape
assertions.

### API Signature Consistency

| Severity | Count | Details |
|----------|-------|---------|
| HIGH | 3 | (1) 4 lambda adapters in rpc_map due to 4 different handler signatures. (2) `RpcHandlerMap = dict[str, Callable[..., Any]]` erases all type information. (3) `permission_callback: Callable[..., Any]` is completely untyped — actual signature is `(str, dict, list) -> Awaitable[str]`. |
| MEDIUM | 5 | (1) `fs/read/write` lack ctx param. (2) `terminal/kill/output/wait/release` lack config param. (3) `create_and_dispatch_thread` has 15 params — needs `DispatchContext` extraction. (4) Service functions have inconsistent keyword-only enforcement. (5) `cancel_thread.trace_headers` has default `None` while others require it. |
| LOW | 3 | `_AcpModelConfig` 16+ fields approaching god-object. `_mcp_request` return type bare `dict`. MCP tool layer is clean. |

**Root cause:** 3 HIGH findings are eliminated by a single fix —
uniform `(rpc_id, params, ctx, config)` signature for all 8 handlers.
This also enables a typed `RpcHandlerMap` protocol.

### Dead Code

| Severity | Count | Details |
|----------|-------|---------|
| HIGH | 1 | `send_notification` in `_acp_session.py` — zero callers |
| LOW | 6 | Empty `__all__: list[str] = []` on private modules (intentional) |

All other functions verified to have callers. Ruff F401/F811/F841 all
clean. No orphaned test helpers.

### `_acp_session.py` Split Feasibility

**Verdict: DEFER.** File is 706 lines with 30% headroom under the 1,000
mandate. A clean three-way split path exists (`_acp_types.py` ~110L /
`_acp_auth.py` ~287L / `_acp_session.py` ~310L) but is not justified
until auth grows past 850 lines.

Key finding: `setup_session` calls `authenticate_rpc` directly — they
must stay together or the caller must bridge. A types module would
resolve the circular import.

**Trigger to revisit:** file exceeds 850 lines or new auth feature
adds >100 lines.

### `_last_auth_url` Dual-Write Analysis

**Severity downgraded: HIGH → LOW.**

Complete lifecycle trace shows the dual-write is **inert**:
- `_capture_auth_progress` writes the same value to both `ctx` and
  `self` simultaneously — copies never diverge during `_astream`
- `authenticate()` public method reads `self._last_auth_url`, but can
  only run during active `_astream` (requires `_require_stdin()` which
  raises if no session) — so `ctx` always exists with the same value
- Stale `self._last_auth_url` across `_astream` calls is inert —
  nothing reads it post-cleanup

**Recommended fix (Option A):** Remove `ctx.last_auth_url` entirely,
keep only `self._last_auth_url`. Pass as parameter to session functions.
Minimal churn (~3 line changes). Deferred — no bug, pure hygiene.

## Prioritized Action Items

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| **P0** | Unify handler signatures to `(rpc_id, params, ctx, config)` | ~30 min | Eliminates 4 lambdas, enables typed RpcHandlerMap, fixes 3 HIGH |
| **P0** | Type `permission_callback` as `Callable[[str, dict, list[dict]], Awaitable[str]]` | ~5 min | Fixes 1 HIGH |
| **P1** | Remove dead `send_notification` | ~2 min | Removes confirmed dead code |
| **P1** | Add protocol-shape assertions to `_MinimalSessionContext` test | ~5 min | Mitigates drift risk |
| **P2** | Remove `ctx.last_auth_url`, keep only `self._last_auth_url` | ~10 min | Eliminates dual-write |
| **P2** | Make all service functions keyword-only after `db` | ~10 min | Consistency |
| **P3** | Define `DispatchContext` dataclass for 15-arg services | ~20 min | Out of Layer 2d scope (Layer 3/service layer) |
| **Defer** | Split `_acp_session.py` into types/auth/session | trigger: 850L | Not needed yet |
