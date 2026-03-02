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
| [coding-teams-research](research/2026-02-25-coding-teams-research.md) | 30 | Foundational A2A/ACP/MCP landscape and team patterns |
| [coding-teams-architecture](research/2026-02-25-coding-teams-architecture-research.md) | 35 | Control modes, topology, two-interface design |
| [web-app-architecture](research/2026-02-25-web-app-architecture-research.md) | 30 | FastAPI vs Starlette, SvelteKit, state management |
| [scope-assessment](audits/2026-02-25-scope-assessment-audit.md) | 35 | Component tiers, dependency graph, risk register |
| [integration-assessment](audits/2026-02-25-phase6-integration-audit.md) | 45 | Data flow, tech boundaries, MVP scope, tech stack |
| [gap-analysis-audit](audits/2026-02-25-architecture-gap-analysis-audit.md) | 50 | 10 critical gaps: provider adapter, LLM layer, process mgr, events |

## Agent Providers

Per-provider analysis of authentication, protocol support, and billing.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [claude](research/2026-02-25-claude-agent-support-research.md) | 25 | Auth, ACP/A2A, permissions, subscription bypass |
| [codex](research/2026-02-25-codex-agent-support-research.md) | 25 | MCP support, multi-agent mode, Windows issues |
| [gemini](research/2026-02-25-gemini-agent-support-research.md) | 25 | OAuth, native ACP, experimental A2A config |
| [glm-5](research/2026-02-25-glm5-agent-support-research.md) | 20 | API-only, OpenAI-compatible REST, Coding Plan |

## Protocols

Protocol compliance analysis and bridging strategies.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [protocol-foundations](research/2026-02-25-phase1-protocol-foundations-research.md) | 45 | A2A SSE mapping, ACP web host, WebSocket design |
| [mcp-a2a-compliance](research/2026-02-25-mcp-tasks-a2a-compliance-research.md) | 40 | Async tasks, state mapping, stable MCP recommendation |

## Control Surface

UI rendering, terminal emulation, and dashboard research.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [ui-dashboard-survey](research/2026-02-25-agent-ui-terminal-dashboard-research.md) | 20 | Agent UIs, terminal-in-browser, dashboards |
| [rendering](research/2026-02-25-control-surface-rendering-research.md) | 25 | xterm.js, syntax highlighting, streaming markdown |

## Process & Operations

Agent lifecycle management, monitoring, and observability.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [process-lifecycle](research/2026-02-25-agent-process-lifecycle-research.md) | 30 | Windows subprocess, graceful shutdown, state machine |
| [monitoring](research/2026-02-25-coding-teams-monitoring-research.md) | 25 | AgentOps, Langfuse, telemetry model, dashboard UX |

## ADRs

_No architecture decision records yet._ Documents above will be distilled into
ADRs in `adr/` as decisions mature past the 60+ threshold.

## Plans

Plans live separately in [`../plans/`](../plans/) to keep research and
roadmaps distinct.

| File | Maturity | Summary |
| ------ | :--------: | --------- |
| [control-surface-research-plan](../plans/2026-25-02-control-surface-research-plan.md) | 30 | Eight-phase research roadmap |

## Maturity Scale

| Range | Meaning |
| ------- | --------- |
| 0–20 | Raw notes, unorganized |
| 20–40 | Structured research, no decisions |
| 40–60 | Analyzed with recommendations |
| 60–80 | Draft ADR candidate |
| 80–100 | Approved architecture decision |
