---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S33'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Audit the agent/tool provisioning mechanism with live evidence: how a session is constructed, the subprocess spawned, the chat-model adapter bound, and tools actually surfaced to the agent (ACP session wiring, subprocess management, chat-model adapter, provider factory), recording what is proven versus presumed

## Scope

- `src/vaultspec_a2a/providers/_acp_session.py`
- `src/vaultspec_a2a/providers/_subprocess.py`
- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/factory.py`

## Description

- Trace the provisioning chain from source, epicenter files read whole. Provider selection: the graph compiler calls `ProviderFactory.create(provider, model, agent_config, workspace_root)`; for CLAUDE/GEMINI it resolves the ACP CLI command through `_classify_acp_command` / `_classify_gemini_command` (ordered fallback chains — explicit executable, docker-bundled node entry, project-local node_modules, system PATH, `.bin` shim, bare name — each tagged with a bounded `runtime_authority`) and returns an `AcpChatModel` carrying the command, a scrubbed env with ONLY the provider token re-injected, and the agent config.
- Subprocess: `AcpChatModel._astream` rebuilds env via `resolve_env_vars` (secrets scrubbed), re-injects the provider token, strips `ANTHROPIC_API_KEY` when an OAuth token is present (ADR-002 flat-rate billing guard), then calls `spawn_acp_process` — Windows uses `create_subprocess_shell` + `CREATE_NEW_PROCESS_GROUP` for `.cmd` shims and atomic `taskkill /T /F` reaping, `use_exec`/POSIX use `create_subprocess_exec`.
- Session handshake: `initialize_session` declares `clientCapabilities.fs.{readTextFile,writeTextFile}` and `terminal`, each GATED by `agent_config.capabilities` (all False when no agent config); `setup_session` issues `session/new` (or `session/load` when resuming) with `cwd` + `mcpServers`; `setup_prompt` sends `session/prompt`; chunks stream back.
- Tool surface: the local `rpc_map` in `_astream` handles the agent-callable RPCs — `session/request_permission`, `fs/read_text_file`, `fs/write_text_file`, and five `terminal/*` methods. `fs/write_text_file -> on_fs_write_text_file` is the SINGLE write chokepoint (the R2 target). Additional tools reach the agent only via `mcp_servers` passed to `session/new` — and `mcp_servers` is a constructor Field defaulting to an empty list that NO call site populates (`ProviderFactory` never sets it; `graph/compiler.py` never passes it).
- Capture live evidence with a handshake-only probe: resolve the real command via the factory classifier, spawn the actual `claude-agent-acp` subprocess through the production `spawn_acp_process`, complete the ACP `initialize` handshake, and reap — stopping before `session/prompt` so the agent performs no work.

## Outcome

The provisioning mechanism is coherent and, at the handshake layer, PROVEN LIVE. The probe spawned the real `node .../claude-agent-acp/dist/index.js` subprocess (PID 60864) and received a valid `initialize` result: `agentCapabilities` reports `loadSession: true`, `sessionCapabilities` {fork, list, resume}, `promptCapabilities` {image, embeddedContext}, and — decisively for the conformance program — `mcpCapabilities: {http: true, sse: true}`, confirming the agent accepts the MCP-server bridge that ADR R4's authoring tools will ride. `authMethods` advertises only `claude-login` (terminal auth), so no token was present in the probe env. The subprocess was reaped cleanly via `kill_process_tree`.

Salvage verdict: the ACP provisioning stack (factory command resolution, env scrub, subprocess spawn/kill, and the initialize/session/prompt RPC ladder) is well-structured, real, and negotiates live with the installed agent binary. It is sound to build the R2 deny-policy and R4 tool-bridge on.

## Notes

Proven vs presumed ledger:

- PROVEN LIVE: factory command resolution; production `spawn_acp_process` against the real binary; ACP `initialize` protocol negotiation and capability exchange; `mcpCapabilities.http/sse` support (R4 bridge is protocol-viable). Separately, S02 proved a full turn through `MockChatModel` — but that path does NOT touch the ACP subprocess.
- PRESUMED (not exercised live here): a full ACP agent turn against real Claude — `session/new` + `session/prompt` + a tool-call round-trip through the `fs`/`terminal` RPCs. This is gated by authentication: the machine's `claude` CLI needs an active login / `CLAUDE_CODE_OAUTH_TOKEN`, absent in the probe env (authMethods returned `claude-login`). Completing it would incur real API usage and potential agent file/terminal actions, so it was deliberately not run in an audit step.
- FINDINGS handed to successor plans (out of W01 scope, recorded not fixed): (1) `src/vaultspec_a2a/providers/probes/` is source-DELETED — only `__pycache__` bytecode remains (`certifying`, `claude`, `gemini`, `openai`, `_http`, `_protocol`, plus a `tests/` cache), and `_subprocess.py`'s docstring still references the gone `probes/_protocol`; a stale orphan of the same class S06 removed. (2) R4 is confirmed GREENFIELD: no `mcp_servers` is wired anywhere, so no authoring/document tools are surfaced to spawned CLIs today. (3) R2 is confirmed SINGLE-POINT: every agent file write funnels through `on_fs_write_text_file` in the one `rpc_map`.

This step made no source changes (audit only), so it has no code commit; the step record commit is deferred to the post-release vault batch.
