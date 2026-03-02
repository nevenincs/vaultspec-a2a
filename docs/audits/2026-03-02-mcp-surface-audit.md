# MCP Surface Audit — Running Record

**Scope:** `lib/protocols/mcp/` and MCP-adjacent findings from other modules
**Auditor:** codebase-researcher
**Started:** 2026-03-02
**Mandate:** Append findings at end of every cycle touching MCP code. This doc
is the authoritative MCP audit record.

---

## Open Issues — Summary Table

| ID | Severity | Finding | File:Line | Status |
|----|----------|---------|-----------|--------|
| MCP-01 | MEDIUM | No input size cap on `initial_message` in `start_thread` | server.py:128 | open |
| MCP-02 | MEDIUM | Preset glob at import; missing directory logs WARNING not ERROR | server.py:53-66 | open |
| MCP-03 | MEDIUM | `send_message` only handles 404 specially; 409/422 expose raw API errors | server.py:256 | open |
| MCP-04 | LOW | Checkpoint ID exposed in `get_thread_status` output | server.py:196 | open |
| MCP-05 | LOW | `get_thread_status` and `send_message` create a new `AsyncClient` per call | server.py:183,237 | open |
| MCP-06 | LOW | `_ws_url_from_api_base` returns bare hostname when URL has no port | server.py:89-92 | open |
| MCP-07 | INFO | `start_thread` hardcodes preset list in docstring — drifts from `_KNOWN_PRESETS` | server.py:110-112 | open |

---

## Cycle 1 — Initial MCP surface review (team_config/graph/mcp batch)

**Date:** 2026-03-02
**Files read:** `lib/protocols/mcp/server.py`

### Findings

| ID | Severity | Description | File:Line |
|----|----------|-------------|-----------|
| MCP-01 | MEDIUM | `start_thread` sends full `initial_message` with no size cap. Title is truncated to 80 chars but the message body is unbounded. Large pastes (entire file contents) inflate the POST body with no client-side guard. No content-length limit on `/api/threads`. | server.py:128 |
| MCP-02 | MEDIUM | `_PRESET_TEAMS_DIR.glob("*.toml")` executes at module import time. If the preset directory is absent (misconfigured wheel install), `glob()` yields nothing silently and the fallback fires with a WARNING. The WARNING is misleading — it also fires on a legitimately empty (but present) directory. A missing directory should log ERROR. | server.py:53-66 |
| MCP-03 | MEDIUM | `send_message` handles 404 with a friendly message but 409 (ingest already active), 422 (Pydantic validation failure), and 400 surface raw `exc.response.text[:200]` which may include internal stack traces inappropriate for IDE display. Same issue in `get_thread_status`. | server.py:256 |
| MCP-04 | LOW | `get_thread_status` includes raw `checkpoint_id` in its return string. Checkpoint IDs are internal LangGraph UUIDs with no meaning to IDE users. Omit or replace with a human-readable `last_updated` field if available. | server.py:191,196 |

---

## Cycle 2 — Deep read, additional findings

**Date:** 2026-03-02
**Files read:** `lib/protocols/mcp/server.py` (full re-read)

### Findings

| ID | Severity | Description | File:Line |
|----|----------|-------------|-----------|
| MCP-05 | LOW | `get_thread_status` and `send_message` each construct a new `httpx.AsyncClient` per call via `async with httpx.AsyncClient(...) as client`. Client creation incurs TCP connection setup on every MCP tool invocation. A module-level or lifespan-scoped shared client would be more efficient. Note: `start_thread` has the same pattern (`server.py:124`). All three tools could share a single client. | server.py:124,183,237 |
| MCP-06 | LOW | `_ws_url_from_api_base` at line 89 uses `parsed.hostname` which strips the port, then re-adds it only `if parsed.port`. For a URL like `http://localhost` (no explicit port), `parsed.port` is `None` so the output is `ws://localhost/ws` — correct. But for `http://localhost:80` or `https://localhost:443` the standard port is omitted by `urlparse` (it normalises away default ports), so `parsed.port` is `None` for default-port URLs. This is actually correct behaviour, but the code comment at line 90 ("Strip credentials") is misleading — `parsed.hostname` also strips the port, not just credentials. Minor documentation gap only. | server.py:89-92 |
| MCP-07 | INFO | `start_thread` docstring at lines 110-112 hardcodes the preset list: `"coding-star"`, `"coding-pipeline"`, `"coding-loop"`, `"solo-coder"`. This list is the same as `_HARDCODED_PRESETS` (line 51) and will drift from `_KNOWN_PRESETS` (which is discovery-based) if new presets are added to `lib/core/presets/teams/`. The tool description shown to IDE users will be stale. | server.py:110-112 |

---
