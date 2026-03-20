# Phase 1 Control Layer Audit -- Rolling

**Date**: 2026-03-20
**Phase**: 1 (CLI Purge + Justfile Rewrite)
**ADR**: 038
**Auditor**: Quality audit agent

## Summary

### Overall: PASS with 14 findings (0 CRIT, 3 HIGH, 6 MED, 3 LOW, 2 INFO)

Phase 1 implementation is structurally sound. The CLI surface matches ADR-038
requirements, deleted modules are cleanly removed, and the control/ module is
well-structured. The main risks are stale documentation references, a minor
SQL injection pattern in db.py, and a rendering quirk in doctor.py.

## Findings

### P1-01 | HIGH | README.md | Stale CLI references to deleted commands

The README still documents `vaultspec service start gateway`, `vaultspec
service start worker`, `vaultspec service start all`, `vaultspec service
status`, and `vaultspec service stop all` (lines 52-62). These commands no
longer exist. The entire "Service Management" section (lines 50-62)
describes the deleted `_service.py` behaviour.

Additionally, lines 32-41 reference `just dev-gateway`, `just dev-worker`,
`just dev-ui`, `just up`, `just dev-stack`, `just up-integration`,
`just dev-integration` -- none of which exist in the new Justfile.

**Fix**: Rewrite the README to document the new `just dev service start`
pattern and remove all `vaultspec service` references.

---

### P1-02 | HIGH | docs/IDE_SETUP.md | Stale service start instructions

Lines 16, 279, 304, 326, and 350 all reference
`uv run vaultspec service start all` which no longer exists.

**Fix**: Replace with `just dev service start` or
`just dev service start gateway` etc.

---

### P1-03 | HIGH | db.py:208 | SQL table names interpolated via f-string

```python
conn.execute(text(f"DELETE FROM {table}"))
```

The `tables` list is hardcoded so this is not user-exploitable, but the
pattern violates defense-in-depth. If the list is ever made dynamic or
extended from config, it becomes a SQL injection vector. SQLAlchemy's
`text()` does not parameterize table names.

**Fix**: Use `sqlalchemy.table()` / `sqlalchemy.Table` metadata objects, or
at minimum add an allowlist assertion:

```python
_ALLOWED_TABLES = frozenset({"cost_tracking", "permission_logs", "artifacts", "threads"})
for table in tables:
    assert table in _ALLOWED_TABLES
    conn.execute(text(f"DELETE FROM {table}"))
```

---

### P1-04 | MED | doctor.py:313-337 | Dashboard "all" rendering duplicates output

When `target == "all"`, section headers ("ports", "config", "services") are
printed immediately, but the check rows are accumulated and only rendered at
the end via `_render_dashboard(rows)`. This means the section headers appear
first (with no rows beneath them), then all rows appear in a single
un-sectioned block at the bottom. The visual output does not match the
docstring's example format.

**Fix**: Either render rows per-section inline, or remove the section
headers when rendering the combined dashboard.

---

### P1-05 | MED | verify.py:35 | `typing.Any` import

`from typing import Any, cast` -- `Any` is used only in `_extract_trace_ids`
(line 430: `result: dict[str, Any]`). Per project rules, Python 3.13 syntax
should be used. `Any` is available from `typing` in 3.13 (there is no
`X | Y` replacement for `Any`), so this is technically compliant but `cast`
is the only item that strictly requires the import. `Any` could be replaced
with `object` in this context since the function only calls `.get()`.

**Fix**: Optional. Replace `dict[str, Any]` with `dict[str, object]` for
consistency with the rest of the file, and drop `Any` from the import.

---

### P1-06 | MED | _team.py:51 | `team watch` referenced but not implemented

The `start` command output includes:

```text
vaultspec team watch {thread_id}
```

But the `watch` command does not exist. ADR-038 lists `team watch` as Phase 6.
Printing a command that doesn't work yet will confuse users.

**Fix**: Either remove the `team watch` hint from `start` output, or add a
stub `watch` command that prints "Not yet implemented (Phase 6)."

---

### P1-07 | MED | Justfile:438-439 | `_dev-build-clean` uses PowerShell without shebang

```just
_dev-build-clean:
    Remove-Item -Recurse -Force dist/, *.egg-info -ErrorAction SilentlyContinue
    fd -t d __pycache__ --exclude .venv -x Remove-Item -Recurse -Force
```

This recipe uses PowerShell cmdlets (`Remove-Item`) but does not have a
`#!/usr/bin/env pwsh` shebang. It relies on the global `set windows-shell`
directive, but `fd ... -x Remove-Item` pipes to PowerShell's `Remove-Item`
which requires the shell context. The `fd -x` flag runs commands directly
(not through PowerShell), so `Remove-Item` will fail as it's not a binary.

**Fix**: Either use a pwsh shebang and run `fd` + `Remove-Item` inside a
PowerShell script block, or use `fd -x rm -rf` (Unix-style, available in
Git Bash) which works cross-shell.

---

### P1-08 | MED | Justfile:121 | Jaeger start uses semicolon chaining

```just
_dev-service-start-jaeger:
    docker run -d ... ; Write-Host "Jaeger UI: ..."
```

`Write-Host` is a PowerShell cmdlet but the recipe lacks a pwsh shebang.
The `set windows-shell` makes `just` execute each line via PowerShell, so
this works in practice, but `Write-Host` in a non-shebang recipe is fragile
if the shell config changes. Same issue on lines 125 (vidaimock).

**Fix**: Add `#!/usr/bin/env pwsh` shebang or replace `Write-Host` with
`@echo`.

---

### P1-09 | MED | Justfile:181-189 | kill-postgres/jaeger target naming mismatch

`_dev-service-kill-postgres` runs `docker kill postgres` -- this assumes the
container is named "postgres". But `_dev-service-start-postgres` uses
`docker compose ... up -d postgres`, which names the container based on the
compose project name (e.g., `vaultspec-a2a-postgres-1`). So `docker kill
postgres` will fail unless the compose service is explicitly named
`postgres` via `container_name`.

Similarly, `_dev-service-kill-jaeger` runs `docker kill jaeger-local`, which
matches the `--name jaeger-local` in the start recipe -- this one is correct.

**Fix**: Use `docker compose -f docker-compose.prod.postgres.yml kill
postgres` instead of `docker kill postgres`.

---

### P1-10 | LOW | control package export list includes missing `hooks`

`__all__ = ["db", "doctor", "hooks", "verify"]` declares `hooks` as a
public member, but the `__init__.py` does not import it. This is fine for
`__all__` as documentation, but if anyone does `from vaultspec_a2a.control
import *`, it will fail for `hooks`. This is a minor inconsistency -- the
other modules are also not imported.

**Fix**: Either remove `__all__` (since these are `python -m` modules, not
library APIs), or add lazy imports.

---

### P1-11 | LOW | _team.py:123 | `resume` sends "Continue." as content fallback

When `--message` is omitted, the resume command sends
`{"content": "Continue."}`. If the API supports a contentless resume (null
content), this may have unintended side effects. The docstring says "omit
for contentless resume" but the implementation sends a non-null string.

**Fix**: Send `{"content": message}` and let the API handle `null`, or
document that a placeholder message is always sent.

---

### P1-12 | LOW | Justfile:485-493 | Backward-compat aliases outside namespaces

The `preps`, `preps-list`, and `mcp` recipes live at the top level, outside
the `dev`/`prod` namespace pattern. ADR-038 does not mention these. They are
marked as backward-compat but there is no deprecation timeline.

**Fix**: Add comments with a removal target date, or move under `dev test`
namespace.

---

### P1-13 | INFO | Justfile | `dev service probe` deviates from ADR dispatch

ADR-038 specifies `just dev service probe PROVIDER` but the Justfile
implements it as `dev-service-probe` (a top-level hyphenated recipe) rather
than routing through the `_dev-service-dispatch` PowerShell dispatcher. This
means `just dev service probe claude` will fail because the dispatcher tries
`just _dev-service-probe-claude` (with the provider as a target suffix).
Instead, users must call `just dev-service-probe claude` directly.

**Fix**: Either route `probe` through the dispatcher with special-case
handling (like `db`), or document the actual invocation pattern.

---

### P1-14 | INFO | CLI package missing future-annotations import

The `__init__.py` does not use `from __future__ import annotations` unlike
the other CLI modules. This is fine since the file has no forward references,
but it's an inconsistency.

**Fix**: Optional. Add the import for consistency.

---

## Verification Matrix

| Check Category | Status | Details |
|---|---|---|
| **Import integrity: no refs to deleted modules** | PASS | No imports of `_service`, `_test`, `_run`, `_database`, `_mcp`, `_verify` found in any CLI or control file |
| **Import integrity: control/ does not import cli/** | PASS | Zero cross-dependency. `control/` modules import only from `..core` and stdlib |
| **Import integrity: deleted files removed** | PASS | All 6 CLI modules and 4 test files confirmed absent from filesystem |
| **CLI surface: ADR-038 ss2.1 commands present** | PASS | All 13 commands present: `team start/message/respond/resume/cancel/delete/archive/status/list/presets`, `agent list/show`, plus `team watch` referenced but deferred to Phase 6 (P1-06) |
| **CLI surface: no extra commands** | PASS | Only ADR-listed commands exist. `watch` is referenced in output text but not registered as a command |
| **CLI surface: root options** | PASS | `--verbose/-v`, `--debug/-d`, `--version/-V`, `--show-config` all implemented correctly |
| **CLI surface: fail-fast message** | PASS | Matches ADR-038 format: "Error: Gateway not running at ..." with `just dev service start` hints |
| **Code quality: no `# noqa`** | PASS | Zero occurrences in cli/ and control/ |
| **Code quality: no emoji** | PASS | No emoji characters found |
| **Code quality: no unittest** | PASS | No `import unittest` anywhere in scope |
| **Code quality: no mock/MagicMock** | PASS | No mock imports found |
| **Code quality: Python 3.13 syntax** | PASS | All type annotations use `X \| None` pattern, no `Optional[]` or `Union[]` |
| **Code quality: `__all__` declarations** | PASS | All 8 files (4 cli + 4 control) declare `__all__` |
| **Justfile: dev-*/prod-* naming** | PASS | All recipes follow the pattern. Internal recipes prefixed with `_` |
| **Justfile: dispatcher routing** | PASS with findings | `dev` and `prod` dispatch correctly. `probe` has a routing issue (P1-13) |
| **Justfile: service targets** | PASS | all/prod/dev/gateway/worker/ui/postgres/jaeger/vidaimock all handled |
| **Justfile: PowerShell compatibility** | PARTIAL | `set windows-shell` is correct, but some recipes mix pwsh cmdlets without shebangs (P1-07, P1-08) |
| **control/ callable via python -m** | PASS | All 4 modules (`db`, `doctor`, `verify`, `hooks`) have `if __name__ == "__main__"` blocks |
| **control/ argparse matches Justfile** | PASS | Justfile calls match argparse interfaces in all modules |
| **pyproject.toml entry points** | PASS | `vaultspec = "vaultspec_a2a.cli:cli"` still valid -- no deleted module references |
| **Stale doc references** | FAIL | README.md (P1-01) and IDE_SETUP.md (P1-02) have stale `vaultspec service` references |
| **db.py SQL safety** | WARN | Hardcoded table list is safe today but pattern is fragile (P1-03) |
| **doctor.py output format** | WARN | "all" target rendering is disjointed (P1-04) |

---

## Phase 2 Audit -- CLI Observability Enrichment

**Date**: 2026-03-20
**Auditor**: Phase 2 quality audit agent
**Scope**: `src/vaultspec_a2a/cli/_team.py` -- `team status`, `team list`, `team respond`, `--json` paths

### Summary

### Overall: PASS with 8 findings (0 CRIT, 2 HIGH, 4 MED, 2 LOW)

Field mappings are accurate against the schema. The `_format_elapsed()` utility
is correct and defensive. The supplementary metadata fetch is logically sound.
The respond command context fetch correctly targets the right endpoint and field.
The main risks are: a missing None-guard on a keyed dict access that will
`KeyError` on malformed data (P2-01), a logic inversion in the `respond` command
that misreports success as failure for the `accepted_not_applied` case (P2-02),
the `--json` on `team status` emitting the raw API dict instead of the enriched
view (P2-03), and the `team list` pending-permissions block accessing
`p['request_id']` without a `.get()` guard (P2-05).

### Findings

---

#### P2-01 | HIGH | _team.py:307 | Hard `p['request_id']` KeyError on malformed permission data

In `team status`, the permissions rendering block uses a hard subscript access:

```python
click.echo(f"    {p['request_id']}  {p.get('description', '')}")
```

and again on line 315-316:

```python
click.echo(
    f"    Respond: vaultspec team respond {thread_id} "
    f"--request-id {p['request_id']} --option <OPTION>"
)
```

`_PermissionSnapshot` guarantees `request_id` is required and non-null when the
Python model is used, but the CLI receives raw JSON and calls `.get()` for all
other fields. If the gateway ever returns a permission object without
`request_id` (e.g., during a schema migration or partial write), this will raise
`KeyError` and crash the entire `status` command rather than gracefully skipping
the bad entry.

**Schema reference**: `_PermissionSnapshot.request_id: str` -- required, no
default. The field is always present in normal operation, but raw JSON parsing
provides no such guarantee.

**Fix**: Replace both `p['request_id']` accesses with `p.get('request_id', '?')`.

---

#### P2-02 | HIGH | _team.py:150 | `respond` command misreports `accepted_not_applied` as success, but also never reports it

The `respond` command branches on `data.get("accepted")` (line 150) to
determine whether to print a success or error message. The
`PermissionResponseResult` schema has `accepted: bool` as its second field.

The problem is the `action_status` reporting. The CLI echoes
`"approved (accepted_not_applied)"` when the normal happy path fires (line 151).
The value `"accepted_not_applied"` is the expected success status from
`ControlActionResultStatus.ACCEPTED_NOT_APPLIED` -- so that message is correct.

However, when a **duplicate** response is submitted, the endpoint returns
`accepted=True, applied=True, action_status="duplicate"`. The CLI will print
`"Permission {request_id}: approved (duplicate)."` with "Thread resuming." This
is misleading: the thread is already running; it did not just resume. The
duplicate case should be reported with a neutral/informational message, not a
resuming message.

Additionally, when `existing_action` is found (idempotent re-submission of a
previously accepted action), the endpoint returns `accepted=True` with
`action_status=existing_action.result_status` -- which could be `"applied"` (a
value not enumerated in the CLI's special-case handling). The CLI will print
`"approved (applied)"` with "Thread resuming." but the thread already ran.

**Fix**: Add a check: if `data.get("applied")` is True, print
`"Permission {request_id}: already applied ({action_status}). No action needed."`
instead of the "resuming" message. The resuming message should only appear when
`applied=False` (i.e., `accepted_not_applied`).

---

#### P2-03 | MED | _team.py:250-252 | `team status --json` emits raw snapshot, not enriched view

When `--json` is passed to `team status`, the implementation returns immediately
after printing `data` (the raw ThreadStateSnapshot JSON from `/threads/{id}/state`):

```python
if emit_json:
    click.echo(json.dumps(data, indent=2))
    return
```

This means the `--json` output does not include the `nickname`, `team_preset`,
`created_at`, or `elapsed` fields that the human-readable path fetches via
`_fetch_thread_metadata()`. A consumer using `--json` to drive tooling gets an
incomplete picture compared to the human-readable output.

This is a design choice, but it creates an inconsistency: the snapshot already
contains `thread_id` and `status` but lacks identity fields. The `team list
--json` path has the same characteristic but is less severe because
`ThreadListResponse` already includes `created_at`, `nickname`, and
`team_preset` in the response body.

**Fix** (suggested): Either document that `--json` emits the raw snapshot (add a
comment), or merge the metadata into the emitted JSON before printing:

```python
if emit_json:
    meta = _fetch_thread_metadata(client, thread_id)
    data.update({k: v for k, v in meta.items() if v is not None})
    click.echo(json.dumps(data, indent=2))
    return
```

---

#### P2-04 | MED | _team.py:332 | `tool_calls` field name comment is incorrect

The comment on line 324 reads:

```python
# Tool calls -- API field is "title" for tool name
```

This is accurate -- `ToolCallSnapshot.title: str` is the tool name, derived from
`tc.get("name", "unknown_tool")` in the endpoint. The CLI accesses
`t.get("title")` on line 332, which is correct.

However, the comment is misleading in another direction: the `status` field the
CLI filters on (`"pending"`, `"in_progress"`) is compared against
`ToolCallStatus` enum values. The `ToolCallStatus` enum only defines `PENDING`
and `COMPLETED` (from `snapshots.py` usage and the endpoint code at line 831-836
of `endpoints.py`), not `"in_progress"`. Filtering on `"in_progress"` will never
match any tool call and the condition is silently dead code.

**Schema reference**: The endpoint creates `ToolCallSnapshot` with status either
`ToolCallStatus.COMPLETED` or `ToolCallStatus.PENDING` -- there is no
`in_progress` assignment path for tool calls built from AIMessage.tool_calls.

**Fix**: Change line 327 to filter on `("pending",)` only, or verify whether
`ToolCallStatus` includes an `IN_PROGRESS` value and whether the aggregator sets
it.

---

#### P2-05 | MED | _team.py:421 | Hard `p['request_id']` in `team list` pending-permissions block

In the `team list` command, the secondary permissions fetch from `/team/status`
accesses `p['request_id']` without a guard:

```python
click.echo(
    f"    [{tid}] {p['request_id']}  {p.get('description', '')}"
)
```

`PendingPermission.request_id: str` is required in the schema, so this will
always be present in well-formed responses. But the pattern is inconsistent with
all other field accesses in this function (which all use `.get()`). If the
endpoint is down, the `except Exception: pass` on the outer block will suppress
the crash -- but if the block runs and returns malformed JSON, a `KeyError` will
propagate uncaught through the `try` block.

**Fix**: Replace `p['request_id']` with `p.get('request_id', '?')`.

---

#### P2-06 | MED | _team.py:37-50 | `_fetch_thread_metadata` silently fails on non-2xx without logging

When `/threads` returns a non-success status or when an exception occurs, the
function silently returns all-None defaults. There is no `--debug` mode hook or
log emission. If the gateway is running but the list endpoint is failing (e.g.,
a DB error returning 500), `team status` will show no preset and no elapsed
time with no indication that the supplementary fetch failed.

The `_handle_response()` utility from `_util.py` would normally surface these
errors, but it is deliberately not used here so the main `status` display can
still proceed.

**Fix**: When `--debug` or `--verbose` is active, emit a warning to stderr:
`click.echo("Warning: could not fetch thread metadata.", err=True)`. This
requires threading the ctx object or checking `click.get_current_context()` for
the verbose flag.

---

#### P2-07 | LOW | _team.py:10-28 | `_format_elapsed` imports inside function on every call

The `_format_elapsed()` function imports `UTC` and `datetime` inside the
function body on every call. With `from __future__ import annotations` at the
top of the file, this is safe, but it is an unusual pattern that incurs a
dictionary lookup on each invocation. In `team list`, this is called once per
thread in the list -- typically harmless but inconsistent with the rest of the
file's import style (all other lazy imports are for heavier dependencies like
`json` or `_util`).

**Fix**: Move `from datetime import UTC, datetime` to the module-level import
block. The stdlib `datetime` import is always available and does not contribute
to startup time in any meaningful way.

---

#### P2-08 | LOW | _team.py:391-393 | `active` count includes only `running` and `input_required`

The active thread counter in `team list` computes:

```python
active = counts.get("running", 0) + counts.get("input_required", 0)
```

The status filter's `click.Choice` includes `"submitted"` and `"cancelling"` as
valid statuses but these are excluded from the active count. A thread in
`"submitted"` state is actively being processed and a thread in `"cancelling"`
is in flight. Excluding them from the active count gives a lower-than-real
number.

**Fix**: Include `submitted` and `cancelling` in the active count:

```python
active = sum(
    counts.get(s, 0)
    for s in ("submitted", "running", "input_required", "cancelling")
)
```

---

### Verification Matrix

| Check | Status | Detail |
|---|---|---|
| **Field: `ThreadStateSnapshot.status`** | PASS | `data.get('status', 'unknown')` -- matches schema `status: str` |
| **Field: `ThreadStateSnapshot.pause_cause`** | PASS | `data.get('pause_cause')` -- matches schema `pause_cause: str \| None` |
| **Field: `ThreadStateSnapshot.next_nodes`** | PASS | `data.get('next_nodes', [])` -- matches schema `next_nodes: list[str]` |
| **Field: `ThreadStateSnapshot.agents`** | PASS | `data.get('agents', [])` -- matches schema `agents: list[_AgentSnapshot]` |
| **Field: `_AgentSnapshot.agent_id`** | PASS | `a.get('agent_id', '?')` -- matches schema `agent_id: str` |
| **Field: `_AgentSnapshot.state`** | PASS | `a.get('state', 'unknown')` -- matches schema `state: AgentLifecycleState` |
| **Field: `_AgentSnapshot.display_name`** | PASS | `a.get('display_name', '')` -- matches schema `display_name: str = ""` |
| **Field: `ThreadStateSnapshot.plan`** | PASS | `data.get('plan', [])` -- matches schema `plan: list[PlanEntry]` |
| **Field: `PlanEntry.content`** | PASS | `entry.get('content', '')` -- matches schema `content: str` |
| **Field: `PlanEntry.status`** | PASS | `entry.get('status', 'pending')` -- matches schema `status: PlanEntryStatus` with default PENDING |
| **Field: `ThreadStateSnapshot.pending_permissions`** | PASS | `data.get('pending_permissions', [])` -- matches schema field |
| **Field: `_PermissionSnapshot.request_id`** | FAIL (P2-01, P2-05) | Hard subscript `p['request_id']` in two places -- no None guard |
| **Field: `_PermissionSnapshot.description`** | PASS | `p.get('description', '')` -- correct |
| **Field: `_PermissionSnapshot.tool_call`** | PASS | `p.get('tool_call')` -- matches schema `tool_call: str \| None` |
| **Field: `_PermissionSnapshot.options`** | PASS | `p.get('options', [])` -- matches schema |
| **Field: `_PermissionOptionSnapshot.option_id`** | PASS | `o.get('option_id', '?')` -- matches schema `option_id: str` |
| **Field: `ThreadStateSnapshot.pending_interrupt_count`** | PASS | `data.get('pending_interrupt_count', 0)` -- matches schema `pending_interrupt_count: int = 0` |
| **Field: `ThreadStateSnapshot.tool_calls`** | PASS | `data.get('tool_calls', [])` -- matches schema |
| **Field: `ToolCallSnapshot.title`** | PASS | `t.get('title')` -- matches schema `title: str` |
| **Field: `ToolCallSnapshot.kind`** | PASS | `t.get('kind', '')` -- matches schema `kind: ToolKind` |
| **Field: `ToolCallSnapshot.status`** | PARTIAL (P2-04) | Filter includes `'in_progress'` which is never emitted by endpoint -- dead filter branch |
| **Field: `ThreadSummary.thread_id`** | PASS | `t['thread_id']` -- required field, always present |
| **Field: `ThreadSummary.status`** | PASS | `t.get('status', 'unknown')` -- matches schema `status: str` |
| **Field: `ThreadSummary.created_at`** | PASS | `t.get('created_at')` -- matches schema `created_at: datetime` |
| **Field: `ThreadSummary.nickname`** | PASS | `t.get('nickname')` -- matches schema `nickname: str \| None` |
| **Field: `ThreadSummary.team_preset`** | PASS | `t.get('team_preset', '')` -- matches schema `team_preset: str \| None` |
| **Field: `PendingPermission.thread_id`** | PASS | `p.get('thread_id', '?')[:8]` -- matches schema `thread_id: str` |
| **Field: `PendingPermission.request_id`** | FAIL (P2-05) | `p['request_id']` hard subscript -- no None guard |
| **Field: `PendingPermission.description`** | PASS | `p.get('description', '')` -- matches schema `description: str` |
| **Field: `TeamPresetsResponse.presets`** | PASS | `data.get('presets', [])` -- matches schema |
| **Field: `TeamPresetSummary.id`** | PASS | `p['id']` -- required, always present |
| **Field: `TeamPresetSummary.display_name`** | PASS | `p.get('display_name', '')` -- matches schema `display_name: str` |
| **Field: `TeamPresetSummary.worker_count`** | PASS | `p.get('worker_count', '?')` -- matches schema `worker_count: int` |
| **Field: `TeamPresetSummary.topology`** | PASS | `p.get('topology', '?')` -- matches schema `topology: str` |
| **Field: `PermissionResponseResult.accepted`** | PASS | `data.get('accepted')` -- matches schema `accepted: bool` |
| **Field: `PermissionResponseResult.action_status`** | PASS | `data.get('action_status', 'unknown')` -- matches schema `action_status: str` |
| **`_format_elapsed()` -- ISO datetime with timezone** | PASS | `.replace("Z", "+00:00")` then `fromisoformat()` handles UTC suffix correctly |
| **`_format_elapsed()` -- None input** | PASS | Early return `""` on falsy input (line 12-13) |
| **`_format_elapsed()` -- malformed input** | PASS | Wrapped in bare `except Exception: return ""` |
| **`_fetch_thread_metadata()` -- correct endpoint** | PASS | `GET /threads` -- matches `list_threads_endpoint` router registration |
| **`_fetch_thread_metadata()` -- thread_id match** | PASS | `t.get('thread_id') == thread_id` -- matches `ThreadSummary.thread_id` field name |
| **`_fetch_thread_metadata()` -- default on failure** | PASS | Returns `{"nickname": None, "team_preset": None, "created_at": None}` on any error |
| **`_fetch_thread_metadata()` -- exception isolation** | PASS | Outer `try/except Exception: pass` prevents crash; returns defaults |
| **`respond` -- pre-fetch endpoint** | PASS | `GET /threads/{thread_id}/state` -- correct endpoint |
| **`respond` -- permission match field** | PASS | `p.get('request_id') == request_id` -- matches `_PermissionSnapshot.request_id` |
| **`respond` -- missing permission grace** | PASS | `perm_description` defaults to `""` if no match; `try/except` wraps the entire fetch |
| **`respond` -- `action_status` values** | PARTIAL (P2-02) | `duplicate` and `applied` cases print misleading "resuming" message |
| **`--json` on `team status`** | PARTIAL (P2-03) | Emits raw snapshot only -- no nickname/preset/elapsed enrichment |
| **`--json` on `team list`** | PASS | `ThreadListResponse` already includes `nickname`, `team_preset`, `created_at` -- no enrichment needed |
| **`--json` on `team presets`** | PASS | `TeamPresetsResponse` is the complete schema -- raw dump is correct |
| **`json.dumps(data, indent=2)` validity** | PASS | All three `--json` paths call `json.dumps` with `indent=2` on the `.json()` dict |

---

## Phase 3 Audit -- Thread Lifecycle Integrity

**Date**: 2026-03-20
**Auditor**: Phase 3 quality audit agent
**Scope**: F-18 cancel transition (executor.py), F-36 reconciliation re-dispatch (app.py), F-17 terminal event flush (executor.py)

### Summary

### Overall: FAIL with 7 findings (1 CRIT, 2 HIGH, 2 MED, 2 LOW)

Fix F-17 (terminal flush) is clean and correct. Fix F-18 (cancel transition) is
structurally sound with a narrow race window that is acceptable under current
architecture. Fix F-36 (reconciliation re-dispatch) has a critical bug:
`thread.metadata_json` accesses a nonexistent attribute on `ThreadModel`, which
will raise `AttributeError` at runtime and prevent any reconciling thread with
metadata from being re-dispatched.

### Findings

---

#### P3-01 | CRIT | app.py:1228 | `thread.metadata_json` does not exist on `ThreadModel`

The `_redispatch_reconciling` background task accesses `thread.metadata_json`
(line 1228) and `_json.loads(thread.metadata_json)` (line 1232). The
`ThreadModel` ORM class defines this column as `thread_metadata` (models.py
line 108), not `metadata_json`. At runtime this will raise `AttributeError` for
every reconciling thread that has metadata, causing the inner `try/except
Exception: pass` to swallow the error and dispatch without `workspace_root`.

The `metadata_json` name exists on `DispatchRequest` (schemas/internal.py:40)
but not on `ThreadModel`. This is a name collision between the schema layer and
the ORM layer.

**Impact**: Every reconciling thread will be re-dispatched with
`workspace_root=None`. The worker will attempt to compile a graph without a
workspace root, which may fail if the team preset requires workspace-scoped
agent discovery (ADR-012 section 2.8). Threads that previously ran with
workspace-scoped configs will fail to reconcile.

**Fix**: Change `thread.metadata_json` to `thread.thread_metadata` on both
lines 1228 and 1232.

---

#### P3-02 | HIGH | app.py:1228-1234 | Inner `except Exception: pass` silently swallows P3-01 bug

The metadata extraction block:

```python
if thread.metadata_json:
    import json as _json
    try:
        meta = _json.loads(thread.metadata_json)
    except Exception:
        pass
```

The `except Exception: pass` on line 1233-1234 will silently swallow the
`AttributeError` from P3-01, making the bug invisible in logs. Even after P3-01
is fixed, this pattern hides JSON parse errors and attribute access errors with
no logging. Debugging reconciliation failures in production will be difficult.

**Fix**: At minimum, log the exception:

```python
except Exception:
    logger.debug("Could not parse metadata for thread %s", thread.id, exc_info=True)
```

---

#### P3-03 | HIGH | app.py:1229 | Redundant `import json as _json` inside loop

`json` is already imported at module level (app.py line 22). The lazy `import
json as _json` inside the for-loop body (line 1229) serves no purpose -- `json`
is a stdlib module with negligible import cost and is already loaded. This also
introduces a confusing alias (`_json` vs `json`) in the same file where `json`
is used extensively at module scope (e.g., lines 459, 460).

This pattern appears to have been copied from a context where `json` was not
already imported.

**Fix**: Remove `import json as _json` and use the module-level `json` import:
`meta = json.loads(thread.thread_metadata)`.

---

#### P3-04 | MED | executor.py:224-229 | TOCTOU race in cancel handler's `is_active` check

The cancel path acquires `_ingest_lock` to read `is_active`, then releases the
lock, then conditionally emits the terminal event:

```python
async with self._ingest_lock:
    is_active = req.thread_id in self._active_ingests
if not is_active:
    await self._emit_terminal_status(req.thread_id, "cancelled")
```

Between releasing the lock and emitting the terminal event, an ingest could
start (another task calls `_mark_ingest_active`). In this scenario:

1. Cancel handler sees `is_active=False`, releases lock.
2. Ingest handler acquires lock, adds thread to `_active_ingests`, starts graph.
3. Cancel handler emits `thread_terminal(cancelled)`.
4. Ingest handler completes, emits `thread_terminal(completed)`.

This produces two terminal events for the same thread. However, the gateway's
`update_thread_status` transition validator would reject the second transition
(CANCELLED -> COMPLETED is not in `_VALID_TRANSITIONS`), so the DB state remains
consistent. The WS broadcast would emit a spurious terminal event but clients
should be resilient to this.

The window is narrow: it requires an ingest dispatch to arrive between the lock
release and the `send_event + flush_events` call (microseconds). In practice,
this is safe because:

- The cancel cooperative flag (`cancel_thread`) is set *before* the lock check
  (line 219), so any new ingest that starts will observe the cancel flag via the
  aggregator and terminate early.
- The gateway transitions the thread to CANCELLING before dispatching cancel,
  and the ingest handler checks thread status.

**Severity justification**: MED rather than HIGH because the DB transition
validator provides a safety net, and the cooperative cancel flag provides a
second layer of defense. But the code comment should document this reasoning.

**Fix**: Document the race window with an inline comment. Alternatively, hold
the lock through the emit call to close the window entirely (but this adds
lock contention on the flush HTTP POST).

---

#### P3-05 | MED | app.py:1241-1265 | No race guard for concurrent user dispatch to reconciling thread

If a user dispatches to a reconciling thread (via `POST /threads/{id}/message`)
at the same time the `_redispatch_reconciling` task dispatches to the same
thread, two `ingest` dispatches arrive at the worker for the same `thread_id`.
The worker's `_mark_ingest_active` will reject the second dispatch (returns
`False`), so the graph won't run twice. However:

- The rejected dispatch is silently dropped (logged at WARNING, no error
  response to the user).
- The thread's status is still RECONCILING, so the gateway's dispatch handler
  may attempt to transition it to RUNNING, conflicting with the reconciliation
  task's own status management.

There is no locking or coordination between the reconciliation task and REST
dispatch paths.

**Severity justification**: MED because the worker-side gating prevents data
corruption, but the UX is poor: the user's message is silently lost with only a
worker-side WARNING log.

**Fix**: Consider either (a) setting the thread status to SUBMITTED before
dispatching in the reconciliation task, so the REST handler sees a non-
RECONCILING status and proceeds normally, or (b) adding a gateway-side check
that skips user dispatch if the thread is RECONCILING with a 409 response.

---

#### P3-06 | LOW | executor.py:729-732 | No exception guard around `flush_events()` in terminal emit

`_emit_terminal_status` calls `await self._bridge.flush_events()` (line 732).
The `flush_events()` method internally catches `httpx.HTTPError` but does not
catch all possible exceptions (e.g., `RuntimeError` from a closed event loop,
`asyncio.CancelledError` during shutdown). If an unexpected exception escapes
`flush_events()`, it propagates through `_emit_terminal_status`.

For the cancel path (line 227-229), this exception would bubble to
`handle_dispatch`'s outer `except Exception` (line 243), which logs it. This is
acceptable. For the ingest/resume paths, it would bubble to the `finally` block
(lines 561-568 / 690-697), where it would *replace* the pending
`_mark_ingest_done` call -- potentially leaking the ingest slot.

In practice, `flush_events()` is defensive and this is unlikely. But the
asymmetry between "flush failure in finally" vs "flush failure in cancel path"
is worth noting.

**Fix**: Wrap the `flush_events()` call in a try/except within
`_emit_terminal_status`:

```python
try:
    await self._bridge.flush_events()
except Exception:
    logger.warning("Failed to flush terminal event for thread %s", thread_id, exc_info=True)
```

---

#### P3-07 | LOW | app.py:1242 | `circuit_breaker.pre_dispatch()` can abort reconciliation mid-loop

Inside the reconciliation loop, `circuit_breaker.pre_dispatch()` (line 1242)
raises `HTTPException(503)` if the breaker is OPEN. This exception is caught by
the per-thread `except Exception as exc` (line 1260), which logs a warning and
continues to the next thread. This is correct behavior.

However, the circuit breaker was designed for request-response handlers (it
raises `HTTPException`). Using it in a background task means the exception type
is `HTTPException` rather than a domain-specific error. The `except Exception`
block catches it correctly, but the logged message includes `exc` which will
show `HTTPException(status_code=503, detail="...")` -- a confusing log entry for
a background task that has no HTTP response context.

**Fix**: Either check `circuit_breaker.state` directly instead of calling
`pre_dispatch()` (which is designed for request handlers), or catch
`HTTPException` specifically with a clearer message:

```python
if circuit_breaker.state == "open":
    logger.info("Circuit breaker open, skipping re-dispatch for thread %s", thread.id)
    continue
```

### Verification Matrix

| Check | Status | Detail |
|---|---|---|
| **F-18: `_ingest_lock` acquired correctly** | PASS | Uses `async with self._ingest_lock:` (line 224) -- standard asyncio Lock context manager |
| **F-18: `is_active` check correctness** | PASS | `req.thread_id in self._active_ingests` correctly checks the set membership |
| **F-18: Race condition analysis** | PASS with finding (P3-04) | TOCTOU window exists but is mitigated by cooperative cancel flag + DB transition validator |
| **F-18: Cooperative cancel path unmodified** | PASS | `self._aggregator.cancel_thread(req.thread_id)` on line 219 is unchanged; active ingests still observe the cancel flag |
| **F-18: Terminal event emitted for idle threads** | PASS | `_emit_terminal_status(thread_id, "cancelled")` correctly called when `not is_active` |
| **F-36: `ensure_worker()` called before dispatch** | PASS | Line 1215: `await worker_spawner.ensure_worker()` is the first operation |
| **F-36: Queries `RECONCILING` threads** | PASS | `list_threads(db, status=ThreadStatus.RECONCILING, limit=100)` on line 1218-1219 |
| **F-36: `DispatchRequest` fields correct** | FAIL (P3-01) | `workspace_root` will always be None due to `thread.metadata_json` AttributeError |
| **F-36: Error handling doesn't crash gateway** | PASS | Outer `except Exception as exc` on line 1266 catches all errors |
| **F-36: Task cancelled on shutdown** | PASS | `reconcile_task.cancel()` on line 1275, gathered with `return_exceptions=True` on line 1276 |
| **F-36: `list_threads` import added correctly** | PASS | Line 50: `from ..database.crud import ThreadStatus, get_thread, list_threads, update_thread_status` |
| **F-36: No circular imports** | PASS | `list_threads` is from `database.crud`, already imported by other functions in app.py |
| **F-36: `json` import inside loop** | FAIL (P3-03) | Redundant -- `json` already imported at module level (line 22) |
| **F-36: Race with user dispatch** | WARN (P3-05) | Worker-side gating prevents double-execution but user message may be silently lost |
| **F-17: `flush_events()` exists on WorkerBridge** | PASS | Defined at ipc.py:144 as `async def flush_events(self) -> None` |
| **F-17: Flush is awaited correctly** | PASS | `await self._bridge.flush_events()` on line 732 |
| **F-17: Flush failure handling** | PASS with finding (P3-06) | `flush_events()` internally catches httpx errors; unexpected exceptions propagate but are caught by outer handler |
| **F-17: Performance impact** | PASS | One extra HTTP POST per thread completion is acceptable; comment on line 729-731 documents the trade-off |
| **Cross-cut: CANCELLING -> CANCELLED transition** | PASS | `_VALID_TRANSITIONS[ThreadStatus.CANCELLING]` includes `ThreadStatus.CANCELLED` (crud.py:380-386) |
| **Cross-cut: RECONCILING -> RUNNING** | PASS | `_VALID_TRANSITIONS[ThreadStatus.RECONCILING]` includes `ThreadStatus.RUNNING` (crud.py:387-398) |
| **Cross-cut: RECONCILING -> COMPLETED** | PASS | `_VALID_TRANSITIONS[ThreadStatus.RECONCILING]` includes `ThreadStatus.COMPLETED` (crud.py:387-398) |
| **Cross-cut: RECONCILING -> FAILED** | PASS | `_VALID_TRANSITIONS[ThreadStatus.RECONCILING]` includes `ThreadStatus.FAILED` (crud.py:387-398) |
| **Cross-cut: RECONCILING -> SUBMITTED** | PASS | `_VALID_TRANSITIONS[ThreadStatus.RECONCILING]` includes `ThreadStatus.SUBMITTED` (crud.py:387-398) |
| **Cross-cut: Watchdog conflict with reconciliation task** | PASS | Watchdog monitors process health and restarts; reconciliation task dispatches threads. They operate on orthogonal concerns. Both use `ensure_worker()` for worker readiness |
| **Cross-cut: No `# noqa` in changed files** | PASS | No new `# noqa` comments in executor.py or app.py changes. Pre-existing `# noqa` in internal.py (2) and test_graph.py (1) are unrelated |
| **Cross-cut: No unittest/mock imports** | PASS | Zero `import unittest` or `from unittest` in the codebase |

---

## Phase 4 Audit -- Backend API Fixes

**Date**: 2026-03-20
**Auditor**: Phase 4 quality audit agent
**Scope**: F-38 tool call metadata (aggregator.py + endpoints.py), F-23 worker_connected heartbeat timestamp (endpoints.py + app.py)

### Summary

### Overall: PASS with 6 findings (0 CRIT, 1 HIGH, 3 MED, 2 LOW)

Both fixes are structurally sound and well-integrated. F-38 tool call metadata
tracking is comprehensive: the `_tool_call_states` dict is correctly keyed,
cleaned up on thread pruning and shutdown, and the merge logic in
`_enrich_snapshot_from_state` correctly deduplicates against checkpoint data.
F-23 worker_connected is correctly applied to all 7 dispatch paths (4 REST
endpoints + 2 WS handlers + 1 reconciliation task). The main risk is unbounded
growth of `_tool_call_states` within a single long-running thread (P4-01), and
a pre-existing circuit breaker inconsistency in the permission endpoint that
F-23 inherits (P4-03).

### Findings

---

#### P4-01 | HIGH | aggregator.py:340-342 | `_tool_call_states` has no per-thread size cap

The `_tool_call_states` dict grows with every tool call start/update for every
active thread. Unlike `_tool_update_last_emit` (which has `debounce_map_max_entries`
and `_evict_oldest` at line 896-899), there is no maximum size constraint on
`_tool_call_states`.

For a long-running thread that invokes thousands of tool calls (e.g., a
multi-hour coding session with many file reads/edits), the dict accumulates
entries that are never pruned until the thread completes and `prune_sequences()`
is called. The `ingest()` finally block (lines 1893-1899) cleans up
`_tool_update_last_emit` for the thread but does NOT clean up
`_tool_call_states`.

This is by design (states are needed for REST snapshot enrichment), but the lack
of any cap means pathological threads can cause OOM in the gateway process.

**Impact**: Memory pressure under sustained high-tool-call workloads. A thread
with 10,000 tool calls would hold ~10,000 dict entries, each ~200 bytes =
~2 MB. Unlikely to cause issues in practice but violates the bounded-memory
pattern established by `_evict_oldest` for other aggregator dicts.

**Fix**: Either (a) add a `_TOOL_CALL_STATES_MAX_PER_THREAD` cap that evicts
the oldest COMPLETED entries when exceeded, or (b) prune COMPLETED tool call
states in the `ingest()` finally block, retaining only PENDING/IN_PROGRESS
entries for snapshot enrichment:

```python
# In ingest() finally block:
completed_tc_keys = [
    k for k in self._tool_call_states
    if k[0] == thread_id
    and self._tool_call_states[k]["status"] == ToolCallStatus.COMPLETED.value
]
for k in completed_tc_keys:
    del self._tool_call_states[k]
```

---

#### P4-02 | MED | aggregator.py:1110 | `sync_worker_event` tool_call_start stores `tc_kind` as raw string without validation

In the `tool_call_start` handler of `sync_worker_event()` (line 1110):

```python
tc_kind = payload.get("kind", ToolKind.OTHER.value)
```

The `kind` value is taken directly from the worker event payload as a raw string
and stored in `_tool_call_states` without validation against the `ToolKind` enum.
If the worker sends an invalid kind value (e.g., `"custom_tool"`), it will be
stored and later passed to `ToolKind(tc_state.get("kind", ...))` in
`_enrich_snapshot_from_state` (line 871), which will raise `ValueError`. The
`try/except ValueError` on lines 872-873 handles this gracefully by falling back
to `ToolKind.OTHER`, so there is no crash. However, the inconsistency means the
`_tool_call_states` dict can contain values that don't match the enum, which
could confuse debug inspection.

By contrast, `emit_tool_call_start()` (line 829) stores `kind.value` from a
typed `ToolKind` parameter, so the local-ingest path is always valid.

**Fix**: Validate on storage:

```python
try:
    tc_kind = ToolKind(payload.get("kind", ToolKind.OTHER.value)).value
except ValueError:
    tc_kind = ToolKind.OTHER.value
```

---

#### P4-03 | MED | endpoints.py:1596 | `record_success()` called unconditionally in permission endpoint

In `respond_to_permission_endpoint` (line 1596), `circuit_breaker.record_success()`
is called after every non-exception HTTP response, including non-2xx responses
(e.g., worker returns 500). The `_mark_worker_connected(request)` call on line
1598 is correctly guarded by `if dispatched:` (where `dispatched = resp.is_success`),
but the CB success recording is not.

Compare with `cancel_thread_endpoint` (lines 1754-1756) which correctly guards
both `record_success()` and `_mark_worker_connected()` behind `resp.is_success`.

This is a pre-existing inconsistency not introduced by Phase 4, but Phase 4's
addition of `_mark_worker_connected` makes the asymmetry more visible. A worker
returning 500 would incorrectly close the circuit breaker.

**Fix**: Move `circuit_breaker.record_success()` inside the `if dispatched:`
block:

```python
dispatched = resp.is_success
if dispatched:
    circuit_breaker.record_success()
    _mark_worker_connected(request)
```

---

#### P4-04 | MED | aggregator.py:1121-1142 | `sync_worker_event` tool_call_update status stored as raw string

In the `tool_call_update` handler (line 1129):

```python
if payload.get("status"):
    existing["status"] = payload["status"]
```

The `status` value is stored directly from the payload without validation against
`ToolCallStatus`. If the worker sends `"running"` (not a valid enum value), it
will be stored and later cause a `ValueError` in `_enrich_snapshot_from_state`
(line 875-876). The `try/except ValueError` handles this gracefully (falls back
to `PENDING`), but the stored value is inconsistent.

The same issue applies to the fallback branch (lines 1134-1141) where
`payload.get("status", ToolCallStatus.PENDING.value)` is stored -- the
`payload.get("status")` part is unvalidated.

**Fix**: Validate on storage in both branches, same pattern as P4-02.

---

#### P4-05 | LOW | endpoints.py:56 | `_classify_tool_kind` imported from private module path

Line 56 imports a private function directly:

```python
from ..core.aggregator import _classify_tool_kind
```

The leading underscore conventionally marks `_classify_tool_kind` as a private
implementation detail of the aggregator module. Importing it in endpoints.py
creates a cross-module coupling to an internal function. If the aggregator
refactors or renames this function, endpoints.py will break.

The function is also used in `emit_permission_request` (line 934) and
`process_langgraph_event` (line 1399), so it is effectively a shared utility
despite the underscore prefix.

**Fix**: Either (a) rename to `classify_tool_kind` (drop the underscore) and
add it to the aggregator module's `__all__`, or (b) move it to a shared utility
module (e.g., `schemas/enums.py` alongside the `ToolKind` enum definition).

---

#### P4-06 | LOW | aggregator.py:69 | `__all__` does not export `_classify_tool_kind` despite cross-module use

`__all__ = ["EventAggregator", "StreamableGraph"]` on line 69 does not include
`_classify_tool_kind`, which is now imported by endpoints.py (line 56). While
`__all__` primarily governs `from module import *` behavior and does not prevent
direct imports, the convention is that `__all__` lists the public API. The
function is effectively public since it's used across module boundaries.

This is the flip side of P4-05. Together they indicate the function should be
promoted to a public export.

**Fix**: See P4-05 -- rename and add to `__all__`, or relocate.

---

### Verification Matrix

| Check | Status | Detail |
|---|---|---|
| **F-38: `_tool_call_states` key format** | PASS | `(thread_id, tool_call_id)` tuple -- consistent across `emit_tool_call_start` (line 828), `emit_tool_call_update` (line 861), `sync_worker_event` tool_call_start (line 1113), and `get_tool_call_states` (line 1004) |
| **F-38: Thread cleanup in `prune_sequences`** | PASS | Lines 440-444: comprehension filters `k[0] not in active_thread_ids`, deletes all matching keys. Correctly covers all tool calls for stale threads |
| **F-38: Cleanup in `shutdown()`** | PASS | Line 1947: `self._tool_call_states.clear()` -- all state cleared |
| **F-38: Memory leak -- unbounded growth** | FAIL (P4-01) | No per-thread size cap. COMPLETED entries persist until thread pruning |
| **F-38: Merge logic deduplication** | PASS | Lines 868-869: `if tc_id in checkpoint_tc_ids: continue` -- tool calls already in checkpoint are not duplicated |
| **F-38: `ToolKind` enum values match `_classify_tool_kind`** | PASS | `_classify_tool_kind` returns `ToolKind` enum members (lines 254-261). `_TOOL_KIND_MAP` values are all `ToolKind` members. Endpoint merge uses `ToolKind(tc_state.get("kind", ...))` with ValueError fallback |
| **F-38: `sync_worker_event` tool_call_start handler** | PASS | Lines 1105-1119: extracts `tool_call_id`, `title`, `kind`, `agent_id` from payload, stores in `_tool_call_states`, advances sequence |
| **F-38: `sync_worker_event` tool_call_update handler** | PASS | Lines 1121-1142: merges into existing state or creates minimal entry, advances sequence |
| **F-38: `get_tool_call_states` return format** | PASS | Returns `dict[str, dict[str, str]]` -- tool_call_id to state dict. Uses `dict(state)` to return copies, not references |
| **F-38: `emit_tool_call_start` stores state before broadcast** | PASS | Lines 828-833: state written before `ToolCallStartEvent` construction and `_broadcast` call |
| **F-38: `emit_tool_call_update` handles missing start** | PASS | Lines 870-878: creates minimal state entry when update arrives without prior start event |
| **F-38: Snapshot `ToolKind` ValueError handling** | PASS | Lines 870-873: `try/except ValueError` falls back to `ToolKind.OTHER` |
| **F-38: Snapshot `ToolCallStatus` ValueError handling** | PASS | Lines 874-879: `try/except ValueError` falls back to `ToolCallStatus.PENDING` |
| **F-23: `_mark_worker_connected` accesses `request.app.state`** | PASS | Line 159: `request.app.state.worker_last_heartbeat_ts = time.monotonic()` -- standard FastAPI pattern |
| **F-23: `request: Request` in `create_thread_endpoint`** | PASS | Line 378: `request: Request` parameter added. FastAPI injects `Request` automatically |
| **F-23: `request: Request` in `send_message_endpoint`** | PASS | Line 1084: `request: Request` parameter present |
| **F-23: `request: Request` in `respond_to_permission_endpoint`** | PASS | Line 1382: `request: Request` parameter present |
| **F-23: `request: Request` in `cancel_thread_endpoint`** | PASS | Line 1666: `request: Request` parameter present |
| **F-23: REST dispatch path 1 (create_thread)** | PASS | Line 555: `_mark_worker_connected(request)` after `circuit_breaker.record_success()` |
| **F-23: REST dispatch path 2 (send_message)** | PASS | Line 1225: `_mark_worker_connected(request)` after `circuit_breaker.record_success()` |
| **F-23: REST dispatch path 3 (permission respond)** | PASS | Line 1598: `_mark_worker_connected(request)` guarded by `if dispatched:` |
| **F-23: REST dispatch path 4 (cancel)** | PASS | Line 1756: `_mark_worker_connected(request)` guarded by `resp.is_success` |
| **F-23: WS dispatch path 5 (message handler)** | PASS | app.py line 503: `app_state.worker_last_heartbeat_ts = time.monotonic()` |
| **F-23: WS dispatch path 6 (control handler)** | PASS | app.py line 583: `app_state.worker_last_heartbeat_ts = time.monotonic()` |
| **F-23: Background dispatch path 7 (reconciliation)** | PASS | app.py line 1263: `app.state.worker_last_heartbeat_ts = time.monotonic()` |
| **F-23: No duplicate writes with existing heartbeat** | PASS | The heartbeat handler (internal.py:585,801) writes the same field; the newer timestamp wins. No conflict |
| **F-23: FastAPI DI compatibility** | PASS | `Request` is a native Starlette/FastAPI type injected automatically. Adding it to endpoint signatures does not break existing `Depends()` parameters |
| **F-23: `_mark_worker_connected` docstring** | PASS | Lines 148-158: clearly documents the intent (F-23), the field written, and the relationship to the heartbeat handler |
| **Cross-cut: No `# noqa` comments** | PASS | Zero `# noqa` in aggregator.py, endpoints.py, app.py |
| **Cross-cut: No mock/unittest imports** | PASS | Zero `import unittest` or `from unittest.mock` in changed files |
| **Cross-cut: Python 3.13 syntax** | PASS | All type annotations use `X \| Y` union syntax, `dict[str, str]`, `list[str]`, etc. No `Optional[]` or `Union[]` |
| **Cross-cut: `__all__` updated** | PASS (with note) | `get_tool_call_states` is a method on `EventAggregator`, not a standalone export -- `__all__` correctly unchanged. `_classify_tool_kind` cross-module use noted in P4-05/P4-06 |
| **Cross-cut: No circular imports** | PASS | endpoints.py imports `_classify_tool_kind` from `core.aggregator`. aggregator.py imports from `api.schemas.enums` (ToolKind, ToolCallStatus). No reverse dependency from aggregator to endpoints |
| **Cross-cut: CB inconsistency in permission endpoint** | WARN (P4-03) | Pre-existing: `record_success()` called unconditionally on line 1596, but `_mark_worker_connected` correctly guarded by `if dispatched:` |

---

## Phase 5+6 Audit -- Service Health Wiring + Team Watch

**Date**: 2026-03-20
**Auditor**: Phase 5+6 quality audit agent
**Scope**: Phase 5: `doctor.py` per-service filtering, Justfile health recipes. Phase 6: `_team.py` `watch` command, `pyproject.toml` websockets dependency.

### Summary

### Overall: PASS with 10 findings (0 CRIT, 2 HIGH, 4 MED, 3 LOW, 1 INFO)

Phase 5 is clean: `_ALL_SERVICES` matches the Justfile targets, all 6 health
recipes correctly delegate to `doctor.py services <name>`, the `_want()` filter
works correctly, ui and vidaimock probes hit the right URLs, and no stale inline
PowerShell health probes remain in the Justfile.

Phase 6 is structurally sound and the WebSocket protocol implementation is
correct. The subscribe command shape matches the server schema, the
`ConnectedEvent` handshake is handled correctly, all 12 server event types have
renderers, and the permission prompt correctly maps `PermissionOptionKind`
values. The main risks are: terminal detection relies on `node_name` which is
only set to `"supervisor"` (never `"vaultspec-supervisor"`, making one branch of
the check dead code), the `_watch_async` function is not exported in `__all__`
despite being a module-level async function, and the `typing.Any` + `cast` usage
imports `Any` which could be replaced.

### Phase 5 Findings

---

#### P5-01 | LOW | doctor.py:304-305 | vidaimock probe uses port 8100 which collides with MCP port label

The vidaimock health probe hits `127.0.0.1:8100/v1/models` (lines 304-305).
The `_DEFAULT_PORTS` list (line 82) labels port 8100 as `"mcp"`:

```python
("mcp", 8100),
```

And the Justfile starts vidaimock on port 8100 via `docker-compose.integration.yml`.
The MCP server (`vaultspec-mcp`) also defaults to port 8100 (via `settings.mcp_port`).
These two services conflict on the same port. When vidaimock is running, the "mcp"
port check in `_check_ports()` will show port 8100 as "in use", which is correct
but misleading -- it's vidaimock, not the MCP server.

The `_check_services()` probe for vidaimock at `:8100/v1/models` will correctly
detect vidaimock (it returns an OpenAI-compatible models list), but if the actual
MCP server is running on 8100 instead, the `/v1/models` probe will likely fail
(404), correctly reporting vidaimock as not running.

**Impact**: Low. Port collision is a deployment concern, not a doctor.py bug.
The probes are correct for their respective services.

**Fix**: Consider adding a comment in `_DEFAULT_PORTS` noting the port 8100
conflict between MCP and vidaimock, or changing the vidaimock integration compose
to use a different port (e.g., 8200).

---

#### P5-02 | INFO | doctor.py:264 | Jaeger health probe uses port 14269, not 13133

The Jaeger health probe (line 264) checks port 14269:

```python
code, _ = _http_probe("127.0.0.1", 14269, "/")
```

But the Justfile's `_dev-service-start-jaeger` recipe (line 121) exposes port
13133 for health (`-p 13133:13133`) and the Jaeger 2.x image uses the OTLP
collector health endpoint at `:13133/status`. Port 14269 was the Jaeger 1.x
admin health port.

The `_DEFAULT_PORTS` list does not include port 13133 or 14269. The MEMORY.md
notes "Jaeger admin health port 14269 returns 204 when ready" but this was for
`jaegertracing/jaeger:2` which the start recipe uses as
`cr.jaegertracing.io/jaegertracing/jaeger:2.16.0`.

In Jaeger 2.x, the `/` path on port 14269 may not be exposed at all (the image
doesn't map it). The Justfile maps 13133 for health. The probe should use 13133.

However, looking at existing test infrastructure: `pytest_runtest_setup` in
MEMORY.md checks port 14269 for Jaeger readiness, suggesting 14269 is expected.
The `docker-compose.integration.yml` and `docker-compose.prod.yml` may also use
14269. This is a pre-existing inconsistency between the new Jaeger start recipe
(which maps 13133) and the older health-check convention (14269).

**Impact**: Info. If the Jaeger container does not expose 14269, the health
probe will always report "not running" even when Jaeger is healthy on 13133.

**Fix**: Verify which port the `cr.jaegertracing.io/jaegertracing/jaeger:2.16.0`
image exposes for health checks. If 13133, update `_http_probe` call to use
13133 and path `/status`. If both ports work, document the mapping.

---

### Phase 6 Findings

---

#### P6-01 | HIGH | _team.py:764 | Dead code branch: `"vaultspec-supervisor"` never appears in `node_name`

The terminal detection logic (line 764) checks:

```python
if node in ("supervisor", "vaultspec-supervisor"):
```

where `node = evt.get("node_name", "")`. However, `node_name` is always
`"supervisor"` for the supervisor node:

- Graph builder: `builder.add_node("supervisor", ...)` (graph.py:448)
- Aggregator: `node_name="supervisor"` (aggregator.py:1839)
- WebSocket fallback: `node_name="supervisor"` (websocket.py:351)
- Worker executor: `emit_agent_status(node_name=task.name)` where the node is named `"supervisor"` in the graph

The value `"vaultspec-supervisor"` appears only as `agent_id` (executor.py:537,
664), never as `node_name`. The second branch of the check will never match.

This is not a bug (the `"supervisor"` branch works correctly), but dead code that
suggests a misunderstanding of the `agent_id` vs `node_name` distinction. If the
graph topology ever changes to use `"vaultspec-supervisor"` as the node name,
the check will still work -- but currently it's misleading.

**Fix**: Remove `"vaultspec-supervisor"` from the tuple:

```python
if node == "supervisor":
```

Or, if the intent is to catch both the node_name and agent_id, check both fields:

```python
node = evt.get("node_name", "")
agent = evt.get("agent_id", "")
if node == "supervisor" or agent == "vaultspec-supervisor":
```

---

#### P6-02 | HIGH | _team.py:758-770 | Terminal detection misses pipeline topology

The terminal state detection only fires when the supervisor node reaches a
terminal state (line 764). In a `pipeline` topology, there is no supervisor node
(graph.py:520: "No supervisor node"). The graph runs through a fixed sequence
of worker nodes and ends at `END`. The last worker's `agent_status` event will
have `node_name` equal to that worker's agent ID, not `"supervisor"`.

This means `team watch` will never detect thread completion for pipeline
topologies. The event stream will end (the server closes the WS or sends no
more events), but the watch command's explicit terminal detection and clean
exit message will never trigger.

In practice, the `async for raw_msg in ws` loop will block indefinitely waiting
for more messages after the pipeline completes, until either: (a) a heartbeat
timeout on the server side disconnects the client, or (b) the user presses
Ctrl+C. Neither produces the "Thread reached terminal state" message.

**Fix**: Additionally detect terminal state by checking the `thread_id` scoped
`agent_status` events where `state` is terminal and then verifying the thread
status via a REST call to `/api/threads/{thread_id}/state`. If the thread's
overall status is terminal (completed/failed/cancelled), break:

```python
if event_type == "agent_status" and state in terminal_states:
    # Check if thread itself is terminal (handles supervisor + pipeline)
    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=5.0) as http:
            check = await http.get(f"/threads/{thread_id}/state")
            if check.is_success:
                tdata = check.json()
                if tdata.get("status") in terminal_states:
                    click.echo(f"\nThread {thread_id} reached terminal state: {tdata['status']}")
                    disconnected_cleanly = True
                    break
    except Exception:
        pass
```

---

#### P6-03 | MED | _team.py:8 | `typing.Any` and `cast` imported at module level

Line 8 imports `Any` and `cast` from `typing`:

```python
from typing import Any, cast
```

`cast` is used in `_render_plan_update` (line 553) and `_render_team_status`
(line 581). `Any` is used as the type argument in these `cast()` calls:
`cast(list[dict[str, Any]], ...)`.

Per Python 3.13 conventions used in this project, `Any` could be avoided by
using `object` in the cast target type. However, `cast` itself requires
`typing.cast`, and `Any` is semantically correct here since the dict values are
heterogeneous JSON.

More importantly, the `cast()` calls are unnecessary. The `evt.get("entries", [])`
and `evt.get("agents", [])` return `object` from the `dict[str, object]`
annotation on `evt`. The `cast` is used to tell the type checker the value is
`list[dict[str, Any]]`. Since this is a CLI rendering function that immediately
calls `.get()` on each element, and the function already handles missing keys
gracefully, the `cast` adds no runtime safety.

**Fix**: Either keep the imports (they are technically correct) or remove the
`cast()` calls and type-ignore the `.get()` calls on the list elements, or
annotate `evt` parameter as `dict[str, Any]` instead of `dict[str, object]`.

---

#### P6-04 | MED | _team.py:692-694 | Permission POST uses `/permissions/{id}/respond` but API requires `/api/permissions/{id}/respond`

The permission response POST (line 692-694) uses:

```python
async with httpx.AsyncClient(base_url=api_url, timeout=10.0) as http:
    resp = await http.post(
        f"/permissions/{request_id}/respond",
        json={"option_id": chosen_option_id},
    )
```

where `api_url = f"{base_url}/api"` (line 475). This means the full URL is
`http://host:port/api/permissions/{request_id}/respond`. The server endpoint
is registered as `router.post("/permissions/{request_id}/respond")` on a
router mounted at `/api` (app.py:1358). So the full path is
`/api/permissions/{request_id}/respond`.

**Verdict**: This is CORRECT. The `base_url` includes `/api`, and the relative
path `/permissions/...` is correctly appended. No finding.

*RETRACTED -- analysis confirmed correctness.*

---

#### P6-04 | MED | _team.py:443-468 | Import error message suggests `uv add` but websockets is already a main dependency

The `websockets` import fallback (lines 457-468) prints:

```text
Install it with:
  uv add websockets
```

However, `websockets>=16.0` is already in the main `dependencies` list in
`pyproject.toml` (line 30). If the import fails, it means the virtualenv is
corrupted or out of sync -- `uv add` would be a no-op since the dependency
already exists. The correct fix instruction would be `uv sync` to reinstall
from the lockfile.

**Fix**: Change the install instructions to:

```python
click.echo(
    "Error: 'websockets' package is required for the watch command.\n"
    "\n"
    "Sync your environment:\n"
    "  uv sync\n",
    err=True,
)
```

---

#### P6-05 | MED | _team.py:453-454 | Redundant `import asyncio` inside `_watch_async`

Line 453 imports `asyncio` inside `_watch_async`:

```python
async def _watch_async(thread_id: str, *, emit_json: bool = False) -> None:
    import asyncio
```

But `asyncio` is already imported at line 438 inside the `watch` command:

```python
def watch(...) -> None:
    import asyncio
    asyncio.run(_watch_async(...))
```

And it is used again inside `_handle_permission` at line 626:

```python
async def _handle_permission(...) -> None:
    import asyncio
```

The `_watch_async` function is a module-level async function (not nested inside
`watch`), so it does need its own import. However, having `import asyncio` in
three different scopes (watch, _watch_async, _handle_permission) is redundant.
Since `_watch_async` and `_handle_permission` are called only from `watch`
(which already imported asyncio), the module cache makes the repeated imports
essentially free. But it violates the project's style where heavy imports are
lazy but stdlib imports are at module level.

**Fix**: Move `import asyncio` to module level (alongside `import click` on line
7). `asyncio` is a stdlib module with negligible import cost.

---

#### P6-06 | MED | _team.py:436 | `__all__` not updated with `watch` command

`__all__ = ["team"]` on line 5 exports only the `team` Click group. The `watch`
command is registered on the group via `@team.command()` so it is accessible
through `team`. However, `_watch_async` is a module-level async function that
could theoretically be imported directly for testing or composition. It is not
in `__all__`.

Per the project's architectural patterns, sub-modules must declare `__all__`
containing their public, exportable APIs. The `_watch_async` function has no
leading underscore in its semantic intent (it is the async implementation of
`watch`), but its name does start with `_` by convention. The `watch` Click
command itself is not separately importable -- it's only accessible via the
`team` group.

**Impact**: Low. `__all__ = ["team"]` is sufficient since all commands are
accessed through the group. No change needed unless `_watch_async` is intended
to be a public API.

**Fix**: No action required. `__all__ = ["team"]` is correct.

*RETRACTED -- `__all__` is correctly unchanged.*

---

#### P6-06 | MED | _team.py:743 | Thread ID filter does not handle events without `thread_id`

The thread ID filter (line 742-743):

```python
evt_thread = evt.get("thread_id")
if evt_thread and evt_thread != thread_id:
    continue
```

This correctly skips events for other threads. However, some event types
(`ConnectedEvent`, `HeartbeatEvent`) do not have a `thread_id` field at all.
For these events, `evt_thread` is `None`, so the filter correctly passes them
through (the `if` condition is false when `evt_thread` is falsy).

But `ErrorEvent` has `thread_id` as a required field on `EventEnvelope`. If
the server sends an error for a different thread, it will be correctly filtered
out. If the server sends a global error (with `thread_id=""`), it will pass
through because `""` is falsy. This is acceptable behavior.

However, `ConnectedEvent` is handled in step 1 (line 714-722) before the
`async for` loop, so it won't reach the filter. And heartbeats return `None`
from `_render_event`. The filter is correct for the multiplexed protocol.

**Verdict**: PASS. No finding.

*RETRACTED -- analysis confirmed correctness.*

---

#### P6-07 | LOW | _team.py:656-660 | Fallback shortcut key collision for unknown option kinds

When an option has an unknown `kind` (not one of the four `PermissionOptionKind`
values), the fallback assigns the first character of `option_id` as the shortcut
key (line 658):

```python
key = oid[0] if oid else name[0] if name else "?"
```

If two options have the same first character in their `option_id` (e.g.,
`"approve_plan"` and `"approve_tool"`), the second will overwrite the first
in `shortcut_map`. The user will only be able to select the second option via
the shortcut, and the first option becomes unreachable via shortcut (though
still reachable by typing the full `option_id`).

This only affects non-standard permission options that don't use the four
canonical `PermissionOptionKind` values. In practice, all options use the
canonical kinds (allow_once, allow_always, reject_once, reject_always).

**Fix**: Use a counter or sequential letter assignment for unknown kinds:

```python
else:
    key = chr(ord("1") + len(shortcut_map))  # "1", "2", "3", ...
    shortcut_map[key] = oid
    labels.append(f"[{key}] {name}")
```

---

#### P6-08 | LOW | _team.py:470-472 | `settings` import at function level may fail without clear error

Line 472 imports settings inside `_watch_async`:

```python
from ..core.config import settings
```

If the settings fail to load (e.g., missing required env vars), the exception
will propagate as an `ImportError` or `ValidationError` from Pydantic. The
outer `except Exception` on line 777 will catch it and print
`"WebSocket error: {exc}"` which is misleading -- the error is a config problem,
not a WebSocket error.

The `start`, `status`, and other commands avoid this by using `_api_client()`
from `_util.py`, which wraps the client construction and provides clear error
messages. The `watch` command bypasses this utility because it needs raw WS
access.

**Fix**: Wrap the settings import in a try/except with a specific message:

```python
try:
    from ..core.config import settings
except Exception as exc:
    click.echo(f"Error: Could not load settings: {exc}", err=True)
    raise SystemExit(1) from None
```

---

#### P6-09 | LOW | _team.py:480-496 | Health check probe creates a new httpx.Client per call

The fail-fast health check (line 480) uses `httpx.get()` (the module-level
convenience function), which creates a new `Client` for each call:

```python
resp = httpx.get(f"{api_url}/health", timeout=5.0)
```

This is a one-shot probe, so creating a new client is acceptable. No finding.

*RETRACTED -- one-shot client is fine.*

---

### Verification Matrix

| Check | Status | Detail |
|---|---|---|
| **P5: `doctor.py` argparse accepts `services gateway`** | PASS | `_build_parser()` (lines 332-355): positional `target` with choices `["all", "ports", "config", "services"]`, optional positional `service` with choices from `_ALL_SERVICES` |
| **P5: `_ALL_SERVICES` matches Justfile targets** | PASS | `_ALL_SERVICES = ("gateway", "worker", "jaeger", "postgres", "ui", "vidaimock")` -- all 6 match the Justfile health recipes: `_dev-service-health-{gateway,worker,ui,postgres,jaeger,vidaimock}` |
| **P5: `_want()` filter logic** | PASS | `_want(name)` returns `True` when `service_filter is None` (all services) or `service_filter == name` (exact match). Used consistently in all 6 service probe blocks |
| **P5: Each Justfile health recipe calls correct doctor.py command** | PASS | All 6 recipes use `uv run python -m vaultspec_a2a.control.doctor services <name>` with the correct service name |
| **P5: UI probe URL** | PASS | `_http_probe("127.0.0.1", 5173, "/")` -- correct for Vite dev server |
| **P5: vidaimock probe URL** | PASS | `_http_probe("127.0.0.1", 8100, "/v1/models")` -- correct for OpenAI-compatible models endpoint |
| **P5: No stale inline PowerShell health probes in Justfile** | PASS | Searched for `Invoke-WebRequest`, `Test-NetConnection`, `curl.*health`, `wget.*health` -- zero matches. All health recipes delegate to doctor.py |
| **P5: `service_filter` parameter plumbing** | PASS | `main()` passes `service` arg to `_check_services(service_filter=service)` (line 380). When target is "services" and service is provided, only that service is probed |
| **P5: Jaeger probe port** | WARN (P5-02) | Probes 14269 but Justfile start recipe maps 13133. Pre-existing inconsistency |
| **P5: Port 8100 collision** | NOTE (P5-01) | MCP and vidaimock both use port 8100 |
| **P6: WS URL correctness** | PASS | `ws://127.0.0.1:{settings.port}/ws` matches `@app.websocket("/ws")` (app.py:1482). The `/ws` endpoint is on the app root, not behind the `/api` prefix |
| **P6: ConnectedEvent handling** | PASS | Checks `connected_evt.get("type") != "connected"` which matches `ServerEventType.CONNECTED = "connected"`. `ConnectedEvent` fields (`client_id`, `server_version`, `active_threads`) are not used by the watch command, which is fine |
| **P6: Subscribe command JSON shape** | PASS | `{"type": "subscribe", "thread_ids": [thread_id]}` matches `SubscribeCommand` schema: `type: Literal["subscribe"]`, `thread_ids: list[str]` |
| **P6: Thread ID filtering for multiplexed connections** | PASS | `evt_thread = evt.get("thread_id"); if evt_thread and evt_thread != thread_id: continue` -- correctly skips events for other threads while passing through events without `thread_id` (heartbeat, connected) |
| **P6: Event type coverage** | PASS | All 12 `ServerEventType` values handled: `agent_status`, `message_chunk`, `thought_chunk`, `tool_call_start`, `tool_call_update` (renderers), `permission_request` (interactive handler), `plan_update`, `artifact_update`, `error`, `team_status` (renderers), `heartbeat`, `connected` (suppressed). Unknown types fall through to default renderer |
| **P6: PermissionOptionKind values** | PASS | Watch command checks `kind == "allow_once"`, `"allow_always"`, `"reject_once"`, `"reject_always"` -- exact match with `PermissionOptionKind` enum values |
| **P6: Permission POST endpoint** | PASS | `POST /permissions/{request_id}/respond` via `httpx.AsyncClient(base_url=api_url)` where `api_url = "{base_url}/api"`. Full URL: `http://host:port/api/permissions/{id}/respond` -- matches router registration |
| **P6: Permission POST JSON body** | PASS | `{"option_id": chosen_option_id}` matches `PermissionResponseCommand.option_id: str` and the REST endpoint's expected body |
| **P6: `run_in_executor` for blocking input** | PASS | `await loop.run_in_executor(None, lambda: click.prompt(...))` -- standard pattern. Uses default executor (thread pool). Handles `EOFError` and `KeyboardInterrupt` |
| **P6: Permission POST error handling** | PASS | Non-success response: prints status code to stderr. Exception: prints error to stderr. Neither crashes the event loop |
| **P6: Supervisor node name matching** | PARTIAL (P6-01) | `node_name` is always `"supervisor"` in graph builder and aggregator. The `"vaultspec-supervisor"` branch in the check is dead code |
| **P6: Pipeline topology terminal detection** | FAIL (P6-02) | No supervisor node in pipeline topology -- terminal state never detected. Watch command will hang until server-side timeout or Ctrl+C |
| **P6: `websockets` import safety** | PASS | `try/except ImportError` with install instructions. Also used for `websockets.exceptions.ConnectionClosed` at line 775 |
| **P6: `asyncio.run()` from sync Click** | PASS | Standard Click CLI is synchronous. `asyncio.run()` creates a new event loop. No conflict with existing loops |
| **P6: `websockets>=16.0` in pyproject.toml** | PASS | Listed in both main `dependencies` (line 30) and `dev` dependency group (line 62). Main deps is correct since watch is a production CLI command |
| **P6: websockets API correctness** | PASS | Uses `websockets.asyncio.client.connect` (the modern async API for websockets 16.x). `ws.recv()` and `ws.send()` are the correct async methods. `async for raw_msg in ws` is the standard iteration pattern |
| **P6: `ConnectionClosed` exception handling** | PASS | `except websockets.exceptions.ConnectionClosed` catches server-initiated disconnects with a clean message |
| **P6: `KeyboardInterrupt` handling** | PASS | Sets `disconnected_cleanly = True` and prints "Thread continues running." -- correct UX for Ctrl+C detach |
| **P6: No `# noqa` comments** | PASS | Zero `# noqa` in `_team.py` |
| **P6: No emoji** | PASS | No emoji characters in any changed file |
| **P6: No mock/unittest imports** | PASS | Zero `import unittest` or `from unittest.mock` in changed files |
| **P6: Python 3.13 syntax** | PASS | All annotations use `X \| Y` pattern (`str \| None`, `bool \| None`). No `Optional[]` or `Union[]` |
| **P6: `__all__` in `_team.py`** | PASS | `__all__ = ["team"]` unchanged. The `watch` command is registered on the `team` group, so it's accessible through the group export. `_watch_async` starts with `_` -- not a public API |
| **P6: `typing.Any` and `cast` usage** | NOTE (P6-03) | `Any` and `cast` imported from typing. `cast` used in 2 places for JSON list typing. Technically correct but `cast` is unnecessary for runtime behavior |
