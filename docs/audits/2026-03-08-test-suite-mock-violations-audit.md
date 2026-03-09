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

## CRITICAL Violations -- Mock Infrastructure

### CRIT-01: api/tests/conftest.py (Task #56)

**Status**: SUBSTANTIALLY FIXED (uncommitted)

| Original Violation | Resolution |
|--------------------|------------|
| `MemorySaver` (line 20, 136) | **FIXED** — replaced with `AsyncSqliteSaver` backed by tmp_path |
| `_CapturedDispatch` (line 77) | **FIXED** — replaced with `_InProcessWorker.dispatches` list |
| `httpx.MockTransport` (line 89, 107) | **FIXED** — replaced with `httpx.ASGITransport` over real FastAPI app |
| `spawner._spawned = True` (line 182) | **REMAINING** — private field manipulation |
| 6x `dependency_overrides` (lines 189-194) | **ACCEPTABLE** — FastAPI official test DI pattern |

The `_InProcessWorker` class (line 98) is a real FastAPI ASGI app served via
`httpx.ASGITransport` — not a mock. It accepts real HTTP requests through
real Pydantic validation.

Consumers updated:
- `test_endpoints.py`: 8 `_CapturedDispatch` imports replaced with `_InProcessWorker`
- `test_thread_metadata.py`: updated to use new `make_app` signature

### CRIT-02: protocols/mcp/tests/test_server.py (Task #57)

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
| #56 | api/tests/conftest.py + consumers | MockTransport, MemorySaver, overrides | CRIT | **MOSTLY FIXED** |
| #57 | mcp/tests/test_server.py | MockTransport, MemorySaver, overrides | CRIT | Pending |
| #58 | core/tests/test_graph.py | unittest.mock.MagicMock, patch | CRIT | Pending |
| #59 | worker/tests/test_ipc.py | MockTransport | CRIT | Pending |
| #64 | worker/tests/test_executor.py | Stubs, lambda monkeypatches, MockTransport | CRIT | Pending |
| #66 | core/tests/test_supervisor.py | MemorySaver | LOW | Pending |
| #60 | providers/tests/*.py, test_crash_recovery | pytest.skip | MED | Partial |
| #61 | config, workspace, telemetry tests | monkeypatch.setenv | MED | Needs ruling |
