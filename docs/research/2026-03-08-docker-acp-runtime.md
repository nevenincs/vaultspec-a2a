# Docker ACP Runtime — 2026-03-08

## Problem Statement (PROV-O01+O02)

The worker Docker image (`docker/prod.Dockerfile`, `worker` target) runs on
`python:3.13-slim-bookworm` with no Node.js runtime. The ACP provider
(`providers/factory.py`) requires Node.js to execute the
`@zed-industries/claude-agent-acp` subprocess:

```python
_CLAUDE_ACP_JS = _PROJECT_ROOT / "node_modules" / "@zed-industries" / \
    "claude-agent-acp" / "dist" / "index.js"

# Invoked as: ["node", str(_CLAUDE_ACP_JS)]
```text

**Failure mode in Docker:** `node` is not in PATH, `node_modules/` is not
copied into the worker image. Any ACP-backed provider (Claude, Gemini) crashes
with `FileNotFoundError` or `ConfigError`.

---

## 1. Current Docker Architecture

```text
prod.Dockerfile multi-stage:

  frontend-build (node:22-alpine)
    └── npm ci + npm run build → /app/src/ui/dist/

  python-base (python:3.13-slim-bookworm)
    └── uv sync → /app/.venv/

  api (FROM python-base)
    └── COPY --from=frontend-build /app/src/ui/dist/ → SPA serving
    └── No Node.js runtime needed (static files only)

  worker (FROM python-base)
    └── No Node.js runtime
    └── No node_modules/
    └── VAULTSPEC_PROJECT_ROOT=/app (env override for path traversal)
    └── ACP providers BROKEN
```text

**Key observation:** The `frontend-build` stage has `node:22-alpine` with a
full Node.js runtime and `npm ci` installs packages. But only the built
`dist/` artifacts are copied out. The runtime Node.js binary and `node_modules/`
are left behind.

---

## 2. @zed-industries/claude-agent-acp Distribution

### 2.1 Package Metadata (from installed node_modules)

```json
{
  "name": "@zed-industries/claude-agent-acp",
  "version": "0.20.2",
  "main": "dist/lib.js",
  "bin": { "claude-agent-acp": "dist/index.js" },
  "dependencies": {
    "@agentclientprotocol/sdk": "0.14.1",
    "@anthropic-ai/claude-agent-sdk": "0.2.68",
    "zod": "^3.25.0 || ^4.0.0"
  }
}
```text

### 2.2 Dependency Tree Size (verified on disk)

| Package | Size | Notes |
|---------|------|-------|
| `@zed-industries/claude-agent-acp` | 169KB | Entry point + dist/ JS files |
| `@agentclientprotocol/sdk` | 911KB | ACP protocol client |
| `@anthropic-ai/claude-agent-sdk` | **77MB** | Bundles `sharp` (image processing) with platform-specific native binaries for every OS/arch, plus 12MB `cli.js` single-file bundle, WASM modules (resvg, tree-sitter) |
| `zod` | 5.5MB | Schema validation |
| **Total production deps** | **~84MB** | |
| **Total node_modules (with devDeps)** | **170MB** | Includes eslint, prettier, typescript, stylelint |

### 2.3 No Binary Release

- `os` and `cpu` fields are null -- no platform-specific distribution
- No prebuilt binary on npm or GitHub releases
- The package ships only JavaScript (dist/ directory with `.js` + `.d.ts` files)
- Entry point is `dist/index.js` -- requires Node.js runtime to execute
- The `@anthropic-ai/claude-agent-sdk` dependency bundles platform-specific
  sharp binaries (darwin-arm64, darwin-x64, linux-arm64, linux-x64, linuxmusl-*,
  win32-*), but these are npm optional deps that auto-select per platform

### 2.4 Binary Mode (Experimental)

The factory also supports a `"binary"` backend (`factory.py` line 60-71) that
looks for a precompiled Bun binary in `src/vaultspec_a2a/bin/`. This was marked
experimental (ADR-002 §5.1) and was confirmed BROKEN on Windows in earlier
testing (Bun binary crashes on `session/new`). Not viable for Docker production.

---

## 3. Options for Adding Node.js to Worker Image

### 3.1 Option A: Multi-Stage Copy from Node Image -- RECOMMENDED

Add a Node.js stage specifically for the worker's ACP runtime. Copy only the
Node.js binary and the production node_modules into the worker stage.

```dockerfile
# ── Stage 1a: Frontend build (existing) ─────────────────────────────────
FROM node:22-alpine AS frontend-build
WORKDIR /app/src/ui
COPY src/ui/package*.json ./
RUN npm ci
COPY src/ui/ .
RUN npm run build

# ── Stage 1b: ACP runtime install ──────────────────────────────────────
FROM node:22-alpine AS acp-runtime
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production
# Result: /app/node_modules/ with only production deps (~84MB)
# node binary at /usr/local/bin/node

# ── Stage 2a: Python base (unchanged) ──────────────────────────────────
FROM python:3.13-slim-bookworm AS python-base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# ... existing uv sync ...

# ── Stage 2c: Worker ───────────────────────────────────────────────────
FROM python-base AS worker

# Copy Node.js binary from the node image
COPY --from=node:22-alpine /usr/local/bin/node /usr/local/bin/node

# Copy only production node_modules from acp-runtime stage
COPY --from=acp-runtime /app/node_modules/ /app/node_modules/

ENV VAULTSPEC_PROJECT_ROOT=/app \
    VAULTSPEC_MCP_API_BASE_URL=http://api:8000
```text

**Pros:**

- Minimal: only `node` binary (~100MB) + production node_modules (~84MB)
- `npm ci --production` skips devDependencies (saves ~86MB vs full install)
- Reuses existing `node:22-alpine` as build stage -- no new base image
- Node.js binary from Alpine is statically linked (musl) -- works in
  slim-bookworm if we also copy the required shared libraries, OR we use the
  Debian-based node image instead

**Cons:**

- Adds ~184MB to worker image (node + node_modules)
- Alpine's node binary is musl-linked; slim-bookworm is glibc. Need to either:
  - (a) Use `node:22-bookworm-slim` as the copy source (matches glibc)
  - (b) Copy musl libs alongside the binary
  - (c) Install node from the Debian repos

**Fix for glibc compatibility:**

```dockerfile
# Use Debian-based node image (not Alpine) so the binary is glibc-linked
FROM node:22-slim AS acp-runtime
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production

# In worker stage:
COPY --from=acp-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=acp-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=acp-runtime /app/node_modules/ /app/node_modules/
```text

### 3.2 Option B: Install Node.js in Python Base Image

Install Node.js directly in the python-base stage using Debian packages.

```dockerfile
FROM python:3.13-slim-bookworm AS python-base

# Install Node.js from NodeSource
RUN apt-get update && apt-get install -y curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# OR: install from Debian repos (older version)
# RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*
```text

**Pros:**

- Simple, single-stage approach
- Node.js is a proper Debian package with correct library dependencies
- npm is also available for `npm ci` in the same stage

**Cons:**

- Bloats the shared python-base image (API stage doesn't need Node.js)
- NodeSource adds an external GPG key dependency
- `apt-get update` adds cache invalidation noise
- Violates separation: API image inherits Node.js it doesn't need

### 3.3 Option C: Sidecar Container

Run the ACP subprocess in a separate `node:22-alpine` container. The worker
communicates with it over HTTP/gRPC instead of subprocess stdin/stdout.

```yaml
# docker-compose.prod.yml
services:
  acp-runtime:
    image: node:22-alpine
    volumes:
      - ./node_modules:/app/node_modules
    command: ["node", "/app/node_modules/@zed-industries/claude-agent-acp/dist/index.js"]
    # Worker connects via TCP instead of subprocess
```text

**Pros:**

- Clean separation: Python image stays pure Python
- Node.js image stays pure Node.js
- Independent scaling

**Cons:**

- **BREAKS the ACP protocol.** AcpChatModel communicates via stdin/stdout
  JSON-RPC. The entire protocol assumes subprocess IPC, not network IPC.
  Switching to network would require rewriting AcpChatModel, which contradicts
  ADR-002.
- Added complexity: service discovery, health checks, connection management
- Single-user desktop tool -- not a microservice architecture

**Verdict:** Not viable without rewriting AcpChatModel.

### 3.4 Option D: Precompiled Single Binary (Bun)

Use Bun to compile the ACP entry point into a single executable that doesn't
need Node.js at runtime.

```bash
bun build --compile node_modules/@zed-industries/claude-agent-acp/dist/index.js \
    --outfile claude-agent-acp
```text

**Pros:**

- No Node.js runtime needed in Docker
- Single ~50-100MB binary
- No node_modules in production image

**Cons:**

- Bun compile is experimental and known to break on some packages
- Already confirmed BROKEN on Windows (session/new crash)
- The `@anthropic-ai/claude-agent-sdk` bundles WASM modules (resvg, tree-sitter)
  that may not survive Bun's single-file compilation
- Untested on Linux x64 (Docker target)
- Adds a Bun dependency to the build pipeline

**Verdict:** Too risky for production. Revisit when Bun compile stabilizes.

---

## 4. Extracting from Frontend-Build Stage

**Question:** Can we reuse the existing `frontend-build` stage instead of adding
a new one?

The `frontend-build` stage runs:

```dockerfile
FROM node:22-alpine AS frontend-build
WORKDIR /app/src/ui
COPY src/ui/package*.json ./
RUN npm ci
```text

This installs `src/ui/package.json` deps (React, Vite, Tailwind, etc.) -- NOT
the root `package.json` deps (`@zed-industries/claude-agent-acp`). The ACP
package is in the **root** `package.json`, not the UI package.

**Verdict:** Cannot reuse frontend-build. Need a separate stage that installs
root `package.json` dependencies.

---

## 5. uv + Node.js Docker Coexistence

### 5.1 Separate Build Stages (Recommended)

```dockerfile
# Python deps: uv in python-base
FROM python:3.13-slim-bookworm AS python-base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN uv sync ...

# Node deps: npm in node stage
FROM node:22-slim AS acp-runtime
RUN npm ci --production

# Combine in worker
FROM python-base AS worker
COPY --from=acp-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=acp-runtime /app/node_modules/ /app/node_modules/
```yaml

No conflict: `uv` manages Python, `npm` manages Node.js, each in its own
build stage. The final worker image has both runtimes but only one package
manager ran in its stage.

### 5.2 Single Stage with Both (Not Recommended)

Installing both `uv` and `npm` in the same Dockerfile stage works but creates
unnecessary coupling and a larger base layer.

---

## 6. Image Size Impact

| Component | Size | Notes |
|-----------|------|-------|
| python:3.13-slim-bookworm (base) | ~180MB | |
| uv + Python deps | ~250MB | Depends on package count |
| node binary (from node:22-slim) | ~100MB | glibc-linked Node.js |
| node_modules (production) | ~84MB | @zed-industries + deps |
| **Worker total (with Node)** | ~614MB | vs ~430MB without |
| **Added by Node+ACP** | **~184MB** | +43% image size |

### 6.1 Optimization: Platform-Specific sharp Install

The `@anthropic-ai/claude-agent-sdk` installs sharp binaries for ALL platforms
(darwin, linux, win32, arm64, x64, musl). In Docker, only linux-x64 (or
linuxmusl-x64 for Alpine) is needed. Using `npm ci --production` with
`--os=linux --cpu=x64` or setting npm config to restrict platforms would save
~50MB.

```dockerfile
FROM node:22-slim AS acp-runtime
WORKDIR /app
COPY package.json package-lock.json ./
ENV npm_config_platform=linux npm_config_arch=x64
RUN npm ci --production --ignore-scripts \
    && npm rebuild --platform=linux --arch=x64
```text

This brings node_modules from ~84MB to ~30-40MB (only linux-x64 sharp binaries).

---

## 7. Recommendation

**Option A (multi-stage copy from node:22-slim)** with platform-specific
optimization.

### 7.1 Concrete Dockerfile Changes

```dockerfile
# ── NEW Stage: ACP runtime deps ──────────────────────────────────────────
FROM node:22-slim AS acp-runtime
WORKDIR /app
COPY package.json package-lock.json ./
# Production only + platform-restrict to shrink sharp
RUN npm ci --production --ignore-scripts \
    && npm rebuild --platform=linux --arch=x64

# ── Worker stage: add Node.js ────────────────────────────────────────────
FROM python-base AS worker

# Node.js runtime -- glibc-linked, matches Debian base
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node

# ACP production node_modules
COPY --from=acp-runtime /app/node_modules/ /app/node_modules/

ENV VAULTSPEC_MCP_API_BASE_URL=http://api:8000 \
    VAULTSPEC_PROJECT_ROOT=/app

EXPOSE 8001
CMD ["uv", "run", "uvicorn", "vaultspec_a2a.worker.app:create_worker_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8001"]
```text

### 7.2 Cross-Platform Considerations

- **Docker target is always Linux x64 (or arm64).** The platform-specific sharp
  optimization is safe -- Docker images are platform-bound.
- **The `node` binary from `node:22-slim` (Debian bookworm) is glibc-linked.**
  It runs correctly in `python:3.13-slim-bookworm` (same glibc base).
  Do NOT use `node:22-alpine` -- its musl-linked binary won't work in a
  glibc-based image.
- **Desktop development (Windows/macOS):** Unaffected. Uses the locally-installed
  `node` from PATH + local `node_modules/` from `npm install`.

### 7.3 API Stage: No Changes

The API stage does not execute ACP providers -- it dispatches to the worker.
No Node.js needed in the API image.

### 7.4 Verification

After building, verify inside the worker container:

```bash
docker compose -f docker-compose.prod.yml exec worker node --version
docker compose -f docker-compose.prod.yml exec worker \
    node /app/node_modules/@zed-industries/claude-agent-acp/dist/index.js --help
```text

---

## 8. Secondary Issue: _PROJECT_ROOT Path Traversal

The `VAULTSPEC_PROJECT_ROOT=/app` env override in the existing Dockerfile is
correct for locating `node_modules/`. With Option A, the node_modules are
copied to `/app/node_modules/`, and `_PROJECT_ROOT = Path("/app")` resolves
`_CLAUDE_ACP_JS` to `/app/node_modules/@zed-industries/.../dist/index.js`.

No code changes needed for path resolution -- the env override works.

See `docs/research/2026-03-08-importlib-resources.md` for a more robust
long-term approach using `importlib.resources`.
