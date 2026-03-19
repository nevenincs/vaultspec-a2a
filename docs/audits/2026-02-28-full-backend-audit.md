---
date: 2026-02-28
type: audit
feature: full-backend
description: 'First-pass 6-agent parallel swarm audit of all lib/ modules producing 101 findings (8 CRITICAL, 33 HIGH, 37 MEDIUM, 23 LOW) including CORS production regression and AcpChatModel security issues.'
related:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-007-tech-stack-deployment-adr.md
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
  - docs/adrs/2026-02-26-010-observability-telemetry-adr.md
---

# Full Backend Code Audit — 2026-02-28

**Scope**: All `lib/`modules — core, api, providers, database, protocols, utils,
telemetry, workspace, and all tests.
**Method**: 6-agent parallel sonnet code review swarm, each agent reviewed ADRs
before auditing.
**Total findings**: 8 CRITICAL, 33 HIGH, 37 MEDIUM, 23 LOW = **101 findings**

---

## Summary by Module

| Module                                         | CRIT | HIGH | MED | LOW | Total |
| ---------------------------------------------- | ---- | ---- | --- | --- | ----- |
| `src/vaultspec_a2a/core/`                                    | 0    | 7    | 9   | 5   | 21    |
| `src/vaultspec_a2a/api/`                                     | 3    | 5    | 7   | 4   | 19    |
| `src/vaultspec_a2a/providers/`                               | 1    | 4    | 7   | 4   | 16    |
| `src/vaultspec_a2a/database/`+`src/vaultspec_a2a/protocols/`               | 0    | 3    | 6   | 4   | 13    |
| `src/vaultspec_a2a/utils/`+`src/vaultspec_a2a/telemetry/`+`src/vaultspec_a2a/workspace/` | 1    | 5    | 8   | 6   | 20    |
| All tests                                      | 3    | 9    | 12  | 0   | 24    |

---

## CRITICAL (8)

### C1.`src/vaultspec_a2a/api/app.py:278-292`— No CORS in production mode

The`create_app()`factory adds`CORSMiddleware`only when`debug=True`. In
production mode, the middleware is absent entirely. Any browser-based UI (the
React SPA) will fail to make cross-origin requests to the API. This is not a
security hardening — it's a functional regression.

**Fix**: Always add `CORSMiddleware`. In production, restrict `allow_origins`to
the configured frontend URL; in debug, allow`["*"]`.

---

### C2. `src/vaultspec_a2a/api/websocket.py:23-40` — Self-referential import path

```python
from ..api.schemas.events import ...  # should be .schemas.events
```python

The import `..api.schemas.*`from within`src/vaultspec_a2a/api/websocket.py`traverses up
to`lib/`then back down into`src/vaultspec_a2a/api/`. This works by coincidence but is
semantically wrong and will break if the module is ever moved or if Python's
import resolver changes relative resolution behavior.

**Fix**: `from .schemas.events import ...`

---

### C3. `src/vaultspec_a2a/api/endpoints.py:439-452`— Missing`response_model`on metadata endpoint

The new`GET /threads/{thread_id}/metadata`endpoint lacks
a`response_model`declaration. FastAPI will not validate or document the response
shape, and the OpenAPI schema will show`Any`.

| **Fix**: Add `response_model=ThreadMetadata | None`(or a wrapper schema) to
the route decorator. |

---

### C4.`src/vaultspec_a2a/providers/acp_chat_model.py:683-747`— Command injection via`terminal/create`

The `terminal/create`RPC handler passes user-supplied`command`directly
to`create_subprocess_shell`without any allowlist or sanitization. A malicious or
hallucinating LLM agent could execute arbitrary shell commands.

| **Fix**: Implement a command allowlist (e.g.,`["python", "pip", "git", "npm",
"node"]`) and validate the command prefix before spawning. Reject any command
containing shell metacharacters (`|`, `&`, `;`, backticks). |

---

### C5. `src/vaultspec_a2a/workspace/git_manager.py:141-142`— Git command injection via unsanitized`agent_id`

`agent_id`flows directly into`git worktree add -b
agent/{agent_id}`and`self._root / "agent" / agent_id`without validation.
An`agent_id`containing`..`traverses the filesystem; one starting with`--`is
interpreted as a git flag.

**Fix**: Validate`agent_id`against`^[a-zA-Z0-9][a-zA-Z0-9_-]*$`regex. Same
for`base_branch`.

---

### C6. `src/vaultspec_a2a/core/tests/test_graph.py:186`— Bare`except Exception: pass`

swallows test failures

`test_graph_execution_routing`catches and discards all exceptions during graph
streaming. A completely broken graph that stores initial state then throws will
still pass. No credential skip guard either.

**Fix**: Remove blanket except or narrow to a specific expected exception type.
Add credential skip guard.

---

### C7.`src/vaultspec_a2a/core/tests/test_graph.py:26-144`— Compile-only tests are tautological

Seven tests assert only`graph is not None`. A `compile_team_graph`that
returned`object()`would pass all of them. No structural assertions on nodes,
topology, or configuration.

**Fix**: Collapse to parametrized test. Add assertions on`graph.nodes.keys()`,
`interrupt_before_nodes`, `config_schema()`.

---

### C8. `src/vaultspec_a2a/providers/tests/test_acp_chat_model.py:63`— Live Gemini tests missing`@pytest.mark.live`

`test_acp_gemini_streaming`and`test_acp_gemini_ainvoke`spawn real Gemini
subprocesses but lack`@pytest.mark.live`. Will fail in CI without Gemini CLI.

**Fix**: Add `@pytest.mark.live`to both tests.

---

## HIGH (33)

### Core Module (7)

**H1.`aggregator.py`—`_broadcast`not thread-safe**:`_subscriptions`dict iterated
without lock while WebSocket handlers add/remove entries concurrently. Risk
of`RuntimeError: dictionary changed size during iteration`.

**H2. `aggregator.py`— Non-deterministic`request_id`for interrupt
events**:`request_id = f"{thread_id}:{uuid4().hex}"`generates a new ID each
time`_emit_interrupt_events`runs. If`ingest()`is called twice for the same
suspended graph (e.g., reconnect), two different`request_id`s are emitted for
the same interrupt, confusing the permission flow.

**H3. `config.py`—`object.__setattr__`on frozen Pydantic model**: Settings
uses`model_config =
ConfigDict(frozen=True)`but`__init__`calls`object.__setattr__(self,
"model_name", ...)`to bypass immutability. This breaks Pydantic's invariant
guarantees.

**H4.`nodes/worker.py`— Shared mutable`permission_callback`**:
`model.permission_callback = _interrupt_permission_callback`mutates the model
instance. If the same`AcpChatModel`instance is reused across concurrent
invocations (LangGraph may do this), callbacks can cross-contaminate.

**H5.`context.py`— Edge case in`compact_context`budget calculation**: Token
budget calculation can go negative when system messages consume most of the
budget, leading to aggressive over-compaction.

**H6.`graph.py`— Silent worker silencing in star topology**: Workers listed
in`team_config`but missing from`agent_configs`are silently skipped. No warning
logged. A typo in config leads to a graph with fewer workers than expected.

**H7.`graph.py`—`loop_node`membership not validated against
workers**:`pipeline_loop`topology accepts a`loop_node`name that may not
correspond to any compiled node, causing a runtime crash only when the loop edge
is traversed.

### API Module (5)

**H8.`endpoints.py`— Permission endpoint missing ingest
guard**:`respond_to_permission`resumes the graph via`Command(resume=...)`but
doesn't verify the graph is actually in an interrupted state. Replaying a stale
permission response could corrupt graph state.

**H9.`endpoints.py`— Thread committed to DB before graph compilation**:
If`compile_team_graph()`fails (bad config, missing provider), the thread row is
already persisted with status "created". Orphaned DB rows accumulate.

**H10.`websocket.py`— Writer/heartbeat loops don't clean up on failure**: If the
writer coroutine crashes (e.g., broken pipe), the heartbeat task continues
running and vice versa. No`TaskGroup`or cancellation scope ties them together.

**H11.`app.py`— MCP server mounted with no authentication**: The FastMCP server
at`/mcp`has no auth middleware. Any client can invoke`start_thread`,
`send_message`, etc. against the API.

**H12. `schemas/rest.py`— TOCTOU race in nickname uniqueness**: Nickname
uniqueness is checked via SELECT then INSERT. Two concurrent requests with the
same nickname can both pass the check, then one fails at DB constraint level
with an unhandled`IntegrityError`.

### Providers Module (4)

**H13. `factory.py`— Gemini detection by substring is fragile**:`if "gemini" in
model_name.lower()`matches any model containing "gemini" (e.g., a hypothetical
"not-gemini-v2"). Should use the`Provider`enum.

**H14.`acp_chat_model.py`—`stdin_lock`bypassed in`fork_session`and public
methods**: Several methods that write to subprocess stdin don't
acquire`_stdin_lock`, risking interleaved JSON-RPC writes.

**H15. `acp_chat_model.py`—`end_turn`detection leaves`prompt_done`unset on
error**: If`_handle_session_update`throws before setting`prompt_done = True`,
the caller loops forever waiting for the session to complete.

**H16. `gemini_auth.py`— Synchronous blocking HTTP in async
context**:`_refresh_google_token()`uses`urllib.request.urlopen()`which blocks
the event loop. Should use`httpx.AsyncClient`.

### Database + Protocols (3)

**H17. `crud.py`— TOCTOU race in nickname uniqueness check**: Same as H12 — the
SELECT-then-INSERT pattern is not atomic.`IntegrityError`from the unique index
is uncaught.

**H18.`session.py`— WAL pragma return value unchecked**:`PRAGMA
journal_mode=WAL`can silently fail (e.g., on read-only filesystems). The return
value is not checked.

**H19.`session.py`—`get_engine()`silently ignores different`db_path`**: The
singleton returns the first-created engine regardless of subsequent calls with
different paths. No warning logged.

### Utils + Telemetry + Workspace (5)

**H20. `git_manager.py:212`—`is_main`detection uses wrong condition**:
The`bare`line in porcelain output only marks bare clones, not the main
worktree.`is_main`is permanently`False`for normal repos.

**H21.`git_manager.py:293-309`— TOCTOU race in merge pre-flight
check**:`has_conflicts()`runs outside the git mutex, then the mutex is acquired
for the actual merge. Another concurrent merge can change state between check
and merge.

**H22.`middleware.py:120-122`— Deprecated OTel semantic convention attributes**:
Uses`http.method`, `http.target`(deprecated v1.22). Current spec
requires`http.request.method`, `url.full`. Modern backends won't recognize these
spans.

**H23. `logging.py:107-119`— Library logger handler assignment bypasses
thread-lock**:`lib_logger.handlers = [log_handler]`directly assigns the list
instead of using`addHandler()`, creating a race on startup.

**H24. `utils/__init__.py`—`Model`, `AcpRequestId`, `MODEL_MAP`absent from
facade**: ADR-009 mandates facade re-exports. These are consumed by 5+ modules
but must be deep-imported.

### Tests (9)

**H25.`test_websocket.py`— Hardcoded`time.sleep(0.1)`in 4 places**:
Timing-dependent tests will be flaky on loaded CI runners.

**H26.`test_aggregator.py:309-319`— Structural fakes substitute for real
LangGraph objects**:`_FakeGraph`, `_FakeNode`, `_FakeTask`bypass actual
LangGraph protocol. Won't detect API changes.

**H27.`test_state.py:140-149`—`test_all_fields_are_primitives`duplicates`test_round_trip_json`**:
Calls `json.dumps`without asserting on the result. Zero additional coverage.

**H28.`test_exceptions.py:322-335`—`test_facade_reexports`is tautological**:
Asserts`X is not None`for names already imported at module scope. Collection
error would catch missing re-exports.

**H29.`test_logging.py:10-38`— Global logging state mutated between tests**: No
fixture resets root logger handlers between test functions. Order-dependent.

**H30.`test_database.py:97-104`— Singleton engine state leaks between
tests**:`get_engine()`singleton not properly isolated. Tests depend on execution
order.

**H31.`test_endpoints.py:339-363`—`_FakeGraph`bypasses real graph lifecycle in
permission test**.

**H32.`test_endpoints.py:376-406`— Autonomous tests assert only status codes**:
Don't verify that`interrupt_before_nodes`differs between modes.

**H33. Coverage gaps — 10 source modules have NO tests**:

-`src/vaultspec_a2a/core/models.py`— dataclass round-trip untested -`src/vaultspec_a2a/core/nodes/supervisor.py`— routing logic untested -`src/vaultspec_a2a/core/nodes/worker.py`— node execution untested -`src/vaultspec_a2a/providers/acp_exceptions.py`

- `src/vaultspec_a2a/providers/gemini_auth.py`— OAuth token refresh untested -`src/vaultspec_a2a/providers/probes/_protocol.py`(+ claude, gemini, openai, zhipu) -`src/vaultspec_a2a/utils/enums.py`
- `src/vaultspec_a2a/utils/printer.py`

---

## MEDIUM (37)

<!-- markdownlint-disable MD033 -->
<details>
<summary>Click to expand 37 MEDIUM findings</summary>
<!-- markdownlint-enable MD033 -->

### Core (9)

- M1. `aggregator.py`—`_chunk_buffers`key collision if two agents share the
  same`thread_id:agent_id`pair
- M2.`aggregator.py`— Missing pagination on`list_threads`query
- M3.`aggregator.py`—`aget_state`timeout hardcoded to 10s with no
  configurability
- M4.`graph.py`—`require_approval_for`field parsed but never validated against
  known tool names
- M5.`graph.py`— Topology enum validated by string comparison, not by enum
  membership
- M6.`state.py`—`loop_count`type annotation says`int`but nothing prevents
  negative values
- M7.`config.py`— Settings validation doesn't
  check`max_tokens`or`max_loops`ranges
- M8.`team_config.py`— TOML parsing errors surface as generic`ValueError`not
  domain exception
- M9.`metadata.py`—`discover_context_refs`reads file content but doesn't handle
  encoding errors

### API (7)

- M10.`endpoints.py`—`list_threads`returns all fields including full message
  arrays (no projection)
- M11.`endpoints.py`— No rate limiting on thread creation endpoint
- M12.`schemas/events.py`—`PermissionOptionKind`enum values not documented in
  OpenAPI
- M13.`schemas/rest.py`—`ThreadSummary.metadata`field serialization inconsistent
  (JSON string vs object)
- M14.`websocket.py`— No maximum message size limit on incoming WebSocket frames
- M15.`websocket.py`— Subscription filter uses string prefix matching (could
  match unintended threads)
- M16.`app.py`— Lifespan context manager doesn't log startup/shutdown events

### Providers (7)

- M17.`acp_chat_model.py`—`_handle_permission_request`doesn't validate option_id
  values
- M18.`acp_chat_model.py`— Hardcoded 60s timeout for ACP subprocess startup
- M19.`acp_chat_model.py`— Token usage tracking accumulates without bound (no
  per-session reset)
-

M20.`acp_chat_model.py`—`_handle_session_update`processes`agent_message_chunk`type
only; ignores`tool_call_chunk`

- M21. `factory.py`— No validation that`model_name`maps to a valid provider
- M22.`acp_exceptions.py`— Exception hierarchy doesn't
  include`__cause__`chaining
- M23.`factory.py`— OpenAI/ZhipuAI branches create`ChatOpenAI`without
  configuring retry policy

### Database + Protocols (6)

- M24.`crud.py`—`get_thread`doesn't eager-load related objects (N+1 query risk)
- M25.`crud.py`—`update_thread_status`accepts any string, not a constrained enum
- M26.`models.py`—`created_at`default uses`func.now()`(DB server time)
  not`datetime.utcnow()`(app time)
- M27.`models.py`— No cascading delete rules on thread → messages/artifacts
- M28.`mcp/server.py`—`_KNOWN_PRESETS`hardcoded as a set literal, not derived
  from team config
- M29.`mcp/server.py`— No request timeout configuration exposed to MCP clients

### Utils + Telemetry + Workspace (8)

- M30.`git_manager.py`—`has_conflicts`uses three separate`rev-parse`calls
  outside mutex (TOCTOU)
- M31.`git_manager.py`—`list_worktrees`parser silently drops final entry edge
  case
- M32.`instrumentation.py`— Module-level env var reads make telemetry config
  impossible to change at runtime
- M33.`middleware.py`— Exception handler uses`get_current_span()`redundantly
  when`span`is in scope
- M34.`environment.py`—`CWD`is a non-standard env var; should use`PWD`(POSIX) or
  omit
- M35.`logging.py` — Dead code in level coercion logic (`if level else "INFO"`is
  unreachable)
- M36.`git_manager.py`—`run_git`public method exposes unrestricted git command
  execution
- M37.`git_manager.py`— Module-level`asyncio.Lock()`may cause cross-loop
  warnings in Python 3.12+

</details>

---

## LOW (23)

<!-- markdownlint-disable MD033 -->
<details>
<summary>Click to expand 23 LOW findings</summary>
<!-- markdownlint-enable MD033 -->

### Core (5)

- L1.`aggregator.py`— Magic number`50`for chunk buffer size undocumented
- L2.`aggregator.py`—`_CHUNK_FLUSH_INTERVAL`is 0.05s but comment says "50ms
  flush interval"
- L3.`config.py`—`api_base_url`default`http://localhost:8000`doesn't match
  typical dev port
- L4.`exceptions.py`—`recovery_action`field values not documented
- L5.`state.py`—`TeamState`TypedDict keys not sorted alphabetically (style)

### API (4)

- L6.`endpoints.py`— Inconsistent
  naming:`create_thread_endpoint`vs`list_threads`(suffix vs no suffix)
-

L7.`schemas/rest.py`—`CreateThreadResponse`includes`thread_id`and`id`(redundant)

- L8.`websocket.py`— Log messages use f-strings instead of lazy`%s`formatting
- L9.`app.py`— Duplicate`tags`on router includes

### Providers (4)

- L10.`acp_chat_model.py`—`# noqa: PLR0912 PLR0915`comment lacks explanation of
  why
- L11.`factory.py`— Import of`ChatOpenAI`at function scope (per lazy import
  mandate — correct but undocumented)
- L12.`probes/_protocol.py`—`assert`statements used for control flow (not for
  debugging)
- L13.`probes/_protocol.py`—`pending`dict never cleaned up on timeout

### Database + Protocols (4)

- L14.`session.py`—`async_sessionmaker`type annotation uses`Any`
- L15. `crud.py`—`create_thread`return type annotation missing
- L16.`mcp/server.py`—`ws://`URL construction via string split is fragile
- L17.`models.py` — Table names use singular (`thread`, `artifact`) —
  inconsistent with convention

### Utils + Telemetry + Workspace (6)

- L18. `printer.py`— Module-level`console`singleton not underscore-prefixed
- L19.`printer.py`— Missing`__all__`
- L20. `logging.py`— Missing`__all__`
- L21. `test_telemetry.py`— Three tests acknowledge in comments they test
  nothing meaningful
- L22.`git_manager.py`— Module-level`asyncio.Lock()`at import time (style
  concern)
- L23.`middleware.py`—`_HTTP_500`naming inconsistent with`_HTTP_SERVER_ERROR`in
  test file

</details>

---

## Test Coverage Gap Analysis

| Source Module                      | Test Coverage                                  |
| ---------------------------------- | ---------------------------------------------- |
| `src/vaultspec_a2a/core/aggregator.py`           | Covered (structural fakes, not real LangGraph) |
| `src/vaultspec_a2a/core/config.py`               | Covered                                        |
| `src/vaultspec_a2a/core/context.py`              | Covered                                        |
| `src/vaultspec_a2a/core/exceptions.py`           | Covered (some tautological)                    |
| `src/vaultspec_a2a/core/graph.py`                | Covered (compile-only, tautological)           |
| `src/vaultspec_a2a/core/metadata.py`             | Covered                                        |
| `src/vaultspec_a2a/core/models.py`               | **MISSING**                                    |
| `src/vaultspec_a2a/core/nodes/supervisor.py`     | **MISSING**                                    |
| `src/vaultspec_a2a/core/nodes/worker.py`         | **MISSING**                                    |
| `src/vaultspec_a2a/core/preamble.py`             | Covered                                        |
| `src/vaultspec_a2a/core/state.py`                | Covered                                        |
| `src/vaultspec_a2a/core/team_config.py`          | Covered                                        |
| `src/vaultspec_a2a/api/endpoints.py`             | Covered                                        |
| `src/vaultspec_a2a/api/websocket.py`             | Covered (timing-dependent)                     |
| `src/vaultspec_a2a/api/schemas/*`                | Covered                                        |
| `src/vaultspec_a2a/database/crud.py`             | Covered                                        |
| `src/vaultspec_a2a/database/models.py`           | Covered                                        |
| `src/vaultspec_a2a/database/session.py`          | Covered (singleton leaks)                      |
| `src/vaultspec_a2a/providers/acp_chat_model.py`  | Live-only                                      |
| `src/vaultspec_a2a/providers/acp_exceptions.py`  | **MISSING**                                    |
| `src/vaultspec_a2a/providers/factory.py`         | Covered                                        |
| `src/vaultspec_a2a/providers/gemini_auth.py`     | **MISSING**                                    |
| `src/vaultspec_a2a/providers/probes/*`           | **MISSING** (5 files)                          |
| `src/vaultspec_a2a/protocols/mcp/server.py`      | Partial                                        |
| `src/vaultspec_a2a/telemetry/instrumentation.py` | Covered (import-time limitation)               |
| `src/vaultspec_a2a/telemetry/middleware.py`      | Covered                                        |
| `src/vaultspec_a2a/utils/enums.py`               | **MISSING**                                    |
| `src/vaultspec_a2a/utils/logging.py`             | Covered (state leaks)                          |
| `src/vaultspec_a2a/utils/printer.py`             | **MISSING**                                    |
| `src/vaultspec_a2a/workspace/git_manager.py`     | Covered                                        |
| `src/vaultspec_a2a/workspace/environment.py`     | Covered                                        |

### 10 source modules have zero test coverage

---

## Mandate Compliance

| Mandate                        | Status                                                                      |
| ------------------------------ | --------------------------------------------------------------------------- |
| `unittest`module imported      | PASS — zero occurrences                                                     |
| `Mock`/`MagicMock`/`patch`used | PASS — zero occurrences                                                     |
| `monkeypatch.setattr/delattr`  | PASS — only`setenv/delenv`(permitted)                                       |
| pytest only                    | PASS                                                                        |
| Tests in`tests/`subdirectories | PASS                                                                        |
| ADR-009 facade re-exports      | PARTIAL —`src/vaultspec_a2a/utils/__init__.py`missing`Model`, `MODEL_MAP`, `AcpRequestId` |
| ADR-010 OTel compliance        | PARTIAL — deprecated semantic convention attributes in middleware           |
| ADR-001 process safety         | PASS —`taskkill /T /F`pattern correct                                       |

---

## Priority Fix Order

### Immediate (security/correctness)

1. **C4** — Command injection in`terminal/create`(command allowlist)
2. **C5** — Git command injection via`agent_id`(input validation)
3. **C1** — CORS missing in production (always add middleware)
4. **C2** — Self-referential import in websocket.py
5. **H4** — Shared mutable`permission_callback`(copy model per invocation)
6. **H14** —`stdin_lock`bypass in public methods

### Next sprint (reliability)

1. **H8** — Permission endpoint missing ingest guard
2. **H9** — Thread committed before graph compilation (transactional)
3. **H16** — Synchronous HTTP in`gemini_auth.py`
4. **H17/H12** — TOCTOU in nickname uniqueness (catch `IntegrityError`)
5. **H21** — Git mutex TOCTOU in merge pre-flight
6. **H22** — OTel attribute names update

### Backlog (quality)

1. **H6/H7** — Silent worker skipping, loop_node validation
2. **H10** — WebSocket cleanup on failure
3. **H24** — Utils facade missing exports
4. **H33** — 10 modules without tests
5. All MEDIUM + LOW findings
