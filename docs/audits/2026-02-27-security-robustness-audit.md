---
date: 2026-02-27
type: audit
feature: security-robustness
description: 'Security and robustness audit identifying 3 critical issues including sandbox path bypass, subprocess command injection, and unchecked loop_count, plus 5 high and 6 medium findings.'
related:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-26-003-protocol-bridging-translation-adr.md
  - docs/adrs/2026-02-27-013-team-composition-topology-adr.md
---

# Security & Robustness Audit -- 2026-02-27

## Auditor: auditor-1

## Scope: Security, Robustness, Test Quality, Internal Contradictions

---

## CRITICAL SECURITY ISSUES

### [SEC-001] Path sandbox bypass via `startswith()`prefix collision -- acp_chat_model.py:470

**Severity:** CRITICAL
**Attack vector:** A malicious or hallucinating ACP agent sends
an`fs/read_text_file`or`fs/write_text_file`RPC with a crafted`path`parameter
that causes`_sandbox_path()`to incorrectly validate access.
**Impact:** Arbitrary file read/write outside the agent's working directory. An
agent sandboxed to`/home/user`could
access`/home/user2/secret`because`"/home/user2/secret".startswith("/home/user")`evaluates
to`True`.
**Evidence:**

```python
# lib/providers/acp_chat_model.py:466-472

def _sandbox_path(self, path: str) -> Path:
    """Resolve and sandbox a path to the agent cwd."""
    cwd = Path(self.cwd) if self.cwd else Path.cwd()
    resolved = (cwd / path).resolve()
    if not str(resolved).startswith(str(cwd.resolve())):
        raise ValueError(f"Path {path!r} escapes sandbox")
    return resolved
```

**Fix:** Replace
`str(resolved).startswith(str(cwd.resolve()))`with`resolved.is_relative_to(cwd.resolve())`(Python
3.9+). The`is_relative_to()`method correctly checks structural path containment,
not string prefixes.

---

### [SEC-002] Unsanitized subprocess command injection in`terminal/create`-- acp_chat_model.py:505-533

**Severity:** CRITICAL
**Attack vector:** The ACP agent sends a`terminal/create`RPC with an
arbitrary`command`and`args`list. These parameters are passed directly
to`asyncio.create_subprocess_exec()`without any validation, sanitization, or
allow-listing.
| **Impact:** Remote code execution. A compromised or hallucinating LLM agent
can execute any command on the host system:`{"command": "powershell.exe",
"args": ["-c", "Invoke-WebRequest ... | iex"]}`. Even non-malicious agents could
accidentally execute destructive commands. |
**Evidence:**

```python
# lib/providers/acp_chat_model.py:509-520

command = params["command"]
args = params.get("args") or []
terminal_cwd = params.get("cwd") or self.cwd or str(Path.cwd())
process = await asyncio.create_subprocess_exec(
    command,
    *args,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=terminal_cwd,
)
```

There is **zero validation** of the `command`parameter. No allowlist. No sandbox
check on`terminal_cwd`. The `cwd`parameter is also attacker-controlled and not
validated via`_sandbox_path()`.
**Fix:**

1. Validate `command`against an allowlist of permitted executables
   (e.g.,`["python", "node", "git", "npm", "uv"]`).
2. Validate `terminal_cwd`through`_sandbox_path()`(once SEC-001 is fixed).
3. Consider disabling`terminal/create`entirely
   unless`agent_config.capabilities.terminal`is`True`(currently checked at
   initialization but not enforced at RPC dispatch).

---

### [SEC-003]`create_subprocess_shell`with user-controlled command string -- acp_chat_model.py:158-174

**Severity:** CRITICAL
**Attack vector:** The`shell_command`on line 158 is constructed
from`self.command`via`" ".join(self.command)`, and passed to
`create_subprocess_shell()`. If the `command`list is sourced from an untrusted
input (e.g., a TOML config loaded from a workspace), a shell injection is
possible via embedded shell metacharacters.
**Impact:** Arbitrary shell command execution at orchestrator startup.
Example:`command = ["claude-agent-acp; rm -rf /"]`would be joined
to`"claude-agent-acp; rm -rf /"` and executed by the shell.
**Evidence:**

```python
# lib/providers/acp_chat_model.py:158-166

shell_command = " ".join(self.command)
# ...

process = await asyncio.create_subprocess_shell(
    shell_command,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    env=env,
    cwd=self.cwd or str(Path.cwd()),
    limit=10 * 1024 * 1024,
)
```

**Mitigating factors:** The `command`list is typically set
by`ProviderFactory`from a hardcoded enum, not from user input. However, the
agent TOML config files (ADR-012) are user-editable, and`AcpChatModel.command`is
a Pydantic field accepting any`list[str]`. If a workspace-local TOML file
provides a malicious command, it passes through unvalidated.
| **Fix:** Validate each element in `self.command`against a strict pattern (no
shell metacharacters:`;`, `|`, `&`, `$`, `` ` ``, `(`, `)`, `>`).
Alternatively, switch to `create_subprocess_exec`with the command list (ADR-006
notes that`create_subprocess_shell`is only needed for`.CMD`shim resolution on
Windows for Gemini). |

---

## HIGH SEVERITY ISSUES

### [SEC-004] Wide-open CORS in development mode -- app.py:147-154

**Severity:** HIGH
**Attack vector:** When`settings.is_dev`is`True` (the default), CORS allows all
origins with credentials. Any website can make authenticated cross-origin
requests to the orchestrator API, including creating threads, sending messages,
and responding to permissions.
**Impact:** Cross-site request forgery on the orchestrator. A malicious website
opened by the user could silently interact with the local orchestrator, approve
permissions, or exfiltrate thread state.
**Evidence:**

```python
# lib/api/app.py:147-154

if settings.is_dev:
    app.add_middleware(
        cast(Any, CORSMiddleware),
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

`allow_origins=["*"]`with`allow_credentials=True`is a dangerous combination.
Note: per CORS spec, browsers should reject`Access-Control-Allow-Origin: *`with
credentials, but Starlette's CORSMiddleware may echo the`Origin`header instead
of`*`in this configuration, effectively bypassing this browser guard.
**Fix:** In production mode there is NO CORS middleware at all (no restrictive
fallback). Either:

1. Always add CORS middleware with a
   restrictive`allow_origins`(e.g.,`["http://localhost:8000"]`).
2. In dev mode, use a specific localhost origin instead of `"*"`.

---

### [SEC-005] No WebSocket origin validation -- websocket.py / app.py:168-173

**Severity:** HIGH
**Attack vector:** The WebSocket endpoint at `/ws` accepts connections from any
origin. A cross-site page can open a WebSocket to the orchestrator and subscribe
to thread events.
**Impact:** Information disclosure and potential state manipulation via
WebSocket commands. Any website the user visits could subscribe to all threads
and read streaming LLM output, tool calls, and permission requests.
**Evidence:**

```python
# lib/api/app.py:168-173

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    cm: ConnectionManager = app.state.connection_manager
    client_id = await cm.connect(websocket)
    await cm.listen(client_id)
```

No origin header check before `accept()`. No authentication of any kind.
**Fix:** Before `websocket.accept()`, validate
`websocket.headers.get("origin")`against an allowlist. Consider adding a
token-based authentication step.

---

### [SEC-006] No authentication on any REST or WebSocket endpoint --

endpoints.py, websocket.py

**Severity:** HIGH
**Attack vector:** All REST endpoints and the WebSocket are unauthenticated. Any
process on the local machine (or any remote attacker if the server is bound
to`0.0.0.0`) can create threads, send messages, respond to permissions, and
subscribe to events.
**Impact:** Full API access without authorization. Permission responses (`POST
/permissions/{id}/respond`) could be answered by an unauthorized party,
effectively bypassing the human-in-the-loop safety mechanism (ADR-006).
**Evidence:** No authentication middleware, no JWT validation, no API key checks
anywhere in `endpoints.py`, `websocket.py`, or `app.py`. The only auth-related
module mentioned in ADR-009 (`lib/api/auth.py`) does not exist.
**Fix:** For v1 local-only deployment, add at minimum:

1. A startup-generated random token printed to the console (like Jupyter).
2. Require this token as a query parameter for WebSocket and as a Bearer header
   for REST.
3. Bind to `127.0.0.1`only (not`0.0.0.0`).

---

### [SEC-007] Permission response has no thread-scoping or ownership check -- endpoints.py:459-519

**Severity:** HIGH
**Attack vector:** `POST /permissions/{request_id}/respond`parses
the`thread_id`from the`request_id`string by splitting on`:`. There is no
verification that the caller owns the thread or that the `request_id`corresponds
to a genuine pending permission request.
**Impact:** Any client can respond to any permission request. An attacker who
guesses or observes a`request_id`can auto-approve destructive actions
(e.g.,`fs.writeTextFile` on sensitive paths).
**Evidence:**

```python
# lib/api/endpoints.py:486-490

thread_id = ""
if ":" in request_id:
    thread_id, _ = request_id.split(":", 1)
graph = registry.get(thread_id) if thread_id else None
```

The `request_id`format is documented as`{thread_id}:{uuid}`but there is no
validation that:

1. The`request_id`corresponds to an actual pending interrupt.
2. The client is authorized to respond to this thread.
   **Fix:** Maintain a set of pending`request_id`values in the`GraphRegistry`. Only
   accept responses for IDs that were actually emitted by a
   `PermissionRequestEvent`. Delete the ID after use (one-shot).

---

### [SEC-008] Unbounded `asyncio.Queue`in`AcpChatModel`-- acp_chat_model.py:183

**Severity:** HIGH
**Attack vector:** A malicious or verbose ACP subprocess
floods`session/update`notifications faster than the`_yield_chunks`consumer can
process them.
**Impact:** Memory exhaustion (OOM) on the server. The`chunk_queue`has
no`maxsize` bound.
**Evidence:**

```python
# lib/providers/acp_chat_model.py:183

chunk_queue=asyncio.Queue(),
```

No `maxsize`parameter. Compare with the`EventAggregator`which correctly
uses`maxsize=512`.
**Fix:** Set `asyncio.Queue(maxsize=1024)`or similar. When full, either drop
oldest or apply backpressure (block on put).

---

## MEDIUM SEVERITY ISSUES

### [SEC-009] No message size limit on WebSocket incoming frames -- websocket.py:176

**Severity:** MEDIUM
**Attack vector:** A client sends a 1GB JSON message via
WebSocket.`websocket.receive_json()` will attempt to parse the entire payload in
memory.
**Impact:** Memory exhaustion (OOM). Starlette's default does not impose a
WebSocket frame size limit.
**Evidence:**

```python
# lib/api/websocket.py:176

raw = await asyncio.wait_for(
    websocket.receive_json(),
    timeout=_DEAD_CLIENT_TIMEOUT,
)
```

**Fix:** Configure Uvicorn's `--ws-max-size`or implement a size check before
JSON parsing.

---

### [SEC-010]`team_preset`not validated against a whitelist -- endpoints.py:163-170

**Severity:** MEDIUM
**Attack vector:**`CreateThreadRequest.team_preset`is validated
by`load_team_config()`which checks filesystem paths. An attacker could probe for
path traversal patterns (e.g.,`../../etc/passwd`) in the preset ID if
`load_team_config`naively constructs paths from the ID.
**Impact:** Potential path traversal during TOML loading depending
on`load_team_config` implementation.
**Evidence:**

```python
# lib/api/endpoints.py:163-170

if body.team_preset:
    try:
        team_config = load_team_config(body.team_preset)
    except TeamConfigNotFoundError as exc:
        raise HTTPException(...)
```

**Fix:** Validate `team_preset`against a strict pattern:`^[a-z0-9-]+$`(no
slashes, no dots).

---

### [SEC-011] Subscription scoping allows any client to subscribe to any thread

-- websocket.py:214-222

**Severity:** MEDIUM
**Attack vector:** A WebSocket client sends a`subscribe`command for
any`thread_id` without authorization.
**Impact:** Information disclosure. Any connected client can observe any
thread's events.
**Evidence:**

```python
# lib/api/websocket.py:214-222

case ClientCommandType.SUBSCRIBE:
    cmd = cast(SubscribeCommand, command)
    self._aggregator.subscribe(client_id, cmd.thread_ids)
```

No ownership check on the `thread_ids`.
**Fix:** Check that the client has permission to subscribe to the requested
threads (e.g., the client must have created the thread or been explicitly
granted access).

---

### [SEC-012] `terminal/output`reads only 64KB but has no cumulative size cap --

acp_chat_model.py:553-585

**Severity:** MEDIUM
**Attack vector:** A terminal subprocess produces unbounded output.
Repeated`terminal/output`RPCs accumulate data with no overall limit.
**Impact:** The per-read 64KB cap prevents single-read OOM, but a malicious
process running indefinitely will consume unbounded memory over time if the
orchestrator keeps reading on behalf of the agent.
**Fix:** Track cumulative bytes read per terminal. Kill the terminal if it
exceeds a configurable limit (e.g., 10MB).

---

### [SEC-013] Synchronous file I/O in async context -- acp_chat_model.py:480, 496

**Severity:** MEDIUM
**Attack vector:** N/A (design issue, not an attack vector).
**Impact:**`file_path.read_text()`and`file_path.write_text()` are synchronous
I/O calls inside async RPC handlers. If the file is on a slow/networked
filesystem, this blocks the entire event loop, freezing all concurrent agents.
**Evidence:**

```python
# acp_chat_model.py:480

text = file_path.read_text(encoding="utf-8", errors="ignore")
# acp_chat_model.py:496

file_path.write_text(params["content"], encoding="utf-8")
```

**Fix:** Use `asyncio.to_thread()`or`aiofiles`for file I/O in async handlers.

---

### [SEC-014] Fire-and-forget`asyncio.create_task`without tracking --

endpoints.py:376, 494

**Severity:** MEDIUM
**Attack vector:** N/A (robustness issue).
**Impact:**`asyncio.create_task()`on lines 376 and 494 creates background tasks
for graph ingest but does not store references to them. If the task raises an
exception, it will be silently lost (garbage-collected with an unhandled
exception warning). The`# noqa: RUF006` comments explicitly suppress the linter
warning about this.
**Evidence:**

```python
# endpoints.py:376-378

asyncio.create_task(  # noqa: RUF006
    aggregator.ingest(thread_id, agent_id, graph, graph_input, config)
)
```

**Fix:** Store task references in a set (like
`ctx.background_tasks`in`AcpChatModel`) and add done callbacks for exception
logging.

---

## LOW SEVERITY ISSUES

### [SEC-015] `_active_session_id`used unsanitized in RPC requests -- acp_chat_model.py

**Severity:** LOW
**Attack vector:** The`_active_session_id`is set from the ACP
subprocess's`session/new`response. If the subprocess returns a malicious session
ID containing JSON-RPC-breaking characters, it could corrupt the request
framing.
**Impact:** Minimal.`json.dumps()`properly escapes all string values, preventing
framing attacks. The session ID flows into a JSON object value, not a structural
position.

---

### [SEC-016] Orphaned response futures are silently dropped -- acp_chat_model.py:395-400

**Severity:** LOW
**Attack vector:** If a JSON-RPC response arrives with an`id`not
in`response_futures` (or already resolved), the response is silently discarded.
**Impact:** Low. No crash, no panic. But debugging is harder because unexpected
responses are invisible.
**Evidence:**

```python
# acp_chat_model.py:398-400

if rid in ctx.response_futures and not ctx.response_futures[rid].done():
    ctx.response_futures[rid].set_result(data)
```

Correctly guarded. This is actually well-implemented. The check for `not
fut.done()` prevents double-set errors.

---

### [SEC-017] Database: SQLAlchemy ORM used exclusively, no raw SQL -- database/crud.py

**Severity:** LOW (positive finding)
**Impact:** All database queries use SQLAlchemy's expression language
(`select()`, `func.sum()`, `mapped_column()`). No raw SQL strings. No SQL
injection vectors. The `text()`call in`session.py:164` (`PRAGMA journal_mode`)
uses a constant string with no interpolation.

---

### [SEC-018] Git command injection mitigated by `create_subprocess_exec`-- git_manager.py

**Severity:** LOW
**Attack vector:** Branch names and paths flow into`_run_git()`as individual
arguments to`create_subprocess_exec()`(not shell-interpolated).
The`*args`unpacking ensures each argument is a separate element.
**Impact:** Minimal. The use of`create_subprocess_exec`(not`shell`) properly
isolates arguments. However, git itself can interpret arguments starting with
`--`as options (e.g.,`branch_name = "--exec=malicious"`).
**Fix:** Consider prepending `--`before user-supplied branch names to prevent
option injection (e.g.,`git checkout -- branch_name`).

---

### [SEC-019] Global git mutex uses `asyncio.shield()`correctly -- git_manager.py:144-157

**Severity:** LOW (positive finding)
**Impact:** The mutex is correctly held with`async with _git_mutex:`and
individual operations are shielded via`asyncio.shield()`to prevent task
cancellation from releasing the lock mid-operation. This correctly addresses
ADR-001's constraint about cancellation safety.

---

## ROBUSTNESS ISSUES

### [ROB-001] No timeout on`_process_stdout_loop`readline -- acp_chat_model.py:348

**Severity:** HIGH
**Attack vector:** The ACP subprocess hangs (e.g., deadlock, infinite loop
without output).`ctx.stdout.readline()`blocks indefinitely.
**Impact:** The`_astream()`generator will never complete.
The`_yield_chunks`polling loop will timeout repeatedly but never raises
because`prompt_done`is never set and`prompt_future` is never resolved.
**Evidence:**

```python
while line := await ctx.stdout.readline():
```

No timeout wrapper. The only way this exits is if the subprocess writes a `\n`or
closes stdout.
**Fix:** Wrap the readline in`asyncio.wait_for()`with a generous timeout
(e.g.,`settings.provider_timeout_seconds`). Alternatively, implement a watchdog
that kills the subprocess if no output is received within a timeout.

---

### [ROB-002] `_broadcast`uses`await queue.put()`which can deadlock -- aggregator.py:307

**Severity:** MEDIUM
**Attack vector:** A slow or disconnected WebSocket client causes its event
queue to fill up (maxsize=512).`await queue.put(event)` blocks the broadcaster,
which holds up all other subscribers.
**Impact:** One slow client blocks event delivery to all clients. A single
unresponsive client can freeze the entire event pipeline.
**Evidence:**

```python
# aggregator.py:304-308

for client_id, queue in list(self._subscribers.items()):
    client_subs = self._subscriptions.get(client_id, set())
    if thread_id is None or thread_id in client_subs:
        await queue.put(event)
```

**Fix:** Use `queue.put_nowait()`with a try/except for`asyncio.QueueFull`,
dropping the event (or disconnecting the slow client). Alternatively, use a
per-client delivery task that drains from a separate bounded channel.

---

### [ROB-003] `_on_request_permission`returns empty dict on GraphBubbleUp -- acp_chat_model.py:451

**Severity:** MEDIUM
**Impact:** When`GraphBubbleUp`is caught, the handler returns`{}`which is then
serialized as JSON and sent to the subprocess's stdin as the RPC response. This
is not a valid JSON-RPC response (missing`jsonrpc`, `id`, and `result`/`error`
fields). The subprocess may reject or mishandle it.
**Evidence:**

```python
# acp_chat_model.py:448-451

except GraphBubbleUp as exc:
    ctx.interrupt_exc.append(exc)
    await ctx.chunk_queue.put(None)
    return {}
```

**Fix:** Return a properly formatted JSON-RPC error response (e.g., `{"jsonrpc":
"2.0", "id": rpc_id, "error": {"code": -32603, "message": "Graph
interrupted"}}`).

---

### [ROB-004] Permission callback exception auto-grants first option -- acp_chat_model.py:452-456

**Severity:** MEDIUM
**Impact:** If the `permission_callback`raises any exception (other
than`GraphBubbleUp`), the handler silently auto-grants the first permission
option. This is a fail-open behavior that could approve destructive actions when
the permission system is broken.
**Evidence:**

```python
except Exception:
    logger.exception(
        "Permission callback raised; auto-granting first option"
    )
    option_id = options[0]["optionId"] if options else "allow_once"
```

**Fix:** Fail-closed. If the permission callback fails, deny the permission or
re-raise to abort the agent.

---

### [ROB-005] `merge_worktree`has TOCTOU race between`has_conflicts()` and merge

-- git_manager.py:282-309

**Severity:** MEDIUM
**Impact:** The pre-flight conflict check (`has_conflicts()`) on line 282 runs
outside the mutex. Another agent could push changes between the check and the
actual merge (which runs inside the mutex), causing an unexpected merge failure.
**Evidence:**

```python
# git_manager.py:282-288

if await self.has_conflicts(worktree_path, target_branch):
    # ... raise MergeConflictError
async with _git_mutex:
    # ... do merge
```

**Fix:** Move `has_conflicts()`inside the`_git_mutex`context, or catch merge
failures gracefully inside the mutex.

---

### [ROB-006]`_sequence`counter is not thread-safe under concurrent ingest -- aggregator.py:183-186

**Severity:** LOW
**Impact:**`_next_sequence()`is a plain dict increment with no lock or atomic
operation. If two concurrent`ingest()`coroutines for the same`thread_id`both
call`_next_sequence()`in the same event loop tick, sequence numbers could be
duplicated. However, Python's GIL and the cooperative async model make this
extremely unlikely in practice (dict operations are atomic at the bytecode
level).
**Fix:** Document that`_next_sequence`relies on GIL atomicity, or protect
with`self._lock`.

---

## TEST QUALITY VIOLATIONS

### [TEST-001] `monkeypatch.setenv`usage -- lib/core/tests/test_config.py:19-54

**Violation:** FORBIDDEN per CLAUDE.md: "Avoid monkeypatching."
**Evidence:** Functions`test_config_vaultspec_env_prefix`(line 19)
and`test_config_aliases`(line 33) use`monkeypatch: pytest.MonkeyPatch`to set
environment variables via`monkeypatch.setenv()`. This appears 10 times across
the file.
**Recommendation:** Use a proper environment fixture that sets and restores real
environment variables, or make environment access part of the official Settings
API (e.g., pass env dict to `Settings()`).

---

### [TEST-002] `monkeypatch.setenv`/`monkeypatch.delenv`usage -- lib/telemetry/tests/test_telemetry.py:60-101

**Violation:** FORBIDDEN per CLAUDE.md: "Avoid monkeypatching."
**Evidence:**

- Line 60:`test_configure_telemetry_sdk_disabled(monkeypatch:
pytest.MonkeyPatch)`uses`monkeypatch.setenv("OTEL_SDK_DISABLED", "true")`
- Line 96: `test_configure_telemetry_langsmith_off(monkeypatch:
  pytest.MonkeyPatch)`uses`monkeypatch.delenv("LANGCHAIN_TRACING_V2",
  raising=False)`
  **Note:** The test itself acknowledges on line 68 that "monkeypatching the env
  var does not affect already-imported modules" -- the test is actually
  ineffective at testing what it claims.

---

### [TEST-003] `pytest.skip()` usage in live tests -- lib/providers/tests/test_acp_chat_model.py:41,103

**Violation:** Red flag per audit scope. Tests that skip based on missing
credentials.
**Evidence:**

```python
if not settings.claude_code_oauth_token:
    pytest.skip("CLAUDE_CODE_OAUTH_TOKEN not set -- Claude ACP unavailable.")
```

**Mitigating factor:** These are `@pytest.mark.live`tests that genuinely require
external credentials. The Gemini tests do NOT skip (they expect credentials to
always be available via`~/.gemini/oauth_creds.json`). This is a reasonable
pattern for live integration tests.
**Assessment:** ACCEPTABLE -- these are not hiding broken code; they guard tests
that require real external services.

---

## STUBS / PLACEHOLDERS IN SOURCE CODE

### [STUB-001] `NotImplementedError`in`_generate` -- lib/providers/acp_chat_model.py:323

### Evidence

```python
def _generate(self, ...) -> ChatResult:
    """Synchronous generate not supported."""
    raise NotImplementedError("AcpChatModel only supports async.")
```

**Assessment:** ACCEPTABLE. This is a `BaseChatModel`abstract method override.
The`_generate`synchronous path is intentionally unsupported per ADR-001 (all
operations must be async). The`NotImplementedError`is the correct pattern for an
abstract method that deliberately refuses synchronous invocation.

---

### [STUB-002]`lib/core/registry.py`and`lib/core/permissions.py` -- DELETED (confirmed)

**Evidence:** Both files are listed as deleted in git status (`MD
lib/core/registry.py`, and `permissions.py`does not exist on disk). ADR-009
mandates their deletion, and this has been completed.
**Assessment:** CLEAN. The ADR-009 mandate is fulfilled. However, git status
shows`registry.py`as`MD`(modified + deleted), suggesting it was staged for
deletion but still tracked. This should be committed.

---

### [STUB-003] Empty`GraphBubbleUp`return in`_on_request_permission`-- acp_chat_model.py:451

**Evidence:**`return {}`-- covered under [ROB-003] above.

---

## INTERNAL CONTRADICTIONS

### [CONTRA-001]`create_subprocess_shell` vs ADR-001 mandate

**ADR reference:** ADR-001 section 5: "cmd.exe /c is strictly forbidden across
all subprocess invocations". ADR-006 section 5.1 point 1:
"`asyncio.create_subprocess_shell(command_str, ...)`" is the **mandated**
pattern for Gemini.
**Evidence:** `acp_chat_model.py:166`uses`create_subprocess_shell()`for all
providers (both Claude and Gemini). ADR-001 bans`cmd.exe /c`but ADR-006
mandates`create_subprocess_shell`specifically for Gemini. For Claude, ADR-002
specifies direct`node.exe`invocation bypassing shell, yet the
same`create_subprocess_shell`is used.
**Assessment:** The implementation correctly follows ADR-006 section 5.1 which
explicitly overrides ADR-001's general guidance for this specific use case.
However, there is a tension: using shell mode for Claude (which deploys
as`dist/index.js`under node) when`create_subprocess_exec`would be safer. The
current`command`field accepts a list but joins them into a shell string, which
is unnecessary for exec-style invocation.

---

### [CONTRA-002] Lazy imports undocumented circular dependency root cause

**ADR reference:** ADR-009 section 5 mandates facade pattern with explicit
imports.
**Evidence:**
Both`lib/core/__init__.py:88-94`and`lib/providers/__init__.py:20-26`use`importlib.import_module()`
lazy imports with comments identifying the circular chain:

```python
# Lazy imports to break circular dependencies:
# - core.aggregator <-> api.websocket
# - core.graph -> providers.factory -> providers.acp_chat_model -> core.team_config -> core.__init__

```

**Assessment:** The comments explain WHAT the cycle is but not WHY it cannot be
resolved structurally. The circular dependency is: `core.__init__`eagerly
imports from`team_config`, while
`providers.acp_chat_model`imports`team_config`and`core.graph`imports`providers.factory`.
This could potentially be resolved by:

1. Not importing `team_config`types eagerly in`core.__init__.py`(they could be
   lazy too)
2. Making`acp_chat_model`accept`AgentConfig`as a plain dict instead of importing
   the Pydantic model

This is a code smell but not a correctness issue. The lazy import pattern works
correctly.

---

### [CONTRA-003]`_broadcast`uses blocking`await queue.put()`despite backpressure

documentation

**ADR reference:** ADR-011 section 5 discusses debouncing rules. Research
section 1.5 specifies backpressure boundaries.
**Evidence:**`EventAggregator.add_subscriber()`correctly creates bounded queues
with`maxsize=512`, but `_broadcast()`uses`await queue.put()`which blocks when
full. The research section says to use backpressure but the implementation
blocks the broadcaster (affecting ALL clients) rather than dropping events for
the slow client.
**Assessment:** The bounded queue is correctly created but the broadcasting
strategy is wrong. See [ROB-002] for details.

---

### [CONTRA-004] ADR-009 lists`lib/api/auth.py`but the file does not exist

**ADR reference:** ADR-009 section 2.2 hierarchy
shows`lib/api/auth.py`(WebSocket/REST authentication).
**Evidence:** No`auth.py`exists in`lib/api/`. No authentication is implemented
anywhere. See [SEC-006].
**Assessment:** ADR-009 describes the target architecture. The authentication
module is unimplemented.

---

## CLEAN (passed all checks)

- **lib/database/crud.py** -- All queries use SQLAlchemy ORM. No raw SQL.
  Parameterized queries throughout. No injection vectors.
- **lib/database/models.py** -- Clean SQLAlchemy declarative models with proper
  FK constraints and indexes.
- **lib/database/session.py** -- WAL mode correctly set via `PRAGMA
journal_mode=WAL`. Connection lifecycle properly managed.
- **lib/database/**init**.py** -- Proper facade with `X as X`re-exports
  and`__all__`.
- **lib/core/state.py** -- Clean TypedDict with custom reducers.
  JSON-serializable as required.
- **lib/core/exceptions.py** -- Well-structured error taxonomy with
  severity/recovery hints.
- **lib/providers/gemini_auth.py** -- Atomic file write pattern. Proper timeout
  on HTTP call. Public client credentials documented correctly.
- **lib/api/schemas/** -- All 6 schema modules clean. Proper `__all__`,
  discriminated unions, and Pydantic v2 patterns.
- **lib/workspace/git_manager.py** -- `create_subprocess_exec` used correctly.
  Mutex + shield pattern correct (except TOCTOU in merge, see [ROB-005]).
- **lib/core/tests/test_exceptions.py** -- No mocks, no stubs.
- **lib/core/tests/test_graph.py** -- No mocks, no stubs.
- **lib/api/schemas/tests/test_schemas.py** -- No mocks, no stubs.
- **lib/utils/tests/test_logging.py** -- No mocks, no stubs.
- **lib/workspace/tests/test_workspace.py** -- Explicitly states "no mocks, no
  monkeypatching" and creates real temp git repos.
- **lib/database/tests/test_database.py** -- Explicitly states "No mocks, no
  monkeypatching" and runs against real aiosqlite.
