"""database group: update, clear, snapshot (list), restore."""

from __future__ import annotations


__all__ = ["database"]

from datetime import UTC
from pathlib import Path

import click


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def _alembic_cfg() -> tuple:
    from alembic.config import Config as AlembicConfig  # noqa: PLC0415

    from ..core.config import settings  # noqa: PLC0415

    cfg = AlembicConfig(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg, settings


def _get_db_path() -> Path:
    from ..core.config import settings  # noqa: PLC0415

    db_path = settings.database_path
    if str(db_path) == ":memory:":
        click.echo("Cannot operate on in-memory database.", err=True)
        raise SystemExit(1)
    return db_path


@click.group()
def database() -> None:
    """Database operations."""


@database.command()
@click.option("--target", default="head", help="Migration target (default: head).")
def update(target: str) -> None:
    """Run pending database migrations."""
    from alembic import command  # noqa: PLC0415

    cfg, _ = _alembic_cfg()
    command.upgrade(cfg, target)
    click.echo(f"Migrated to {target}.")


@database.command()
@click.option(
    "--yes", is_flag=True, required=True, help="Confirm destructive operation."
)
def clear(yes: bool) -> None:
    """Delete all application data (preserves schema)."""
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    from ..core.config import settings  # noqa: PLC0415

    engine = create_engine(settings.database_url.replace("+aiosqlite", ""))
    tables = ["cost_tracking", "permission_logs", "artifacts", "threads"]
    with engine.begin() as conn:
        for table in tables:
            conn.execute(text(f"DELETE FROM {table}"))
    click.echo(f"Cleared {len(tables)} tables.")


@database.group(invoke_without_command=True)
@click.pass_context
def snapshot(ctx: click.Context) -> None:
    """Create a timestamped snapshot, or manage snapshots (use 'snapshot list')."""
    if ctx.invoked_subcommand is not None:
        return

    import sqlite3  # noqa: PLC0415

    from datetime import datetime  # noqa: PLC0415

    db_path = _get_db_path()
    if not db_path.exists():
        click.echo(f"Database not found: {db_path}", err=True)
        raise SystemExit(1)

    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    dest = db_path.with_suffix(f".snapshot.{ts}")

    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    click.echo(f"Snapshot: {dest}")


@snapshot.command("list")
def snapshot_list() -> None:
    """List available database snapshots."""
    db_path = _get_db_path()

    pattern = f"{db_path.stem}.snapshot.*"
    files = sorted(db_path.parent.glob(pattern), reverse=True)
    if not files:
        click.echo("No snapshots found.")
        return
    for f in files:
        size_kb = f.stat().st_size / 1024
        click.echo(f"  {f.name}  ({size_kb:.0f} KB)")


@database.command()
@click.option("--name", required=True, help="Snapshot filename to restore.")
@click.option("--yes", is_flag=True, help="Confirm destructive operation.")
def restore(name: str, yes: bool) -> None:
    """Restore database from a snapshot. Refuses if service is running."""
    if not yes:
        click.echo("This will overwrite the current database. Pass --yes to confirm.")
        raise SystemExit(1)

    import sqlite3  # noqa: PLC0415

    import httpx  # noqa: PLC0415

    from ..core.config import settings  # noqa: PLC0415

    checks = [
        (settings.port, "/internal/health"),
        (settings.worker_port, "/health"),
    ]
    for check_port, path in checks:
        try:
            httpx.get(f"http://127.0.0.1:{check_port}{path}", timeout=2.0)
            click.echo(
                "Service is running. Stop it first: vaultspec service stop", err=True
            )
            raise SystemExit(1)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            pass

    db_path = _get_db_path()
    snapshot_path = db_path.parent / name
    if not snapshot_path.resolve().is_relative_to(db_path.parent.resolve()):
        click.echo("Invalid snapshot name.", err=True)
        raise SystemExit(1)
    if not snapshot_path.exists():
        click.echo(f"Snapshot not found: {snapshot_path}", err=True)
        raise SystemExit(1)

    src_conn = sqlite3.connect(str(snapshot_path))
    dst_conn = sqlite3.connect(str(db_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    click.echo(f"Restored from {name}.")
