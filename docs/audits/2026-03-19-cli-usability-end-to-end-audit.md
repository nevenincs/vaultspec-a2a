# CLI Usability & End-to-End Audit — 2026-03-19

**Auditor**: Claude Opus 4.6 (hands-on, black-box approach)
**Method**: Assume CLI is fully operable; exercise every command against live gateway+worker+Jaeger; record findings as-encountered.
**Environment**: Windows 11, Python 3.13, bash shell, Docker Desktop, no WSL.

---

## Executive Summary

The CLI is **feature-rich and well-structured** with 7 command groups, 23+ subcommands, 12 team presets, 12 agent presets, 4 mock scenarios, and 11 MCP tools. **However, getting the system running from scratch is unreasonably difficult.** A developer attempting to start a team against the gateway and worker will hit 5-8 blocking issues before seeing their first successful thread. Once running, the core workflow (start → status → stop → delete) works, mock scenarios execute, and Jaeger traces appear. The system is architecturally sound but operationally fragile.

**Verdict**: The system *can* run a team against the gateway and worker — but only after significant manual troubleshooting. Not production-ready for a new developer.

---

## Section 1: Service Startup Experience (CRITICAL)

### F-01 [CRIT] Default config points to Postgres but no Postgres is running

- **What happened**: `vaultspec --show-config` reveals `database_backend=postgres`, `database_url=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/vaultspec`. No Postgres service is running locally.
- **Impact**: `vaultspec service start gateway` spawns a process that **immediately crashes** with no error output to the user. The CLI reports `gateway: started local process pid=XXXX on http://0.0.0.0:8000` — success message for a dead process.
- **Fix required**: Either default to SQLite when Postgres is unreachable, or fail loudly at `service start` time.

### F-02 [CRIT] `service start` does not propagate environment variables to subprocess

- **What happened**: Setting `VAULTSPEC_DATABASE_BACKEND=sqlite` before `vaultspec service start gateway` had no effect — the subprocess read from `.env`/defaults, not the caller's env.
- **Impact**: The only way to override config for `service start` is modifying `.env` file or config files. The CLI's own `service start` command is unusable for ad-hoc config overrides.
- **Workaround used**: Had to run `uv run uvicorn vaultspec_a2a.api.app:create_app --factory ...` directly.

### F-03 [HIGH] `service start` returns success for dead processes

- **What happened**: Gateway start returned `gateway: started local process pid=74244 on http://0.0.0.0:8000`. The process was already dead by the time the message appeared.
- **Root cause**: No post-spawn health check. The CLI fires-and-forgets the subprocess.
- **Expected**: The CLI should wait 2-3 seconds and probe the health endpoint before declaring success, or at minimum warn that the process is not yet confirmed healthy.

### F-04 [HIGH] PID tracking does not survive manual uvicorn starts

- **What happened**: `vaultspec service status` reported `stopped` for both gateway and worker even though both were running on ports 8090/8091.
- **Root cause**: PID tracking only knows about processes started via `vaultspec service start`. Manually started uvicorn instances are invisible.
- **Impact**: `service kill` cannot stop manually-started services. Port conflicts arise silently.

### F-05 [HIGH] Port 8000 held by unknown process, `service kill` cannot clean up

- **What happened**: After gateway crashed, port 8000 was held by PID 6540 (not our process). `taskkill` returned "Access denied". Had to use alternate ports 8090/8091.
- **Impact**: Default ports unusable. No guidance from CLI on how to resolve port conflicts.
- **Expected**: `service start` should detect port-in-use *before* spawning, and suggest `--port` override.

### F-06 [MED] Worker URL not configurable through `service start`

- **What happened**: Gateway hardcodes `worker_url=http://127.0.0.1:8001`. When worker runs on 8091, gateway cannot find it. `VAULTSPEC_WORKER_URL` must be set before the gateway process starts.
- **Impact**: The `service start` command has `--port` but no `--worker-url` or `--worker-port` option. Multi-port setups require manual uvicorn.

### F-07 [MED] No stderr/stdout capture visible for `service start` failures

- **What happened**: When gateway crashed on startup (Postgres connection failure), the user sees only `gateway: started local process pid=XXXX`. No error output, no log path, no hint at the failure.
- **Expected**: Stream at least the first 5 lines of stderr, or point to a log file.

### What I had to do to get it running (narrative)

1. Ran `vaultspec service start gateway` — got success message, but process was dead.
2. Ran `curl localhost:8000/health` — empty reply. Checked `service status` — `pid-stale`.
3. Realized config defaulted to Postgres. Set `VAULTSPEC_DATABASE_BACKEND=sqlite`.
4. Tried `service start` again — same crash, env vars not propagated.
5. Resorted to direct `uv run uvicorn ...` with explicit env exports.
6. Hit `[Errno 13] port 8000 forbidden` — stale process holding the port.
7. Tried `service kill gateway` — reported `not-tracked`.
8. Used `netstat -ano` to find PID 6540 on port 8000. `taskkill` denied.
9. Changed to port 8090 — gateway started.
10. Started worker on 8091 — success.
11. But gateway showed `worker_connected: false` — it was looking for worker on 8001.
12. Killed everything, restarted with `VAULTSPEC_WORKER_URL=http://127.0.0.1:8091`.
13. Both services up, but gateway *still* shows `worker_connected: false` — uses passive heartbeat detection, not active probe.
14. Despite `worker_connected: false`, thread creation and dispatch worked.

**Total time from first command to working system: ~15 minutes of troubleshooting.**
**Expected for a usable CLI: <30 seconds.**

---

## Section 2: CLI Command Coverage & UX

### F-08 [GOOD] Command structure is logical and well-organized

```text
vaultspec
├── agent (ask, list)
├── database (clear, restore, snapshot, update)
├── mcp (discovery, status, tools)
├── run (mock, probe)
├── service (kill, start, status, stop)
├── team (archive, delete, list, overview, presets, respond, resume, start, status, stop)
└── test (benchmark, claude-docker, gemini-docker, prodlike-docker, prodlike-provider, smoke, unit)
```text
- 7 command groups, 23+ subcommands
- `-h` works on every level (not just `--help`)
- `--show-config` at top level is excellent for debugging

### F-09 [GOOD] Team presets are rich and well-named
```yaml
12 team presets: mock-autonomous, mock-failure-tool, mock-human-in-loop,
mock-invalid, mock-looping, mock-success-multi, mock-success-single,
vaultspec-adaptive-coder, vaultspec-continuous-audit, vaultspec-iterative-coder,
vaultspec-solo-coder, vaultspec-structured-coder
```text
- Mock presets cover key scenarios (success, failure, looping, human-in-loop)
- Real presets cover solo through multi-agent team topologies

### F-10 [GOOD] 4 mock scenarios available via `run mock`
```text
solo_coder, pipeline_team, plan_approval, autonomous
```text
- `solo_coder` ran end-to-end successfully, showing ACP subprocess spawn/terminate and LangGraph output.
- `plan_approval` correctly demonstrated GraphInterrupt on plan approval flow.

### F-11 [MED] `team status` output is minimal — just "Status: running"
- **What happened**: `vaultspec team status --id <thread>` returns only `Status: running`.
- **Expected**: Show agent names, current phase, elapsed time, message count, plan progress.
- **The API endpoint `/api/threads/{id}/state` returns much richer data** — the CLI discards it.

### F-12 [MED] `team overview` shows "No agents registered" even with active threads
- **What happened**: 3 threads running, `team overview` says "No agents registered. Active threads: 0".
- **Root cause**: Overview reads from a different state source than thread list. The agent registration is transient (heartbeat-based) and doesn't persist.
- **Impact**: The overview command is essentially useless for monitoring — it shows less than `team list`.

### F-13 [MED] `agent ask` is fire-and-forget with no output streaming
- **What happened**: `vaultspec agent ask --agent mock-coder-success --message "What is 2+2?"` created a thread and immediately returned `Thread <id> created`. No response, no streaming, no way to see the answer.
- **Expected**: Either stream the response inline (like a chat), or at minimum tell the user how to retrieve the result (`vaultspec team status --id <id>`).

### F-14 [LOW] `team start` output doesn't suggest next steps
- **Output**: `Thread 9912ba... (audit-test-1) started.`
- **Expected**: `Thread 9912ba... (audit-test-1) started. Use 'vaultspec team status --id 9912ba...' to monitor.`

### F-15 [LOW] INFO-level HTTP request logging bleeds into user output
- **What happened**: Every CLI command prints `INFO HTTP Request: GET http://...` before the actual output.
- **Expected**: CLI should suppress httpx logs at INFO level; only show at `--verbose` or `--debug`.

### F-16 [LOW] `team start` `--id` is not a positional argument
- **UX friction**: Must type `--id 9912ba8280ab4cd890fa474bf50ec761` instead of `vaultspec team status 9912ba...`.
- **Similarly**: `team stop --id`, `team delete --id`, `team archive --id`, `team resume --id` all require the flag.

---

## Section 3: Thread Lifecycle Findings

### F-17 [HIGH] Threads started via `team start` are stuck in "running" indefinitely
- **What happened**: Started `mock-success-single` and `mock-success-multi` presets via `team start`. Both remained "running" after 5+ minutes. The mock scenarios via `run mock` complete successfully, but `team start` dispatches to the worker via gateway and the worker seems unable to complete mock threads.
- **Root cause (suspected)**: The mock presets may require a mock API server (`vidaimock`) that isn't running, or the worker is failing silently.
- **Impact**: The primary user-facing workflow (`team start` → monitor → complete) does not produce a completed thread.

### F-18 [HIGH] Thread stuck in "cancelling" state — cannot be archived
- **What happened**: Cancelled a running thread. It moved to `cancelling` but never reached `cancelled`. `team archive` returned `409: Cannot archive thread in 'cancelling' state`.
- **Workaround**: `team delete` works on threads in any state (good).
- **Impact**: The cancel → archive workflow is broken. Users must use `delete` to clean up.

### F-19 [MED] `team overview` active thread count disagrees with `team list`
- `team list` shows 3 threads (2 running, 1 cancelling)
- `team overview` shows "Active threads: 0"
- These should be consistent.

---

## Section 4: Observability & Tracing

### F-20 [GOOD] Jaeger traces appear for both gateway and worker
- **Services registered**: `vaultspec-a2a` (gateway), `vaultspec-worker`
- **Trace depth**: Up to 13 spans per trace, showing full request lifecycle.
- **Jaeger UI**: Accessible at http://localhost:16686

### F-21 [GOOD] Health endpoints are informative
- Gateway `/health` returns rich JSON: service name, worker connection status, circuit breaker state, database backend, SQLite fallback details, WAL mode, repair backlog, checkpoint status.
- Worker `/health` returns database backend info.

### F-22 [MED] Jaeger traces only appear when OTEL env vars are explicitly set
- Must set `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_INSECURE` manually.
- `service start` doesn't accept tracing configuration flags.
- **Expected**: `--enable-tracing` flag or auto-detect running Jaeger.

### F-23 [MED] `worker_connected: false` even when worker is healthy
- Gateway health shows `worker_connected: false` despite the worker being up and responding to health checks, and despite successful thread dispatch.
- The gateway uses passive heartbeat detection. If the worker hasn't sent a heartbeat yet, it appears disconnected even when functional.
- **Impact**: Monitoring dashboards would show a false-negative "worker down" state.

---

## Section 5: Mock Scenario Results

### F-24 [GOOD] `run mock solo_coder` completes successfully
- ACP subprocess spawns and terminates cleanly.
- LangGraph produces actual AI output (palindrome function).
- Full graph execution with mount and agent update events.

### F-25 [MED] `run mock plan_approval` errors with "Subprocess closed"
```text
ERROR:asyncio:Future exception was never retrieved
future: <Future finished exception=RuntimeError('Subprocess closed')>
RuntimeError: Subprocess closed
```text
- The scenario correctly hits the GraphInterrupt for plan approval.
- But after resuming with `approved=True`, the ACP subprocess terminates prematurely.
- The error is logged but doesn't crash the CLI cleanly — it prints to stderr and exits.

### F-25b [MED] `run mock pipeline_team` also errors with "Subprocess closed"
- Same pattern as plan_approval: hits GraphInterrupt on a tool permission request (mkdir), then `RuntimeError: Subprocess closed` after resume.
- Confirms this is a **systemic issue** with interrupt resume in all multi-step scenarios, not a one-off.

### F-26 [HIGH] `run mock autonomous` fails with TimeoutError
- The autonomous scenario (star topology, auto-approve) **crashes with `TimeoutError`** from `langgraph.pregel._runner.atick`.
- The ACP subprocess spawns but the graph stream times out waiting for a response.
- Exit code 1 — the only mock scenario that actually fails (others exit 0 despite errors).
- Stack: `asyncio.wait_for` → `TimeoutError` inside `langgraph.pregel.main.astream`.
- **Impact**: The most complex mock scenario (3 agents, autonomous) is completely broken.
- **Expected**: Mock scenarios should complete quickly with deterministic mock responses, not time out.

---

## Section 6: API Surface

### F-27 [GOOD] OpenAPI spec is served at `/docs` and `/openapi.json`
- 17 API paths covering full CRUD + lifecycle + internal IPC.
- Swagger UI accessible for interactive testing.

### F-28 [GOOD] REST API is well-designed
- Proper HTTP status codes (201 Created, 204 No Content, 409 Conflict).
- Clean path structure (`/api/threads/{id}/state`, `/api/threads/{id}/cancel`).
- Internal endpoints separated (`/internal/events`, `/internal/heartbeat`).

---

## Section 7: MCP Server Surface

### F-29 [GOOD] 11 MCP tools cover the full orchestration workflow
```text
archive_thread, cancel_thread, delete_thread, get_pending_permissions,
get_team_status, get_thread_status, list_team_presets, list_threads,
respond_to_permission, send_message, start_thread
```text

### F-30 [GOOD] MCP discovery info is well-formatted
- Both stdio and streamable-http transport documented.
- Environment variable guidance included.

---

## Section 8: Configuration & Defaults

### F-31 [HIGH] Default database backend is Postgres — should be SQLite for local dev
- `database_backend=postgres` in resolved config with no `.env` override.
- This means every fresh clone will fail to start the gateway.
- **Expected**: Default to SQLite for local development; Postgres opt-in.

### F-32 [MED] `--show-config` exposes API keys in cleartext
- Output shows partial keys: `openai_api_key=****hb0A`, `zhipu_api_key=****MZrf`, etc.
- The masking is partial (last 4 chars visible) — better than nothing but inconsistent.
- `langsmith_api_key=****abbb` is masked. `anthropic_api_key=` shows empty. `figma_access_token` is not in config output (good).

### F-33 [LOW] No `.env.example` or `.env.template` in the repo root
- New developers must guess which env vars to set.
- `.env.integration.example` exists but only covers OTEL vars.

---

## Section 9: Real-Work Execution (Live LLM + Real Tools)

This section covers testing with **real LLM providers** (Claude via ACP), **real filesystem tools**, and **real permission gates**. No mocks. The goal: can a team run a real coding task end-to-end?

### Startup Narrative (what it actually took)

Getting the system running for real work required:

1. **Kill the Postgres-defaulting gateway** (crashed silently twice)
2. **Set 8 environment variables** manually: `VAULTSPEC_DATABASE_BACKEND`, `VAULTSPEC_CHECKPOINT_BACKEND`, `VAULTSPEC_DATABASE_URL`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `VAULTSPEC_AUTO_SPAWN_WORKER`, `VAULTSPEC_WORKER_URL`, `VAULTSPEC_PORT`
3. **Use raw `uv run uvicorn` commands** because `service start` doesn't propagate env vars
4. **Find alternative ports** (8090/8091) because 8000/8001 were held by zombie processes
5. **Kill and restart both services** to align the worker URL config
6. **Total setup time**: ~15 minutes of troubleshooting before the first thread could be dispatched

### F-34 [CRIT] Permission response system is fundamentally broken
- **What happened**: Supervised threads (`auto_approve=false`) correctly generate permission requests visible in `/threads/{id}/state` (e.g., `"Approval required for tool 'Write greet.py'"`). The CLI `team respond` command sends the response. The API returns HTTP 200.
- **But**: Every response returns `{"accepted": false, "action_status": "rejected_invalid_state"}`.
- **Root cause** (`endpoints.py:1361-1372`): `get_permission_request(db, request_id)` returns `None` because permission requests are **surfaced from LangGraph checkpoint interrupt state** but **never persisted to the database** as `PermissionRequest` rows. The endpoint requires DB persistence to resolve.
- **Impact**: **No supervised workflow can ever proceed.** Every permission request is unresolvable. The human-in-the-loop flow is completely non-functional.
- **Also**: The CLI prints "Permission <id>: rejected." — the user thinks *they* rejected the permission, when the system rejected their approval. No distinction in the UX.

### F-35 [CRIT] Permission request IDs regenerate on every state query
- **What happened**: The permission `request_id` changes on every poll (same prefix, different suffix). First query: `c98c30c11fbb8e91a0be3ec86fe58700`. Next query: `c98c30c11fbb8e912ec07c029759b512`.
- **Impact**: Even if the DB persistence bug (F-34) were fixed, there's a race condition — by the time the user copies the request_id and runs `team respond`, the ID may have already changed.
- **Expected**: Permission request IDs must be stable and deterministic.

### F-36 [HIGH] `reconciling` state for threads from previous gateway session
- **What happened**: Threads created before a gateway restart enter `reconciling` state and never recover. The new gateway cannot resume them.
- **Impact**: Any gateway restart loses all in-flight work. Threads must be deleted and restarted.

### F-37 [HIGH] Autonomous solo-coder tool calls stall at `pending`
- **What happened**: The autonomous solo-coder thread (`auto_approve=true`) generated 3 tool calls and stalled. The agent said "Let me fetch the tools" but the tools remained `pending` with no name, no input, no progress. Worker trace stopped at 36 spans.
- **Note**: Despite this stall on the `real-audit-hello` thread, the **earlier thread from the pre-restart session** (which was picked up on restart) DID complete and write files (F-39). So the stall may be timing-dependent or related to graph checkpoint rehydration.

### F-38 [HIGH] Tool call metadata missing in API response
- **What happened**: `tool_calls` array in thread state shows `{"name": null, "status": "pending", "input": null, "tool_kind": null}` for all entries.
- **Impact**: The user cannot see *what* tool the agent wants to execute, making it impossible to monitor or debug tool execution.
- **Expected**: Tool name, input, and kind should be populated from the LangGraph checkpoint state.

### F-39 [GOOD] Autonomous solo-coder DID create real files on disk
- **What happened**: The `real-solo-timestamp` thread (created in the pre-restart session, reconciled after restart) successfully wrote two files:
  - `workspaces/audit-test/hello.py`: `def hello() -> str: return "Hello, world!"`
  - `workspaces/audit-test/test_hello.py`: Valid pytest test with `from hello import hello`
- **Significance**: This proves the full pipeline works end-to-end: LLM → tool call → file write → real artifact on disk. The ACP subprocess was invoked, Claude generated code, and the tool executed.
- **Caveats**: Import is not package-qualified; only 1 test case instead of the multi-case request.

### F-40 [GOOD] Jaeger traces capture full execution pipeline
- Both `vaultspec-a2a` and `vaultspec-worker` services report traces.
- Worker traces include: `POST /dispatch`, `executor.compile_graph`, `executor.ingest`, `aggregator.broadcast`, `aggregator.flush_chunks` — full observability of the execution pipeline.
- Up to 269 spans in a single trace, showing detailed LangGraph graph execution.
- **Improvement**: Gateway-to-worker dispatch is not correlated as a single trace — they appear as separate traces.

### F-41 [GOOD] Permission request surfacing works (display path)
- The `/threads/{id}/state` endpoint correctly surfaces permission requests from LangGraph interrupts.
- Permission descriptions are human-readable (e.g., "Approval required for tool 'Write Y:/code/.../greet.py'")
- Three options offered: `allow_always`, `allow`, `reject` — correct per the design.
- **The display path works; the response path is broken** (F-34).

### F-42 [MED] CLI `team respond` shows "rejected" even on HTTP 200
- **What happened**: `vaultspec team respond --request-id X --option allow_always` returns `Permission X: rejected.`
- **Root cause**: The CLI checks the `accepted` field in the response, which is always `false` due to F-34. But even when the system rejects the approval, the CLI should distinguish "your approval was rejected by the system" from "you rejected the permission".
- **Expected**: Different messages for user-initiated rejection vs system rejection. E.g., "Permission X: system error — rejected_invalid_state. The permission request may have expired or the thread is in an invalid state."

### F-43 [MED] `team overview` shows 0 agents even during active execution
- Even while the worker is actively processing threads with real LLM calls, `team overview` reports "No agents registered. Active threads: 0."
- Agent registration is transient and heartbeat-based. It doesn't persist across gateway restarts and doesn't correlate with actual thread execution.

---

## Severity Summary (Updated)

| Severity | Count | Key Issues |
|----------|-------|------------|
| CRITICAL | 4     | F-01 (Postgres default), F-02 (env not propagated), F-34 (permissions broken), F-35 (request ID cycling) |
| HIGH     | 9     | F-03, F-04, F-05, F-17, F-18, F-26, F-31, F-36, F-37, F-38 |
| MEDIUM   | 11    | F-06, F-07, F-11, F-12, F-13, F-19, F-22, F-23, F-25, F-25b, F-42, F-43 |
| LOW      | 4     | F-14, F-15, F-16, F-33 |
| GOOD     | 11    | F-08, F-09, F-10, F-20, F-21, F-24, F-27, F-28, F-29, F-30, F-39, F-40, F-41 |

---

## Recommended Priority Fixes

### P0 — System is Non-Functional Without These
1. **Fix permission request DB persistence** (F-34, F-35) — Permission requests from LangGraph interrupts must be written to the DB so the REST endpoint can resolve them. This is the #1 blocker for any supervised workflow.
2. **Change default `database_backend` to `sqlite`** (F-01, F-31) — single-line fix, unblocks all new developers from instant startup failures.
3. **`service start` must propagate caller's env vars** (F-02) — or at minimum read from `.env` with overrides. Without this, the CLI's own service management is unusable for non-default configs.

### P1 — Severely Degraded Without These
4. **Fix tool call metadata in thread state** (F-38) — tool name, input, and kind must be populated. Without this, monitoring is blind.
5. **Fix "cancelling" → "cancelled" transition** (F-18) — threads stuck in cancelling can't be archived.
6. **Fix reconciling thread recovery** (F-36) — threads must survive gateway restarts.
7. **`service start` post-spawn health check** (F-03) — wait 3s, probe `/health`, warn if dead. Currently reports success for dead processes.
8. **Port-in-use detection before spawn** (F-05) — check before starting, suggest `--port` override.

### P2 — Usability & Polish
9. **Enrich `team status` output** (F-11) — show agents, phase, elapsed time.
10. **Fix CLI `team respond` error messages** (F-42) — distinguish user rejection from system error.
11. **`agent ask` should stream or wait for response** (F-13) — fire-and-forget is not useful.
12. **Suppress httpx INFO logs in CLI** (F-15) — set `httpx` logger to WARNING.
13. **Fix `team overview` agent registration** (F-43, F-12) — correlate with actual thread execution.

---

## Appendix: Proof of End-to-End Execution

Despite the issues above, the system DID demonstrate real end-to-end execution:

```yaml
Thread: real-solo-timestamp (3ec1e4a1...)
Preset: vaultspec-solo-coder (auto_approve=true)
Provider: Claude via ACP subprocess
Result: Files created on disk:
  - workspaces/audit-test/hello.py (47 bytes)
  - workspaces/audit-test/test_hello.py (114 bytes)
Jaeger: 120+ spans captured across gateway and worker
```text

The core pipeline (gateway → worker → LangGraph → ACP → Claude → tool execution → file write) is functional. The failures are in the **control plane** (permissions, state management, service lifecycle), not the **execution plane**.

---

## Appendix B: Honest Operator Assessment

This section is a first-person account of the auditor's experience. It is not a wishlist. It is a factual record of what happened, how long it took, what was expected at each step, and what the CLI should have done differently. The purpose is to establish the gap between the CLI's advertised surface and its actual operational readiness.

### Time Budget

| Phase | Time Spent | Expected |
|-------|-----------|----------|
| Understanding CLI structure (`--help` at all levels) | 2 min | 2 min (this was fine) |
| First attempt to start gateway (`service start gateway`) | 30 sec | 30 sec |
| Diagnosing why gateway died silently | 4 min | 0 sec (should not happen) |
| Discovering Postgres default via `--show-config` | 1 min | 0 sec (should warn on startup) |
| Attempting env var override with `service start` | 2 min | 0 sec (should just work) |
| Falling back to raw `uv run uvicorn` | 1 min | Should not be necessary |
| Discovering port 8000 is held, cannot be freed | 3 min | 0 sec (should detect before spawn) |
| Switching to ports 8090/8091 | 1 min | Should not be necessary |
| Realizing gateway can't find worker on non-default port | 2 min | 0 sec (should be coordinated) |
| Killing everything and restarting with aligned config | 2 min | Should not be necessary |
| **Total setup before first successful thread** | **~18 min** | **< 30 sec** |

### What I Expected vs What Happened

**Expected**: Run `vaultspec service start all`, see both gateway and worker come up, run `vaultspec team start --preset vaultspec-solo-coder --message "..."`, see work happen.

**What actually happened**: A 12-step manual process involving 8 environment variables, 2 raw uvicorn commands, 3 port overrides, and 2 full-stack restarts before dispatching the first thread. The CLI's own `service start` command was never usable.

### What the CLI Should Have Done (Minimum Viable Operator Experience)

These are not feature requests. These are the minimum behaviors a CLI must have to be considered operational.

#### 1. The CLI must start its own backend or tell you it can't

When I ran `vaultspec team start --preset vaultspec-solo-coder --message "..."`, the CLI should have:
- Detected that no gateway is running on the configured port
- Either auto-started it (like `vaultspec-mcp` auto-starts the gateway), or printed: `Error: Gateway not running at http://127.0.0.1:8000. Start it with 'vaultspec service start gateway' or set VAULTSPEC_PORT.`

Instead: raw httpx `RemoteProtocolError` traceback. 76 lines of Python stack trace. No guidance.

#### 2. `service start` must validate preconditions before reporting success

When I ran `vaultspec service start gateway`, the CLI said `gateway: started local process pid=74244 on http://0.0.0.0:8000`. The process was already dead. The CLI must:
- Check that the port is free before spawning
- Wait 2-3 seconds and probe the health endpoint
- If the process dies, show the last 10 lines of stderr
- Never print a success message for a dead process

Instead: a confident success message for a process that lived for <100ms. This is worse than no message at all — it actively misleads the operator.

#### 3. Configuration failures must surface before they become silent crashes

The default `database_backend=postgres` targets a Postgres instance that doesn't exist. This is the very first thing that kills the gateway on startup. The CLI should:
- On `service start`, test the database connection before spawning the subprocess
- On failure, print: `Error: Cannot connect to PostgreSQL at 127.0.0.1:5432. Set VAULTSPEC_DATABASE_BACKEND=sqlite for local development.`

Instead: process spawns, crashes silently, user sees "started" message, then discovers the process is dead only by running `curl` manually.

#### 4. `service status` must detect running services regardless of how they were started

I started services with `uv run uvicorn ...` directly (because `service start` was broken). `vaultspec service status` said `stopped` for both. The CLI tracks PIDs internally but doesn't probe the actual ports. The CLI should:
- Probe the configured health endpoints (`http://host:port/health`) on every `service status` call
- Report "running (externally managed)" if a service responds but wasn't started by the CLI

Instead: "stopped" for services that are actively handling requests.

#### 5. Error messages must be actionable, not raw tracebacks

When `vaultspec team presets` hit a dead gateway, the output was a 76-line Python traceback ending in `httpx.RemoteProtocolError: Server disconnected without sending a response.` The CLI should:
- Catch `httpx.ConnectError` and `RemoteProtocolError` at the top level
- Print: `Error: Cannot reach gateway at http://127.0.0.1:8000. Is the service running?`

Instead: the full stack trace of httpx → httpcore → Python socket internals. This is what a developer sees when they `import httpx` in a script and forget error handling. A CLI must not expose this.

#### 6. Permission responses must work or fail with a clear explanation

When I ran `vaultspec team respond --request-id X --option allow_always`, the API returned 200 OK and the CLI printed "Permission X: rejected." Three things are wrong:
- The API returns 200 for a failed operation (should be 409 or 422)
- The CLI says "rejected" when the user chose "allow" — the system rejected the user's approval, not the other way around
- No explanation of why — just "rejected"

The CLI should print: `Error: Permission request X could not be resolved (rejected_invalid_state). The request may have expired or the thread state is inconsistent. Current pending permission: Y (use this ID instead).`

Instead: a single misleading word.

#### 7. The supervised workflow must actually work

The supervised (human-in-the-loop) workflow is the primary differentiator of this system. It is the reason for the permission system, the `team respond` command, the `auto_approve` flag, and half the API surface. It does not work. Permission requests are generated by LangGraph interrupts but never persisted to the database. The REST endpoint that resolves them queries the database. There is no code path that connects the two. This is not a minor bug — it means the entire supervised workflow was never tested end-to-end with a real permission response.

#### 8. The CLI should explain its own architecture

Running `vaultspec --help` shows 7 command groups. None of them explain:
- What a "gateway" is and why it needs a separate "worker"
- That both must be running before any team command works
- That the gateway dispatches to the worker and they communicate via internal HTTP
- What the MCP server is and how it relates to the gateway
- That Jaeger needs to be running for tracing

A `vaultspec doctor` or `vaultspec status` command that checks all preconditions (database, gateway, worker, Jaeger, ports, config) and reports a single health dashboard would eliminate 90% of the setup pain.

### What Does Work

To be fair, the things that work, work well:
- The CLI command structure is logical and discoverable. `--help` at every level is correct.
- `--show-config` is excellent — it showed me the Postgres default immediately.
- Team presets are rich and well-named. 12 presets covering solo through multi-agent.
- The OpenAPI spec at `/docs` is served and accurate.
- Health endpoints return rich, informative JSON.
- Jaeger traces capture the full execution pipeline with high fidelity.
- The core execution pipeline (LLM → tool call → file write) actually works.
- `team list`, `team stop`, `team delete` all work correctly.

### Final Verdict

**The execution plane is sound. The control plane is not operational.**

The system can compile a LangGraph, spawn an ACP subprocess, invoke Claude, execute tool calls, and write files to disk. That is impressive engineering. But the operator cannot:
- Start services without manual intervention (CRITICAL)
- Approve permission requests (CRITICAL — the supervised workflow is dead)
- Monitor tool execution (tool metadata is empty)
- Recover from gateway restarts (threads enter irrecoverable state)
- Trust the CLI's own status messages (success for dead processes, "rejected" for approvals)

This is a **research prototype with a production-quality execution engine wrapped in a pre-alpha control plane**. The gap between the two is the gap between "it works on my machine with the right env vars" and "an operator can run it."
