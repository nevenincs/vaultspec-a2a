"""Programmatic Alembic migration runner.

Provides ``run_migrations()`` for applying pending schema upgrades at
application startup.  Uses ``asyncio.to_thread`` to avoid blocking the
event loop — Alembic's ``command.upgrade`` is synchronous internally.

The migration scripts ship as package data under
``vaultspec_a2a.database.migrations`` and are resolved through
``importlib.resources`` so a clean installed capsule (no source checkout and no
repo-root ``alembic.ini``) can upgrade its own schema.  The repo-root
``alembic.ini`` remains the developer CLI entry point; it points at the same
in-package script directory but is never required at runtime.
"""

import asyncio
import logging
from importlib import resources
from pathlib import Path
from threading import Lock

from alembic import command
from alembic.config import Config

__all__ = ["build_migration_config", "migration_script_location", "run_migrations"]

logger = logging.getLogger(__name__)

# The migration scripts are package data, not a checkout-relative directory.
_MIGRATIONS_PACKAGE = "vaultspec_a2a.database.migrations"
_MISSING_MIGRATIONS_MESSAGE = (
    "Alembic migration package data is unavailable or incomplete; reinstall "
    "vaultspec-a2a from a complete distribution"
)
_MIGRATION_LOCK = Lock()


def _alembic_option(value: str) -> str:
    """Escape literal percent signs for Alembic's interpolating parser."""
    return value.replace("%", "%%")


def migration_script_location() -> Path:
    """Return the installed migration script directory.

    Resolved from the ``vaultspec_a2a.database.migrations`` package through
    ``importlib.resources`` so the location is valid whether the code runs from
    a source checkout or a clean installed wheel.  Wheels install unzipped, so
    the traversable is a real filesystem directory that Alembic can read.
    """
    try:
        script_location = Path(str(resources.files(_MIGRATIONS_PACKAGE)))
    except (ModuleNotFoundError, TypeError) as exc:
        raise FileNotFoundError(_MISSING_MIGRATIONS_MESSAGE) from exc

    if not (
        script_location.is_dir()
        and (script_location / "env.py").is_file()
        and (script_location / "versions").is_dir()
    ):
        raise FileNotFoundError(_MISSING_MIGRATIONS_MESSAGE)
    return script_location


def build_migration_config(database_url: str) -> Config:
    """Build an Alembic ``Config`` bound to the package-owned scripts.

    The configuration is assembled programmatically rather than read from a
    repo-root ``alembic.ini``: ``script_location`` points at the installed
    migration package and ``sqlalchemy.url`` carries the caller's database URL.
    No config file is attached, so ``env.py`` skips ``fileConfig`` and the
    application's own logging configuration remains authoritative.

    Args:
        database_url: Full SQLAlchemy URL, e.g.
            ``sqlite+aiosqlite:///path/to/vaultspec.db``.
    """
    script_location = migration_script_location()
    cfg = Config()
    cfg.set_main_option("script_location", _alembic_option(str(script_location)))
    cfg.set_main_option("sqlalchemy.url", _alembic_option(database_url))
    return cfg


def _upgrade_to_head(cfg: Config) -> None:
    """Run Alembic while holding its process-wide command-context lock."""
    with _MIGRATION_LOCK:
        command.upgrade(cfg, "head")


async def run_migrations(database_url: str) -> None:
    """Apply any pending Alembic migrations.

    Args:
        database_url: Full SQLAlchemy URL, e.g.
            ``sqlite+aiosqlite:///path/to/vaultspec.db``.

    Raises:
        FileNotFoundError: If the packaged migration scripts are not present.
    """
    cfg = build_migration_config(database_url)

    logger.info("Running Alembic migrations (upgrade head)...")
    await asyncio.to_thread(_upgrade_to_head, cfg)
    logger.info("Alembic migrations complete")
