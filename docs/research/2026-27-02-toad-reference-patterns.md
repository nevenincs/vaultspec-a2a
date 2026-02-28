# TOAD Reference Patterns for ACP Audit Issues

**Date:** 2026-02-27
**Source:** `knowledge/repositories/toad/src/toad/acp/agent.py` (807 lines, read in full)
**Supporting files:** `protocol.py`, `messages.py`, `danger.py`, `widgets/terminal_tool.py`, `widgets/conversation.py`, `jsonrpc.py`

---

## Issue 1: terminal/create command injection (SEC-002)

### TOAD Implementation (agent.py:381-414, widgets/terminal_tool.py:177-210, danger.py:9-105)

**agent.py `rpc_terminal_create` (lines 381-414):**
```python
@jsonrpc.expose("terminal/create")
async def rpc_terminal_create(
    self,
    command: str,
    _meta: dict | None = None,
    args: list[str] | None = None,
    cwd: str | None = None,
    env: list[protocol.EnvVariable] | None = None,
    outputByteLimit: int | None = None,
    sessionId: str | None = None,
) -> protocol.CreateTerminalResponse:
    self._terminal_count = self._terminal_count + 1
    terminal_id = f"terminal-{self._terminal_count}"

    terminal_env = (
        {variable["name"]: variable["value"] for variable in env} if env else {}
    )
    result_future: asyncio.Future[bool] = asyncio.Future()
    self.post_message(
        messages.CreateTerminal(
            terminal_id,
            command=command,
            args=args,
            cwd=cwd,
            env=terminal_env,
            output_byte_limit=outputByteLimit,
            result_future=result_future,
        )
    )
    await result_future
    if not result_future.result():
        raise jsonrpc.JSONRPCError("Failed to create a terminal.")
    return {"terminalId": terminal_id}
```

**terminal_tool.py `_run` (lines 177-210) -- actual process creation:**
```python
command = self._command
environment = os.environ | command.env

if " " in command.command:
    run_command = command.command
else:
    run_command = f"{command.command} {shlex.join(command.args)}"

shell = os.environ.get("SHELL", "sh")
run_command = shlex.join([shell, "-c", run_command])

try:
    process = self._process = await asyncio.create_subprocess_shell(
        run_command,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=environment,
        cwd=command.cwd,
    )
```

**danger.py `SAFE_COMMANDS` (lines 9-105) and `UNSAFE_COMMANDS` (lines 107-182):**
```python
SAFE_COMMANDS = {
    "echo", "cat", "less", "more", "head", "tail", "tac", "nl",
    "ls", "tree", "pwd", "file", "stat", "du", "df",
    "find", "locate", "which", "whereis", "type", "grep", "egrep", "fgrep",
    "wc", "sort", "uniq", "cut", "paste", "column", "tr", "diff", "cmp", "comm",
    "whoami", "who", "w", "id", "hostname", "uname", "uptime", "date", "cal", "env", "printenv",
    "ps", "top", "htop", "pgrep", "jobs", "pstree",
    "ping", "traceroute", "nslookup", "dig", "host", "netstat", "ss", "ifconfig", "ip",
    "zcat", "zless",
    "history", "man", "help", "info", "apropos", "whatis",
    "md5sum", "sha256sum", "sha1sum", "cksum", "sum",
    "bc", "expr", "test", "sleep", "true", "false", "yes", "seq", "basename", "dirname", "realpath", "readlink",
}

UNSAFE_COMMANDS = {
    "mkdir", "touch", "mktemp", "mkfifo", "mknod",
    "rm", "rmdir", "shred",
    "mv", "cp", "rsync", "scp", "install",
    "sed", "awk", "tee",
    "chmod", "chown", "chgrp", "chattr", "setfacl",
    "ln", "link", "unlink",
    "tar", "untar", "zip", "unzip", "gzip", "gunzip", "bzip2", "bunzip2", "xz", "unxz", "7z", "rar", "unrar",
    "wget", "curl", "fetch", "aria2c",
    "dd", "truncate", "fallocate",
    "split", "csplit",
    "sync",
    "useradd", "userdel", "usermod", "groupadd", "groupdel", "passwd",
    "mount", "umount", "mkfs", "fdisk", "parted", "swapon", "swapoff",
    "patch",
}
```

**danger.py `analyze()` (lines 253-355) -- path validation using `is_relative_to`:**
```python
project_path = Path(project_directory).resolve()
# ...
if not target_path.is_relative_to(project_path):
    yield CommandAtom("redirect", DangerLevel.DESTRUCTIVE, target_path, command_node.pos)
# ...
if level == DangerLevel.DANGEROUS and not target_path.is_relative_to(project_path):
    level = DangerLevel.DESTRUCTIVE
```

### Key Pattern
TOAD does **not** validate or allowlist `command` at the ACP protocol handler level (`rpc_terminal_create`). The command is passed through unmodified to `TerminalTool`, which wraps it in `sh -c <command>` and runs via `create_subprocess_shell`. However, TOAD has a separate `danger.py` module that performs command classification (SAFE/UNKNOWN/DANGEROUS/DESTRUCTIVE) using `bashlex` AST parsing, plus `is_relative_to()` for path boundary checks. This danger analysis is used by the **UI layer** (conversation widget) for visual warnings and permission prompts -- it is NOT enforced at the protocol handler level.

### What Our Code Should Do
1. **Adopt the danger analysis pattern**: Implement a command classifier that categorizes commands into SAFE/UNKNOWN/DANGEROUS/DESTRUCTIVE levels using the command name and path arguments relative to project root.
2. **Use `is_relative_to()`** for cwd validation rather than string prefix matching.
3. **Consider requiring permission** for DANGEROUS/DESTRUCTIVE commands before execution.
4. The `env` parameter merges agent-requested env vars over `os.environ` (TOAD line 188: `os.environ | command.env`), so our code should do the same but may want to filter sensitive vars.

---

## Issue 2: Path sandbox (_sandbox_path) (SEC-001)

### TOAD Implementation (danger.py:265,314,340; agent.py:357-359,377)

**danger.py path validation (line 265, 314, 340):**
```python
project_path = Path(project_directory).resolve()
# ...
if not target_path.is_relative_to(project_path):
    # DESTRUCTIVE
```

**agent.py `rpc_read_text_file` (lines 348-370):**
```python
@jsonrpc.expose("fs/read_text_file")
def rpc_read_text_file(
    self, sessionId: str, path: str,
    line: int | None = None, limit: int | None = None,
) -> dict[str, str]:
    # TODO: what if the read is outside of the project path?
    read_path = self.project_root_path / path
    try:
        text = read_path.read_text(encoding="utf-8", errors="ignore")
    except IOError:
        text = ""
    # ...
```

**agent.py `rpc_write_text_file` (lines 372-378):**
```python
@jsonrpc.expose("fs/write_text_file")
def rpc_write_text_file(self, sessionId: str, path: str, content: str) -> None:
    # TODO: What if the agent wants to write outside of the project path?
    write_path = self.project_root_path / path
    write_path.write_text(content, encoding="utf-8", errors="ignore")
```

### Key Pattern
TOAD has the **same vulnerability** in its `fs/read_text_file` and `fs/write_text_file` handlers -- there is no path sandboxing at all. The code has explicit `TODO` comments acknowledging the gap (lines 357 and 374). However, in the `danger.py` module (used for terminal commands), TOAD uses `Path.is_relative_to()` for proper path boundary validation -- this is the correct approach.

Additionally, `toad/prompt/resource.py:39` has proper sandbox validation:
```python
if not resource_path.is_relative_to(root):
```

### What Our Code Should Do
1. **Replace `str(resolved).startswith(str(cwd.resolve()))` with `resolved.is_relative_to(cwd.resolve())`**. The `startswith` approach has a prefix collision bug: `/home/user/project-secrets` would be accepted as within `/home/user/project`.
2. Apply this check to both `fs/read_text_file` and `fs/write_text_file`.
3. Resolve the path first, then check `is_relative_to`, which handles `..` traversal attempts.

---

## Issue 3: Permission callback fail-closed (ROB-004)

### TOAD Implementation (agent.py:302-346)

```python
@jsonrpc.expose("session/request_permission")
async def rpc_request_permission(
    self,
    sessionId: str,
    options: list[protocol.PermissionOption],
    toolCall: protocol.ToolCallUpdatePermissionRequest,
    _meta: dict | None = None,
) -> protocol.RequestPermissionResponse:
    result_future: asyncio.Future[Answer] = asyncio.Future()
    tool_call_id = toolCall["toolCallId"]

    permission_tool_call = toolCall.copy()
    permission_tool_call.pop("sessionUpdate", None)
    tool_call = cast(protocol.ToolCall, permission_tool_call)
    if tool_call_id in self.tool_calls:
        self.tool_calls[tool_call_id] |= tool_call
    else:
        self.tool_calls[tool_call_id] = deepcopy(tool_call)

    tool_call = deepcopy(self.tool_calls[tool_call_id])

    message = messages.RequestPermission(options, tool_call, result_future)
    self.post_message(message)
    await result_future
    ask_result = result_future.result()

    request_permission_outcome: protocol.OutcomeSelected = {
        "optionId": ask_result.id,
        "outcome": "selected",
    }
    result: protocol.RequestPermissionResponse = {
        "outcome": request_permission_outcome
    }
    return result
```

**TOAD's JSONRPC error handling (jsonrpc.py:144-170):**
```python
async def _dispatch_object(self, json: JSONObject) -> JSONType | None:
    # ...
    try:
        return await self._dispatch_object_call(request_id, json)
    except JSONRPCError as error:
        return {
            "jsonrpc": "2.0", "id": error.id,
            "error": {"code": int(error.code), "message": error.message},
        }
    except Exception as error:
        return {
            "jsonrpc": "2.0", "id": request_id,
            "error": {"code": int(ErrorCode.INTERNAL_ERROR),
                      "message": f"An error occurred handling your request: {error!r}"},
        }
```

### Key Pattern
TOAD **fails closed by default**. If any exception occurs in `rpc_request_permission`, the JSONRPC server wrapper catches it and returns an error response to the subprocess. It does NOT auto-grant or select any option. The subprocess (agent) receives a JSONRPC error and must handle it. The permission flow uses `asyncio.Future` and awaits a user-provided `Answer` -- if the future fails or an exception propagates, it becomes a JSONRPC error response, not an auto-grant.

There is no `try/except` with fallback-to-first-option anywhere in TOAD's permission handler. The permission outcome is only constructed after successfully awaiting the user's answer.

### What Our Code Should Do
1. **Remove the auto-grant-on-exception pattern**. If `permission_callback` raises, the correct behavior is to deny (fail closed) by either:
   - Returning a JSONRPC error response to the subprocess, OR
   - Returning an `outcome: "cancelled"` response
2. The `protocol.OutcomeCancelled` type (`{"outcome": "cancelled"}`) exists in TOAD's protocol for exactly this purpose (protocol.py:341-342).
3. Never construct `OutcomeSelected` unless the user has explicitly selected an option.

---

## Issue 4: Plan session update (ACP-002)

### TOAD Implementation (agent.py:260-261, protocol.py:244-248,285-288, messages.py:56-57)

**agent.py (lines 260-261):**
```python
case {"sessionUpdate": "plan", "entries": entries}:
    self.post_message(messages.Plan(entries))
```

**protocol.py `PlanEntry` (lines 244-248):**
```python
class PlanEntry(SchemaDict, total=False):
    content: Required[str]
    priority: Literal["high", "medium", "low"]
    status: Literal["pending", "in_progress", "completed"]
```

**protocol.py `Plan` (lines 285-288):**
```python
class Plan(SchemaDict, total=False):
    entries: Required[list[PlanEntry]]
    sessionUpdate: Required[Literal["plan"]]
```

**messages.py (lines 56-57):**
```python
@dataclass
class Plan(AgentMessage):
    entries: list[protocol.PlanEntry]
```

### Key Pattern
TOAD pattern-matches the `"plan"` session update, extracts the `entries` list (each entry has `content: str`, optional `priority: "high"|"medium"|"low"`, optional `status: "pending"|"in_progress"|"completed"`), and posts a `Plan` message to the UI. It is a simple dispatch -- no transformation, no storage.

### What Our Code Should Do
1. Add a `"plan"` case to `_handle_session_update`.
2. Extract `entries` from the update payload.
3. Emit a `plan_update` server event to connected WebSocket clients with the plan entries.
4. Use the `PlanEntry` data structure: `{content: str, priority?: "high"|"medium"|"low", status?: "pending"|"in_progress"|"completed"}`.

---

## Issue 5: tool_call_update for unknown toolCallId (ACP-004)

### TOAD Implementation (agent.py:263-288)

```python
case {
    "sessionUpdate": "tool_call_update",
    "toolCallId": tool_call_id,
}:
    if tool_call_id in self.tool_calls:
        current_tool_call = self.tool_calls[tool_call_id]
        for key, value in update.items():
            if value is not None:
                current_tool_call[key] = value

        self.post_message(
            messages.ToolCallUpdate(deepcopy(current_tool_call), update)
        )
    else:
        # The agent can send a tool call update, without previously sending the tool call *rolls eyes*
        current_tool_call: protocol.ToolCall = {
            "sessionUpdate": "tool_call",
            "toolCallId": tool_call_id,
            "title": "Tool call",
        }
        for key, value in update.items():
            if value is not None:
                current_tool_call[key] = value

        self.tool_calls[tool_call_id] = current_tool_call
        self.post_message(messages.ToolCall(current_tool_call))
```

### Key Pattern
When a `tool_call_update` arrives for an unknown `toolCallId`, TOAD creates a **synthetic `tool_call` entry** with:
- `sessionUpdate`: `"tool_call"` (not `"tool_call_update"`)
- `toolCallId`: the unknown ID
- `title`: `"Tool call"` (generic fallback)

Then it merges all non-None fields from the update into this synthetic entry, stores it in `self.tool_calls`, and posts it as a **new `ToolCall` message** (not `ToolCallUpdate`). This ensures the UI always has a valid tool_call record to reference.

### What Our Code Should Do
1. When a `tool_call_update` arrives for an unknown `toolCallId`, synthesize a tool_call record with the fields above.
2. Merge the update fields into the synthetic record.
3. Store it in the tool_calls dictionary.
4. Emit a `tool_call_start` event (not `tool_call_update`) to initialize the UI.

---

## Issue 6: fs/read_text_file line/limit parameters (ACP-005)

### TOAD Implementation (agent.py:348-370)

```python
@jsonrpc.expose("fs/read_text_file")
def rpc_read_text_file(
    self,
    sessionId: str,
    path: str,
    line: int | None = None,
    limit: int | None = None,
) -> dict[str, str]:
    """Read a file in the project."""
    # TODO: what if the read is outside of the project path?
    read_path = self.project_root_path / path
    try:
        text = read_path.read_text(encoding="utf-8", errors="ignore")
    except IOError:
        text = ""
    if line is not None:
        line = max(0, line - 1)
        if limit is None:
            text = "\n".join(text.splitlines()[line:])
        else:
            text = "\n".join(text.splitlines()[line : line + limit])
    return {"content": text}
```

### Key Pattern
1. Read the full file content first (UTF-8 with `errors="ignore"`).
2. If `line` is provided, convert from 1-based to 0-based: `line = max(0, line - 1)`.
3. If only `line` is given (no `limit`): slice from that line to end: `text.splitlines()[line:]`.
4. If both `line` and `limit` are given: slice a range: `text.splitlines()[line : line + limit]`.
5. Rejoin with `"\n".join(...)`.
6. Return `{"content": text}`.
7. On `IOError`, return empty string (not an error response).

### What Our Code Should Do
1. Accept optional `line: int | None` and `limit: int | None` parameters in `fs/read_text_file`.
2. Implement the same slicing logic: 1-based `line` converted to 0-based, optional `limit` for range.
3. Always read the full file first, then slice (simple and correct for reasonable file sizes).

---

## Issue 7: terminal/output exitStatus field (ACP-006)

### TOAD Implementation (agent.py:425-445)

```python
@jsonrpc.expose("terminal/output")
async def rpc_terminal_output(
    self, sessionId: str, terminalId: str, _meta: dict | None = None
) -> protocol.TerminalOutputResponse:
    from toad.widgets.terminal_tool import ToolState

    result_future: asyncio.Future[ToolState] = asyncio.Future()

    if not self.post_message(messages.GetTerminalState(terminalId, result_future)):
        raise RuntimeError("Unable to get terminal output")

    await result_future
    terminal_state = result_future.result()

    result: protocol.TerminalOutputResponse = {
        "output": terminal_state.output,
        "truncated": terminal_state.truncated,
    }
    if (return_code := terminal_state.return_code) is not None:
        result["exitStatus"] = {"exitCode": return_code}
    return result
```

**protocol.py `TerminalExitStatus` (lines 57-60):**
```python
class TerminalExitStatus(SchemaDict, total=False):
    _meta: dict
    exitCode: int | None
    signal: str | None
```

### Key Pattern
1. The base response always includes `output` and `truncated`.
2. `exitStatus` is **conditionally included** -- only when `return_code is not None` (process has exited).
3. The `exitStatus` object has the shape `{"exitCode": int | None, "signal": str | None}`.
4. If the process is still running, `exitStatus` is omitted entirely (not set to `None`).

### What Our Code Should Do
1. Track process return code per terminal.
2. In `terminal/output` response, conditionally include `exitStatus` only when the process has finished.
3. Use the `{"exitCode": return_code}` shape, optionally including `signal`.

---

## Issue 8: session/update handling completeness

### TOAD Implementation (agent.py:215-300)

All 8 session update types handled in TOAD's `rpc_session_update`:

| # | sessionUpdate type | Line range | Handler action |
|---|---|---|---|
| 1 | `user_message_chunk` | 234-239 | Post `UserMessage(type, text)` |
| 2 | `agent_message_chunk` | 241-245 | Post `Update(type, text)` |
| 3 | `agent_thought_chunk` | 247-251 | Post `Thinking(type, text)` |
| 4 | `tool_call` | 253-258 | Store in `tool_calls` dict, post `ToolCall(update)` |
| 5 | `plan` | 260-261 | Post `Plan(entries)` |
| 6 | `tool_call_update` | 263-288 | Merge into existing or create synthetic, post update |
| 7 | `available_commands_update` | 290-294 | Post `AvailableCommandsUpdate(available_commands)` |
| 8 | `current_mode_update` | 296-297 | Post `ModeUpdate(mode_id)` |

Additionally, lines 299-300 handle `_meta.field_meta.openhands.dev/metrics.status_line` as a cross-cutting concern (OpenHands-specific status reporting).

### Key Pattern
TOAD handles all 8 `SessionUpdate` variants defined in the protocol union type (protocol.py:311-320). The match uses structural pattern matching on `{"sessionUpdate": "<type>"}`.

### What Our Code Is Missing
Based on the audit, our `_handle_session_update` handles 5 of 8:
- **Missing: `plan`** -- Needs plan entry dispatch
- **Missing: `available_commands_update`** -- Needs slash command list relay
- **Missing: `current_mode_update`** -- Needs mode change notification

---

## Issue 9: asyncio.Queue backpressure in TOAD

### TOAD Implementation

**TOAD does not use `asyncio.Queue` in its ACP agent.** Searched all files in `toad/acp/` -- zero matches for `asyncio.Queue` or `Queue(`.

Instead, TOAD uses a **message-passing architecture** built on Textual's `Message` system:
- `self.post_message(message)` (agent.py, used throughout) posts Textual `Message` objects to a `MessagePump`.
- `asyncio.Future` is used for request-response patterns (permission, terminal create, terminal output, terminal wait).
- The Textual message pump handles backpressure internally via its own event loop.

For the terminal output buffering, TOAD uses a **bounded `deque`** in `terminal_tool.py`:
```python
self._output: deque[bytes] = deque()
# ...
while self._output_bytes_count > self._output_byte_limit and self._output:
    oldest_bytes = self._output[0]
    # ... evict oldest
    self._output.popleft()
    self._output_bytes_count -= oldest_bytes_count
```

### Key Pattern
TOAD avoids unbounded queue growth by:
1. Using `asyncio.Future` for single-response patterns (no queue needed).
2. Using Textual's message pump (bounded by the UI event loop) for streaming updates.
3. Using byte-limited `deque` for terminal output buffering with explicit eviction.

### What Our Code Should Do
1. For our `asyncio.Queue`-based architecture, use **bounded queues** (`asyncio.Queue(maxsize=N)`) for all inter-task communication.
2. Use `put_nowait()` with a try/except `asyncio.QueueFull` for non-blocking producers, with a drop-oldest or backpressure strategy.
3. For terminal output, adopt the byte-limited deque pattern with eviction.
