---
tags:
  - '#audit'
  - '#orchestration-capabilities'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `orchestration-capabilities` audit: `provider, execution, trace-review and test capability audit`

## Scope

Full-system capability audit of the vaultspec-a2a engine against the go-forward mission: deliver VaultSpec pipeline documents via a provider-agnostic LangChain/LangGraph orchestration network, supporting both local desktop CLI agents and remote model APIs. Four parallel discovery passes: provider/orchestration architecture, local-CLI vs remote-API execution surfaces, trace-based review and benchmarking, and live test-suite health. Grounded in `2026-07-14-a2a-edge-conformance-adr` (linked in frontmatter) and the deletion manifest reference.

Provenance: authored in a parallel owner session on 2026-07-14 and adopted
into the corpus the same day by owner decision. Retained under its own
`#orchestration-capabilities` feature tag: its subject is the platform's
go-forward capability envelope (dual-mode providers, trace review,
benchmarking) - a successor-plan program distinct from, and wider than,
the `#a2a-edge-conformance` plan whose grounding it complements. Two
claims were refreshed at adoption against W01 outcomes; findings below
are otherwise unaltered.

## Findings

### Orchestration is real LangGraph, not a label

`graph/compiler.py` builds genuine `StateGraph` topologies (`star`, `pipeline`, `pipeline_loop`) with real checkpointers (`langgraph-checkpoint-{sqlite,postgres}`), `RetryPolicy` with a custom retryable-error predicate, and bespoke vault-mounting/phase-gating nodes (ADR-020/023). One fragility: `graph.step_timeout` is an undocumented Pregel attribute pinned to LangGraph internals (`compiler.py:388-391`).

### Provider layer: sound seam, flat abstraction

- `ProviderFactory.create()` (`providers/factory.py:235-459`) is the single dispatch point behind a clean `ProviderFactoryProtocol` DI boundary (`graph/protocols.py:25-40`); the compiler never touches the concrete factory.
- Five hardcoded branches: CLAUDE and GEMINI spawn ACP-speaking CLIs over stdio via the generic `AcpChatModel(BaseChatModel)`; OPENAI and ZHIPU are plain remote `ChatOpenAI` HTTP clients; MOCK is in-process.
- **Remote-API support exists today** - but only for OpenAI/Zhipu. There is zero direct-API path for Claude or Gemini (no `langchain_anthropic`, no `google.generativeai` anywhere in `src/`).
- **Structural defect: `Provider` (`graph/enums.py:126-133`) conflates vendor identity with execution mechanism.** "Claude" means "Claude via ACP subprocess"; there is no config axis for `execution_mode` (CLI vs API) per agent. Fixing this touches `graph/enums.py`, `team/team_config.py` (AgentConfig/WorkerRef/TeamDefaultsConfig + TOML parsing), `factory.py`, and every preset TOML - contained, but it is the load-bearing refactor for the dual-mode mandate.
- Provider-identity leaks inside the generic layer: `AcpChatModel._astream` triggers Gemini token refresh by sniffing the executable basename (`acp_chat_model.py:239-240`); auth handling grows as inline if/elif rather than a pluggable per-provider auth hook. Command resolution hardcodes npm package paths, a Docker absolute path, and a 5-deep Gemini fallback chain (`factory.py:69-171`).
- Adding a provider today: remote-API ~15 lines (mirror Zhipu); ACP-compliant CLI is mechanical (command resolver + enum + MODEL_MAP); a non-ACP CLI requires a whole new `BaseChatModel` subclass - ACP is the only normalized local-agent wire protocol.

### Subprocess lifecycle: deliberate and Windows-aware, thin isolated coverage

`providers/_subprocess.py` handles shell-vs-exec spawn, `CREATE_NEW_PROCESS_GROUP`, `taskkill /T /F` tree-kill, `.cmd` shims, and an intentional private `process._transport` reach-in for cpython#114177. Cancellation sends `session/cancel` with timeout before tree-kill; crash-before-`end_turn` raises rather than silently returning. However `spawn_acp_process`/`kill_process_tree` have no direct unit tests - only transitive coverage through the ACP simulator integration tests - so the Windows kill path and the `use_exec` binary branch could regress silently.

### Trace-based review and benchmarking: vapor

- No judge, evaluator, scorer, rubric, or benchmark harness exists in `src/` - not even a stub, and no governing ADR/research/plan names it. The remembered "previous stab at trace-based review and benchmarking" is not evidenced in this repo.
- What exists: a live WebSocket event-fan-out bus (`streaming/aggregator.py`), OTel export-only telemetry (`telemetry/instrumentation.py`), and LangGraph's opaque internal checkpointing. **There is no persisted, queryable trace store of the project's own** - no event/run table in `database/models.py`; ADR-004 explicitly rejected a custom event log in favor of LangGraph checkpoints.
- The domain event model (`graph/events.py`) is provider-agnostic plain dataclasses with an enforced core-never-imports-api boundary - it would survive redesign; everything above it is a from-scratch build.
- **No code path connects agent runs to `.vault/` document production.** The mission-critical bridge (run -> trace -> review -> vault document) does not exist; the ADR's planned `authoring/` package is not yet built.

### Google-A2A protocol: dead, correctly slated for deletion

`protocols/a2a/` and `protocols/adapter/` are 3-line stubs with zero importers (manifest-verified). "A2A" in this repo's name now means the engine<->dashboard HTTP+SSE edge, not Google's protocol. Live protocol surfaces are `api/` (FastAPI), `protocols/mcp/` (working MCP server, `vaultspec-mcp` entrypoint), and `ipc/` (gateway<->worker wire types).

### Test suite: healthy, contrary to suspicion

- `uv run --no-sync pytest`: **1177 passed, 0 failed, 0 skipped, 144s** (non-service default; `service`-marked Docker-compose tests deselected). Zero skip/xfail markers anywhere.
- Real-I/O discipline largely holds: database tests drive real SQLite; ACP lifecycle is exercised against a genuine subprocess simulator speaking real JSON-RPC. Monkeypatch use is concentrated in env-var/credential-scrub tests (`workspace/tests`, 19 hits) - mostly legitimate, unaudited case-by-case.
- **Coverage cliff in `control/`:** 19 source files, 3 test files. thread_service, permission_service, message_service, team_service, worker_management (including the restart/backoff watchdog), health, diagnostics, snapshot, projection, and circuit_breaker have no dedicated tests.
- Nothing exercises a live provider end-to-end (no live CLI turn, no live API call) - the ADR itself flags one real end-to-end agent turn as unverified.

## Recommendations

- **Introduce an explicit execution-mode axis** (vendor x mechanism) in the provider config model before adding any new provider: split `Provider` into vendor identity plus `execution_mode: cli|api`, thread through AgentConfig/TOML, and add `langchain_anthropic`-style direct-API branches for Claude/Gemini in the factory. This is the single highest-leverage refactor for the stated mandate.
- **Extract a per-provider auth/command-resolution plugin interface** to stop the inline basename-sniffing and if/elif auth growth inside `AcpChatModel` and `factory.py`.
- **Treat trace-review/benchmarking as a greenfield feature**: it needs its own research -> ADR first (persisted run/event store, scoring harness, vault-document bridge). Do not assume salvageable prior work; there is none. The existing event dataclasses and streaming bus are the only reusable substrate.
- **Build the run -> vault-document bridge** (the ADR's `authoring/` package) as the mission's centerpiece; today no code produces VaultSpec documents from orchestration runs.
- **Close the `control/` test gap and add direct unit tests for `_subprocess.py`** spawn/kill on Windows; add at least one gated live end-to-end agent turn (service-marked) so the primary execution path is not permanently unverified.
- **Execute the deletion manifest** (`protocols/a2a/`, `protocols/adapter/`) - adoption-time refresh: the stale `.vault/runtime` path in `control/worker_management.py` was already repointed to the machine-global A2A home in W01 (commit `d41c4c4`), and the same wave's orphan cleanup removed the empty top-level packages (commit `d4f3092`); the two protocol stubs remain for W02. Promote the two matching-but-still-`proposed` ADRs (event-aggregation, OTel) to accepted - noting the conformance ADR supersedes event-aggregation's UI-serving half.
