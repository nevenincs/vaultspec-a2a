---
adr_id: 016
title: Task Runner & Developer Bootstrap
date: 2026-02-28
status: Proposed
related:
  - docs/adrs/007-tech-stack-deployment.md
  - docs/adrs/015-dependency-hygiene-cli-entry-point.md
  - docs/packaging/2026-28-02-packaging-distribution-research.md
---

# ADR-016: Task Runner & Developer Bootstrap

**Date:** 2026-02-28
**Status:** Proposed

## 1. Context & Problem Statement

The project currently has no task runner, no bootstrap script, and no
single-command setup. A new contributor must manually:

1. Install Python 3.13
2. Install uv
3. Run `uv sync`
4. Install Node.js (version unspecified)
5. Run `npm install` in `src/ui/`
6. Copy environment variables (no `.env.example` exists)
7. Know to run `uvicorn lib.api.app:create_app --factory` (or now
   `uv run vaultspec`)

This is 7 manual steps with no automation, no prerequisite checking, and
no discoverability. The project's Windows-primary development environment
(PWSH terminal, no WSL) further constrains tool choice — POSIX-only tools
like Makefile require Git Bash or WSL workarounds.

### 1.1 Reference Project Survey

| Project        | Task Runner       | Windows Support       |
| -------------- | ----------------- | --------------------- |
| LangChain      | Makefile          | Requires WSL/Git Bash |
| LangGraph      | Makefile          | Requires WSL/Git Bash |
| DeepAgents     | Makefile          | Requires WSL/Git Bash |
| acp-python-sdk | Makefile          | Requires WSL/Git Bash |
| Open WebUI     | Makefile (Docker) | Docker Desktop        |
| Dify           | Docker Compose    | Docker Desktop        |

None of the reference projects support native PowerShell development.
This is a gap we can fill.

## 2. Decision

### 2.1 Task Runner: Justfile

Adopt `just` (Justfile) as the project's task runner.

**Why `just` over alternatives:**

| Criterion                  | Makefile                   | Justfile                    | Taskfile.dev      |
| -------------------------- | -------------------------- | --------------------------- | ----------------- |
| Windows/PWSH native        | No                         | Yes (`set windows-shell`)   | Yes               |
| Install                    | Pre-installed (Unix)       | `winget install Casey.Just` | Go binary         |
| Syntax                     | Tab-sensitive, POSIX shell | Simple, no tabs             | YAML              |
| `.env` loading             | Manual                     | `set dotenv-load := true`   | Manual            |
| Platform branching         | Awkward                    | `os()` function             | `{{OS}}` variable |
| Adoption in Rust ecosystem | Low                        | High                        | Low               |
| Complexity                 | Low                        | Low                         | Medium            |

`just` is the only task runner that supports native PowerShell recipes
while remaining simple and low-overhead. It is a single static binary
with no runtime dependencies.

### 2.2 Bootstrap: `just setup`

A single command that validates prerequisites and installs all
dependencies:

```justfile
setup: _check-uv _check-node
    uv sync --all-groups
    cd src/ui && npm install
    @echo "Setup complete. Run 'just dev' to start."
```

### 2.3 Development: `just dev`

Start both the Python backend and Node frontend dev servers:

```justfile
dev:
    uv run vaultspec &
    cd src/ui && npm run dev
```

### 2.4 Environment Template: `.env.example`

A committed `.env.example` file documents all configurable environment
variables with sensible defaults. `.env` remains gitignored.

## 3. Implementation

### 3.1 Justfile

```justfile
set windows-shell := ["powershell.exe", "-c"]
set dotenv-load := true

# Show available recipes
default:
    @just --list

# Bootstrap: install all dependencies
setup: _check-uv _check-node
    uv sync --all-groups
    cd src/ui && npm install
    @echo "Setup complete. Run 'just dev' to start."

# Start backend + frontend dev servers
dev:
    uv run vaultspec &
    cd src/ui && npm run dev

# Run the test suite
test *ARGS:
    uv run pytest {{ARGS}}

# Run linter
lint:
    uv run ruff check .
    uv run ruff format --check .

# Auto-fix lint issues
format:
    uv run ruff check --fix .
    uv run ruff format .

# Type check
typecheck:
    uv run ty check

# Run dependency audit
audit:
    uv run deptry lib/

# Build wheel (includes frontend if hatch_build.py exists)
build:
    cd src/ui && npm run build
    uv build

# Docker build
docker-build:
    docker build -t vaultspec-a2a .

# Docker dev environment (with Jaeger)
docker-dev:
    docker compose up --build

# Clean build artifacts
clean:
    rm -rf dist/ build/ lib/api/static/ src/ui/build/

# --- Prerequisites ---

_check-uv:
    @uv --version || (echo "Install uv: https://docs.astral.sh/uv/getting-started/installation/" && exit 1)

_check-node:
    @node --version || (echo "Install Node.js 22+ via volta (https://volta.sh) or fnm (https://github.com/Schniz/fnm)" && exit 1)
```

### 3.2 .env.example

```env
# --- Server ---
VAULTSPEC_HOST=0.0.0.0
VAULTSPEC_PORT=8000

# --- Database ---
VAULTSPEC_DATABASE_URL=sqlite+aiosqlite:///vaultspec.db

# --- CORS (comma-separated origins) ---
# VAULTSPEC_CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8000

# --- LLM API Keys (at least one required for agent execution) ---
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# GEMINI_API_KEY=

# --- OpenTelemetry (mandatory — traces go to Jaeger or external backend) ---
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_INSECURE=true
# OTEL_SDK_DISABLED=true  # uncomment to suppress OTel when no collector is running
# OTEL_EXPORTER_CONSOLE=true  # uncomment to dump spans to stdout

# --- LangSmith (optional — LangChain tracing) ---
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=
# LANGCHAIN_PROJECT=vaultspec-a2a
```

### 3.3 Node Version Pinning

Add volta config to `src/ui/package.json`:

```json
{
  "volta": {
    "node": "22.0.0"
  }
}
```

This ensures contributors using volta automatically get the correct Node
version. Those using fnm should create a `.node-version` file at the
project root.

## 4. Consequences

### 4.1 Positive

- **One-command bootstrap**: `just setup` replaces 7 manual steps.
- **Discoverable**: `just` (no args) lists all available recipes.
- **Cross-platform**: Native PowerShell on Windows, bash on Unix.
- **Environment documented**: `.env.example` makes all config visible.
- **Consistent with ecosystem**: All recipe bodies delegate to `uv run`
  — the same pattern used by LangChain, LangGraph, and acp-python-sdk
  (just with `just` instead of `make`).

### 4.2 Negative

- **New tool to install**: Contributors must install `just` — mitigated
  by `winget install Casey.Just` or `scoop install just` (one command).
- **Not Makefile**: The reference repos all use Makefile. Developers
  familiar with `make lint` must learn `just lint` — the mapping is 1:1.

### 4.3 Neutral

- `just` does not replace `uv` — it orchestrates it. Every recipe body
  is a thin wrapper around `uv run`, `npm`, or `docker` commands.

## 5. Compliance Matrix

| ADR                        | Relationship                                       | Status    |
| -------------------------- | -------------------------------------------------- | --------- |
| ADR-007 (Tech Stack)       | Aligns — `just` orchestrates the uv + npm stack    | Compliant |
| ADR-009 (Module Hierarchy) | No impact                                          | N/A       |
| ADR-015 (Dep Hygiene)      | Builds on — `just audit` runs `uv run deptry lib/` | Compliant |
