"""The db tooling must migrate an installed distribution, not just a checkout.

The migration action used to read a configuration file resolved four parents up
from ``__file__``.  That arithmetic only lands on a repository root when the
package is imported from ``src/``; the production image installs the wheel
non-editable, so the path resolved inside ``site-packages`` to a file that does
not exist, and every ``migrate`` invocation died before touching the database.
The script location that file names is worse still - it is relative to the
working directory, so even in a checkout the action only worked when run from
the repository root.

These tests pin the module to the project's one migration-configuration
authority: a configuration assembled programmatically, with revision scripts
resolved from installed package data and no file read from outside the package.
They then drive a real Alembic upgrade against a real SQLite file and assert the
schema actually reached head.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.script import ScriptDirectory

import vaultspec_a2a

from ...control import db as control_db
from ...database import migration_script_location
from ...database.models import Base

_PACKAGE_ROOT = Path(vaultspec_a2a.__file__).resolve().parent


def _head_revision() -> str:
    """Return the single head of the packaged revision chain."""
    heads = ScriptDirectory.from_config(
        control_db._alembic_cfg("sqlite+aiosqlite:///:memory:")
    ).get_heads()
    assert len(heads) == 1, f"expected one head, found {sorted(heads)}"
    return heads[0]


def _tables(database: Path) -> set[str]:
    conn = sqlite3.connect(str(database))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def test_the_migration_config_reads_no_file_outside_the_package() -> None:
    """A configuration file is a checkout artefact; the wheel ships without one."""
    cfg = control_db._alembic_cfg("sqlite+aiosqlite:///runtime.db")

    assert cfg.config_file_name is None


def test_the_revision_scripts_resolve_from_installed_package_data() -> None:
    """The script location must be an absolute path inside the installed package."""
    cfg = control_db._alembic_cfg("sqlite+aiosqlite:///runtime.db")
    script_location = cfg.get_main_option("script_location")

    assert script_location is not None
    resolved = Path(script_location)
    assert resolved.is_absolute(), (
        "a working-directory-relative script location breaks every invocation "
        f"made from anywhere but one directory: {script_location}"
    )
    assert resolved.resolve() == migration_script_location().resolve()
    assert resolved.resolve().is_relative_to(_PACKAGE_ROOT)


def test_the_caller_database_url_is_the_one_that_gets_migrated() -> None:
    """The URL handed in is the URL Alembic binds, escaping and all."""
    url = "sqlite+aiosqlite:///C:/Vault Spec/runtime%25.db"
    cfg = control_db._alembic_cfg(url)

    assert cfg.get_main_option("sqlalchemy.url") == url


def test_no_module_constant_points_outside_the_installed_package() -> None:
    """A checkout-relative constant is the defect itself; none may survive here."""
    escaping = {
        name: value
        for name, value in vars(control_db).items()
        if isinstance(value, Path) and not value.resolve().is_relative_to(_PACKAGE_ROOT)
    }

    assert not escaping, (
        "these constants resolve outside the installed package and are absent "
        f"from a non-editable installation: {escaping}"
    )


def test_a_real_upgrade_reaches_head_and_builds_the_declared_schema(
    tmp_path: Path,
) -> None:
    """The action's own seam migrates a real database to the real head revision."""
    database = tmp_path / "tooling.db"

    control_db._migrate_to_head(f"sqlite+aiosqlite:///{database}")

    tables = _tables(database)
    assert tables >= set(Base.metadata.tables)
    assert "alembic_version" in tables

    conn = sqlite3.connect(str(database))
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        conn.close()
    assert version is not None
    assert version[0] == _head_revision()


def test_a_real_upgrade_survives_a_percent_in_the_database_directory(
    tmp_path: Path,
) -> None:
    """Alembic interpolates its options; a literal percent must not be eaten."""
    directory = tmp_path / "capsule%runtime"
    directory.mkdir()
    database = directory / "tooling.db"

    control_db._migrate_to_head(f"sqlite+aiosqlite:///{database}")

    assert _tables(database) >= set(Base.metadata.tables)
