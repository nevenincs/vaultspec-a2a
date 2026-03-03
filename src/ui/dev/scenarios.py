"""Fixture scenario data for visual testing of the React 5 frontend.

All data is in wire-protocol format — matching the TypeScript types in
src/ui/src/lib/api/types.ts exactly. Field names, enum values, and JSON
shapes are authoritative.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4


# ── Sequence counters (auto-incrementing per thread) ─────────────────────────

_seq_counters: dict[str, int] = {}


def _seq(thread_id: str) -> int:
    _seq_counters.setdefault(thread_id, 0)
    _seq_counters[thread_id] += 1
    return _seq_counters[thread_id]


def _ts(minutes_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


def _envelope(
    event_type: str,
    thread_id: str,
    agent_id: str | None = None,
    minutes_ago: float = 0,
    **extra: object,
) -> dict:
    return {
        "type": event_type,
        "thread_id": thread_id,
        "agent_id": agent_id,
        "timestamp": _ts(minutes_ago),
        "sequence": _seq(thread_id),
        "metadata": None,
        **extra,
    }


# ── Thread summaries (GET /threads) ─────────────────────────────────────────

THREAD_SUMMARIES: list[dict] = [
    {
        "thread_id": "thread-001",
        "title": "Debug auth session bug",
        "status": "running",
        "agent_state": "working",
        "created_at": _ts(30),
        "updated_at": _ts(3),
        "nickname": "auth-fix-star-a3f2",
        "feature_tag": "auth-flow",
        "source_branch": "fix/auth-session",
        "callee": "claude-cli",
    },
    {
        "thread_id": "thread-002",
        "title": "Refactor database models",
        "status": "running",
        "agent_state": "idle",
        "created_at": _ts(60),
        "updated_at": _ts(12),
        "nickname": "db-refactor-star-b7c1",
        "feature_tag": "sqlmodel-migration",
        "source_branch": "feat/sqlmodel",
        "callee": "api",
    },
    {
        "thread_id": "thread-003",
        "title": "Add API rate limiting",
        "status": "completed",
        "agent_state": "completed",
        "created_at": _ts(120),
        "updated_at": _ts(45),
        "nickname": "rate-limit-pipe-c4d9",
        "feature_tag": "rate-limiting",
        "source_branch": "feat/rate-limit",
        "callee": "gemini-cli",
    },
    {
        "thread_id": "thread-004",
        "title": "Update CI/CD pipeline",
        "status": "failed",
        "agent_state": "failed",
        "created_at": _ts(180),
        "updated_at": _ts(120),
        "nickname": "cicd-update-star-e8f0",
        "feature_tag": "github-actions",
        "source_branch": "chore/cicd",
        "callee": "mcp-bridge",
    },
]

# ── Team status (GET /team/status) ──────────────────────────────────────────

TEAM_STATUS: dict = {
    "agents": [
        {
            "agent_id": "planner-1",
            "node_name": "Planner",
            "state": "working",
            "provider": "claude",
            "model": "high",
        },
        {
            "agent_id": "coder-1",
            "node_name": "Coder",
            "state": "idle",
            "provider": "claude",
            "model": "high",
        },
        {
            "agent_id": "reviewer-1",
            "node_name": "Reviewer",
            "state": "idle",
            "provider": "gemini",
            "model": "mid",
        },
    ],
    "active_threads": ["thread-001"],
    "pending_permissions": [],
}


# ── Thread-001 events (rich scenario) ────────────────────────────────────────

_T1 = "thread-001"

_SESSION_PY = """\
import jwt
from datetime import datetime, timedelta
from fastapi import Request, Response

SESSION_EXPIRY = timedelta(seconds=0)  # BUG: expiry set to 0 seconds

def create_session(user_id: str, response: Response):
    token = jwt.encode(
        {"user_id": user_id, "exp": datetime.utcnow() + SESSION_EXPIRY},
        SECRET_KEY,
        algorithm="HS256"
    )
    response.set_cookie("session", token, httponly=True)
    return token

def validate_session(request: Request):
    token = request.cookies.get("session")
    if not token:
        raise AuthError("No session cookie")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["user_id"]
    except jwt.ExpiredSignatureError:
        raise AuthError("Session expired")\
"""

_SETTINGS_TOML = """\
[auth]
secret_key = "dev-secret-key-change-in-production"
session_duration_hours = 24
cookie_secure = false
cookie_samesite = "lax"\
"""

_SESSION_PY_FIXED = """\
import jwt
import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import Request, Response

_config = tomllib.loads(Path("config/settings.toml").read_text())
SESSION_EXPIRY = timedelta(hours=_config["auth"]["session_duration_hours"])

def create_session(user_id: str, response: Response):
    token = jwt.encode(
        {"user_id": user_id, "exp": datetime.utcnow() + SESSION_EXPIRY},
        SECRET_KEY,
        algorithm="HS256"
    )
    response.set_cookie("session", token, httponly=True)
    return token

def validate_session(request: Request):
    token = request.cookies.get("session")
    if not token:
        raise AuthError("No session cookie")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["user_id"]
    except jwt.ExpiredSignatureError:
        raise AuthError("Session expired")\
"""

_PERM_REQ_ID = f"{_T1}:{uuid4().hex}"

THREAD_001_EVENTS: list[dict] = [
    # Agent starts working
    _envelope(
        "agent_status",
        _T1,
        "planner-1",
        8.0,
        state="working",
        node_name="Planner",
        detail="Processing request",
    ),
    # Planner thinks
    _envelope(
        "thought_chunk",
        _T1,
        "planner-1",
        7.8,
        content="Need to check the session handling in middleware to understand "
        "the auth flow. The issue is likely in session cookie configuration "
        "or token expiry settings. Let me create a plan and delegate to the Coder.",
        message_id="thought-001",
    ),
    # Plan update
    _envelope(
        "plan_update",
        _T1,
        "planner-1",
        7.5,
        entries=[
            {
                "content": "Analyze auth module",
                "status": "completed",
                "priority": "high",
            },
            {
                "content": "Read session config",
                "status": "completed",
                "priority": "medium",
            },
            {
                "content": "Fix token validation",
                "status": "in_progress",
                "priority": "high",
            },
            {"content": "Update unit tests", "status": "pending", "priority": "low"},
            {"content": "Run test suite", "status": "pending", "priority": "medium"},
        ],
    ),
    # Planner message
    _envelope(
        "message_chunk",
        _T1,
        "planner-1",
        7.0,
        content="I've created an execution plan to debug the auth session issue. "
        "I'll start by analyzing the auth module and session configuration. "
        "Let me read the relevant files first.",
        message_id="msg-001",
        finish_reason="stop",
    ),
    # Coder starts
    _envelope(
        "agent_status",
        _T1,
        "coder-1",
        6.9,
        state="working",
        node_name="Coder",
        detail="Reading source files",
    ),
    # Tool call: read session.py
    _envelope(
        "tool_call_start",
        _T1,
        "coder-1",
        6.5,
        tool_call_id="tc-001",
        title="Reading src/auth/session.py",
        kind="read",
        status="in_progress",
        locations=[{"path": "src/auth/session.py", "line": 1}],
        content=[],
    ),
    _envelope(
        "tool_call_update",
        _T1,
        "coder-1",
        6.4,
        tool_call_id="tc-001",
        title=None,
        kind=None,
        status="completed",
        locations=None,
        content=[{"content_type": "text", "text": _SESSION_PY}],
    ),
    # Coder thinks
    _envelope(
        "thought_chunk",
        _T1,
        "coder-1",
        6.0,
        content="Found it! `SESSION_EXPIRY = timedelta(seconds=0)` \u2014 the session "
        "expires immediately upon creation. This was likely introduced during "
        "testing and never reverted. The fix is to set a proper expiry duration "
        "like 24 hours.",
        message_id="thought-002",
    ),
    # Tool call: read config
    _envelope(
        "tool_call_start",
        _T1,
        "coder-1",
        5.5,
        tool_call_id="tc-002",
        title="Reading config/settings.toml",
        kind="read",
        status="in_progress",
        locations=[{"path": "config/settings.toml", "line": 12}],
        content=[],
    ),
    _envelope(
        "tool_call_update",
        _T1,
        "coder-1",
        5.4,
        tool_call_id="tc-002",
        title=None,
        kind=None,
        status="completed",
        locations=None,
        content=[{"content_type": "text", "text": _SETTINGS_TOML}],
    ),
    # Coder message
    _envelope(
        "message_chunk",
        _T1,
        "coder-1",
        5.0,
        content="Found the bug. In `src/auth/session.py`, `SESSION_EXPIRY` is set to "
        "`timedelta(seconds=0)`, meaning sessions expire immediately. The config "
        "file at `config/settings.toml` has `session_duration_hours = 24`, but "
        "this value is **never read** by the session module. I'll fix this now.",
        message_id="msg-002",
        finish_reason="stop",
    ),
    # Tool call: edit with diff
    _envelope(
        "tool_call_start",
        _T1,
        "coder-1",
        4.5,
        tool_call_id="tc-003",
        title="Editing src/auth/session.py",
        kind="edit",
        status="in_progress",
        locations=[{"path": "src/auth/session.py", "line": 5}],
        content=[],
    ),
    _envelope(
        "tool_call_update",
        _T1,
        "coder-1",
        4.4,
        tool_call_id="tc-003",
        title=None,
        kind=None,
        status="completed",
        locations=None,
        content=[
            {
                "content_type": "diff",
                "path": "src/auth/session.py",
                "old_text": "SESSION_EXPIRY = timedelta(seconds=0)  # BUG: expiry set to 0 seconds",
                "new_text": (
                    "import tomllib\n"
                    "from pathlib import Path\n"
                    "\n"
                    '_config = tomllib.loads(Path("config/settings.toml").read_text())\n'
                    'SESSION_EXPIRY = timedelta(hours=_config["auth"]["session_duration_hours"])'
                ),
            }
        ],
    ),
    # Artifact: full updated file
    _envelope(
        "artifact_update",
        _T1,
        "coder-1",
        4.0,
        artifact_id="art-001",
        filename="src/auth/session.py",
        content=_SESSION_PY_FIXED,
        append=False,
        last_chunk=True,
    ),
    # Tool call: execute shell (in_progress — tests running)
    _envelope(
        "tool_call_start",
        _T1,
        "coder-1",
        3.5,
        tool_call_id="tc-004",
        title="Running pytest tests/auth/ -v",
        kind="execute",
        status="in_progress",
        locations=[],
        content=[{"content_type": "terminal", "terminal_id": "term-001"}],
    ),
    # Coder summary message (markdown)
    _envelope(
        "message_chunk",
        _T1,
        "coder-1",
        3.0,
        content=(
            "I've fixed the session expiry bug and am running the auth test suite. "
            "Here's a summary:\n\n"
            "## Root Cause\n"
            "`SESSION_EXPIRY = timedelta(seconds=0)` \u2014 sessions expired "
            "**immediately** upon creation.\n\n"
            "## Fix Applied\n"
            "The module now reads `session_duration_hours` from `config/settings.toml`:\n\n"
            "```python\n"
            "import tomllib\n"
            "from pathlib import Path\n\n"
            '_config = tomllib.loads(Path("config/settings.toml").read_text())\n'
            'SESSION_EXPIRY = timedelta(hours=_config["auth"]["session_duration_hours"])\n'
            "```\n\n"
            "## What changed\n"
            "- **Before:** hardcoded `timedelta(seconds=0)`\n"
            "- **After:** reads from config \u2192 `timedelta(hours=24)`\n"
            "- Config key: `[auth] session_duration_hours = 24`\n\n"
            "> The fix also makes session duration configurable per environment \u2014 "
            "no more hardcoded values.\n\n"
            "Running `pytest tests/auth/ -v` now\u2026"
        ),
        message_id="msg-003",
        finish_reason="stop",
    ),
    # Permission request: allow shell execution
    _envelope(
        "permission_request",
        _T1,
        "coder-1",
        2.5,
        request_id=_PERM_REQ_ID,
        description="Run npm install in the project root to install new dependencies "
        "required for the rate limiter.",
        options=[
            {"option_id": "opt-allow", "name": "Allow", "kind": "allow_once"},
            {"option_id": "opt-always", "name": "Always Allow", "kind": "allow_always"},
            {"option_id": "opt-deny", "name": "Deny", "kind": "reject_once"},
        ],
        tool_call="execute_shell",
    ),
    # Agent goes to input_required (waiting for permission)
    _envelope(
        "agent_status",
        _T1,
        "coder-1",
        2.5,
        state="input_required",
        node_name="Coder",
        detail="Waiting for permission to execute shell command",
    ),
]


# ── Thread-002 events (idle, search tool) ────────────────────────────────────

_T2 = "thread-002"

THREAD_002_EVENTS: list[dict] = [
    _envelope(
        "agent_status",
        _T2,
        "planner-1",
        14.0,
        state="working",
        node_name="Planner",
        detail="Analyzing request",
    ),
    _envelope(
        "message_chunk",
        _T2,
        "planner-1",
        13.5,
        content="I'll analyze the existing model structure and create a migration plan. "
        "SQLModel combines Pydantic and SQLAlchemy, so we'll get type safety and "
        "validation automatically. Let me map out the dependencies first.",
        message_id="msg-201",
        finish_reason="stop",
    ),
    _envelope(
        "agent_status",
        _T2,
        "coder-1",
        13.0,
        state="working",
        node_name="Coder",
        detail="Searching files",
    ),
    _envelope(
        "tool_call_start",
        _T2,
        "coder-1",
        12.5,
        tool_call_id="tc-201",
        title="Searching for model definitions",
        kind="search",
        status="in_progress",
        locations=[],
        content=[],
    ),
    _envelope(
        "tool_call_update",
        _T2,
        "coder-1",
        12.3,
        tool_call_id="tc-201",
        title=None,
        kind=None,
        status="completed",
        locations=None,
        content=[
            {
                "content_type": "text",
                "text": "Found 4 model files:\n"
                "  src/models/user.py\n"
                "  src/models/project.py\n"
                "  src/models/team.py\n"
                "  src/models/audit_log.py",
            }
        ],
    ),
    _envelope(
        "agent_status",
        _T2,
        "planner-1",
        12.0,
        state="idle",
        node_name="Planner",
        detail=None,
    ),
    _envelope(
        "agent_status",
        _T2,
        "coder-1",
        12.0,
        state="idle",
        node_name="Coder",
        detail=None,
    ),
]


# ── Thread-003 events (completed) ───────────────────────────────────────────

_T3 = "thread-003"

THREAD_003_EVENTS: list[dict] = [
    _envelope(
        "agent_status",
        _T3,
        "planner-1",
        50.0,
        state="working",
        node_name="Planner",
        detail="Implementing rate limiter",
    ),
    _envelope(
        "message_chunk",
        _T3,
        "planner-1",
        48.0,
        content="Rate limiting is now fully implemented using a sliding window algorithm "
        "with Redis as the backend store. All API endpoints are covered with "
        "configurable limits per endpoint group (auth: 10/min, api: 60/min, "
        "uploads: 5/min).",
        message_id="msg-301",
        finish_reason="stop",
    ),
    _envelope(
        "agent_status",
        _T3,
        "planner-1",
        47.0,
        state="completed",
        node_name="Planner",
        detail="Task complete",
    ),
]


# ── Thread-004 events (failed with error) ────────────────────────────────────

_T4 = "thread-004"

THREAD_004_EVENTS: list[dict] = [
    _envelope(
        "agent_status",
        _T4,
        "planner-1",
        125.0,
        state="working",
        node_name="Planner",
        detail="Migrating CI/CD config",
    ),
    _envelope(
        "error",
        _T4,
        "planner-1",
        120.0,
        code="AGENT_TIMEOUT",
        message='Connection to agent "Planner" lost. The agent process exited unexpectedly.',
        recoverable=False,
    ),
    _envelope(
        "agent_status",
        _T4,
        "planner-1",
        120.0,
        state="failed",
        node_name="Planner",
        detail="Agent process exited unexpectedly",
    ),
]


# ── Events by thread ────────────────────────────────────────────────────────

THREAD_EVENTS: dict[str, list[dict]] = {
    "thread-001": THREAD_001_EVENTS,
    "thread-002": THREAD_002_EVENTS,
    "thread-003": THREAD_003_EVENTS,
    "thread-004": THREAD_004_EVENTS,
}


# ── Thread state snapshots (GET /threads/{id}/state) ─────────────────────────


def _build_snapshot(thread_id: str) -> dict:
    """Build a ThreadStateSnapshot from a thread's event list."""
    events = THREAD_EVENTS.get(thread_id, [])
    summary = next((t for t in THREAD_SUMMARIES if t["thread_id"] == thread_id), None)

    messages: list[dict] = []
    tool_calls: list[dict] = []
    artifacts: list[dict] = []
    plan: list[dict] = []
    agents: list[dict] = []
    pending_permissions: list[dict] = []
    last_seq = 0

    seen_agents: set[str] = set()

    for ev in events:
        last_seq = max(last_seq, ev.get("sequence", 0))
        t = ev["type"]

        if t == "message_chunk":
            messages.append(
                {
                    "message_id": ev["message_id"],
                    "role": "assistant",
                    "content": ev["content"],
                    "agent_id": ev["agent_id"],
                    "timestamp": ev["timestamp"],
                }
            )

        elif t == "tool_call_start":
            tool_calls.append(
                {
                    "tool_call_id": ev["tool_call_id"],
                    "title": ev["title"],
                    "kind": ev["kind"],
                    "status": ev["status"],
                    "locations": ev["locations"],
                    "content": ev["content"],
                }
            )

        elif t == "tool_call_update":
            # Merge update into existing tool call
            for tc in tool_calls:
                if tc["tool_call_id"] == ev["tool_call_id"]:
                    if ev.get("status") is not None:
                        tc["status"] = ev["status"]
                    if ev.get("content") is not None:
                        tc["content"] = ev["content"]
                    if ev.get("locations") is not None:
                        tc["locations"] = ev["locations"]
                    break

        elif t == "artifact_update":
            artifacts.append(
                {
                    "artifact_id": ev["artifact_id"],
                    "filename": ev["filename"],
                    "content": ev["content"],
                    "complete": ev.get("last_chunk", True),
                }
            )

        elif t == "plan_update":
            plan = ev["entries"]

        elif t == "agent_status":
            aid = ev.get("agent_id", "")
            if aid and aid not in seen_agents:
                seen_agents.add(aid)
                agents.append(
                    {
                        "agent_id": aid,
                        "node_name": ev["node_name"],
                        "state": ev["state"],
                        "provider": "claude",
                        "model": "high",
                    }
                )
            else:
                # Update existing agent state
                for a in agents:
                    if a["agent_id"] == aid:
                        a["state"] = ev["state"]

        elif t == "permission_request":
            pending_permissions.append(
                {
                    "request_id": ev["request_id"],
                    "description": ev["description"],
                    "options": [
                        {
                            "option_id": o["option_id"],
                            "name": o["name"],
                            "kind": o["kind"],
                        }
                        for o in ev["options"]
                    ],
                    "tool_call": ev.get("tool_call"),
                }
            )

    return {
        "thread_id": thread_id,
        "status": summary["status"] if summary else "unknown",
        "messages": messages,
        "tool_calls": tool_calls,
        "pending_permissions": pending_permissions,
        "artifacts": artifacts,
        "plan": plan,
        "agents": agents,
        "last_sequence": last_seq,
        "checkpoint_id": None,
    }


THREAD_STATE_SNAPSHOTS: dict[str, dict] = {
    tid: _build_snapshot(tid) for tid in THREAD_EVENTS
}


# ── Interactive response builder ─────────────────────────────────────────────


def build_interactive_response(
    thread_id: str,
    user_content: str,
) -> list[tuple[dict, float]]:
    """Build a timed event sequence simulating an agent response.

    Returns list of (event_dict, delay_seconds) tuples.
    """
    msg_id = uuid4().hex[:16]
    tc_id = uuid4().hex[:16]

    events: list[tuple[dict, float]] = []

    # 1. Agent starts working
    events.append(
        (
            _envelope(
                "agent_status",
                thread_id,
                "planner-1",
                state="working",
                node_name="Planner",
                detail="Processing message",
            ),
            0.0,
        )
    )

    # 2. Thought
    events.append(
        (
            _envelope(
                "thought_chunk",
                thread_id,
                "planner-1",
                content="Let me analyze this request and determine the best approach. "
                "I should examine the relevant source files first.",
                message_id=f"thought-{msg_id}",
            ),
            0.2,
        )
    )

    # 3. Streamed message chunks (word by word)
    response_text = (
        "I'll help you with that. Let me start by examining the relevant "
        "files and understanding the current implementation. This looks like "
        "it will require changes to the core module and its configuration."
    )
    words = response_text.split()
    for i, word in enumerate(words):
        chunk = word + (" " if i < len(words) - 1 else "")
        is_last = i == len(words) - 1
        events.append(
            (
                _envelope(
                    "message_chunk",
                    thread_id,
                    "planner-1",
                    content=chunk,
                    message_id=f"msg-{msg_id}",
                    finish_reason="stop" if is_last else None,
                ),
                0.05,
            )
        )

    # 4. Tool call: read file
    events.append(
        (
            _envelope(
                "tool_call_start",
                thread_id,
                "coder-1",
                tool_call_id=tc_id,
                title="Reading src/main.py",
                kind="read",
                status="in_progress",
                locations=[{"path": "src/main.py", "line": 1}],
                content=[],
            ),
            0.3,
        )
    )

    # 5. Tool call completed with content
    events.append(
        (
            _envelope(
                "tool_call_update",
                thread_id,
                "coder-1",
                tool_call_id=tc_id,
                title=None,
                kind=None,
                status="completed",
                locations=None,
                content=[
                    {
                        "content_type": "text",
                        "text": (
                            "from fastapi import FastAPI\n"
                            "from .config import settings\n"
                            "from .routes import router\n\n"
                            "app = FastAPI(\n"
                            '    title="VaultSpec",\n'
                            "    version=settings.version,\n"
                            ")\n"
                            "app.include_router(router)\n"
                        ),
                    }
                ],
            ),
            0.5,
        )
    )

    # 6. Plan update
    events.append(
        (
            _envelope(
                "plan_update",
                thread_id,
                "planner-1",
                entries=[
                    {
                        "content": "Analyze request",
                        "status": "completed",
                        "priority": "high",
                    },
                    {
                        "content": "Read source files",
                        "status": "completed",
                        "priority": "medium",
                    },
                    {
                        "content": "Implement changes",
                        "status": "in_progress",
                        "priority": "high",
                    },
                    {"content": "Run tests", "status": "pending", "priority": "medium"},
                ],
            ),
            0.2,
        )
    )

    # 7. Follow-up message chunks
    follow_up = (
        "The code looks straightforward. I've identified the key areas "
        "that need modification. The main entry point loads configuration "
        "from settings and wires up the router. I'll proceed with the changes."
    )
    words2 = follow_up.split()
    for i, word in enumerate(words2):
        chunk = word + (" " if i < len(words2) - 1 else "")
        is_last = i == len(words2) - 1
        events.append(
            (
                _envelope(
                    "message_chunk",
                    thread_id,
                    "coder-1",
                    content=chunk,
                    message_id=f"msg2-{msg_id}",
                    finish_reason="stop" if is_last else None,
                ),
                0.05,
            )
        )

    # 8. Agent completes
    events.append(
        (
            _envelope(
                "agent_status",
                thread_id,
                "planner-1",
                state="idle",
                node_name="Planner",
                detail="Waiting for next instruction",
            ),
            0.2,
        )
    )

    return events
