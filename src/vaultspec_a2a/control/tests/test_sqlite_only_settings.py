"""SQLite is the only store, and every input that asks for another is refused.

A retired backend selector, a retired requirement flag and a store URL naming
another database are each refused when the settings load, with an error that
names SQLite as the only store. None is ignored and none is translated, and a
stale pool setting from the older example still loads. A URL SQLAlchemy cannot
parse is refused at the same seam, and no refusal repeats the credential a URL
may carry.

These tests drive the real settings load over real environment variables, and
read the refusal the way the service reports it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from vaultspec_core.config import ConfigurationError

from ...testing import armed_environment, build_settings
from ..config import Settings
from ..settings_base import ENV_FILE_ENV, PROJECT_ROOT_ENV, read_configuration

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from pathlib import Path

_STORE_NAMES = (
    "VAULTSPEC_A2A_DATABASE_BACKEND",
    "VAULTSPEC_A2A_CHECKPOINT_BACKEND",
    "VAULTSPEC_A2A_POSTGRES_REQUIRED",
    "VAULTSPEC_A2A_DATABASE_URL",
    "VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL",
    "VAULTSPEC_A2A_DESKTOP_APP_HOME",
)

_SECRET = "s3cr3t-db-password"
_ONLY_SQLITE = "SQLite is the only supported store"


def _stores(root: Path, **values: str | None) -> AbstractContextManager[None]:
    """Return the environment of an unarmed project, plus the store inputs given."""
    return armed_environment(
        **{
            **dict.fromkeys(_STORE_NAMES),
            PROJECT_ROOT_ENV: str(root),
            ENV_FILE_ENV: None,
            **values,
        }
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("VAULTSPEC_A2A_DATABASE_BACKEND", "postgres"),
        ("VAULTSPEC_A2A_CHECKPOINT_BACKEND", "postgres"),
        ("VAULTSPEC_A2A_POSTGRES_REQUIRED", "true"),
        (
            "VAULTSPEC_A2A_DATABASE_URL",
            f"postgresql+asyncpg://postgres:{_SECRET}@db.example:5432/vaultspec",
        ),
        (
            "VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL",
            f"postgresql+psycopg://postgres:{_SECRET}@db.example:5432/vaultspec",
        ),
    ],
    ids=[
        "database-backend",
        "checkpoint-backend",
        "required-flag",
        "database-url",
        "checkpoint-url",
    ],
)
def test_a_postgres_input_fails_the_settings_load_naming_sqlite(
    tmp_path: Path, name: str, value: str
) -> None:
    with (
        _stores(tmp_path, **{name: value}),
        pytest.raises(ConfigurationError) as refusal,
    ):
        read_configuration(Settings)

    reported = str(refusal.value)
    assert name in reported
    assert _ONLY_SQLITE in reported
    assert _SECRET not in reported


def test_every_refused_input_is_reported_in_one_pass(tmp_path: Path) -> None:
    with (
        _stores(
            tmp_path,
            VAULTSPEC_A2A_DATABASE_BACKEND="postgres",
            VAULTSPEC_A2A_CHECKPOINT_BACKEND="postgres",
            VAULTSPEC_A2A_POSTGRES_REQUIRED="true",
            VAULTSPEC_A2A_DATABASE_URL="postgresql://db.example/vaultspec",
        ),
        pytest.raises(ConfigurationError) as refusal,
    ):
        read_configuration(Settings)

    reported = str(refusal.value)
    for name in (
        "VAULTSPEC_A2A_DATABASE_BACKEND",
        "VAULTSPEC_A2A_CHECKPOINT_BACKEND",
        "VAULTSPEC_A2A_POSTGRES_REQUIRED",
        "VAULTSPEC_A2A_DATABASE_URL",
    ):
        assert name in reported


def test_the_sqlite_spellings_of_the_retired_settings_still_load(
    tmp_path: Path,
) -> None:
    with _stores(
        tmp_path,
        VAULTSPEC_A2A_DATABASE_BACKEND="sqlite",
        VAULTSPEC_A2A_CHECKPOINT_BACKEND="sqlite",
        VAULTSPEC_A2A_POSTGRES_REQUIRED="false",
    ):
        loaded = read_configuration(Settings)

    assert loaded.database_backend == "sqlite"
    assert loaded.checkpoint_backend == "sqlite"
    assert loaded.postgres_required is False


def test_a_pool_setting_from_the_older_example_is_ignored(tmp_path: Path) -> None:
    """The pool sized an engine that no longer exists; it must not stop a start."""
    with _stores(
        tmp_path,
        VAULTSPEC_A2A_DB_POOL_SIZE="5",
        VAULTSPEC_A2A_DB_POOL_MAX_OVERFLOW="10",
    ):
        loaded = read_configuration(Settings)

    assert loaded.database_backend == "sqlite"


def test_an_unparseable_url_fails_at_settings_construction(tmp_path: Path) -> None:
    """A URL SQLAlchemy cannot parse is refused at boot, not at first use."""
    with (
        _stores(tmp_path, VAULTSPEC_A2A_DATABASE_URL="not-a-sqlalchemy-url"),
        pytest.raises(
            ValueError,
            match="VAULTSPEC_A2A_DATABASE_URL is not a parseable SQLAlchemy URL",
        ),
    ):
        build_settings(env_file=None)


def test_a_url_naming_another_database_is_refused_with_its_backend(
    tmp_path: Path,
) -> None:
    with (
        _stores(
            tmp_path,
            VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL="mysql+aiomysql://u:p@127.0.0.1/db",
        ),
        pytest.raises(
            ValueError, match="VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL"
        ) as raised,
    ):
        build_settings(env_file=None)

    assert "'mysql'" in str(raised.value)


def test_the_refusal_never_echoes_the_credential(tmp_path: Path) -> None:
    """An unparseable URL may still carry a secret; this message must not repeat it.

    Scoped to the validator's own message. Pydantic's surrounding
    ``ValidationError`` envelope renders ``input_value``, which for a model
    validator is the whole settings input mapping - a disclosure surface shared
    by every validator on this model, and one this check cannot fix from inside.
    """
    with (
        _stores(tmp_path, VAULTSPEC_A2A_DATABASE_URL="::not-a-url::hunter2::"),
        pytest.raises(ValidationError) as raised,
    ):
        build_settings(env_file=None)

    messages = [error["msg"] for error in raised.value.errors()]
    assert any("not a parseable SQLAlchemy URL" in message for message in messages)
    assert not any("hunter2" in message for message in messages), messages


def test_a_sqlite_store_url_loads(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'store.db').as_posix()}"
    with _stores(tmp_path, VAULTSPEC_A2A_DATABASE_URL=url):
        loaded = build_settings(env_file=None)

    assert loaded.database_url == url
