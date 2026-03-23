"""Programmatic Alembic migration runner (ADR-029).

Provides ``run_migrations()`` for applying pending schema upgrades at
application startup.  Uses ``asyncio.to_thread`` to avoid blocking the
event loop — Alembic's ``command.upgrade`` is synchronous internally.

References:
    - ADR-029: Database Migration Framework
"""

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from ..control.config import settings

__all__ = ["run_migrations"]

logger = logging.getLogger(__name__)


async def run_migrations(database_url: str) -> None:
    """Apply any pending Alembic migrations.

    Args:
        database_url: Full SQLAlchemy URL, e.g.
            ``sqlite+aiosqlite:///path/to/vaultspec.db``.

    Raises:
        FileNotFoundError: If ``alembic.ini`` is not found at the repo root.
    """
    alembic_ini = Path(settings.project_root) / "alembic.ini"
    if not alembic_ini.exists():
        msg = (
            f"alembic.ini not found at {alembic_ini}; ensure it exists at the repo root"
        )
        raise FileNotFoundError(msg)

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", database_url)

    logger.info("Running Alembic migrations (upgrade head)...")
    await asyncio.to_thread(command.upgrade, cfg, "head")
    logger.info("Alembic migrations complete")
