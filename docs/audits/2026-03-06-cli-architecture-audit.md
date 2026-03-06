# CLI Architecture Audit — 2026-03-06

Status: **In progress**

---

## Current CLI (implemented)

```
vaultspec serve            [--host] [--port] [--log-level]
vaultspec worker           [--port] [--log-level]
vaultspec test             [TARGET] [-- PYTEST_ARGS]
vaultspec migrate upgrade  [--target]
vaultspec migrate stamp    [--target]
vaultspec config
vaultspec preps            [SCENARIO]
vaultspec eval smoke
vaultspec eval nightly
```

## Target CLI (approved)

```
vaultspec test unit        [PATH] [-- PYTEST_ARGS]
vaultspec test smoke
vaultspec test benchmark   [smoke | nightly]

vaultspec run mock         [solo | pipeline | approval | autonomous]
vaultspec run probe        [claude | gemini | openai | zhipu]

vaultspec team start       --preset NAME [--name NICKNAME]
vaultspec team status      --id ID
vaultspec team resume      --id ID
vaultspec team stop        --id ID
vaultspec team delete      --id ID
vaultspec team archive     --id ID
vaultspec team list        [running | completed | archived]
```

## Not yet decided

```
vaultspec serve            ???
vaultspec worker           ???
vaultspec migrate          ???
vaultspec config           ???
```

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

### Domain split

- **`test`** — pass/fail verification. "Is the code right? Is the quality acceptable?"
- **`run`** — human observation. "Does this work when I point it at things?"
- **`team`** — lifecycle management. "Start, stop, resume, list, clean up agent teams."

### `team` — backend support status

| Command | Backend support | Notes |
|---------|----------------|-------|
| `team start` | Supported | `POST /threads`. Preset, workspace, autonomous all wired. |
| `team status` | Supported | `GET /threads/{id}/state`. Returns full snapshot. CLI formats: agent count, statuses, runtime, message count, last message excerpts. Header with health/error/stopped. |
| `team resume` | Partial | Works for interrupted threads (permission pause). Cannot resume completed/failed. |
| `team stop` | Supported | `POST /threads/{id}/cancel`. Sets status to cancelled. |
| `team delete` | NOT implemented | No endpoint. Thread data persists forever. Needs new endpoint + CRUD. |
| `team archive` | NOT implemented | No "archived" status in `ThreadStatus` enum. Needs new status + endpoint. |
| `team list` | Partial | `GET /threads` exists with pagination. No status filter param yet. |
| `--name` | Supported | Maps to `nickname` field on thread creation. |
| `--id` override | NOT supported | Thread IDs are generated server-side (uuid4). |
| `--agents` compose | NOT supported | Graph compiled from preset TOML. No dynamic agent list. |

### Open questions

1. Should bare `vaultspec test` default to `test unit`?
2. Should bare `vaultspec test benchmark` run all suites or just fast?
3. Should `run mock` with no arg list scenarios or run all?
4. Should `run probe` accept `--backend`, `--debug`, `--timeout`?
5. What happens to serve, worker, migrate, config?
6. `team delete` and `team archive` need backend work — defer to CLI v2 or implement now?
7. `team list` needs a status filter param on `GET /threads` — small backend change.
8. Should `team resume` support sending a new message into a completed thread (new backend flow)?

### Design principles

1. Command names understandable without docs.
2. Sub-commands complete a sentence: "I want to test ___" / "I want to run ___."
3. Defaults do the most common thing.
4. Max 3 segments for the common case.
5. `test` = verification. `run` = execution. `team` = lifecycle.
