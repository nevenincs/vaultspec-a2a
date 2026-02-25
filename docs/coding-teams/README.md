---
name: "Coding Teams Documentation Index"
date: 2026-25-02
type: index
summary: "Master index for all coding teams research, organized by theme with maturity scores to track progression toward architecture decision records."
maturity: 40
---

# Coding Teams Documentation

Research and analysis supporting the A2A agent orchestration control surface.
All documents here are **supporting research** — none have reached ADR status
yet. Maturity scores indicate how close each document is to informing a formal
architecture decision.

## Architecture & Scope

System-level design, component inventory, and integration analysis.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [coding-teams-research](architecture/2026-25-02-coding-teams-research.md) | 30 | Foundational A2A/ACP/MCP landscape and team patterns |
| [coding-teams-architecture](architecture/2026-25-02-coding-teams-architecture-research.md) | 35 | Control modes, topology, two-interface design |
| [web-app-architecture](architecture/2026-25-02-web-app-architecture-research.md) | 30 | FastAPI vs Starlette, SvelteKit, state management |
| [scope-assessment](architecture/2026-25-02-scope-assessment.md) | 35 | Component tiers, dependency graph, risk register |
| [integration-assessment](architecture/2026-25-02-phase6-integration-assessment.md) | 45 | Data flow, tech boundaries, MVP scope, tech stack |

## Agent Providers

Per-provider analysis of authentication, protocol support, and billing.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [claude](agents/2026-25-02-claude-agent-support.md) | 25 | Auth, ACP/A2A, permissions, subscription bypass |
| [codex](agents/2026-25-02-codex-agent-support.md) | 25 | MCP support, multi-agent mode, Windows issues |
| [gemini](agents/2026-25-02-gemini-agent-support.md) | 25 | OAuth, native ACP, experimental A2A config |
| [glm-5](agents/2026-25-02-glm5-agent-support.md) | 20 | API-only, OpenAI-compatible REST, Coding Plan |

## Protocols

Protocol compliance analysis and bridging strategies.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [protocol-foundations](protocols/2026-25-02-phase1-protocol-foundations.md) | 45 | A2A SSE mapping, ACP web host, WebSocket design |
| [mcp-a2a-compliance](protocols/2026-25-02-mcp-tasks-a2a-compliance-research.md) | 40 | Async tasks, state mapping, stable MCP recommendation |

## Control Surface

UI rendering, terminal emulation, and dashboard research.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [research-plan](control-surface/2026-25-02-control-surface-research-plan.md) | 30 | Eight-phase research roadmap |
| [ui-dashboard-survey](control-surface/2026-25-02-agent-ui-terminal-dashboard-research.md) | 20 | Agent UIs, terminal-in-browser, dashboards |
| [rendering](control-surface/2026-25-02-control-surface-rendering-research.md) | 25 | xterm.js, syntax highlighting, streaming markdown |

## Process & Operations

Agent lifecycle management, monitoring, and observability.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [process-lifecycle](process/2026-25-02-agent-process-lifecycle-research.md) | 30 | Windows subprocess, graceful shutdown, state machine |
| [monitoring](process/2026-25-02-coding-teams-monitoring-research.md) | 25 | AgentOps, Langfuse, telemetry model, dashboard UX |

## ADRs

_No architecture decision records yet._ Documents above will be distilled into
ADRs in `../adr/` as decisions mature past the 60+ threshold.

## Maturity Scale

| Range | Meaning |
| ------- | --------- |
| 0–20 | Raw notes, unorganized |
| 20–40 | Structured research, no decisions |
| 40–60 | Analyzed with recommendations |
| 60–80 | Draft ADR candidate |
| 80–100 | Approved architecture decision |
