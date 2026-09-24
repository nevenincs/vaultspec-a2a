---
tags:
  - '#research'
  - '#architecture-review'
date: '2026-09-24'
modified: '2026-09-24'
body_schema: 'body-v2'
body_hash: 'sha256:765971a820ac5e3a35ae80b2888673e4ba2fa2948ff253fb588280c405f024b8'
related:
  - "[[2026-07-15-graph-agent-framework-harness-adr]]"
  - "[[2026-07-15-agent-harness-provisioning-adr]]"
  - "[[2026-07-19-a2a-edge-conformance-adr]]"
---

# `architecture-review` research: `modern agent orchestration standards baseline`

What do current agent-orchestration frameworks and protocols treat as baseline for graph execution, session and run management, context, tool permissions, structured logging, provider-binary acquisition, and agent-to-agent interoperability, and where does that baseline bear on this repository's accepted decisions? Gathered on 2026-09-24 against the locked stack (`langgraph@1.2.11`, `langgraph-checkpoint@4.2.0`, `langchain-core@1.6.3`, `fastapi@0.141.1`, `@agentclientprotocol/claude-agent-acp@0.59.0`). The evidence shows the durable-execution core already matches LangGraph and Agent Server practice closely; the distance from the baseline is concentrated in multitask policy, stream resumption, permission posture on external CLI lanes, provider-binary identity, and durable event logging. A2A protocol capability is an open option the accepted record set explicitly declined; the findings frame it without deciding it. Findings against this codebase live in `2026-09-24-architecture-review-audit`.

## Findings

### LangGraph 1.x execution semantics

Durable execution resumes a thread by re-invoking with `None` input on the same `thread_id`; LangGraph re-runs only the tasks of the interrupted super-step and keeps pending writes from branches that completed, so replaying the original input is not a resume. Nodes re-execute from the top on resume, so any side effect before `interrupt()` must be idempotent, and the documented pattern splits an idempotent commit node from a pure interrupt node. Durability is selectable per invocation (`exit`, `async`, `sync`); `async` is the default. Graph guards belong in edges or `Command(goto=...)` routing, and `Command`-returning nodes declare `destinations` so topology introspection is correct. Run-scoped dependencies belong in Runtime context (`context_schema`, `Runtime[Context]`) rather than checkpointed state or closures. `recursion_limit` with `RemainingSteps` lets a graph end gracefully before the hard limit. As of 1.2 nodes accept `timeout=` (including idle timeouts refreshed by heartbeat), `error_handler=`, `retry_policy=` with jitter, and `cache_policy=`, and `DeltaChannel` (beta) stores channel deltas instead of full values per checkpoint. Checkpoint serde supports a strict msgpack allowlist and `EncryptedSerializer`. `astream_events` v2 does not honour the `langsmith:nostream` tag; `stream_mode="messages"` does.

The per-agent loop baseline in `langchain@1.x` is `create_agent` plus middleware: `HumanInTheLoopMiddleware` pauses after the model emits tool calls and before they execute, offering approve, edit, or reject per call; `SummarizationMiddleware` triggers on a fraction of the model profile's window and persists a real summary; `ModelCallLimitMiddleware` and `ToolCallLimitMiddleware` bound loops. Deep Agents triggers summarization at 85% and offloads original messages to a filesystem.

### Agent Server and the Agent Protocol

LangGraph's Agent Server (the Agent Protocol reference) models assistants, threads, and runs, where one thread holds many runs. A second input on a busy thread is governed by an explicit `multitask_strategy` of `reject`, `interrupt`, `rollback`, or `enqueue` (default `enqueue`). Streams are resumable: `stream_resumable` plus `Last-Event-ID`, and the v2 event-stream protocol replays from a sequence. Threads support TTL-based cleanup, checkpoint forking, and time travel. The Postgres saver is sized by a pool (`LANGGRAPH_POSTGRES_POOL_MAX_SIZE`) rather than a single connection. Agent Server also exposes an A2A endpoint per assistant (`/a2a/{assistant_id}`, JSON-RPC only) that maps `contextId` to a thread and each turn to a new task.

### A2A protocol

The Linux Foundation A2A specification (v1.0, with v0.3 method names still common) defines an Agent Card at `/.well-known/agent-card.json` advertising skills, capabilities, security schemes, and supported interfaces; JSON-RPC 2.0, gRPC, and HTTP+JSON bindings; `SendMessage`, `SendStreamingMessage`, `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask`, and push-notification configuration; task states submitted, working, input-required, auth-required, completed, canceled, failed, and rejected; Text, Data, and File parts; `contextId` grouping tasks; and client-supplied `messageId` deduplication. `SubscribeToTask` must return the current Task as its first event. The reference Python SDK `a2a-sdk@1.1.5` mounts on FastAPI (`add_a2a_routes_to_fastapi`, `create_agent_card_routes`, `create_jsonrpc_routes`, `create_rest_routes`) and separates a transport-facing `RequestHandler` from an in-process `AgentExecutor`; it pulls `protobuf`, `google-api-core`, and `json-rpc`. For a service whose execution runs out of process, the fit is a custom `RequestHandler` over existing control services, not `DefaultRequestHandler`.

The option space for this repository is: keep the dashboard loopback edge as the only surface (the accepted position); add an optional A2A adapter extra over the existing control services; or expose A2A as a first-class edge. The ADR must settle whether `contextId` maps to a thread holding many runs (requiring a multi-run thread model) or to a single run, how input-required answers route to the typed respond verbs, where the Agent Card's skills come from under the served-profile rule, and how workspace and actor tokens travel (an A2A extension or metadata).

### Coding-agent CLI harnesses

Claude Agent SDK: permission modes `default`, `acceptEdits`, `plan`, `dontAsk`, and `bypassPermissions`; tools matched by `allowedTools` are auto-approved and never reach `canUseTool`; `disallowedTools` is the hard removal; `settingSources` selects which user, project, and local settings load (the adapter under review defaults to all three); sessions support `resume`, `fork_session`, and `continue`, and persist as JSONL transcripts under the configuration directory, whose format is documented as internal. Project settings files have been an attack vector (CVE-2025-59536).

Codex app-server: threads and turns with `thread/start`, `thread/resume`, `thread/fork`, `turn/steer`, and `turn/interrupt`; approval policies (`untrusted`, `on-request`, `never`) and sandbox modes (`read-only`, `workspace-write`, `danger-full-access`); rollout JSONL persisted unless `ephemeral`; integrators may pin binary versions. OpenAI's CI authentication guidance requires writing a refreshed `auth.json` back after a run and not sharing one file across concurrent jobs; credentials may live in the OS keyring (`cli_auth_credentials_store=auto`).

Agent Client Protocol: `session/request_permission` offers `allow_once`, `allow_always`, `reject_once`, and `reject_always`, and remembering an "always" decision is the client's job; client capabilities (`fs`, `terminal`) are hints the agent may ignore, not a sandbox. The ACP agent registry distributes agents with exact npm versions or binary archives carrying sha256 digests, launched from client-managed absolute install directories.

### Observability and structured logs

OpenTelemetry GenAI semantic conventions (development status) define `invoke_agent`, chat, and `execute_tool` spans and `gen_ai.usage.*` attributes, including cache read and cache write input tokens, with content capture opt-in. The OpenAI Agents SDK groups spans under traces carrying `trace_id`, `group_id`, and metadata, with sensitive-data inclusion opt-in. Claude Code and Codex both persist an append-only, per-line-flushed JSONL record per session, and `codex exec --json` streams typed `thread.*`, `turn.*`, and `item.*` events. Common structured-logging practice is one JSON object per line with a schema version, RFC 3339 UTC timestamps, a monotonic durable sequence, correlation ids, and redaction before serialization.

### Supply chain and agency

OWASP's LLM Top 10 (2025) names excessive agency (LLM06: complete mediation, least privilege), prompt injection (LLM01: private data plus untrusted content plus an outbound channel), and supply chain (LLM03). npm supports registry signature verification (`npm audit signatures`). Python's `shutil.which` searches the current directory first on Windows unless `NoDefaultCurrentDirectoryInExePath` is set, and `cmd.exe` argument quoting is the BatBadBut class (CVE-2024-24576).

### What was not investigated

No live provider turn was run (no provider credential is available to this environment); Windows-specific behaviour was reasoned from code and documentation, not executed; the dashboard repository's side of the edge contract was not read.

## Sources

- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langgraph/fault-tolerance
- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://docs.langchain.com/oss/python/langgraph/checkpointers
- https://docs.langchain.com/oss/python/langgraph/streaming
- https://docs.langchain.com/oss/python/langchain/middleware/built-in
- https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- https://docs.langchain.com/oss/python/deepagents/context-engineering
- https://docs.langchain.com/langsmith/double-texting
- https://docs.langchain.com/langsmith/streaming
- https://docs.langchain.com/langsmith/configure-ttl
- https://docs.langchain.com/langsmith/server-a2a
- https://docs.langchain.com/langsmith/env-var-self-hosted
- https://github.com/langchain-ai/agent-protocol
- https://a2a-protocol.org/latest/specification/
- https://github.com/a2aproject/a2a-python
- https://pypi.org/project/a2a-sdk/
- https://code.claude.com/docs/en/agent-sdk/permissions
- https://code.claude.com/docs/en/agent-sdk/sessions
- https://code.claude.com/docs/en/sessions
- https://research.checkpoint.com/2026/rce-and-api-token-exfiltration-through-claude-code-project-files-cve-2025-59536/
- https://developers.openai.com/codex/app-server
- https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
- https://learn.chatgpt.com/docs/auth
- https://learn.chatgpt.com/docs/auth/ci-cd-auth
- https://github.com/openai/codex/issues/15502
- https://agentclientprotocol.com/protocol/tool-calls
- https://agentclientprotocol.com/protocol/terminals
- https://github.com/agentclientprotocol/registry/blob/main/FORMAT.md
- https://zed.dev/docs/ai/external-agents
- https://opentelemetry.io/docs/specs/semconv/gen-ai/
- https://github.com/open-telemetry/semantic-conventions-genai
- https://openai.github.io/openai-agents-python/tracing/
- https://genai.owasp.org/llmrisk/llm01-prompt-injection/
- https://genai.owasp.org/llmrisk/llm062025-excessive-agency/
- https://genai.owasp.org/llmrisk/llm032025-supply-chain/
- https://docs.npmjs.com/verifying-registry-signatures/
- https://docs.python.org/3/library/shutil.html
- https://discuss.python.org/t/is-python-affected-by-cve-2024-24576/50740
- https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/
- https://www.uvicorn.org/settings/
- https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- https://modelcontextprotocol.io/specification/2025-06-18/server/tools
