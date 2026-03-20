# Control Layer — Execution Plan

**Date**: 2026-03-19
**ADR**: `docs/adrs/038-control-layer-cli-justfile-separation.md`
**Research**: `docs/research/2026-03-19-service-control-layer-research.md`
**Audit**: `docs/audits/2026-03-19-cli-usability-end-to-end-audit.md`

---

## Phase 1 — CLI Purge + Justfile Rewrite

**Goal**: Strip the Python CLI to production-only. Rebuild the Justfile with
dev/prod namespaces.

**Depends on**: Nothing — this is the foundation.

### 1.1 Delete CLI modules

| File | What it contains |
|------|-----------------|
| `cli/_service.py` | service start/stop/kill/status |
| `cli/_test.py` | test unit/smoke/benchmark/prodlike-* |
| `cli/_verify.py` | prod-like Docker verification |
| `cli/_run.py` | run mock/probe |
| `cli/_database.py` | database update/clear/snapshot/restore |
| `cli/_mcp.py` | mcp status/tools/discovery |

### 1.2 Update `cli/__init__.py`

Remove all imports and registrations for deleted modules. Only `team` and
`agent` remain:

```python
cli.add_command(agent)
cli.add_command(team)
```

### 1.3 Add root options

Add `--verbose`, `--debug`, `--version` to match vaultspec-core pattern.
Keep `--show-config` (already exists).

### 1.4 Rename `stop` → `cancel` in `_team.py`

Rename the command, update the API call path if needed.

### 1.5 Add `message` command to `_team.py`

```python
@team.command()
@click.argument("thread_id")
@click.option("--content", required=True)
@click.option("--agent", "agent_id", default=None)
def message(thread_id, content, agent_id):
    body = {"content": content}
    if agent_id:
        body["agent_id"] = agent_id
    resp = client.post(f"/threads/{thread_id}/messages", json=body)
```

### 1.6 Make `--id` positional for all thread commands

Change `@click.option("--id", "thread_id", required=True)` to
`@click.argument("thread_id")` for: status, cancel, delete, archive,
resume, respond, message, watch.

### 1.7 Make `status` require THREAD_ID

Remove the no-arg team-wide behavior. `list` becomes the dashboard.

### 1.8 Enrich `list` to be the team-wide dashboard

`team list` output includes:

- Thread table (id, status, preset, elapsed)
- Summary counts (active, completed, failed)
- Pending permission count

### 1.9 Add `agent show NAME` command

Read-only: loads and displays a preset TOML file.

### 1.10 Remove `agent ask`

It was a confusing alias for `team start --preset <agent-name>`.

### 1.11 Update `_api_client()` fail-fast message

Reference `just dev service start` instead of `vaultspec service start`.

### 1.12 Create `src/vaultspec_a2a/control/` module

Move Python implementations out of CLI:

| Source | Destination | Purpose |
|--------|------------|---------|
| `_database.py` logic | `control/db.py` | migrate, snapshot, restore, clear |
| `_verify.py` logic | `control/verify.py` | prod-like Docker verification |
| New | `control/doctor.py` | Port scanning, config validation, service health |

Each module is callable via `python -m vaultspec_a2a.control.<module>`.

### 1.13 Rewrite Justfile

Full rewrite following the dev/prod namespace pattern. See ADR-038 §2.3 for
complete surface. Key recipes:

```text
dev service start|stop|kill|restart|rebuild|health|logs|probe
dev service db migrate|snapshot|restore|clear
dev code check|fix
dev test unit|live|smoke|tracing|mock|verify|ci|all
dev build package|docker|docker-prod|clean
dev deps install|sync|upgrade|lock
prod team|agent
```

### 1.14 Delete stale CLI test files

Remove tests in `cli/tests/` that test deleted commands (service, test, run,
database, mcp). Keep tests for team and agent.

### 1.15 Update `.env.example`

Consolidate all configurable vars with sensible defaults and comments.

---

## Phase 2 — CLI Observability Enrichment

**Goal**: The production CLI surfaces the rich data the API provides.
**Depends on**: Phase 1 (CLI structure in place).

### 2.1 Enrich `team status THREAD_ID`

Show all fields from `/threads/{id}/state`:

- Thread metadata (id, nickname, preset, elapsed time)
- Status + `pause_cause` if applicable
- Agent list with states
- Plan progress (checkboxes)
- Pending permissions with respond command hint
- Recent activity (last 5 events)

### 2.2 Enrich `team list`

Team-wide dashboard:

- Thread table with columns: id, status, preset, agents, elapsed
- Summary row: N active, N completed, N failed
- Pending permissions count with thread IDs

### 2.3 Enrich `team respond`

After responding, show:

- What was approved/rejected (tool name, action)
- What happens next (which agent resumes)
- Confirmation of the thread state change

### 2.4 Enrich `team message`

After sending, show:

- Confirmation with thread ID
- Routing hint: "Message sent to supervisor" or "Message directed to {agent}"
- Next step hint: `vaultspec team status {id}` or `vaultspec team watch {id}`

### 2.5 Suppress httpx INFO logs

Set `httpx` and `httpcore` loggers to WARNING in the CLI entry point
unless `--verbose` or `--debug` is set.

### 2.6 Add `--json` to status, list, presets, agent list, agent show

Machine-readable output for scripting.

---

## Phase 3 — Thread Lifecycle Integrity

**Goal**: Threads reach terminal states reliably.
**Depends on**: Phase 1 (CLI structure), independent of Phase 2.

### 3.1 Fix `cancelling` → `cancelled` transition (F-18)

Ensure cancel dispatch reaches the worker and the worker confirms the
transition. The gateway must update the DB status to `cancelled` when the
worker acknowledges.

### 3.2 Fix reconciling thread recovery (F-36)

On gateway restart, threads in `running` or `input_required` state from a
previous session must either:

- Be re-dispatched to the worker (if worker is connected), or
- Be marked as `failed` with reason "gateway restarted"

### 3.3 Investigate stuck "running" threads (F-17)

May be caused by:

- Mock presets requiring vidaimock which isn't running
- Worker failing silently on dispatch
- Graph execution hanging without timeout

### 3.4 Investigate tool call stall (F-37)

May be caused by:

- Graph checkpoint rehydration issue on restart
- ACP subprocess not spawning correctly
- Tool execution timeout

---

## Phase 4 — Backend API Fixes

**Goal**: API returns correct data for the CLI to display.
**Depends on**: Phase 1, independent of Phases 2-3.

### 4.1 Fix tool call metadata (F-38)

Tool calls in `/threads/{id}/state` show `name: null, input: null,
tool_kind: null`. The aggregator must populate these from the LangGraph
checkpoint's tool call records.

### 4.2 Fix `worker_connected` false negative (F-23)

Gateway health shows `worker_connected: false` even when the worker is
healthy and dispatching works. The heartbeat detection is passive — add
an active probe on first successful dispatch to flip the connected flag.

### 4.3 Enrich `team respond` API response

The `POST /permissions/{id}/respond` endpoint should return:

- `tool_name`: what tool was approved/rejected
- `action`: what the tool will do
- `thread_status`: new thread status after response
- `next_agent`: which agent will resume

Currently returns only `{accepted: bool, action_status: str}`.

---

## Phase 5 — Service Health Module

**Goal**: `just dev service health` shows a useful dashboard.
**Depends on**: Phase 1 (control module exists).

### 5.1 Implement `control/doctor.py`

Callable via `python -m vaultspec_a2a.control.doctor [target]`.

Checks:

- **Port availability**: `socket.bind()` test for configured ports
- **Service health**: HTTP probe to `/health` on gateway and worker
- **Config validation**: database backend, required API keys, URL derivation
- **Jaeger reachability**: probe `localhost:13133/status`
- **Postgres reachability**: probe configured postgres URL (if backend=postgres)

### 5.2 Dashboard output

```text
just dev service health

  gateway ........ healthy (200, :8000, up 5m)
  worker ......... healthy (200, :8001, connected)
  ui ............. healthy (200, :5173)
  postgres ....... not configured (sqlite mode)
  jaeger ......... healthy (200, :16686)
  vidaimock ...... not running

  5/6 healthy, 1 not running
```

### 5.3 Per-service health

```text
just dev service health gateway

  gateway ........ healthy
  status ......... 200 OK
  port ........... 8000
  pid ............ 12345
  uptime ......... 5m 12s
  worker ......... connected
  circuit breaker  CLOSED
  database ....... sqlite, WAL mode
  threads ........ 3 active, 12 total
```

---

## Phase 6 — `team watch`

**Goal**: Live event streaming with inline permission approval.
**Depends on**: Phases 1-4 (CLI structure + enriched API data).

### 6.1 WebSocket client

Add `websockets` dependency. New `cli/_watch.py` module.

Connect to `ws://127.0.0.1:{port}/ws/threads/{thread_id}` and render
events to the terminal.

### 6.2 Event rendering

```text
[00:00] Thread started. Preset: vaultspec-structured-coder
[00:02] planner: Analyzing task requirements...
[00:05] planner: Plan created (3 steps)
[00:08] PERMISSION REQUIRED: Write greet.py
        [a]llow  [A]llow always  [r]eject
        > a
[00:09] Permission granted. coder resuming.
[00:12] coder: Writing greet.py (47 bytes)
[00:18] Thread completed.
```

### 6.3 Inline permission approval

When a `PermissionRequestEvent` arrives:

1. Print the permission description and options
2. Prompt the user for input (a/A/r)
3. POST to `/permissions/{id}/respond` with the selected option
4. Print confirmation and continue streaming

### 6.4 Graceful disconnect

Ctrl+C cleanly disconnects the WebSocket. The thread continues running.

---

## Execution Order

```text
Phase 1 (CLI Purge + Justfile) ────┐
                                    │
Phase 2 (CLI Observability) ───────┤
                                    ├──→ Phase 6 (team watch)
Phase 3 (Thread Lifecycle) ────────┤
                                    │
Phase 4 (Backend API Fixes) ───────┤
                                    │
Phase 5 (Service Health) ──────────┘
```

Phases 2, 3, 4, 5 are independent and can run in parallel after Phase 1.
Phase 6 depends on all prior phases.

---

## Success Criteria

### Phase 1 complete

- [ ] Python CLI has only `team` and `agent` command groups
- [ ] `team message`, `team cancel`, `agent show` exist
- [ ] Thread ID is positional for all thread commands
- [ ] Every CLI command fail-fasts if gateway is down
- [ ] `just dev service start` starts gateway in foreground with reload
- [ ] `just dev service health` shows service dashboard
- [ ] `just dev test unit` runs unit tests
- [ ] `just prod team list` passes through to Python CLI
- [ ] No `_service.py`, `_test.py`, `_run.py`, `_database.py`, `_mcp.py` in CLI

### Phase 2 complete

- [ ] `team status THREAD_ID` shows agents, plan, permissions, activity
- [ ] `team list` shows thread table + summary + pending permissions
- [ ] `team respond` confirms what was approved and what happens next
- [ ] `--json` works on all applicable commands
- [ ] httpx INFO logs suppressed unless `--verbose`

### Phase 3 complete

- [ ] Cancelled threads reach `cancelled` state and can be archived
- [ ] Threads survive gateway restart (reconciling → resumed or failed)
- [ ] Stuck "running" threads root-caused and fixed

### Phase 4 complete

- [ ] Tool call metadata (name, input, kind) populated in API response
- [ ] `worker_connected` correctly reflects worker state
- [ ] Permission respond endpoint returns tool name and next agent

### Phase 5 complete

- [ ] `just dev service health` probes all services and prints dashboard
- [ ] Per-service detail with port, pid, uptime, connections

### Phase 6 complete

- [ ] `team watch THREAD_ID` streams live events
- [ ] Inline permission approval works (prompt → respond → continue)
- [ ] Ctrl+C cleanly disconnects without stopping the thread
