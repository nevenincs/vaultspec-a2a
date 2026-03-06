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


__all__ = ["run_migrations"]

logger = logging.getLogger(__name__)

# alembic.ini lives at the repo root (team-lead decision)
_ALEMBIC_INI = Path(__file__).resolve().parent.parent.parent.parent / "alembic.ini"


async def run_migrations(database_url: str) -> None:
    """Apply any pending Alembic migrations.

    Args:
        database_url: Full SQLAlchemy URL, e.g.
            ``sqlite+aiosqlite:///path/to/vaultspec.db``.

    Raises:
        FileNotFoundError: If ``alembic.ini`` is not found at the repo root.
    """
    if not _ALEMBIC_INI.exists():
        msg = f"alembic.ini not found at {_ALEMBIC_INI}; ensure it exists at the repo root"
        raise FileNotFoundError(msg)

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)

    logger.info("Running Alembic migrations (upgrade head)...")
    await asyncio.to_thread(command.upgrade, cfg, "head")
    logger.info("Alembic migrations complete")
