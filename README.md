# Vaultspec's A2A Agent Orchestration Implementation

This repository contains work-in-progress implementation to be used by vaultspec
to support its custom agentic coding workflow. Vaultspects code can be found at
`Y:/code/vaultspec-worktrees/main`.

## Goal

To implement the library backends required to offload work to custom coding
agents. We're aiming to implement two modes:

- **Subagent mode:** A client app will call on an agent to perform a task. The
  preferred way of handing off non-parallelized, non-concurrent tasks from a
  client, like gemini cli, claude code or antigravity.
- **Team mode:** A coding team that self-orchestrates between the members to
  perform a task. The preferred way of handling parallelized, concurrent tasks.
  For example, a team of coders, supervisors and orchestrators working against
  a set list of ADRs, plans and research knowledge.
- **Implement robust abstractions layers** to support Claude, Gemini and Codex
  agents.

## Frontend Development Workflows

Postgres is the default backend posture for development and production-facing
verification. SQLite remains a fallback convenience mode only and does not
certify production readiness.

Use one of these three workflows depending on what you need:

1. Local split-terminal development
   Run the gateway, worker, and Vite UI in separate terminals:
   - `just dev-gateway`
   - `just dev-worker`
   - `just dev-ui`
   Or run `just dev` to print the recommended commands and start the UI.
2. Frontend-ready Docker stack
   Run `just up` or `just dev-stack` to start `gateway`, `worker`, and `frontend`.
   This is the lowest-friction shared stack for frontend work.
3. Full integration Docker stack
   Run `just up-integration` or `just dev-integration` to add `vidaimock`,
   `mock-seeder`, and Jaeger tracing.

Expected URLs:

- Gateway: `http://localhost:8000`
- UI: `http://localhost:5173`
- Worker health: `http://localhost:8001/health`
- Jaeger UI: `http://localhost:16686` when using the integration or prod stack

## Service Management

`vaultspec service ...` is a local process manager only. It tracks gateway and
worker processes that were started by the CLI itself and does not manage Docker
containers.

Examples:

- `uv run vaultspec service start gateway`
- `uv run vaultspec service start worker`
- `uv run vaultspec service start all`
- `uv run vaultspec service status`
- `uv run vaultspec service stop all`

## Verification

Use these targets to validate the backend surface the frontend depends on:

- `just verify-frontend-backend`
  Runs the gateway, schema, and worker unit tests most relevant to frontend work
  with repo-local pytest temp/cache directories.
- `just smoke-backend`
  Runs the live smoke suite against a real gateway + worker stack.
- `just check-secrets`
  Verifies checked-in compose/env files do not contain obvious live secrets.

## References

Code references and knowledgebase:
