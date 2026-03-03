---
date: 2026-02-28
type: audit
feature: full-backend-swarm-4
description: 'Fourth-pass 6-agent independent audit producing ~110 unique findings (14 CRITICAL, 37 HIGH, 59 MEDIUM, 38 LOW) against all 17 ADRs, resolving final lint violations and achieving 702 tests passing.'
related:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
  - docs/adrs/2026-02-27-013-team-composition-topology-adr.md
  - docs/adrs/2026-02-28-015-dependency-hygiene-cli-entry-adr.md
  - docs/adrs/2026-02-28-016-task-runner-dev-bootstrap-adr.md
  - docs/adrs/2026-02-28-017-containerization-strategy-adr.md
---

# Fourth-Pass Audit Report — Consolidated

**Date:** 2026-02-28
**Auditors:** 6 independent sonnet agents (fresh pass, no assumptions from prior
audits)
**Scope:** Full `lib/`backend, MCP server, all test files — audited against all
17 ADRs, security mandates, testing mandates, and architectural patterns.

---

## Executive Summary

| Agent                | Scope                                          | CRIT   | HIGH   | MED    | LOW    | Total   |
| -------------------- | ---------------------------------------------- | ------ | ------ | ------ | ------ | ------- |
| core-auditor         | `lib/core/`                                    | 4      | 6      | 8      | 7      | 25      |
| api-auditor          | `lib/api/`                                     | 0      | 6      | 13     | 7      | 26      |
| providers-auditor    | `lib/providers/`                               | 2      | 6      | 9      | 6      | 23      |
| db-protocol-auditor  | `lib/database/`+`lib/protocols/`               | 0      | 5      | 8      | 6      | 19      |
| utils-auditor        | `lib/utils/`+`lib/telemetry/`+`lib/workspace/` | 3      | 5      | 6      | 4      | 18      |
| test-quality-auditor | Cross-cutting test quality                     | 5      | 9      | 15     | 8      | 37      |
| **TOTAL (raw)**      |                                                | **14** | **37** | **59** | **38** | **148** |

**Note:** The test-quality-auditor findings overlap significantly with other
agents' test findings. After dedup, unique actionable findings are approximately
**~110**.

---

## CRITICAL Findings (14)

### CORE-C1:`_loop_router`Can Return Unregistered Route Key

**File:**`lib/core/graph.py:513-533`
The router returns `state.get("next", "revise")`but the conditional edges map
only registers`{"revise": loop_target, "FINISH": END}`. Any worker setting
`state["next"]`to a value other than`"revise"`or`"FINISH"`causes a runtime
crash.

### CORE-C2:`load_team_config`Has No Path Traversal Protection

**File:**`lib/core/team_config.py:336-365`
`team_id`is interpolated into filesystem paths without validation
(unlike`load_agent_config`which validates against`_SAFE_AGENT_ID_RE`). A crafted
`team_id`like`"../../etc/passwd"`creates a path-traversal vector.

### CORE-C3:`config.py`Missing`__all__`Declaration

**File:**`lib/core/config.py`
ADR-009 §5.3 mandates `__all__`on every
sub-sub-module.`config.py`exports`Settings`and`settings`but declares neither.

### CORE-C4: Pervasive Hand-Rolled Stubs in`test_aggregator.py`

**File:** `lib/core/tests/test_aggregator.py` (multiple locations)
`_FakeNode`, `_FakeGraph`, `FakeChunk`, `BigChunk`, `EmptyChunk`,
`_FakeInterrupt`, `_FakeTask`, `_FakeState`, `_FakeGraphWithInterrupt`— all
violate the no-mocks/no-stubs mandate.

### PROV-C1:`prompt_future.result()`Raises RuntimeError, Bypasses Domain Error Path

**File:**`lib/providers/acp_chat_model.py:368-393`
When subprocess dies mid-session,
`prompt_future.result()`re-raises`RuntimeError("Subprocess closed")`instead of
going through the`AcpError`domain error path.

### PROV-C2:`_FakeWriter`and`_FakeCtx`Stubs Violate No-Mocks Mandate

**Files:**`lib/providers/probes/tests/test_protocol.py:141-326`,
`lib/providers/tests/test_acp_security.py:200-215`
Five `_FakeWriter`classes and`_FakeCtx`are hand-rolled stubs replacing real
objects.

### WS-CRIT-001:`is_main`Detection Inverted in`list_worktrees`

**File:** `lib/workspace/git_manager.py:245-258`
Off-by-one in `entry_index`causes the main worktree to always
get`is_main=False`in multi-worktree scenarios. Only single-worktree repos
produce correct results.

### TEL-CRIT-001: Dead`except ImportError`in`_build_sdk_meter_provider`

**File:** `lib/telemetry/instrumentation.py:218-226`
Inner `try/except ImportError`inside`if otlp_available:`branch is both
unreachable dead code AND an ADR-015 §2.3 violation (no try/except guards for
OTel packages).

### TEL-CRIT-002: Stale Docstring + Dead Code Branch for "Optional SDK"

**File:**`lib/telemetry/instrumentation.py:1-8, 269-275`
Module docstring still describes SDK as optional; `else` branch at line 271 is
unreachable. Both contradict ADR-015 which mandates SDK as a runtime dependency.

### TEST-CRIT-001 through TEST-CRIT-005: Fake Class Stubs Across Test Suite

**Files:** Multiple test files
`_FakeGraph`, `_FakeNode`, `FakeChunk`, `_FakeWriter`, `_AcpLikeModel`,
`_NullTaskGroup`— all violate the testing mandate.

---

## HIGH Findings (37)

### Core (6)

| ID      | File                                               | Issue                                                                            |
| ------- | -------------------------------------------------- | -------------------------------------------------------------------------------- |
| CORE-H1 | `graph.py:513-527`                                 | No test validates exact loop iteration count semantics                           |
| CORE-H2 | `nodes/tests/test_worker.py:41-55`                 | `_AcpLikeModel`stub replaces real AcpChatModel                                   |
| CORE-H3 | `nodes/tests/test_supervisor.py`, `test_worker.py` | `FakeListChatModel`violates "live real code" mandate                             |
| CORE-H4 | `aggregator.py:401-444`                            | `_broadcast`race on`_subscriptions`dict without lock                             |
| CORE-H5 | `aggregator.py:586-601`                            | `emit()`re-sequences events that already have assigned sequences                 |
| CORE-H6 | `tests/test_graph.py:283-308`                      | `test_loop_router_worker_can_signal_finish`is vacuous — never invokes the router |

### API (6)

| ID     | File                        | Issue                                                                          |
| ------ | --------------------------- | ------------------------------------------------------------------------------ |
| API-H1 | `auth.py`/ all endpoints    | `authenticate_request`declared but never wired — all endpoints unauthenticated |
| API-H2 | `tests/conftest.py:105-113` | `_NullTaskGroup`silently swallows ingest errors                                |
| API-H3 | `websocket.py:156-157`      | `asyncio.create_task()`escapes structured concurrency (should use anyio)       |
| API-H4 | `endpoints.py:582`          | `asyncio.wait_for()`instead of`anyio.fail_after()`                             |
| API-H5 | `schemas/rest.py:136-137`   | `PermissionResponseRequest.kind`accepted but silently ignored                  |
| API-H6 | `endpoints.py:258`          | `workspace_root`not`.resolve()`d — symlink traversal possible                  |

### Providers (6)

| ID      | File                          | Issue                                                             |
| ------- | ----------------------------- | ----------------------------------------------------------------- |
| PROV-H1 | `gemini_auth.py:162,166`      | `write_text()`and`replace()`are blocking I/O in async context     |
| PROV-H2 | `gemini_auth.py:116`          | `creds_path.read_text()`is blocking I/O in async context          |
| PROV-H3 | `acp_chat_model.py:310-314`   | `AIMessage`type silently dropped — conversation history corrupted |
| PROV-H4 | `probes/_protocol.py:143-227` | `_ProbeSession`has no`stdin_lock`                                 |
| PROV-H5 | `gemini_auth.py:78-84`        | `os.fsync()`on read-only fd is semantically incorrect             |
| PROV-H6 | `acp_chat_model.py:1319-1336` | `authenticate()`has no credential redaction                       |

### Database + MCP (5)

| ID          | File                           | Issue                                                                              |
| ----------- | ------------------------------ | ---------------------------------------------------------------------------------- |
| DB-HIGH-01  | `session.py`, `pyproject.toml` | `aiosqlite`used directly but not declared as direct dependency (ADR-015 DEP003)    |
| DB-HIGH-02  | `crud.py:93,191`               | `ThreadStatus`enum never enforced — raw strings bypass enum                        |
| DB-HIGH-03  | `models.py:49`, ADR-014        | ADR-014 §2.5 specifies `metadata`but impl uses`thread_metadata`— ADR never updated |
| MCP-HIGH-01 | `test_server.py:192-229`       | "Connectivity" tests always exercise error branch — success path untested          |
| MCP-HIGH-02 | `test_server.py:107-183`       | `TestCreateThreadViaApp`creates real`vaultspec.db`on disk                          |

### Utils/Telemetry/Workspace (5)

| ID           | File                              | Issue                                                                                    |
| ------------ | --------------------------------- | ---------------------------------------------------------------------------------------- |
| WS-HIGH-001  | `git_manager.py:296-435`          | `has_conflicts`and`merge_worktree`accept arbitrary`worktree_path`without path validation |
| WS-HIGH-002  | `tests/test_workspace.py`         | No adversarial path-traversal tests for any worktree method                              |
| WS-HIGH-003  | `tests/test_workspace.py`         | No test asserts`is_main=True`— WS-CRIT-001 survived because of this                      |
| TEL-HIGH-001 | `tests/test_telemetry.py`         | Middleware tests never verify span attributes                                            |
| TEL-HIGH-002 | `tests/test_telemetry.py:229-244` | `test_inject_trace_context`tautological: only asserts`isinstance(carrier, dict)`         |

### Test Quality (9)

| ID                | Issue                                                                                         |
| ----------------- | --------------------------------------------------------------------------------------------- |
| TEST-HIGH-001–009 | Vacuous isinstance assertions, fuzzy keyword matching, exception swallowing across test suite |

---

## MEDIUM Findings (59)

### Core (8): CORE-M1 through CORE-M8

- Silent skip of missing workers in star topology
- Tool call debounce sequence number inconsistency -`compact_context`untested edge case (system msgs > max_tokens) -`generate_nickname`no post-generation validation
- Test accepts either ConfigError or AgentConfigNotFoundError -`_append_artifacts`crashes on missing`id`key
- Concurrent ingest cancellation race
- Fallback supervisor prompt incomplete when workers silently skipped

### API (13): API-M1 through API-M13

-`title`, `agent_id`, `team_preset`missing max_length/format validation -`GET /threads`pagination untested -`GET /team/status`test only checks key presence -`_enrich_snapshot_from_state`untested in isolation -`contextlib.suppress(Exception)`masks TeamConfig errors -`TERMINATE`→`cancel_thread()`integration untested -`_NullTaskGroup`doesn't implement full anyio interface -`pending_permissions`permanently empty (TODO hidden by test) -`recursion_limit: 100`hardcoded in 3 places

### Providers (9): PROV-M1 through PROV-M9

-`pending.pop(rid, "?")`silently absorbs unknown responses

- Zero test coverage for auto-approve path (autonomous mode) -`_FakeCtx.stdin_lock`is class-level (shared across tests) -`Path("python3.13").stem`returns`"python3"`(dead allowlist entry)
- Probe per-line timeout equals total timeout
- Zero test coverage for capability gate in`_handle_server_rpc`
- No concurrent refresh lock in `gemini_auth`
- `uvx`missing from`_TERMINAL_COMMAND_ALLOWLIST`

### Database + MCP (8): DB-MEDIUM-01 through -05, MCP-MEDIUM-01 through -03

- TOCTOU test bypasses `create_thread()`entirely
- Module docstring claims WAL coverage that doesn't exist
- No commit-then-retrieve durability tests -`close_db()`, `get_session_factory()`, `get_db()`untested
- Cascade delete behavior untested -`_ws_url_from_api_base()`credential-stripping untested -`start_thread`success path untested -`initial_message[:80]`truncation edge cases untested

### Utils/Telemetry/Workspace (6): Various

-`JSONFormatter`has no functional tests -`JSONFormatter`not re-exported from facade`__init__.py`

- SDK-disable tests documented as tautological
- `test_all_methods_are_static`only checks`callable`, not `staticmethod`
- `handlers.clear()`bypasses logging lock
- Detached HEAD ValueError in`merge_worktree`untested

### Test Quality (15)

- Trivial tests, meta-tests, coverage gaps across test suite

---

## LOW Findings (38)

Distributed across all modules — stale comments, dead code, minor validation
gaps, documentation issues. Full details in individual agent reports.

---

## Cross-Cutting Patterns

### 1. Boundary Validation Deficit

Path traversal gaps
in`load_team_config`(CORE-C2),`has_conflicts`/`merge_worktree`(WS-HIGH-001),`workspace_root`(API-H6).
Input length limits missing on`title`, `agent_id`, `team_preset`, `thread_ids`
elements.

### 2. asyncio vs anyio Inconsistency

`asyncio.create_task()`in WebSocket (API-H3),`asyncio.wait_for()`in endpoints
(API-H4),`asyncio.ensure_future()`in`_NullTaskGroup` (API-H2). ADR-007 mandates
anyio throughout.

### 3. Stub/Mock Pervasiveness Despite Mandate

`_FakeGraph`, `_FakeNode`, `FakeChunk`, `_FakeWriter`, `_FakeCtx`,
`_AcpLikeModel`, `_NullTaskGroup`, `FakeListChatModel` — all violate the
explicit "Mocks are FORBIDDEN" mandate. This is the single largest category of
findings.

### 4. Vacuous Test Assertions

`isinstance(x, bool)`, `x is not None`, `graph is not None`,
`isinstance(carrier, dict)` — assertions that cannot fail and provide zero
verification of actual behavior.

### 5. ADR Drift

ADR-014 §2.5 (`metadata`vs`thread_metadata`), ADR-015 §2.3 (dead ImportError
guards still present), ADR-013 §2.7 (interrupt_before docs stale).

### 6. Blocking I/O in Async Context

`gemini_auth.py`: `write_text()`, `read_text()`, `replace()`all synchronous
inside`async def`. `team_config.py`: `path.open("rb")`at config-load time
(acceptable at startup, not hot path).

### 7. Silent Error Masking

Three`contextlib.suppress(Exception)`blocks in`endpoints.py`that swallow all
errors without logging.

---

## Recommended Fix Priority

### Block Release (immediate)

1. **CORE-C2**: Add`_SAFE_TEAM_ID_RE`validation to`load_team_config`
2. **API-H6**: Add `.resolve()`to`workspace_root`path handling
3. **WS-CRIT-001**: Fix`is_main`off-by-one in`list_worktrees`
4. **PROV-H3**: Add `AIMessage`to the isinstance check in`_astream`
5. **PROV-C1**: Guard `prompt_future.result()`with`.exception()`check

### High Priority (next sprint)

1. **DB-HIGH-01**: Add`aiosqlite`to direct dependencies
2. **DB-HIGH-02**: Enforce`ThreadStatus`enum in CRUD layer
3. **CORE-C3**: Add`__all__`to`config.py`
4. **API-H3/H4**: Replace `asyncio.create_task`/`asyncio.wait_for`with anyio
   equivalents
5. **WS-HIGH-001**: Add path validation to`has_conflicts`/`merge_worktree`
6. **TEL-CRIT-001/002**: Remove dead OTel ImportError guards and stale docstring
7. **PROV-H1/H2**: Offload blocking file I/O in
   `gemini_auth`to`asyncio.to_thread`
8. **PROV-M8**: Add `asyncio.Lock`for concurrent Gemini token refresh

### Medium Priority (subsequent sprints)

1. Replace all fake class stubs with real object tests or extract pure
   validation functions
2. Add meaningful assertions replacing vacuous isinstance/is-not-None checks
3. Add input length validation to all REST/WebSocket schema fields
4. Test pagination, enrichment, shutdown, and integration paths
5. Update ADR-014 §2.5 to reflect`thread_metadata`naming

---

## Positive Findings (Compliance)

The following areas were confirmed compliant across all auditors:

- **stdin_lock coverage**: All 14 write paths in`acp_chat_model.py` acquire the
  lock
- **`_kill_process_tree`**: Correct Windows/Unix implementation
- **`CREATE_NEW_PROCESS_GROUP`**: Correctly set on Windows
- **Sandbox path validation**: `.resolve()`+`.is_relative_to()` — immune to
  symlink attacks
- **`__all__`declarations**: Present on all production modules
  (except`config.py`)
- **Relative imports**: No violations found in any production code
- **Facade pattern**: `lib/database/__init__.py` is a model implementation (all
  22 symbols)
- **`permission_callback`isolation**:`model_copy()`correctly isolates per
  invocation
- **CORS always-on**: Via`settings.cors_allowed_origins`
- **Terminal allowlist**:
  `_TERMINAL_COMMAND_ALLOWLIST`+`_SHELL_METACHAR_RE`validation
- **Agent ID
  validation**:`_AGENT_ID_RE`in`git_manager`and`_SAFE_AGENT_ID_RE`in`team_config`
