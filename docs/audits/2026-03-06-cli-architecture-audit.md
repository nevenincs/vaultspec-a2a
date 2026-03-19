# CLI Architecture Audit — 2026-03-06

Status: **In progress**

---

## Current CLI (implemented)

```bash
vaultspec serve            [--host] [--port] [--log-level]
vaultspec worker           [--port] [--log-level]
vaultspec test             [TARGET] [-- PYTEST_ARGS]
vaultspec migrate upgrade  [--target]
vaultspec migrate stamp    [--target]
vaultspec config
vaultspec preps            [SCENARIO]
vaultspec eval smoke
vaultspec eval nightly
```text

## Target CLI (approved)

```bash
vaultspec --show-config

vaultspec test                              # defaults to: test unit
vaultspec test unit        [PATH] [-- PYTEST_ARGS]
vaultspec test smoke
vaultspec test benchmark   [smoke | nightly] # bare = run all

vaultspec run mock         [solo | pipeline | approval | autonomous]  # bare = run all
vaultspec run probe        [claude | gemini | openai | zhipu]

vaultspec team start       --preset NAME [--name NICKNAME]
vaultspec team status      --id ID
vaultspec team resume      --id ID [--message TEXT]
vaultspec team stop        --id ID
vaultspec team delete      --id ID
vaultspec team archive     --id ID
vaultspec team list        [running | completed | archived]

vaultspec agent ask        --agent NAME --message TEXT
vaultspec agent list

vaultspec service start    [backend | worker | DOCKER_SERVICE]  # bare = backend + worker
vaultspec service stop     [backend | worker | DOCKER_SERVICE]
vaultspec service kill     [backend | worker | DOCKER_SERVICE]
vaultspec service delete   DOCKER_SERVICE  # Docker only, errors on backend/worker

vaultspec database clear   --yes
vaultspec database update  [--target REVISION]
vaultspec database snapshot
vaultspec database snapshot list
vaultspec database restore --name SNAPSHOT  # refuses if service is running
```text

---

## Notes

### Why the rename

| Current | Target | Reason |
|---------|--------|--------|
| `test [TARGET]` | `test unit` | Bare `test` was a grab-bag. `unit` is precise. |
| `eval smoke/nightly` | `test benchmark` | "eval" is meaningless. These grade agent quality against datasets. |
| `preps [SCENARIO]` | `run mock` | "preps" sounds like setup. These run real orchestration against mock LLM tapes. |
| (python -m probes) | `run probe` | Provider connectivity checks had no CLI surface. Now they do. |
| (no CLI) | `team *` | Thread/team lifecycle had no CLI surface — only REST and MCP. |
| (no CLI) | `agent *` | Single-agent execution had no surface. Complements `team` for one-shot interactions. |
| `serve` / `worker` | `service start` | "serve" and "worker" were two unrelated top-level commands for the same concept: starting processes. Unified under `service`. |
| `migrate upgrade/stamp` | `database update/clear/snapshot/restore` | "migrate" is developer jargon. "database" is the actual domain. Migration is just one operation (update). Snapshot/restore are new. |
| `config` | `--show-config` | Not a domain. A diagnostic flag. Prints resolved settings and exits. |

### Domain split

- **`test`** — pass/fail verification. "Is the code right? Is the quality acceptable?"
- **`run`** — human observation. "Does this work when I point it at things?"
- **`agent`** — single-agent execution. "Ask one agent something without team orchestration."
- **`team`** — lifecycle management. "Start, stop, resume, list, clean up agent teams."
- **`service`** — process management. "Start, stop, kill backend/worker/docker services."
- **`database`** — data management. "Update schema, clear data, snapshot, restore."

### Resolved decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Bare `vaultspec test` default? | Defaults to `test unit`. |
| 2 | Bare `test benchmark` scope? | Runs all suites (smoke + nightly). |
| 3 | `run mock` with no arg? | Runs all scenarios sequentially. |
| 4 | `run probe` extra options? | No. Just provider arg. Power users use `python -m` for `--backend`/`--debug`. |
| 5 | `service start` with no arg? | Launches both backend + worker. |
| 6 | `database clear` confirmation? | Requires `--yes` flag. |
| 7 | `database restore` while running? | Checks for active service, refuses with error. |
| 8 | `service delete` scope? | Docker only. Errors if target is backend/worker. |
| 9 | `team delete` / `team archive` timing? | Implement now. Full backend work in this sprint. |
| 10 | `team resume` for completed/failed? | Yes. `--message` flag for new input. Not allowed for archived threads. |
| 11 | `config` placement? | Global flag `--show-config` on root command. Not a subcommand. |

### Backend work required

| CLI command | Backend gap |
|-------------|-------------|
| `agent ask` | New lightweight execution path: load agent config, wire provider + tools, single-node graph with checkpointer, stream response. No supervisor/routing. |
| `agent list` | Glob agent TOML presets from `core/presets/agents/`. Trivial. |
| `team delete` | New DELETE endpoint + CRUD function to remove thread + artifacts. |
| `team archive` | New `ThreadStatus.ARCHIVED` enum value + endpoint to set it. |
| `team list [status]` | Add status query param to `GET /threads`. |
| `team resume --message` | Allow `send_message` on completed/failed threads (re-dispatch to worker). Block on archived. |
| `database clear` | New CRUD function to truncate tables. |
| `database snapshot` | File copy of SQLite DB with timestamp suffix. |
| `database snapshot list` | Glob for `*.snapshot.*` files in DB directory. |
| `database restore` | Copy snapshot back to active DB path. Check for running process. |
| `service stop/kill` | PID tracking or signal handling for native processes. Docker compose stop/kill for containers. |
| `service delete` | Wrap `docker compose down --rmi` for target service. |

### Design principles

1. Command names understandable without docs.
2. Sub-commands complete a sentence: "I want to test _**" / "I want to run**_."
3. Defaults do the most common thing.
4. Max 3 segments for the common case.
5. `test` = verification. `run` = execution. `agent` = single-agent. `team` = multi-agent lifecycle. `service` = process control. `database` = data management.
