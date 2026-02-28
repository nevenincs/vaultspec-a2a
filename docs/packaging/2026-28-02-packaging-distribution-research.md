# Packaging & Distribution Research

**Date**: 2026-02-28
**Status**: Research Complete — Pending ADR Decisions
**Scope**: Python 3.13 backend (FastAPI/LangGraph/uv/hatchling) + SvelteKit 5
frontend, monorepo, Windows-primary development

---

## 1. Executive Summary

This document consolidates research from 5 parallel investigations into how to
package, containerize, bootstrap, and distribute vaultspec-a2a — a hybrid
Python+Node monorepo with complex AI/ML dependencies.

**Key findings:**

1. The **embedded frontend** pattern (hatchling build hook → bundled static
   assets in wheel) is the industry standard used by Gradio, Chainlit, Open
   WebUI, and LangFlow.
2. **`just` (Justfile)** is the best task runner for our Windows-primary,
   cross-platform needs — superior to Makefile for PWSH.
3. **Docker** follows a well-established multi-stage pattern (Node build →
   Python runtime), with `uv` having official Docker best practices.
4. The **`claude-agent-sdk` git dependency** is the single biggest blocker to
   PyPI distribution.
5. **Platform markers** (`sys_platform == 'win32'`) must be added to
   pywin32/winfcntl immediately — the current pyproject.toml breaks on
   Linux/macOS.

---

## 2. Reference Project Analysis

### 2.1 Open-Source Hybrid Projects

| Project | Backend | Frontend | Build System | Task Runner | Distribution |
|---------|---------|----------|-------------|-------------|-------------|
| **LangFlow** | FastAPI/LangChain | React/Vite | hatchling + uv workspace | Makefile | PyPI wheel (embedded) |
| **Open WebUI** | FastAPI | SvelteKit | hatchling `force-include` | Makefile (Docker) | Docker + PyPI |
| **Chainlit** | FastAPI/Socket.IO | React/Vite | hatchling `CustomBuildHook` | None (hook is coordinator) | PyPI wheel (embedded) |
| **Dify** | Flask | Next.js | Poetry | Docker Compose | Docker only |
| **Gradio** | FastAPI | Svelte/JS | hatchling custom hook | `gradio cc build` | PyPI wheel (embedded) |
| **Streamlit** | Tornado | React | setuptools | Make | PyPI wheel (embedded) |

**Dominant pattern**: hatchling build hook triggers `npm run build`, copies
output into Python package directory, wheel ships everything. FastAPI serves
static assets via `StaticFiles(html=True)`.

### 2.2 Knowledge Repository Patterns

| Repo | Build System | Task Runner | Docker | Monorepo Strategy |
|------|-------------|-------------|--------|-------------------|
| **a2a-python** | hatchling + uv-dynamic-versioning | Shell scripts | Compose (test only) | Single package, optional extras |
| **a2a-samples** | hatchling per agent | None (uv workspace) | Minimal per-agent | uv workspace, shared lockfile |
| **acp-python-sdk** | pdm-backend | Makefile (uv targets) | None | Single package |
| **claude-agent-sdk** | hatchling | None | Dockerfile.test | Single package, src/ layout |
| **langgraph/cli** | hatchling | Makefile | Programmatic compose generation | Multi-lib, independent |
| **deepagents** | setuptools (mixed) | Root Makefile | None | Multi-lib, independent lockfiles |
| **toad** | hatchling (pinned) | Makefile | None | uv workspace, single member |

**Cross-cutting observations:**

- `uv` is universal — every repo uses it for env management
- Makefile is the common task orchestrator, always delegating to `uv run`
- hatchling dominates as build backend
- Docker is used sparingly (test infra or deployment, not dev workflow)
- `ty` (Astral type checker) is replacing mypy across ACP-world repos
- `prek` replacing pre-commit in ACP-world repos

---

## 3. Packaging Strategy: Embedded Frontend

### 3.1 How It Works

```
src/ui/ (SvelteKit source)
  └── npm run build → src/ui/build/ (static HTML/JS/CSS)
       └── hatch_build.py copies to → lib/api/static/
            └── uv build → wheel includes lib/api/static/**
                 └── FastAPI serves via StaticFiles(html=True)
```

### 3.2 pyproject.toml Changes

```toml
[tool.hatch.build.targets.wheel]
packages = ["lib"]
artifacts = [
  "lib/api/static/**",  # VCS-ignored but included in wheel
]

[tool.hatch.build.targets.wheel.hooks.custom]
path = "hatch_build.py"
```

### 3.3 Build Hook (hatch_build.py)

```python
"""Hatchling build hook: builds SvelteKit frontend and embeds in wheel."""

import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        ui_dir = Path(self.root) / "src" / "ui"
        target = Path(self.root) / "lib" / "api" / "static"

        # Skip if already built (e.g., sdist → wheel)
        if target.exists() and any(target.iterdir()):
            return

        subprocess.run(["npm", "ci"], cwd=ui_dir, check=True)
        subprocess.run(["npm", "run", "build"], cwd=ui_dir, check=True)

        build_dir = ui_dir / "build"  # adapter-static output
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(build_dir, target)
```

### 3.4 FastAPI Static Serving

```python
from pathlib import Path
import importlib.resources

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Locate embedded frontend assets (works in wheel and dev)
static_dir = Path(importlib.resources.files("lib.api") / "static")

# API routes MUST be registered BEFORE the catch-all static mount
app.include_router(api_router, prefix="/api")

# SPA catch-all: serves index.html for unknown routes
app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
```

### 3.5 SvelteKit Adapter

Currently using `@sveltejs/adapter-static` — this is correct for the embedded
pattern. Output is pure HTML/JS/CSS with no Node runtime needed. No change
required.

---

## 4. Docker Strategy

### 4.1 Multi-Stage Dockerfile

```dockerfile
# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build
WORKDIR /app/src/ui
COPY src/ui/package*.json ./
RUN npm ci
COPY src/ui/ .
RUN npm run build

# Stage 2: Python runtime
FROM python:3.13-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Two-phase uv sync: deps first (cached), then app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev --locked

COPY lib/ ./lib/
COPY --from=frontend-build /app/src/ui/build ./lib/api/static/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-editable

# Non-root user
RUN groupadd -g 1001 app && useradd -u 1001 -g app -m appuser
USER appuser

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "lib.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 4.2 Base Image Decision

**Recommended: `python:3.13-slim-bookworm`**

- Alpine breaks compiled packages (musl vs glibc — grpcio, SQLAlchemy)
- `slim-bookworm` ≈ 130MB, avoids Alpine pitfalls
- Alternative: `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` (uv pre-bundled)

### 4.3 Docker Compose (Development)

```yaml
services:
  backend:
    build:
      context: .
      target: runtime
    ports: ["8000:8000"]
    volumes:
      - db-data:/app/data
    environment:
      - DATABASE_URL=sqlite:////app/data/vaultspec.db
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
      - OTEL_EXPORTER_OTLP_INSECURE=true
    depends_on:
      - jaeger

  frontend:
    image: node:22-alpine
    working_dir: /app/src/ui
    command: npm run dev -- --host 0.0.0.0
    ports: ["5173:5173"]
    volumes:
      - ./src/ui:/app/src/ui

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "4317:4317"   # OTLP gRPC receiver
      - "4318:4318"   # OTLP HTTP receiver
      - "16686:16686" # Jaeger UI
    environment:
      - COLLECTOR_OTLP_ENABLED=true

volumes:
  db-data:
```

### 4.4 SQLite in Docker

- Named volume for `vaultspec.db` + WAL/SHM files — must stay together
- WAL mode requires single-host access (no NFS, no multi-container sharing)
- Single-container deployment with named volume is the correct pattern

### 4.5 Platform-Specific Dependencies

> **Resolved by ADR-015:** pywin32, winfcntl, and claude-agent-sdk have
> been removed entirely from `pyproject.toml` (zero imports in codebase).
> No platform markers or git-dep handling needed in Docker.

### 4.7 Dev Container (.devcontainer)

```json
{
  "name": "vaultspec-a2a",
  "image": "mcr.microsoft.com/devcontainers/base:debian-12",
  "features": {
    "ghcr.io/devcontainers/features/node:1": { "version": "22" },
    "ghcr.io/jsburckhardt/devcontainer-features/uv:1": {}
  },
  "postCreateCommand": "uv sync && cd src/ui && npm install",
  "forwardPorts": [8000, 5173],
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "charliermarsh.ruff",
        "svelte.svelte-vscode"
      ]
    }
  }
}
```

---

## 5. Developer Experience & Bootstrap

### 5.1 Task Runner: Justfile (Recommended)

**Why `just` over Makefile:**

- Native PowerShell support (`set windows-shell := ["powershell.exe", "-c"]`)
- Windows binary via `winget install Casey.Just`
- Auto-loads `.env` files
- No tab-sensitivity footgun
- Platform branching via `os()` function

**Why not alternatives:**

- Makefile: POSIX-only, needs Git Bash on Windows
- Taskfile.dev: More verbose, overkill for our needs
- uv scripts: Feature request closed as "not planned"

### 5.2 Proposed Justfile

```justfile
set windows-shell := ["powershell.exe", "-c"]
set dotenv-load := true

# Bootstrap: install all dependencies
setup: _check-uv _check-node
    uv sync --all-groups
    cd src/ui && npm install
    @echo "Setup complete. Run 'just dev' to start."

# Development: start backend + frontend
dev:
    uv run uvicorn lib.api.app:app --reload --port 8000 &
    cd src/ui && npm run dev

# Run test suite
test:
    uv run pytest

# Lint and format
lint:
    uv run ruff check .
    uv run ruff format --check .

format:
    uv run ruff check --fix .
    uv run ruff format .

# Type check
typecheck:
    uv run ty check

# Build wheel (includes frontend)
build:
    cd src/ui && npm run build
    uv build

# Docker build
docker-build:
    docker build -t vaultspec-a2a .

# Prerequisite checks
_check-uv:
    @uv --version || (echo "Install uv: https://docs.astral.sh/uv/" && exit 1)

_check-node:
    @node --version || (echo "Install Node via volta or fnm" && exit 1)
```

### 5.3 Node Version Pinning

**Recommended: Volta** (pins in `package.json`, Windows-native)

```json
{
  "volta": {
    "node": "22.0.0",
    "npm": "10.0.0"
  }
}
```

**Alternative: fnm** (Rust-based, uses `.node-version` file). Both work on
Windows natively. nvm does NOT work on Windows.

### 5.4 Python Version

Already handled by `uv` via `requires-python = ">=3.13"` in pyproject.toml.
No additional tooling needed.

### 5.5 Environment Variables

Already using `pydantic-settings` with `.env` file support. Justfile's
`set dotenv-load := true` complements this. Add a `.env.example` template.

---

## 6. Distribution Strategies

### 6.1 Decision Matrix

| Strategy | Complexity | User Experience | PyPI-Ready | Blocks |
|----------|-----------|----------------|-----------|--------|
| **A. PyPI wheel (embedded frontend)** | Medium | `pip install vaultspec-a2a` | Yes | Frontend build hook |
| **B. Docker image** | Low | `docker run vaultspec-a2a` | N/A | None |
| **C. GitHub install** | Low | `pip install git+https://...` | N/A | None |
| **D. uvx ephemeral** | Low | `uvx vaultspec-a2a` | Yes | PyPI publish |
| **E. Binary (PyInstaller)** | High | Download `.exe` | N/A | Build pipeline |
| **F. Desktop (Tauri)** | Very High | Native app | N/A | Rust toolchain |

> **Update (ADR-015):** The claude-agent-sdk git dependency has been
> removed (zero imports). pywin32 and winfcntl also removed. The PyPI
> blocker is resolved — all remaining deps are on PyPI. CLI entry point
> (`vaultspec` command) is implemented.

### 6.2 Recommended Phased Approach

**Phase 1 (Now):** Developer tooling + Docker

- Justfile for dev bootstrap (`just setup`, `just dev`, `just test`)
- Dockerfile + docker-compose.yml with Jaeger
- `.devcontainer` for Codespaces/VS Code
- `.env.example` template

**Phase 2 (Next):** PyPI distribution

- hatchling build hook bundles frontend (`hatch_build.py`)
- `pip install vaultspec-a2a` / `uvx vaultspec-a2a`
- GitHub Actions CI + Trusted Publishing

**Phase 3 (Optional):** Binary/Desktop

- PyInstaller for Windows `.exe`
- Tauri wrapper for native desktop experience

---

## 7. Action Items

### 7.1 Completed (ADR-015)

- ~~Add `sys_platform == 'win32'` markers to pywin32 and winfcntl~~
  **Removed entirely** — zero imports in codebase
- ~~Remove claude-agent-sdk git dependency~~
  **Removed** — PyPI blocker resolved
- ~~Add `[project.scripts]` entry point~~
  **Done** — `vaultspec = "lib.api.app:main"`
- ~~Promote OTel to mandatory runtime dep~~
  **Done** — try/except guards removed
- ~~Add deptry to dev tooling~~
  **Done** — zero violations
- ~~Remove 8 additional dead deps~~
  **Done** — 25 → 17 runtime deps, 144 → 100 resolved packages

### 7.2 Remaining: New Files to Create

1. `Justfile` — task runner for dev workflow
2. `Dockerfile` — multi-stage build
3. `docker-compose.yml` — dev environment (with Jaeger)
4. `.devcontainer/devcontainer.json` — VS Code dev container
5. `hatch_build.py` — frontend build hook (Phase 2)
6. `.env.example` — environment template
7. `.dockerignore` — exclude knowledge/, node_modules/, .venv/, etc.

### 7.3 Remaining: ADR Topics

1. **ADR-016: Task Runner & Dev Bootstrap** — Justfile, `just setup`,
   `just dev`, cross-platform recipes
2. **ADR-017: Containerization Strategy** — Dockerfile, docker-compose,
   devcontainer, Jaeger sidecar
3. **ADR-018: Frontend Embedding & PyPI Distribution** — hatchling build
   hook, GitHub Actions CI, Trusted Publishing

---

## 8. Open Questions for ADR Phase

1. Should the frontend be served by FastAPI in production, or by a separate
   Nginx/Caddy reverse proxy?
2. Should we adopt `mise` for polyglot version pinning, or keep uv + volta
   separate?
3. Is the `lib` package name acceptable for PyPI, or should we rename to
   `vaultspec_a2a` for the public module?
4. ~~Should we vendor `claude-agent-sdk` or wait for PyPI release?~~
   **Resolved** — removed entirely (ADR-015).
5. Do we need a `langgraph.json` manifest for LangGraph CLI deployment
   compatibility?
6. ~~Should telemetry (OTel collector) be part of the default Docker
   Compose, or a separate overlay?~~ **Resolved** — Jaeger included in
   default dev compose. OTel is mandatory (ADR-015).

---

## 9. Sources

### Hybrid Project References

- [LangFlow build system](https://deepwiki.com/langflow-ai/langflow/2-build-system-and-package-management)
- [LangFlow DEVELOPMENT.md](https://github.com/langflow-ai/langflow/blob/main/DEVELOPMENT.md)
- [Open WebUI architecture](https://deepwiki.com/open-webui/open-webui/17.1-installation-and-setup)
- [Chainlit developer guide](https://deepwiki.com/Chainlit/chainlit/11-developer-guide)
- [Gradio pyproject.toml](https://github.com/gradio-app/gradio/blob/main/pyproject.toml)
- [Embedding React in FastAPI](https://medium.com/@asafshakarzy/embedding-a-react-frontend-inside-a-fastapi-python-package-in-a-monorepo-c00f99e90471)

### Docker & Containerization

- [uv in Docker (official)](https://docs.astral.sh/uv/guides/integration/docker/)
- [Optimal uv Dockerfile — Depot](https://depot.dev/docs/container-builds/how-to-guides/optimal-dockerfiles/python-uv-dockerfile)
- [Production Python Docker with uv — Hynek](https://hynek.me/articles/docker-uv/)
- [Python base image recommendations](https://pythonspeed.com/articles/base-image-python-docker-images/)
- [SQLite in Docker](https://oneuptime.com/blog/post/2026-02-08-how-to-run-sqlite-in-docker-when-and-how/view)
- [Docker Compose Watch](https://docs.docker.com/compose/how-tos/file-watch/)
- [SvelteKit Docker guide](https://khromov.se/dockerizing-your-sveltekit-applications-a-practical-guide/)
- [Dify Docker deployment](https://deepwiki.com/langgenius/dify-docs/3.2-docker-compose-deployment)

### Developer Experience

- [just manual](https://just.systems/man/en/)
- [mise documentation](https://mise.jdx.dev/tasks/)
- [Volta](https://volta.sh/)
- [fnm](https://github.com/Schniz/fnm)

### Distribution

- [Hatch build hooks](https://hatch.pypa.io/latest/plugins/build-hook/reference/)
- [PyPI git dependency discussion](https://discuss.python.org/t/packages-installed-from-pypi-cannot-depend-on-packages-which-are-not-also-hosted-on-pypi/3736)
- [uv tools docs](https://docs.astral.sh/uv/concepts/tools/)
- [PEP 508 markers](https://peps.python.org/pep-0631/)
- [GitHub Actions PyPI publish](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
- [PyInstaller vs Nuitka](https://coderslegacy.com/nuitka-vs-pyinstaller/)
- [Tauri + FastAPI template](https://github.com/fudanglp/tauri-fastapi-full-stack-template)
