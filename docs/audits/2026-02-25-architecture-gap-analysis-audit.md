---
date: 2026-02-25
type: audit
feature: architecture-gap-analysis
description: "Systematic audit of all coding-teams research identifying ten critical gaps in server management, code reuse, provider abstraction, and error handling."
related:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-25-002-llm-context-provider-abstraction-adr.md
  - docs/adrs/2026-02-26-003-protocol-bridging-translation-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
---

# Research Gap Analysis Audit

Cross-cutting audit of all 16 research documents in `docs/coding-teams/`.
Evaluates coverage of server management, code reuse boundaries, and stack
gaps introduced by overlapping implementation options.

---

## Findings Summary

| # | Gap | Severity | Blocker? |
| --- | --- | :------: | :------: |
| 1 | No provider adapter interface | CRITICAL | Yes |
| 2 | LLM integration layer missing | CRITICAL | Yes |
| 3 | Process manager underspecified | HIGH | Yes |
| 4 | Event aggregator reliability undefined | HIGH | Yes |
| 5 | Permission flow granularity absent | HIGH | Yes |
| 6 | Error recovery strategy absent | HIGH | Partial |
| 7 | State persistence schema missing | MEDIUM | No |
| 8 | Testing strategy absent | HIGH | Yes |
| 9 | Context window management unaddressed | HIGH | Partial |
| 10 | Merge conflict strategy missing | MEDIUM | No |

---

## Gap 1: No Provider Adapter Interface

**What exists**: Four standalone research docs (Claude, Codex, Gemini, GLM-5)
each covering auth, pricing, and protocol support.

**What is missing**: A unified interface that all four providers implement.
The docs analyse providers in isolation but never converge on a shared
contract. Key omissions:

- No `ProviderAdapter`or`AgentWrapper`protocol definition.
- No standard launch command patterns. For each provider the exact
 `subprocess.Popen(...)`invocation is unspecified.
- Different execution models never reconciled:
  - Claude/Codex: CLI binary wrapping via ACP adapter
  - Gemini: Native A2A support (no wrapping needed)
  - GLM-5: Direct API, custom Python A2A server
- Credential injection mechanism undefined — env vars? config files?
  secret store? Different approach per provider.
- No common`LLMClient`interface over the four different tool-calling
  schemas (Claude, OpenAI, Gemini, Zhipu).

**Impact**: Without a shared adapter contract, each provider integration
becomes a one-off. The orchestrator cannot treat agents generically.

**Resolution**: Define a formal`AgentAdapter`protocol (spawn, send,
poll, tools, shutdown) and a provider-specific implementation spec per
provider including exact subprocess invocation.

---

## Gap 2: LLM Integration Layer Missing

**What exists**: Architecture docs reference "LLM Client (model-specific)"
as a box in diagrams.

**What is missing**: Everything beneath that box:

- Token counting and budget enforcement.
- Prompt engineering strategy (system prompt templates per agent role).
- Context window overflow handling (chunking? summarization? truncation?).
- Tool-calling convention translation across providers.
- Retry and backoff for LLM API errors.
- Model selection logic (which model for which role).
- Multi-turn conversation state management within an agent.
- Cost attribution per agent per task.

**Impact**: LLM integration is the core of agent behaviour. Without
implementation guidance, each agent wrapper will reinvent these patterns
inconsistently.

**Resolution**: Dedicated research doc covering LLM client abstraction,
token budgets, and prompt management patterns.

---

## Gap 3: Process Manager Underspecified

**What exists**: 10-state process machine (lifecycle research), Windows
signal handling notes (CTRL_BREAK_EVENT), health check concept.

**What is missing**: Implementation parameters:

- Health check: which endpoint, timeout thresholds, retry count before
  declaring dead, action on failure (restart? remove? escalate?).
- Port allocation: range, conflict resolution, cleanup when agent crashes
  without releasing port, platform-specific release timing.
- Graceful drain: what DRAINING state actually does, timeout before force
  kill, handling of in-flight A2A requests during drain.
- Zombie prevention: Windows Job Objects mentioned but not specified.
- Cascading failure: what if agent fails while draining? Extend timeout
  or force immediate shutdown?
- Restart: hot reload not discussed. Orchestrator restart while agents
  run has undefined behaviour.

**Contradiction found**: Architecture (scope assessment) marks Process
Manager as Tier 3 complexity and "must build from scratch", yet the core
architecture document assumes subprocess spawning as a solved baseline.
No existing sample demonstrates A2A agent spawning on Windows.

**Impact**: Highest-risk custom component with least specification.

**Resolution**: Detailed Process Manager spec with concrete timeout
values, health check protocol, port allocation algorithm, and Windows
Job Object integration.

---

## Gap 4: Event Aggregator Reliability Undefined

**What exists**: Phase 6 describes data flow: Agent SSE → Orchestrator
Event Aggregator → WebSocket → Browser. Grafana Live pattern referenced.

**What is missing**:

- SSE reconnection strategy (if connection drops, how to resume? event
  IDs? sequence numbers? full replay from snapshot?).
- Event ordering guarantee across multiple concurrent SSE streams.
- Event deduplication if reconnection replays already-seen events.
- Backpressure: what if browser client is slower than agent output?
- At-least-once vs at-most-once delivery semantics.
- Failure mode: if Event Aggregator crashes, all agent events are lost.
  No fallback documented.

**Contradiction found**: Architecture research rejects SSE for
user-facing streaming (Mode A) but uses it internally for agent→
orchestrator. The docs never explain why internal SSE is acceptable
when user-facing SSE was rejected.

**Impact**: Event loss during reconnection could cause stale UI state
with no recovery path.

**Resolution**: Event stream reliability spec: event ID scheme,
reconnection protocol, snapshot-based recovery.

---

## Gap 5: Permission Flow Granularity Absent

**What exists**: PermissionBroker pattern (from ACP), CanUseTool callback
(from Claude Agent SDK), four permission modes documented.

**What is missing**:

- Granularity: per-tool-type? per-individual-call? per-session? per-agent?
- Concurrent requests: 3 agents request permission simultaneously — queue?
  round-robin? parallel modals?
- Timeout: how long before unapproved request times out? Agent blocked?
- Escalation: user denies permission — does agent retry? fail task? ask
  differently?
- Persistence: if user approves "write_file" once, remembered next session?
- Dangerous tool policy: delete_file, run_command — always require
  approval? configurable?
- Provider translation: how orchestrator permission model maps to
  provider-specific tool permission formats.

**Impact**: Permission flow is the primary human-in-the-loop control lever.
Underspecification here means the UI cannot be designed.

**Resolution**: Permission state machine ADR with approval granularity,
timeout, escalation, and persistence rules.

---

## Gap 6: Error Recovery Strategy Absent

**What exists**: Process-level errors documented (exit codes, health check
failures). MCP state transitions to FAILED. Restart policies (always,
on_failure, never).

**What is missing**:

- No error taxonomy: transient vs permanent, agent vs orchestrator vs
  infrastructure.
- No retry logic per error type.
- Agent failure mid-task: retry same agent? spawn new agent? reassign
  task? escalate to user?
- Network errors (A2A SendMessage fails): retry with backoff? fail task?
- Permission denial recovery: agent retry? abort? ask differently?
- Partial completion: if agent produced 3 of 5 artifacts before crash,
  are the 3 kept?

**Impact**: Without error classification, the orchestrator cannot make
intelligent recovery decisions. Every failure becomes a crash.

**Resolution**: Error taxonomy document + decision tree for each error
class.

---

## Gap 7: State Persistence Schema Missing

**What exists**: "SQLite via aiosqlite, WAL mode" chosen. SessionAccumulator
pattern for in-memory aggregation.

**What is missing**:

- No database schema. No tables defined for tasks, sessions, artifacts,
  permissions, cost tracking.
- No specification of what is persistent vs ephemeral.
- No recovery protocol: after orchestrator restart, what state is
  available? Can sessions resume?
- No migration strategy: if schema changes, how to upgrade existing
  databases?
- Postgres mentioned in one doc but never specified for v1 vs v2.
  Migration path from SQLite to Postgres undefined.

**Impact**: Blocks all persistence-dependent features (session resumption,
cost tracking, audit logging).

**Resolution**: Database schema design document with tables, indices,
and migration strategy.

---

## Gap 8: Testing Strategy Absent

**What exists**: CLAUDE.md mandates "mocks are FORBIDDEN, every test must
run live real code against real services."

**What is missing**: The architecture docs contain zero testing guidance.

- How to test Process Manager (simulate agent crashes? real subprocesses?).
- How to test Event Aggregator (multiple SSE streams? real agents?).
- How to test WebSocket multiplexing (browser clients?).
- How to test scoped MCP server (path escape attempts?).
- How to test permission flow (real approval UI?).
- How to run integration tests with real LLM providers (cost? rate limits?).
- CI/CD implications: Windows-specific tests need Windows runners.

**Impact**: The "no mocks" mandate combined with complex infrastructure
(subprocesses, WebSockets, SSE) creates a significant testing challenge
that is completely unaddressed.

**Resolution**: Testing strategy document covering fixtures, real service
requirements, CI/CD setup, and cost management for live LLM tests.

---

## Gap 9: Context Window Management Unaddressed

**What exists**: Phase 6 integration assessment lists "context window
overflow" as open question #5.

**What is missing**: Any solution strategy.

- What happens when an agent exceeds token limits on a large task?
- Summarization? Chunking? Truncation? Tool-result compression?
- Who is responsible: the LLM client layer? the agent executor? the
  orchestrator?
- How does context carryover work between agents (planner → coder)?
- Does the orchestrator manage cumulative token usage per session?

**Impact**: Agents will fail silently on large tasks without mitigation.
This is a v1 blocker for any non-trivial coding task.

**Resolution**: Context management strategy covering overflow handling,
cross-agent context transfer, and token accounting.

---

## Gap 10: Merge Conflict Strategy Missing

**What exists**: Git worktrees chosen for workspace isolation. Per-agent
scoped filesystem access. Workspace Manager component identified.

**What is missing**:

- Merge strategy after coder finishes: fast-forward? rebase? merge commit?
- Conflict handling when two coders modify the same file.
- Worktree cleanup on failure (agent crashes mid-task, worktree dangling).
- Branch naming convention.
- Integration with main branch: when and how is merge decided?
- Stashing/reset behaviour on task cancellation.

**Impact**: Multiple concurrent coders will inevitably produce conflicts.
Without a strategy, the system cannot handle its primary use case.

**Resolution**: Git integration spec covering merge strategy, conflict
resolution policy, and worktree lifecycle.

---

## Contradictions Between Documents

| Doc A | Doc B | Contradiction |
| --- | --- | --- |
| Architecture (rejects SSE Mode A) | Phase 6 (uses SSE internally) | SSE rejected for users but used agent→orchestrator without justification |
| Architecture (Option C hybrid) | Scope Assessment ("nothing in samples") | Subprocess spawning assumed as baseline but noted as novel Tier 3 work |
| Web App Architecture (SQLite only) | Architecture (mentions Postgres) | SQLite for v1 but Postgres mentioned with no migration path |
| Architecture (ephemeral agents) | Scope Assessment (startup overhead) | Cold-start not measured; deferred to v2 without data |

---

## Code Reuse Assessment

### SDK Capabilities (from source audit)

**a2a-python SDK (v0.3.0)** — most complete for orchestration:

-`A2AFastAPIApplication`/`A2ARESTFastAPIApplication`— ready-to-use
  FastAPI server with built-in routing and`.well-known`endpoint.
-`Client`+`ClientFactory`— multi-transport client (JSON-RPC, gRPC,
  HTTP+JSON). Handles SendMessage, GetTask, streaming.
-`RequestHandler`abstraction — dispatches get_task, cancel_task,
  message_send to your implementation.
-`AgentExecutor`— abstract base you implement with business logic.
-`EventQueue`— bounded async queue with typed events.
-`TaskModel`+`PushNotificationConfigModel`— SQLAlchemy models with
  built-in support for PostgreSQL, MySQL, SQLite.
-`PydanticType`/`PydanticListType`— SQLAlchemy custom types for
  Pydantic serialization. Database layer is already built.

- Transports: JSON-RPC, gRPC, HTTP+JSON all supported client and server.
- Auth: JWT signing, API keys.
- Telemetry: OpenTelemetry tracing built in.

**mcp-python-sdk** — complete for tool layer:

-`MCPServer`with`@server.tool()`, `@server.resource()`,
  `@server.prompt()`decorators — high-level ergonomic API.
-`Server`(low-level) — callback-based handler dispatch.
-`Client`+`ClientSession`— unified client for all transports.

- Transports: stdio, SSE (with resumability), HTTP streamable, WebSocket.
- Auth: OAuth2, Bearer tokens via middleware.
-`Context`dataclass for request-scoped dependency injection.
- In-memory transport for testing.

**acp-python-sdk** — narrow but useful patterns:

-`Agent`and`Client`Protocol interfaces — method signatures for
  initialize, new_session, prompt, session_update, request_permission.
-`AgentSideConnection`/`ClientSideConnection`— JSON-RPC dispatch.

- Helper builders for content blocks (text, image, audio, resources)
  and message updates (tool calls, thoughts, plans).
- **Stdio only** — no HTTP server. Designed for local subprocess comms.

### SDK Composition

| Composition | Feasible? | Notes |
| --- | :---: | --- |
| A2A + MCP | Yes | A2A agent embeds MCP client for tools. Samples exist. |
| MCP + ACP | Maybe | Both use JSON-RPC but different schemas. Bridge needed. |
| A2A + ACP | Unlikely | Different problem domains. A2A is more general. |
| All three | No | ACP is IDE-specific (Zed). A2A+MCP is the right pair. |

**Conflicts**: A2A and MCP both provide HTTP servers — need careful
routing if combined in same process. Message schemas are incompatible
across all three. Auth approaches differ (ACP: none, MCP: OAuth,
A2A: API keys/JWT).

### Directly Reusable (high confidence)

- **a2a-python**: A2AFastAPIApplication, RequestHandler, AgentExecutor,
  EventQueue, Agent Card serving, Client/ClientFactory, SQLAlchemy
  task models, OpenTelemetry tracing.
- **mcp-python-sdk**: MCPServer with decorators, tool/resource/prompt
  registration, Client/ClientSession, stdio + SSE transports.
- **FastAPI**: HTTP + WebSocket + REST + static files + lifespan.
- **xterm.js**: Terminal emulation (via xterm-svelte wrapper).
- **CodeMirror 6**: Read-only code viewer.
- **SQLAlchemy** (via a2a-python): Task persistence already modelled.

### Requires Adaptation (medium confidence)

- **ACP SessionAccumulator**: Port accumulation pattern to A2A event
  types (use the concept, not the ACP transport).
- **ACP PermissionBroker**: Port permission request pattern. ACP's
 `request_permission()` maps well to our approval flow concept.
- **ACP content helpers**: Builders for text/image/audio blocks could
  inform our A2A Part construction utilities.
- **xterm-svelte**: Integration with SvelteKit + WebSocket stdout relay.

### Must Build Custom (no existing library)

- Process Manager (Windows subprocess lifecycle)
- Event Aggregator (multi-SSE fan-in, WebSocket fan-out)
- Provider Adapter layer (per-provider CLI/API wrappers)
- LLM Client abstraction (tool-calling translation across providers)
- Permission Manager (runtime policy engine)
- Scoped MCP Tool Server (per-agent filesystem isolation + path validation)
- WebSocket Connection Manager (channel multiplexing)
- Workspace Manager (git worktree lifecycle)
- Message Router (user→correct agent routing in team context)
- Agent Registry (id→port→health mapping, stale entry cleanup)

---

## Recommendations

### Before Implementation Starts

1. **Provider Adapter ADR** — Define the shared interface all four
   providers implement, including exact subprocess launch commands.
2. **LLM Client Research** — Token counting, prompt templates, context
   overflow strategy.
3. **Process Manager Spec** — Concrete timeout values, health check
   protocol, Windows Job Objects.
4. **Event Reliability Spec** — Event IDs, reconnection protocol,
   delivery guarantees.
5. **Permission State Machine** — Granularity, timeout, escalation,
   persistence rules.

### During Implementation

1. **Error Taxonomy** — Classify errors, define recovery per class.
2. **Database Schema** — Tables, indices, migration strategy.
3. **Testing Strategy** — Fixtures, real service setup, CI/CD.
4. **Git Integration Spec** — Merge strategy, conflict resolution.
5. **Context Management** — Overflow handling, cross-agent transfer.
