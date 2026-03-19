# Test Suite Mock Violations Audit -- 2026-03-08

## Context

User mandate (non-negotiable): **NO MOCKS. NO FAKES. NO STUBS. NO SKIPS.
NO PATCHES. NO MONKEYPATCHES. EVER.**

CLAUDE.md line 94: "Mocks are FORBIDDEN. Every test must run live real code
against real services."

This audit scans every test file in `src/` for violations.

---

## Methodology

Full codebase grep for:
`MockTransport|MemorySaver|dependency_overrides|unittest.mock|monkeypatch|
MagicMock|patch|pytest.mark.skip|pytest.mark.xfail|pytest.skip`

Scope: `src/vaultspec_a2a/**/tests/**/*.py`

---

## 2026-03-09 Refresh

The original scan is now stale in several important places.

### Refreshed status

- `protocols/mcp/tests/test_server.py`
  - `MemorySaver`: removed
  - `httpx.MockTransport`: removed
  - private `spawner._spawned = True`: removed in the latest slice
  - `dependency_overrides`: removed
- `worker/tests/test_ipc.py`
  - `httpx.MockTransport`: removed
- `worker/tests/test_executor.py`
  - `httpx.MockTransport`: removed
  - lambda monkeypatches / capturing stub classes from the original audit are
    no longer present
  - `object.__new__(Executor)`: removed in the latest slice
- `core/tests/test_graph.py`
  - `unittest.mock`: removed
  - `Provider.MOCK`: removed in the latest slice
- `core/tests/test_supervisor.py`
  - `MemorySaver`: removed
  - remaining gap is now `_StubChatModel`, not `MemorySaver`

### Current real remaining gaps

1. `core/tests/test_supervisor.py`
   - local `_StubChatModel` still violates the repository's stricter
     no-stubs mandate

### Verification for the latest refresh slice

- `uv run ruff check src/vaultspec_a2a/worker/executor.py src/vaultspec_a2a/worker/tests/test_executor.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`
- `uv run pytest src/vaultspec_a2a/worker/tests/test_executor.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q`
- result: `63 passed`

---

## CRITICAL Violations -- Mock Infrastructure

### CRIT-01: api/tests/conftest.py (Task #56)

**Status**: FIXED

| Original Violation | Resolution |
|--------------------|------------|
| `MemorySaver` (line 20, 136) | **FIXED** — replaced with `AsyncSqliteSaver` backed by file-backed SQLite state |
| `_CapturedDispatch` (line 77) | **FIXED** — replaced with `_InProcessWorker.dispatches` list |
| `httpx.MockTransport` (line 89, 107) | **FIXED** — replaced with `httpx.ASGITransport` over real FastAPI app |
| `spawner._spawned = True` (line 182) | **FIXED** — replaced with `LazyWorkerSpawner.replace_process(None)` |
| 6x `dependency_overrides` (old lines 189-194) | **FIXED** — replaced with `app.state` injection plus `get_db(request)` session-factory lookup |
| In-memory SQLite test DBs | **FIXED** — API harness now uses isolated file-backed SQLite databases per test module/case |

The `_InProcessWorker` class (line 98) is a real FastAPI ASGI app served via
`httpx.ASGITransport` — not a mock. It accepts real HTTP requests through
real Pydantic validation.

Consumers updated:

- `test_endpoints.py`: 8 `_CapturedDispatch` imports replaced with `_InProcessWorker`
- `test_thread_metadata.py`: updated to use new `make_app` signature
- `test_projection.py`: stale-checkpoint coverage now uses file-backed SQLite, not `:memory:`

Verification:

- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\api\tests\conftest.py src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_projection.py`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_projection.py src\vaultspec_a2a\api\tests\test_internal.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
- Result: `49 passed`

### CRIT-02: protocols/mcp/tests/test_server.py (Task #57, now fixed)

| Line | Violation | Type |
|------|-----------|------|
| 26 | `from langgraph.checkpoint.memory import MemorySaver` | Fake checkpointer |
| 107 | `checkpointer = MemorySaver()` | Fake checkpointer |
| 120 | `transport = httpx.MockTransport(_handler)` | Fake HTTP transport |
| 131-134 | 4x `app.dependency_overrides[...]` | DI monkeypatching |

### CRIT-03: core/tests/test_graph.py (Task #58)

| Line | Violation | Type |
|------|-----------|------|
| 542 | `from unittest.mock import MagicMock, patch` | unittest.mock |
| 555 | `fallback_model = MagicMock()` | Fake LLM model |
| 581 | `from unittest.mock import patch` | unittest.mock |

### CRIT-04: worker/tests/test_ipc.py + test_executor.py (Tasks #59, #64)

**test_ipc.py:**

| Line | Violation | Type |
|------|-----------|------|
| 37 | `transport=httpx.MockTransport(handler)` | Fake HTTP transport |

**test_executor.py:**

| Line | Violation | Type |
|------|-----------|------|
| 35,42 | `httpx.MockTransport` | Fake HTTP transport |
| 335,402,458,504,560,621 | `class _CapturingAggregator` | Handwritten stub (6x) |
| 365,531,587 | `executor._compile_graph = lambda req:` | Lambda monkeypatch (3x) |

---

## MEDIUM Violations -- pytest.skip

### MED-01: Provider tests (Task #60)

| File | Lines | Reason |
|------|-------|--------|
| test_acp_chat_model.py | 42, 105 | No CLAUDE_CODE_OAUTH_TOKEN |
| test_factory.py | 45, 54, 62, 94, 114 | No binary in bin/ |
| test_gemini_auth.py | 165, 169 | No credentials |
| test_crash_recovery.py | 268, 324 | Windows TIME_WAIT port reuse |

Total: 11 skip sites. Should use `@pytest.mark.requires_*` markers with
`pytest.fail()` in `pytest_runtest_setup` (pattern exists in
`src/vaultspec_a2a/tests/conftest.py`).

---

## MEDIUM Violations -- monkeypatch.setenv

### MED-02: Environment variable tests (Task #61)

| File | Lines | Count | Purpose |
|------|-------|-------|---------|
| core/tests/test_config.py | 19-53 | 8 | Settings env var parsing |
| workspace/tests/test_workspace.py | 358-416 | 11 | Env var filtering |
| telemetry/tests/test_telemetry.py | 100-141 | 3 | OTel config |

Total: 22 monkeypatch.setenv uses. All test env var behavior at the system
boundary. **Needs user ruling** on whether monkeypatch.setenv is acceptable
for env var testing or must be replaced with subprocess isolation.

---

## LOW Violations -- MemorySaver as in-memory checkpointer

| File | Line | Usage | Task |
|------|------|-------|------|
| core/tests/test_supervisor.py | 674 | `MemorySaver()` in graph compile | #66 |

This uses MemorySaver as a real in-memory checkpointer (not as a mock of
something else). However, per user mandate, all checkpointers must be
`AsyncSqliteSaver` — MemorySaver is FORBIDDEN regardless of intent.

---

## CLEAN Files (no violations)

- `database/tests/test_database.py` -- real aiosqlite, no mocks
- `core/tests/test_rules.py` -- real tmp_path, no mocks
- `core/tests/test_team_config.py` -- real TOML parsing
- `api/tests/test_auth.py` -- clean
- `api/tests/test_websocket.py` -- clean
- `api/tests/test_internal.py` -- uses httpx.ASGITransport (correct pattern)
- `tests/test_smoke.py` -- real subprocesses, zero mocks
- `tests/test_crash_recovery.py` -- real subprocesses (except 2 skips)

---

## Fix Task Summary

| Task | File(s) | Violation Type | Priority |
|------|---------|----------------|----------|
| #56 | api/tests/conftest.py + consumers | MockTransport, MemorySaver, overrides, in-memory SQLite | CRIT | **FIXED** |
| #57 | mcp/tests/test_server.py | MockTransport, MemorySaver, overrides | CRIT | FIXED |
| #58 | core/tests/test_graph.py | unittest.mock.MagicMock, patch | CRIT | Pending |
| #59 | worker/tests/test_ipc.py | MockTransport | CRIT | Pending |
| #64 | worker/tests/test_executor.py | Stubs, lambda monkeypatches, MockTransport | CRIT | Pending |
| #66 | core/tests/test_supervisor.py | MemorySaver | LOW | Pending |
| #60 | providers/tests/*.py, test_crash_recovery | pytest.skip | MED | Partial |
| #61 | config, workspace, telemetry tests | monkeypatch.setenv | MED | Needs ruling |

---

## Refresh -- 2026-03-10 Supervisor/Core Slice

This refresh supersedes the older `#66` assessment above.

### Fixed in this slice

- `core/tests/test_supervisor.py`
  - `_StubChatModel` removed
  - old in-graph `MemorySaver` / local model-double path removed
  - routing, gate, approval-request, and message-building checks now hit
    deterministic production helpers directly
- `Justfile`
  - added `verify-core` so the core graph/supervisor slice runs with the same
    repo-local temp/cache isolation pattern already used by other backend
    verification targets

### Current remaining no-doubles gaps after this slice

- `core/nodes/tests/test_supervisor.py`
  - still uses `FakeListChatModel`
- `core/nodes/tests/test_worker.py`
  - still uses `FakeListChatModel`
- `core/tests/test_worker.py`
  - still uses `_GraphInterruptModel`

These are now the real remaining core model-double tasks. They should not stay
hidden behind the old `#66` supervisor entry.

### Updated task state

- `#66` should now be treated as **FIXED**.
- A new task is required for the remaining core worker/node fake-model cleanup.

## Refresh -- 2026-03-10 Core Node/Worker Slice

This refresh supersedes the `#81` note above.

### Fixed in this slice

- `core/nodes/tests/test_supervisor.py`
  - `FakeListChatModel` removed
  - deterministic supervisor helper coverage kept
- `core/nodes/tests/test_worker.py`
  - `FakeListChatModel` removed
  - callback-wiring checks now use real `AcpChatModel`
  - non-ACP passthrough check now uses real `ChatOpenAI`
- `core/tests/test_worker.py`
  - local `BaseChatModel` subclasses removed
  - worker exception/interrupt behavior now validated through the production
    `_wrap_worker_exception(...)` helper and real `GraphInterrupt` values
- `core/nodes/worker.py`
  - deterministic production helpers extracted so the suites can stay on real
    code paths without test-only model doubles
- `Justfile`
  - `verify-core` now includes the node-level worker/supervisor suites

### Updated task state

- `#81` should now be treated as **FIXED**.

## Refresh -- 2026-03-10 Live IPC + MCP Slice

This refresh supersedes the older `#35` / `#36` pending state above.

### Fixed in this slice

- `tests/test_ipc_heartbeat_live.py`
  - added real gateway + worker + Postgres verification for worker heartbeat
    truth and `active_threads` visibility
  - the suite now drives a real cancel request instead of waiting for
    provider-dependent autonomous completion, which makes the certifying
    heartbeat assertion deterministic
- `tests/test_mcp_e2e_live.py`
  - added real MCP stdio verification through the installed MCP client
  - the suite now launches the real server, initializes a real session, lists
    tools, starts a real thread, and reads its live status through the gateway
- `Justfile`
  - added `verify-live-orchestration` for this live Postgres certifying slice

### Updated task state

- `#35` should now be treated as **FIXED**.
- `#36` should now be treated as **FIXED**.

### Remaining critical-path no-doubles work

- `#60`
  - skip-based policy drift is now narrowed to CLI stale-PID tests

## Refresh -- 2026-03-10 Provider Skip Slice

This refresh supersedes the older provider portion of `#60`.

### Fixed in this slice

- `providers/tests/test_factory.py`
  - removed all remaining `pytest.skip()` paths from the Claude binary-backend
    tests
  - the suite now asserts the positive binary behavior when a bundled binary is
    present and the real `ConfigError` negative contract when it is absent

### Verification

- `.\\.venv\\Scripts\\python.exe -m ruff check src\\vaultspec_a2a\\providers\\tests\\test_factory.py`
- `.\\.venv\\Scripts\\python.exe -m pytest src\\vaultspec_a2a\\providers\\tests\\test_factory.py -q`
- result: `19 passed, 4 deselected`

### Updated task state

- The provider-factory portion of `#60` should now be treated as **FIXED**.
- The remaining skip debt is now outside the provider suite.

## Refresh -- 2026-03-10 CLI Skip Slice

This refresh supersedes the `#82` follow-up above.

### Fixed in this slice

- `cli/tests/test_service.py`
  - removed the final two `pytest.skip()` escape hatches
  - stale-PID tests now create a real short-lived child process, wait for it to
    exit, and reuse that PID for stale-record assertions

### Updated task state

- `#60` should now be treated as **FIXED**.
- `#82` should now be treated as **FIXED**.

### New follow-up

- `#83`
  - fixed: the CLI module was moved off `tmp_path` onto a repo-local runtime
    fixture, and the follow-up stale-PID assumption was corrected in the same
    slice
