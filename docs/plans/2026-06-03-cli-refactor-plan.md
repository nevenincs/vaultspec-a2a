# CLI Refactor Implementation Plan — 2026-03-06

**ADR:** 034-cli-domain-restructure
**Research:** `docs/research/2026-06-03-cli-refactor-research.md`
**Audit:** `docs/audits/2026-03-06-cli-architecture-audit.md`

---

## Phase 1 — CLI Restructure (no backend changes)

**Goal**: Reorganize existing commands into domain groups. Zero functional
changes — all existing behavior preserved under new names.

### Step 1.1 — Create `cli/` package skeleton

Convert `src/vaultspec_a2a/cli.py` → `src/vaultspec_a2a/cli/__init__.py`.

**Files created:**

```
src/vaultspec_a2a/cli/
├── __init__.py     # root group + --show-config + subgroup imports
├── _test.py        # test group
├── _run.py         # run group
├── _service.py     # service group
├── _database.py    # database group
└── _util.py        # _mask(), shared helpers
```

**`__init__.py`:**

```python
"""Click CLI for vaultspec-a2a."""

__all__ = ["cli", "main"]

import click

from ._util import _show_config_callback


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--show-config",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_show_config_callback,
    help="Print resolved settings and exit.",
)
def cli() -> None:
    """Vaultspec A2A -- agent orchestration server and tooling."""


# Import and register subgroups
from ._database import database  # noqa: E402
from ._run import run  # noqa: E402
from ._service import service  # noqa: E402
from ._test import test  # noqa: E402

cli.add_command(test)
cli.add_command(run)
cli.add_command(service)
cli.add_command(database)

main = cli
```

**`_util.py`:**

```python
"""Shared CLI helpers."""

from __future__ import annotations

import click

_SENSITIVE_SUBSTRINGS = ("key", "token", "secret", "password")
_MASK_MIN_LEN = 4


def _mask(name: str, value: object) -> str:
    text = str(value)
    if (
        any(s in name.lower() for s in _SENSITIVE_SUBSTRINGS)
        and len(text) > _MASK_MIN_LEN
    ):
        return f"****{text[-4:]}"
    return text


def _show_config_callback(
    ctx: click.Context, _param: click.Parameter, value: bool,
) -> None:
    if not value:
        return
    from ..core.config import settings
    for name in settings.model_fields:
        click.echo(f"{name}={_mask(name, getattr(settings, name))}")
    ctx.exit()
```

### Step 1.2 — `_test.py` (test group)

```python
"""test group: unit, smoke, benchmark."""

from __future__ import annotations

import subprocess
import sys

import click


@click.group(invoke_without_command=True)
@click.pass_context
def test(ctx: click.Context) -> None:
    """Run tests and benchmarks."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(unit)


@test.command()
@click.argument("path", default="all")
@click.argument("extra", nargs=-1, type=click.UNPROCESSED)
def unit(path: str, extra: tuple[str, ...]) -> None:
    """Run unit tests (default). PATH: all | marker | file path.

    Extra arguments after -- are forwarded to pytest.
    """
    cmd: list[str] = [sys.executable, "-m", "pytest"]

    if path == "all":
        pass
    elif "/" in path or "\\" in path or path.endswith(".py"):
        cmd.append(path)
    else:
        cmd += [
            "--override-ini=addopts=--durations=10 --showlocals -ra --capture=sys",
            "-m",
            path,
        ]

    cmd.extend(extra)
    sys.exit(subprocess.run(cmd, check=False).returncode)


@test.command()
def smoke() -> None:
    """Run smoke tests (pytest -m smoke)."""
    cmd = [sys.executable, "-m", "pytest", "-m", "smoke"]
    sys.exit(subprocess.run(cmd, check=False).returncode)


@test.command()
@click.argument(
    "suite",
    required=False,
    default=None,
    type=click.Choice(["smoke", "nightly"], case_sensitive=False),
)
def benchmark(suite: str | None) -> None:
    """Run evaluation benchmarks. SUITE: smoke | nightly (bare = run all)."""
    suites = [suite] if suite else ["smoke", "nightly"]
    for s in suites:
        cmd = [
            sys.executable,
            "-m",
            f"vaultspec_a2a.tests.evals.suites.{s}",
        ]
        returncode = subprocess.run(cmd, check=False).returncode
        if returncode != 0:
            sys.exit(returncode)
```

### Step 1.3 — `_run.py` (run group)

```python
"""run group: mock, probe."""

from __future__ import annotations

import subprocess
import sys

import click


@click.group()
def run() -> None:
    """Run scenarios and probes."""


@run.command()
@click.argument("scenario", required=False, default=None)
def mock(scenario: str | None) -> None:
    """Run a mock scenario (or list available scenarios)."""
    if scenario is None:
        cmd = [sys.executable, "-m", "vaultspec_a2a.tests.preps"]
    else:
        cmd = [
            sys.executable,
            "-m",
            f"vaultspec_a2a.tests.preps.{scenario}",
        ]
    sys.exit(subprocess.run(cmd, check=False).returncode)


@run.command()
@click.argument(
    "provider",
    required=False,
    default=None,
    type=click.Choice(
        ["claude", "gemini", "openai", "zhipu"], case_sensitive=False,
    ),
)
def probe(provider: str | None) -> None:
    """Run a provider connectivity probe. Bare = list available."""
    if provider is None:
        click.echo("Available probes: claude, gemini, openai, zhipu")
        return
    cmd = [
        sys.executable,
        "-m",
        f"vaultspec_a2a.providers.probes.{provider}",
    ]
    sys.exit(subprocess.run(cmd, check=False).returncode)
```

### Step 1.4 — `_service.py` (service group)

```python
"""service group: start, stop, kill, delete."""

from __future__ import annotations

import click


@click.group()
def service() -> None:
    """Manage backend and worker processes."""


@service.command()
@click.argument(
    "target",
    required=False,
    default=None,
    type=click.Choice(["backend", "worker"], case_sensitive=False),
)
@click.option("--host", default=None, help="Bind host (default: from settings).")
@click.option("--port", default=None, type=int, help="Bind port (default: from settings).")
@click.option("--log-level", default=None, help="Uvicorn log level.")
def start(
    target: str | None,
    host: str | None,
    port: int | None,
    log_level: str | None,
) -> None:
    """Start backend and/or worker. Bare = start both."""
    import uvicorn

    from ..core.config import settings

    level = (log_level or settings.log_level.value).lower()

    if target is None or target == "backend":
        uvicorn.run(
            "vaultspec_a2a.api.app:create_app",
            factory=True,
            host=host or settings.host,
            port=port or settings.port,
            log_level=level,
        )
    elif target == "worker":
        uvicorn.run(
            "vaultspec_a2a.worker.app:create_worker_app",
            factory=True,
            host="127.0.0.1",
            port=port or settings.worker_port,
            log_level=level,
        )
```

### Step 1.5 — `_database.py` (database group)

```python
"""database group: update, clear, snapshot, restore."""

from __future__ import annotations

from pathlib import Path

import click

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def _alembic_cfg() -> tuple:
    from alembic.config import Config as AlembicConfig

    from ..core.config import settings

    cfg = AlembicConfig(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg, settings


@click.group()
def database() -> None:
    """Database operations."""


@database.command()
@click.option("--target", default="head", help="Migration target (default: head).")
def update(target: str) -> None:
    """Run pending database migrations."""
    from alembic import command

    cfg, _ = _alembic_cfg()
    command.upgrade(cfg, target)
    click.echo(f"Migrated to {target}.")
```

### Step 1.6 — Delete old `cli.py`, update `pyproject.toml`

- Delete `src/vaultspec_a2a/cli.py`.
- Verify `pyproject.toml` entry point: `vaultspec = "vaultspec_a2a.cli:cli"` —
  this already works because `cli/__init__.py` exports `cli`.

### Step 1.7 — Update Justfile recipes

| Old | New |
|-----|-----|
| `just worker` | `vaultspec service start worker` |
| `just preps SCENARIO` | `vaultspec run mock {{SCENARIO}}` |
| `just preps-list` | `vaultspec run mock` |
| `just eval-smoke` | `vaultspec test benchmark smoke` |
| `just eval-nightly` | `vaultspec test benchmark nightly` |

### Step 1.8 — Verify

- [ ] `vaultspec --help` shows 6 groups
- [ ] `vaultspec --show-config` prints settings
- [ ] `vaultspec test` runs unit tests
- [ ] `vaultspec test unit` runs unit tests
- [ ] `vaultspec test smoke` runs smoke tests
- [ ] `vaultspec test benchmark smoke` runs eval smoke
- [ ] `vaultspec run mock` lists scenarios
- [ ] `vaultspec run mock solo_coder` runs scenario
- [ ] `vaultspec run probe` lists probes
- [ ] `vaultspec run probe claude` runs probe
- [ ] `vaultspec service start backend` starts API server
- [ ] `vaultspec service start worker` starts worker
- [ ] `vaultspec database update` runs migrations

---

## Phase 2 — Database Utilities

**Goal**: Add `clear`, `snapshot`, `snapshot list`, `restore` to `_database.py`.

### Step 2.1 — `database clear --yes`

```python
@database.command()
@click.option("--yes", is_flag=True, required=True, help="Confirm destructive operation.")
def clear(yes: bool) -> None:
    """Delete all application data (preserves schema)."""
    from sqlalchemy import create_engine, text

    from ..core.config import settings

    engine = create_engine(settings.database_url.replace("+aiosqlite", ""))
    tables = ["cost_tracking", "permission_logs", "artifacts", "threads"]
    with engine.begin() as conn:
        for table in tables:
            conn.execute(text(f"DELETE FROM {table}"))  # noqa: S608
    click.echo(f"Cleared {len(tables)} tables.")
```

### Step 2.2 — `database snapshot`

```python
@database.command()
def snapshot() -> None:
    """Create a timestamped snapshot of the database."""
    import shutil
    from datetime import datetime, timezone

    from ..core.config import settings

    db_path = settings.database_path
    if db_path is None:
        click.echo("Cannot snapshot in-memory database.", err=True)
        raise SystemExit(1)

    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = db_path.with_suffix(f".snapshot.{ts}")
    shutil.copy2(db_path, dest)
    # Also copy WAL if present
    wal = db_path.with_suffix(".db-wal")
    if wal.exists():
        shutil.copy2(wal, dest.with_suffix(f".{ts}-wal"))
    click.echo(f"Snapshot: {dest}")
```

### Step 2.3 — `database snapshot list`

Use a Click multi-command or nested group. Since Click doesn't support
`snapshot list` as two words easily, implement as `database snapshots` (list)
and `database snapshot` (create). Alternative: use `database snapshot --list`.

**Decision**: `database snapshot` creates, `database snapshots` lists.

```python
@database.command()
def snapshots() -> None:
    """List available database snapshots."""
    from ..core.config import settings

    db_path = settings.database_path
    if db_path is None:
        click.echo("No snapshots for in-memory database.", err=True)
        return

    pattern = f"{db_path.stem}.snapshot.*"
    files = sorted(db_path.parent.glob(pattern), reverse=True)
    if not files:
        click.echo("No snapshots found.")
        return
    for f in files:
        size_kb = f.stat().st_size / 1024
        click.echo(f"  {f.name}  ({size_kb:.0f} KB)")
```

### Step 2.4 — `database restore --name`

```python
@database.command()
@click.option("--name", required=True, help="Snapshot filename to restore.")
def restore(name: str) -> None:
    """Restore database from a snapshot. Refuses if service is running."""
    import shutil

    import httpx

    from ..core.config import settings

    # Check if service is running
    try:
        httpx.get(f"{settings.api_base_url}/health", timeout=2.0)
        click.echo("Service is running. Stop it first: vaultspec service stop", err=True)
        raise SystemExit(1)
    except httpx.ConnectError:
        pass  # Not running, safe to proceed

    db_path = settings.database_path
    snapshot_path = db_path.parent / name
    if not snapshot_path.exists():
        click.echo(f"Snapshot not found: {snapshot_path}", err=True)
        raise SystemExit(1)

    shutil.copy2(snapshot_path, db_path)
    click.echo(f"Restored from {name}.")
```

### Step 2.5 — Verify

- [ ] `vaultspec database clear --yes` empties tables
- [ ] `vaultspec database snapshot` creates timestamped copy
- [ ] `vaultspec database snapshots` lists available snapshots
- [ ] `vaultspec database restore --name X` restores (refuses if running)

---

## Phase 3 — Backend Gaps + Team/Agent CLI

**Goal**: Add backend endpoints and CRUD, then wire CLI commands.

### Step 3.1 — Backend: ThreadStatus.ARCHIVED

Add `ARCHIVED = "archived"` to `ThreadStatus` enum in `crud.py`.
Create Alembic migration for the CHECK constraint update.

### Step 3.2 — Backend: delete_thread()

```python
async def delete_thread(session: AsyncSession, thread_id: str) -> bool:
    """Hard-delete thread and cascading artifacts."""
    result = await session.execute(
        delete(ThreadModel).where(ThreadModel.id == thread_id)
    )
    await session.commit()
    return result.rowcount > 0
```

Cascade deletes configured via SQLAlchemy relationship `cascade="all, delete-orphan"`.

### Step 3.3 — Backend: list_threads status filter

Add optional `status: ThreadStatus | None = None` param to `list_threads()`.
When provided, add `.where(ThreadModel.status == status.value)` to query.

### Step 3.4 — Backend: New endpoints

| Endpoint | Method | Handler |
|----------|--------|---------|
| `DELETE /threads/{id}` | DELETE | `delete_thread_endpoint()` |
| `POST /threads/{id}/archive` | POST | `archive_thread_endpoint()` |
| `GET /threads?status=running` | GET | Update existing `list_threads_endpoint()` |
| `POST /admin/shutdown` | POST | `shutdown_endpoint()` |

### Step 3.5 — CLI: `_team.py`

```python
"""team group: start, status, resume, stop, delete, archive, list."""

import click
import httpx

from ._util import _api_client


@click.group()
def team() -> None:
    """Manage agent teams (threads)."""


@team.command()
@click.option("--preset", required=True, help="Team preset name.")
@click.option("--name", default=None, help="Optional nickname.")
def start(preset: str, name: str | None) -> None:
    """Start a new team from a preset."""
    with _api_client() as client:
        body = {"team_preset": preset}
        if name:
            body["nickname"] = name
        resp = client.post("/threads", json=body)
        resp.raise_for_status()
        data = resp.json()
        click.echo(f"Thread {data['thread_id']} started.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def status(thread_id: str) -> None:
    """Get team status."""
    with _api_client() as client:
        resp = client.get(f"/threads/{thread_id}/state")
        resp.raise_for_status()
        data = resp.json()
        click.echo(f"Status: {data.get('status', 'unknown')}")
        # Print agent summaries, recent events, etc.


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
@click.option("--message", default=None, help="New input message.")
def resume(thread_id: str, message: str | None) -> None:
    """Resume a stopped/completed team."""
    with _api_client() as client:
        body = {}
        if message:
            body["message"] = message
        resp = client.post(f"/threads/{thread_id}/messages", json=body)
        resp.raise_for_status()
        click.echo(f"Thread {thread_id} resumed.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def stop(thread_id: str) -> None:
    """Cancel a running team."""
    with _api_client() as client:
        resp = client.post(f"/threads/{thread_id}/cancel")
        resp.raise_for_status()
        click.echo(f"Thread {thread_id} cancelled.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def delete(thread_id: str) -> None:
    """Delete a thread and all its data."""
    with _api_client() as client:
        resp = client.delete(f"/threads/{thread_id}")
        resp.raise_for_status()
        click.echo(f"Thread {thread_id} deleted.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def archive(thread_id: str) -> None:
    """Archive a completed team."""
    with _api_client() as client:
        resp = client.post(f"/threads/{thread_id}/archive")
        resp.raise_for_status()
        click.echo(f"Thread {thread_id} archived.")


@team.command("list")
@click.argument(
    "status_filter",
    required=False,
    default=None,
    type=click.Choice(
        ["running", "completed", "failed", "archived", "cancelled"],
        case_sensitive=False,
    ),
)
def list_cmd(status_filter: str | None) -> None:
    """List teams. Optional filter: running | completed | archived."""
    with _api_client() as client:
        params = {}
        if status_filter:
            params["status"] = status_filter
        resp = client.get("/threads", params=params)
        resp.raise_for_status()
        data = resp.json()
        threads = data.get("threads", [])
        if not threads:
            click.echo("No threads found.")
            return
        for t in threads:
            nick = t.get("nickname") or t["thread_id"][:8]
            click.echo(f"  {t['thread_id']}  {t['status']:12s}  {nick}")
```

### Step 3.6 — CLI: `_agent.py`

```python
"""agent group: ask, list."""

from __future__ import annotations

from pathlib import Path

import click


@click.group()
def agent() -> None:
    """Single-agent operations."""


@agent.command("list")
def list_cmd() -> None:
    """List available agent presets."""
    presets_dir = (
        Path(__file__).resolve().parent.parent / "core" / "presets" / "agents"
    )
    if not presets_dir.exists():
        click.echo("No agent presets directory found.", err=True)
        return

    tomls = sorted(presets_dir.glob("*.toml"))
    if not tomls:
        click.echo("No agent presets found.")
        return
    for t in tomls:
        click.echo(f"  {t.stem}")


@agent.command()
@click.option("--agent", "agent_name", required=True, help="Agent preset name.")
@click.option("--message", required=True, help="Message to send.")
def ask(agent_name: str, message: str) -> None:
    """Ask a single agent a question (via solo-coder team preset)."""
    from ._util import _api_client

    with _api_client() as client:
        # Create thread with solo-coder preset, override agent
        resp = client.post(
            "/threads",
            json={
                "team_preset": "vaultspec-solo-coder",
                "initial_message": message,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        click.echo(f"Thread {data['thread_id']} — streaming response...")
        # TODO: SSE/WS streaming for real-time output
```

### Step 3.7 — Register team + agent groups

Add to `cli/__init__.py`:

```python
from ._agent import agent
from ._team import team

cli.add_command(team)
cli.add_command(agent)
```

### Step 3.8 — Verify

- [ ] `vaultspec team list` shows threads
- [ ] `vaultspec team start --preset vaultspec-solo-coder` creates thread
- [ ] `vaultspec team status --id X` shows state
- [ ] `vaultspec team stop --id X` cancels
- [ ] `vaultspec team delete --id X` removes
- [ ] `vaultspec team archive --id X` archives
- [ ] `vaultspec agent list` shows presets
- [ ] `vaultspec agent ask --agent vaultspec-coder --message "hello"` works

---

## Phase 4 — Service Management

**Goal**: Add `stop`, `kill`, `delete` to service group.

### Step 4.1 — `service stop`

HTTP POST to `/admin/shutdown` endpoint. Connection refused = already stopped.

### Step 4.2 — `service kill`

On Windows: `taskkill /F /PID <pid>`. Requires PID file or port-based PID
lookup via `netstat`.

### Step 4.3 — `service delete`

```python
@service.command()
@click.argument("docker_service")
def delete(docker_service: str) -> None:
    """Remove a Docker service (not backend/worker)."""
    if docker_service in ("backend", "worker"):
        click.echo("Cannot delete native services. Use 'service stop'.", err=True)
        raise SystemExit(1)
    import subprocess, sys
    sys.exit(subprocess.run(
        ["docker", "compose", "down", "--rmi", "local", docker_service],
        check=False,
    ).returncode)
```

### Step 4.4 — Verify

- [ ] `vaultspec service stop` gracefully shuts down
- [ ] `vaultspec service stop backend` stops only backend
- [ ] `vaultspec service kill worker` force-kills worker
- [ ] `vaultspec service delete jaeger` removes Docker service

---

## Execution Order

| Phase | Effort | Dependencies | Blocked By |
|-------|--------|-------------|------------|
| 1 | ~2 hours | None | Nothing |
| 2 | ~1 hour | Phase 1 | Nothing |
| 3 | ~4 hours | Phase 1 + backend endpoints | BE-A through BE-H |
| 4 | ~2 hours | Phase 1 + shutdown endpoint | BE-G |

**Recommended**: Ship Phase 1 + 2 together, then Phase 3 + 4 as a follow-up.
