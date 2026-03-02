---
adr_id: 015
title: Dependency Hygiene, Pruning, OTel Mandate & CLI Entry Point
date: 2026-02-28
status: Accepted
related:
  - docs/adrs/007-tech-stack-deployment.md
  - docs/adrs/009-approved-module-hierarchy.md
  - docs/adrs/010-observability-telemetry-integration.md
  - docs/packaging/2026-28-02-packaging-distribution-research.md
---

# ADR-015: Dependency Hygiene, Pruning, OTel Mandate & CLI Entry Point

**Date:** 2026-02-28
**Status:** Proposed

## 1. Context & Problem Statement

The project's dependency stack and module declarations have accumulated
cruft that must be carefully pruned and updated before the project can be
packaged, containerized, or distributed. A systematic audit of
`pyproject.toml` against actual codebase imports reveals three categories
of issues:

| Category | Finding | Impact |
| ---------- | --------- | -------- |
| **Dead dependencies** | `pywin32>=311` and `winfcntl>=1.1.9` are listed as unconditional runtime deps but are **imported nowhere** in the codebase (0 matches across all of `lib/`). | `uv sync` / `pip install` **fails on Linux and macOS** because pywin32 has no non-Windows wheels. Cross-platform install, Docker builds, and CI on Ubuntu are all broken. |
| **Phantom dependency** | `claude-agent-sdk` is pinned to a git URL (`git+https://github.com/anthropics/claude-agent-sdk-python.git@main`) but is **imported nowhere** in the codebase. | Blocks PyPI distribution entirely (PyPI rejects packages with git-based deps). Adds ~3,100 lines of unused transitive code to the venv. Couples the lockfile to GitHub availability. |
| **Speculative deps** | 8 additional runtime deps (`PyYAML`, `a2a-sdk`, `agent-client-protocol`, `fastmcp`, `langchain-anthropic`, `langchain-google-genai`, `langchain-mcp-adapters`, `sse-starlette`) are **imported nowhere** — added speculatively as the architecture evolved to use ACP subprocess wrappers instead of direct SDK calls. | Bloated dependency surface (25 → 17 runtime deps). Slower installs, larger venv, false sense of coupling. |
| **Misscoped OTel** | OpenTelemetry packages are in `[project.optional-dependencies] telemetry` with try/except guards in `app.py`. | ADR-010 mandates observability. Optional OTel contradicts the mandate — telemetry must be unconditional. |
| **Transitive `anyio`** | `anyio` is directly imported in 3 files (`app.py`, `endpoints.py`) but only available transitively. | Fragile — if a transitive dep drops anyio, the project breaks silently. |
| **Missing entry point** | No `main()` function, no `__main__.py`, no `[project.scripts]` entry exists. | The server can only be started via manual `uvicorn` CLI invocation. No `uvx`, `pipx`, or `vaultspec` CLI command is possible. |

The dependency stack and module declarations need careful pruning and
updating. The project accumulated 25+ runtime deps without systematic
auditing — a `deptry` scan revealed that **11 of 25 runtime deps are
entirely unused** (zero imports in `lib/`). This is the consequence of
rapid architectural evolution: the project moved from direct LangChain
provider imports to ACP subprocess wrappers, but the now-dead direct
deps were never cleaned up.

### 1.1 Root Cause Analysis

**pywin32 / winfcntl:** Added as precautionary deps when Windows-specific
subprocess logic was implemented in `AcpChatModel`. The code then evolved
to use only stdlib `subprocess` primitives (`CREATE_NEW_PROCESS_GROUP`,
`taskkill` via `create_subprocess_exec`), but the now-unused
`pyproject.toml` entries were never removed. pywin32 remains available as
a correctly-guarded transitive dependency of `mcp>=1.26.0`.

**claude-agent-sdk:** Used as a **design research reference** during
architecture. The project's `AcpChatModel` re-implements subprocess
management over raw ACP JSON-RPC — a deliberately different wire protocol
from the SDK's `stream-json` format. The `knowledge/repositories/
claude-agent-sdk/` clone continues to serve as the reference artifact.

**Missing entry point:** The codebase was developed as a library-first
project (`packages = ["lib"]`) with the assumption that uvicorn would
always be invoked externally. No thought was given to self-contained
execution.

## 2. Decision

### 2.1 Remove All Dead Dependencies (11 packages)

Remove the following 11 packages from `pyproject.toml`
`[project.dependencies]` — all confirmed zero imports in `lib/`:

| Package | Why it was there | Why it's dead |
| --------- | ----------------- | --------------- |
| `pywin32` | Precautionary for Windows subprocess | Code uses only stdlib `subprocess.CREATE_NEW_PROCESS_GROUP`. Remains available transitively via `mcp>=1.26.0` (correctly guarded). |
| `winfcntl` | Precautionary fcntl compat | Zero consumers anywhere. |
| `claude-agent-sdk` | Design research reference | AcpChatModel uses raw ACP JSON-RPC, not the SDK's stream-json. Eliminates only git-based dep (PyPI blocker). |
| `PyYAML` | Speculative | Not imported. Config uses pydantic-settings, not YAML. |
| `a2a-sdk` | Speculative | Not imported. A2A protocol handled at HTTP/WS level. |
| `agent-client-protocol` | Speculative | Not imported. ACP implemented from scratch in `acp_chat_model.py`. |
| `fastmcp` | Confusion with `mcp.server.fastmcp` | `FastMCP` is imported from `mcp` package, not `fastmcp` (different PyPI package). |
| `langchain-anthropic` | Early direct LLM calls | Claude now invoked via ACP subprocess, not LangChain provider. |
| `langchain-google-genai` | Early direct LLM calls | Gemini now invoked via ACP subprocess, not LangChain provider. |
| `langchain-mcp-adapters` | Speculative MCP integration | Not imported. MCP handled directly via `mcp` package. |
| `sse-starlette` | Speculative SSE support | Not imported. SSE handled by FastAPI/Starlette natively. |

### 2.2 Remove Phantom Dependency

Remove `claude-agent-sdk` from `pyproject.toml` `[project.dependencies]`.

**Rationale:**

- Zero imports across the entire codebase.
- Different wire protocol: our `AcpChatModel` uses ACP JSON-RPC, the SDK
  uses `stream-json`. They are parallel implementations, not consumer and
  library.
- Eliminates the **only git-based dependency**, unblocking PyPI
  distribution.
- The `knowledge/repositories/claude-agent-sdk/` clone remains available
  as a design reference.
- If future Claude-Code-specific integration is needed, the SDK can be
  re-added (with a PyPI release or as an optional extra) and a
  `ClaudeSDKChatModel(BaseChatModel)` adapter built alongside
  `AcpChatModel` — the `BaseChatModel` interface in
  `lib/core/nodes/worker.py` is already the correct abstraction point.

### 2.3 Promote OpenTelemetry to Mandatory Runtime Dependency

Move the three OpenTelemetry packages from `[project.optional-dependencies]
telemetry` to `[project.dependencies]` and remove all try/except guards
and conditional checks in `lib/api/app.py`.

**Rationale:**

- ADR-010 mandates observability as a first-class architectural concern.
  Optional telemetry contradicts this mandate — if OTel is optional,
  production deployments may silently lack instrumentation.
- The `lib/telemetry/` module already imports OTel unconditionally (no
  guards in `middleware.py` or `instrumentation.py`). The try/except
  existed only in `app.py` as a consumer convenience — but it masked
  installation failures rather than surfacing them.
- Removes the `[telemetry]` optional extras section entirely. OTel is
  always installed, always configured, always active.

**Packages promoted:**

- `opentelemetry-sdk>=1.39.1`
- `opentelemetry-exporter-otlp-proto-grpc>=1.39.1`
- `opentelemetry-instrumentation-fastapi>=0.60b0`

**Code changes in `lib/api/app.py`:**

- `try: from ..telemetry import ...` → direct import (no guard)
- `if _configure_telemetry is not None:` → unconditional `configure_telemetry()`
- `if _TelemetryMiddleware is not None:` → unconditional
  `app.add_middleware(..., TelemetryMiddleware)`

### 2.4 Promote anyio to Direct Dependency

Add `anyio>=4.9.0` to `[project.dependencies]`.

**Rationale:**

- Directly imported in `lib/api/app.py` and `lib/api/endpoints.py` for
  `anyio.create_task_group()` — a core concurrency primitive.
- Previously only available transitively via FastAPI/uvicorn/starlette.
  Relying on transitive availability is fragile — if a dep drops anyio,
  the project breaks silently.
- deptry flagged this as DEP003 (transitive dep used directly).

### 2.5 Add CLI Entry Point

Add a `main()` function to `lib/api/app.py` and declare a
`[project.scripts]` entry point in `pyproject.toml`:

```toml
[project.scripts]
vaultspec = "lib.api.app:main"
```

```python
def main() -> None:
    """Launch the vaultspec-a2a server."""
    import uvicorn

    uvicorn.run(
        "lib.api.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
    )
```

**Rationale:**

- Enables `vaultspec` CLI command after `pip install`.
- Enables `uvx vaultspec-a2a` for ephemeral execution.
- Enables `pipx install vaultspec-a2a` for persistent global install.
- Builds on the existing `create_app()` factory and `_lifespan` context
  manager — no architectural changes required.
- uvicorn import is deferred to function body to avoid import-time side
  effects.

### 2.6 Mandate Systematic Dependency Audit

Introduce `deptry` as a dev dependency and mandate its use in CI and
pre-commit. `deptry` (already used by `acp-python-sdk` in the reference
repos) detects:

- **DEP001** — Missing dependencies (imported but not declared)
- **DEP002** — Unused dependencies (declared but not imported)
- **DEP003** — Transitive dependencies (imported but only available
  transitively, not declared directly)
- **DEP004** — Misplaced dev dependencies (dev deps imported in runtime
  code)

```toml
[dependency-groups]
dev = [
  # ... existing ...
  "deptry>=0.22.0",
]
```

The initial audit run is expected to surface additional issues beyond the
three confirmed dead dependencies. All findings must be triaged and
resolved before any packaging or distribution work proceeds.

**Audit scope:**

- All entries in `[project.dependencies]`
- All entries in `[project.optional-dependencies]`
- All entries in `[dependency-groups]`
- Cross-reference against actual imports in `lib/` source (excluding
  `knowledge/` and `tests/`)

## 3. Implementation

### 3.1 pyproject.toml Changes

```diff
 [project.dependencies]
+  "anyio>=4.9.0",
   "fastapi>=0.133.1",
   "httpx>=0.28.1",
   "langchain-core>=1.2.16",
   "langchain-openai>=1.1.10",
   "langgraph>=0.2.16",
   "langgraph-checkpoint-sqlite>=2.0.0",
   "mcp>=1.26.0",
+  "opentelemetry-sdk>=1.39.1",
+  "opentelemetry-exporter-otlp-proto-grpc>=1.39.1",
+  "opentelemetry-instrumentation-fastapi>=0.60b0",
   "pydantic>=2.12.5",
   "pydantic-settings>=2.13.1",
   "rich>=14.3.2",
   "sqlalchemy[asyncio]>=2.0.40",
   "starlette>=0.52.1",
   "uvicorn>=0.41.0",

-  "PyYAML>=6.0.3",
-  "a2a-sdk>=0.3.24",
-  "agent-client-protocol>=0.8.1",
-  "claude-agent-sdk @ git+https://...",
-  "fastmcp>=3.0.2",
-  "langchain-anthropic>=1.3.4",
-  "langchain-google-genai>=4.2.1",
-  "langchain-mcp-adapters>=0.2.1",
-  "pywin32>=311",
-  "sse-starlette>=3.2.0",
-  "winfcntl>=1.1.9",

+[project.scripts]
+vaultspec = "lib.api.app:main"

-[project.optional-dependencies]
-telemetry = [...]  # moved to [project.dependencies]

-[tool.hatch.metadata]
-allow-direct-references = true  # no longer needed (git dep removed)
```

**Net result:** 25 → 17 runtime deps. 11 removed, 3 promoted (OTel
from optional), 1 added (anyio from transitive).

### 3.2 lib/api/app.py Changes

```diff
-# Telemetry is an optional extra; import once at module level so the
-# function reference is stable and the import lives at the top level.
-try:
-    from ..telemetry import TelemetryMiddleware as _TelemetryMiddleware
-    from ..telemetry import configure_telemetry as _configure_telemetry
-except ImportError:
-    _configure_telemetry: Callable[[], None] | None = None
-    _TelemetryMiddleware: type | None = None
+from ..telemetry import TelemetryMiddleware, configure_telemetry

 # In _lifespan:
-        if _configure_telemetry is not None:
-            _configure_telemetry()
-        else:
-            logger.debug("Telemetry packages not installed, skipping")
+        configure_telemetry()
+        logger.info("Telemetry configured")

 # In create_app:
-    if _TelemetryMiddleware is not None:
-        app.add_middleware(cast(Any, _TelemetryMiddleware))
+    app.add_middleware(cast(Any, TelemetryMiddleware))
```

Add `main()` function (CLI entry point):

```python
def main() -> None:
    """Launch the vaultspec-a2a server."""
    import uvicorn

    uvicorn.run(
        "lib.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
```

### 3.3 deptry Configuration

```toml
[tool.deptry]
extend_exclude = ["knowledge", "tests"]

[tool.deptry.package_module_name_map]
opentelemetry-sdk = "opentelemetry"
opentelemetry-exporter-otlp-proto-grpc = "opentelemetry"
opentelemetry-instrumentation-fastapi = "opentelemetry"

[tool.deptry.per_rule_ignores]
# CLI tools — invoked as commands, not imported in Python
DEP002 = ["ruff", "ty", "prek", "identify", "nodeenv",
          "pytest-timeout", "deptry"]
```

### 3.4 Lockfile Regeneration

```bash
uv lock    # Resolved 100 packages (down from 144)
uv sync
```

### 3.5 Verification

1. `uv lock` — resolves 100 packages (was 144 before pruning)
2. `uv sync` — clean install on Windows
3. `uv run pytest` — 536 passed, 0 failed
4. `uv run deptry lib/` — zero actionable violations
5. `uv run vaultspec` — starts the server via CLI entry point
6. `uv build` — wheel builds without git-dep errors

## 4. Consequences

### 4.1 Positive

- **Cross-platform install**: `uv sync` / `pip install` now works on
  Linux and macOS — unblocking Docker, CI, and contributor onboarding.
- **PyPI-ready**: No git-based dependencies remain. The package can be
  published to PyPI (pending the frontend embedding work in a future
  ADR).
- **CLI usability**: `vaultspec` command available after install. `uvx
  vaultspec-a2a` works for ephemeral use.
- **Dependency hygiene**: `deptry` in CI catches future dep drift
  automatically. Reduced from 144 → 100 resolved packages.
- **Mandatory observability**: OTel is always installed, always
  configured, always active. No deployment can silently lack
  instrumentation. Aligns with ADR-010 mandate.
- **Smaller, honest dep surface**: 25 → 17 runtime deps. Each one is
  directly imported. No speculative or phantom dependencies.

### 4.2 Negative

- **No claude-agent-sdk at runtime**: If a future feature requires the
  SDK's `query()` or `ClaudeSDKClient`, it must be re-added. This is
  mitigated by the `BaseChatModel` abstraction — a new adapter can be
  built without changing orchestration code.
- **No direct LangChain provider deps**: `langchain-anthropic` and
  `langchain-google-genai` are removed. If the architecture ever moves
  from ACP subprocess wrappers back to direct provider calls, these must
  be re-added. Current architecture makes this unlikely.
- **OTel is no longer optional**: Every install pulls in gRPC and OTel
  SDK packages. This adds ~15MB to the venv but aligns with the
  observability mandate.

### 4.3 Neutral

- `knowledge/repositories/claude-agent-sdk/` remains untouched as a
  design reference.
- pywin32 remains available transitively via `mcp` with correct platform
  markers. No code depends on it directly.

## 5. Compliance Matrix

| ADR | Relationship | Status |
| ----- | ------------- | -------- |
| ADR-007 (Tech Stack) | Aligns — removes undeclared platform coupling | Compliant |
| ADR-009 (Module Hierarchy) | Aligns — `lib/api/app.py` gains `main()` in its public surface | Compliant |
| ADR-010 (Observability) | **Enforces** — OTel promoted from optional to mandatory runtime dep | Compliant |
| Research doc | Implements "Immediate Action Items §7.1" from packaging research | Compliant |

## 6. Open Questions

1. Should the `vaultspec` CLI accept `--host` / `--port` arguments, or
   defer to environment variables via `pydantic-settings`? (Deferred to
   implementation — start with env-only, add CLI args if needed.)
2. Should `deptry` be added to the `prek` pre-commit hook chain, or run
   only in CI? (Recommend CI-only — `deptry` scans are slow for
   pre-commit.)
3. The `lib` package name may conflict with other packages on PyPI. A
   rename to `vaultspec_a2a` is a separate concern tracked in the
   packaging research document §8, question 3.
