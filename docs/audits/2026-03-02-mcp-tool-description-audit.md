# MCP Tool Description Audit — 2026-03-02

**Scope**: `lib/protocols/mcp/server.py` — all `@mcp.tool()` functions and the
FastMCP `instructions` string.

**Audited by**: codebase-researcher (langgraph-hardening team)

**Source read**: direct file read of `server.py` at commit-time (2026-03-02).

**Reference**: `docs/research/2026-03-02-mcp-tool-description-best-practices-research.md`
(docs-researcher deliverable — not yet landed at time of writing; this audit will
be updated once that document is merged).

---

## Executive Summary

The server exposes **7 tools** as of this audit:

| Tool                      | Status  |
| ------------------------- | ------- |
| `start_thread`            | Present |
| `list_threads`            | Present |
| `respond_to_permission`   | Present |
| `get_thread_status`       | Present |
| `send_message`            | Present |
| `get_team_status`         | Present |
| `get_pending_permissions` | Present |

The surface is now close to full REST parity. The primary category of remaining
issues is **description quality** — several tool and parameter docstrings contain
internal jargon, stale content, or insufficient guidance for an LLM caller. No
missing tools remain in the HIGH priority category. The FastMCP `instructions`
string is the most impactful single defect.

---

## Finding Index

| ID     | Severity | Tool / Location                       | Summary                                                                                      |
| ------ | -------- | ------------------------------------- | -------------------------------------------------------------------------------------------- |
| MCD-01 | HIGH     | `FastMCP instructions`                | `respond_to_permission` and `get_team_status` omitted from server instructions               |
| MCD-02 | HIGH     | `FastMCP instructions`                | No workflow sequence guidance; LLM cannot infer tool call order                              |
| MCD-03 | MEDIUM   | `start_thread` → `team_preset`        | Description references `_KNOWN_PRESETS` (internal Python symbol)                             |
| MCD-04 | MEDIUM   | `start_thread` → `workspace_root`     | Description cites "ADR-014" (internal jargon opaque to LLM callers)                          |
| MCD-05 | MEDIUM   | `get_thread_status`                   | Docstring claims "checkpoint ID" in return but MCP-04 removed it                             |
| MCD-06 | MEDIUM   | `respond_to_permission` → `option_id` | No guidance on how to discover valid option IDs                                              |
| MCD-07 | MEDIUM   | `respond_to_permission`               | Internal ADR reference in description body ("ADR-011 §2.2")                                  |
| MCD-08 | LOW      | `send_message`                        | Title parenthetical "(async, returns 202)" exposes HTTP implementation detail                |
| MCD-09 | LOW      | `send_message`                        | No size constraint mentioned; `initial_message` cap (32k) is documented but `message` is not |
| MCD-10 | LOW      | `get_thread_status`                   | Possible status values not enumerated in description                                         |
| MCD-11 | LOW      | `get_team_status`                     | Internal ADR reference ("ADR-011 §2.2") in description                                       |
| MCD-12 | LOW      | `list_threads`                        | No enumeration of what thread status values look like                                        |
| MCD-13 | INFO     | `get_pending_permissions`             | Hits `/api/team/status` — subset of `get_team_status`; overlap not documented                |

---

## Detailed Findings

### MCD-01 — HIGH: FastMCP `instructions` omits two tools

**Location**: `server.py:79-85`

**Current text**:

```python
"Vaultspec A2A Orchestrator MCP tools. "
"Use 'start_thread' to launch a multi-agent coding workflow, "
"'list_threads' to discover existing threads, "
"'get_thread_status' to check a specific thread, and "
"'send_message' to send follow-up input into a running thread."
```

**Problem**: `respond_to_permission` and `get_team_status` are not mentioned.
`respond_to_permission` is the **only** way to unblock a supervised thread;
without it appearing in the instructions, an LLM agent will not know the tool
exists until it scans individual tool descriptions. The FastMCP `instructions`
field is the primary discovery surface — it is injected into the system prompt
before the tool list. Omitting critical tools here degrades routing accuracy.

`get_pending_permissions` is also absent, though its overlap with
`get_team_status` reduces the severity of that omission.

**Recommendation**: Rewrite the instructions string to name all primary tools
and describe the autonomous vs supervised mode distinction.

---

### MCD-02 — HIGH: No workflow sequence guidance in `instructions`

**Location**: `server.py:79-85`

**Problem**: The instructions string presents tools as a flat list without
describing the typical invocation sequence. An LLM agent starting a supervised
coding workflow must:

1. Call `start_thread` with `autonomous=False`
2. Monitor via `get_thread_status` or `get_team_status`
3. When status is `input_required`, call `get_pending_permissions` to discover
   request IDs
4. Call `respond_to_permission` with the correct `permission_request_id` and
   `option_id`

Without this sequence documented in the instructions (or in tool descriptions
that cross-reference each other), an LLM is likely to poll `get_thread_status`
and never discover the permission-unblocking step.

**Recommendation**: Add a one-paragraph workflow description to `instructions`
covering both the autonomous path and the supervised path.

---

### MCD-03 — MEDIUM: `start_thread.team_preset` references `_KNOWN_PRESETS`

**Location**: `server.py:122-124`

**Current text**:

```
team_preset: Team configuration preset to use. Available presets:
             see ``_KNOWN_PRESETS`` (auto-discovered from TOML files).
             Defaults to ``vaultspec-adaptive-coder``.
```

**Problem**: `_KNOWN_PRESETS` is a Python module-level variable. An LLM caller
reading the tool description cannot dereference this symbol. The actual preset
names (e.g. `vaultspec-adaptive-coder`, `vaultspec-structured-coder`,
`vaultspec-iterative-coder`, `vaultspec-solo-coder`) are known at import time
and should be listed verbatim. The runtime validation at line 142-146 produces
the correct list on error, but an LLM should not need to trigger an error to
discover valid values.

**Recommendation**: Replace the `_KNOWN_PRESETS` reference with the hardcoded
fallback preset names (since those are stable) and note that additional presets
may be available via `list_threads` or `get_team_status`.

---

### MCD-04 — MEDIUM: `start_thread.workspace_root` cites "ADR-014"

**Location**: `server.py:128-130`

**Current text**:

```
workspace_root: Optional absolute path to the workspace directory.
                Enables ADR-014 context injection (.vault/ auto-discovery)
                and scopes ACP agent CWD to this directory.
```

**Problem**: "ADR-014" and "ACP agent CWD" are internal architecture
terminology opaque to any LLM caller outside the development team. An IDE agent
(Cursor, Windsurf, Claude Code) cannot interpret these references. The
functional behaviour — scanning `.vault/` for context files and setting the
agent's working directory — should be described in plain terms.

**Recommendation**:

```
workspace_root: Optional absolute path to the project root. When provided,
                the agent team uses this directory as their working directory
                and automatically discovers context files from a .vault/
                subdirectory (markdown, TOML) to inject as background knowledge.
                Example: "/home/user/myproject"
```

---

### MCD-05 — MEDIUM: `get_thread_status` docstring claims checkpoint ID is returned

**Location**: `server.py:321-328`

**Current text**:

```
Returns a human-readable summary of the thread's current state including
message count and checkpoint ID.  For real-time streaming updates, connect
to the WebSocket endpoint listed in the response.
```

**Problem**: The comment at line 341 explicitly removes checkpoint_id from the
output (`# MCP-04: omit checkpoint_id`). The actual return at lines 343-347
includes `thread_id`, `status`, `msg_count`, and `ws_live_url` — no
`checkpoint_id`. The description is stale and will mislead LLM callers that
attempt to extract checkpoint ID from the return value.

**Recommendation**: Remove "checkpoint ID" from the description. List the four
actual fields returned: thread ID, status, message count, live WebSocket URL.

---

### MCD-06 — MEDIUM: `respond_to_permission.option_id` provides no discovery guidance

**Location**: `server.py:274-277`

**Current text**:

```
option_id: The ID of the chosen permission option.
```

**Problem**: An LLM caller does not know where to find valid option IDs. The
correct flow is: receive a `PermissionRequestEvent` over the WebSocket (or via
`get_pending_permissions`) → extract `options[].id` → pass one as `option_id`.
Without this guidance, a caller is likely to guess or use the wrong value.

**Recommendation**:

```
option_id: The ID of the chosen option from the PermissionRequestEvent.
           Call ``get_pending_permissions`` to list pending requests and their
           available option IDs. Example option IDs: "approve", "approve_all",
           "reject".
```

---

### MCD-07 — MEDIUM: `respond_to_permission` description body cites "ADR-011 §2.2"

**Location**: `server.py:267-272`

**Current text**:

```
...Use this tool to submit the chosen option and unblock the
graph (ADR-011 §2.2).
```

**Problem**: "ADR-011 §2.2" is an internal architecture document reference
meaningless to an LLM calling the tool. This appears in the _body_ of the
description (not just a parameter comment), so it will be included in the LLM's
context.

**Recommendation**: Remove the ADR reference. The sentence functions correctly
without it: "Use this tool to submit the chosen option and unblock the stalled
thread."

---

### MCD-08 — LOW: `send_message` title exposes HTTP implementation detail

**Location**: `server.py:372`

**Current text**:

```
Send a follow-up message into an existing thread (async, returns 202).
```

**Problem**: "(async, returns 202)" is an HTTP status code detail. MCP tool
callers receive a string return value — they do not see HTTP status codes. This
parenthetical is noise and may confuse callers that look for "202" in the return
string.

**Recommendation**: Remove the parenthetical. The body already explains it is
asynchronous ("Returns immediately — the graph processes the message
asynchronously").

---

### MCD-09 — LOW: `send_message.message` has no documented size constraint

**Location**: `server.py:380-381`

**Problem**: `start_thread.initial_message` has a documented 32,000-character
cap (MCP-01 guard at line 136), but `send_message.message` has no such guard
and no documented limit. The REST endpoint may have its own body size limit.
Without documentation, an LLM may send oversized payloads.

**Recommendation**: Add `message` parameter note: "Maximum ~32,000 characters.
Long inputs should be split across multiple messages."

---

### MCD-10 — LOW: `get_thread_status` does not enumerate possible status values

**Location**: `server.py:317-328`

**Problem**: The `status` field returned by the tool can take values such as
`submitted`, `running`, `completed`, `failed`, `input_required`, `cancelled`.
Without this enumeration, an LLM caller cannot branch on status correctly (e.g.
it will not know that `input_required` means `respond_to_permission` is needed).

**Recommendation**: Add to the return description: "Possible status values:
`submitted`, `running`, `input_required` (waiting for permission response),
`completed`, `failed`, `cancelled`."

---

### MCD-11 — LOW: `get_team_status` description cites "ADR-011 §2.2"

**Location**: `server.py:423-427`

**Current text**:

```
...and any outstanding permission requests that need responses (ADR-011 §2.2).
```

Same issue as MCD-07. Internal reference should be replaced with plain
description: "and any permission requests that are blocking thread execution."

---

### MCD-12 — LOW: `list_threads` does not enumerate status values

**Location**: `server.py:199-212`

**Problem**: The listing output includes `status` per thread but the description
does not tell callers what status values to expect. Same gap as MCD-10 but for
the list view.

**Recommendation**: Add a note: "Thread status will be one of: `submitted`,
`running`, `input_required`, `completed`, `failed`, `cancelled`."

---

### MCD-13 — INFO: `get_pending_permissions` overlaps with `get_team_status`

**Location**: `server.py:476-522`

**Problem**: `get_pending_permissions` calls `GET /api/team/status` (line 490)
and extracts `pending_permissions` — a strict subset of what `get_team_status`
returns. LLM callers may be confused about when to use one vs the other.

**Current state**: `get_pending_permissions` has a cleaner, focused description
that is appropriate for the supervised-thread unblocking workflow. The overlap
is acceptable but should be acknowledged in both descriptions.

**Recommendation**: Add a cross-reference in `get_team_status`: "For a focused
view of only permission requests, use `get_pending_permissions`."

---

## Summary Table — Recommended Fixes by Priority

| Priority             | Finding(s)                             | Description                                                                             |
| -------------------- | -------------------------------------- | --------------------------------------------------------------------------------------- |
| P0 (Fix immediately) | MCD-01, MCD-02                         | Rewrite `instructions` string to include all tools and both workflow paths              |
| P1 (Fix this sprint) | MCD-03, MCD-04, MCD-05, MCD-06, MCD-07 | Remove internal jargon, fix stale checkpoint_id claim, add option_id discovery guidance |
| P2 (Fix next sprint) | MCD-08, MCD-09, MCD-10, MCD-11, MCD-12 | Low-friction polish: remove HTTP parenthetical, add size hint, enumerate status values  |
| Informational        | MCD-13                                 | Document tool overlap; no code change required                                          |

---

## Proposed `instructions` Rewrite

```python
mcp = FastMCP(
    name="vaultspec-orchestrator",
    instructions=(
        "Vaultspec A2A Orchestrator — tools for launching and managing multi-agent "
        "coding workflows.\n\n"
        "Autonomous workflow (no human approval needed):\n"
        "  1. start_thread(initial_message, autonomous=True) → get thread_id\n"
        "  2. get_thread_status(thread_id) → poll until status is 'completed' or 'failed'\n"
        "  3. send_message(thread_id, ...) → inject follow-up input\n\n"
        "Supervised workflow (human approves tool calls):\n"
        "  1. start_thread(initial_message, autonomous=False) → get thread_id\n"
        "  2. get_thread_status(thread_id) → poll; when status is 'input_required':\n"
        "  3. get_pending_permissions() → list request IDs and option IDs\n"
        "  4. respond_to_permission(permission_request_id, option_id) → unblock thread\n\n"
        "Discovery: list_threads() to find existing threads. "
        "get_team_status() for overall agent health and active thread count."
    ),
)
```

---

_Audit completed: 2026-03-02. Next review recommended after docs-researcher
best-practices document lands and after MCD-01/02 P0 fixes are applied._
