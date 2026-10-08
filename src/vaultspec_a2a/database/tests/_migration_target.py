"""A real, empty SQLite target for the revision-step migration proofs.

A proof about one revision walks the packaged Alembic chain up and down from
an empty database; a proof about the migrated head takes the root
``migrated_session_factory`` fixture instead. Nothing here stands in for
anything: the target is a real file, brought to each revision by the packaged
chain rather than by ``create_all``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import command
from sqlalchemy.engine import make_url

from ..migrate import build_migration_config

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "downgrade",
    "empty_database_url",
    "synchronous_url",
    "upgrade",
]


def empty_database_url(directory: Path) -> str:
    """Return the async URL of an empty, unmigrated SQLite file in *directory*.

    *directory* must be a test-owned temporary path.
    """
    return f"sqlite+aiosqlite:///{directory / 'application.db'}"


def synchronous_url(url: str) -> str:
    """Return the synchronous equivalent of an async SQLite URL.

    Reflection is a synchronous API, so it reads the same file through the
    stdlib driver.
    """
    return make_url(url).set(drivername="sqlite").render_as_string(hide_password=False)


def upgrade(url: str, revision: str = "head") -> None:
    """Drive the packaged Alembic chain against *url* up to *revision*.

    Synchronous on purpose: ``env.py`` opens an event loop of its own, so this
    must never be called from inside a running one.
    """
    command.upgrade(build_migration_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    """Drive the packaged Alembic chain against *url* down to *revision*."""
    command.downgrade(build_migration_config(url), revision)
