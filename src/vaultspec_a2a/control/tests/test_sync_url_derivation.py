"""The synchronous URLs the admin and destructive CLI paths run on must be real.

``database.admin`` builds a synchronous engine straight from ``database_sync_url``
and ``checkpoint_sync_url`` — including inside ``clear``, which deletes rows. The
derivation used to be a substring replace of ``+asyncpg`` with ``+psycopg``, which
is a silent no-op on a URL that declares no driver at all. The shipped
``.env.example`` documented exactly such a URL for the checkpoint store, so an
operator who copied it got a URL SQLAlchemy resolves to its default synchronous
driver, psycopg2 — a package this project does not ship. The failure surfaced as
``ModuleNotFoundError`` part-way through a destructive command.

These tests drive the real ``Settings`` construction seam through the real
environment variables, and assert against SQLAlchemy itself rather than against a
string: a derived URL is only correct if ``create_engine`` can build an engine from
it on a driver this project actually depends on.
"""

from __future__ import annotations

import pathlib

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from ...control.config import Settings
from ...testing import armed_environment as _environment

# The synchronous drivers this project declares in pyproject.toml. psycopg2 is
# absent from that list, and ``aiosqlite`` is asynchronous, so an engine landing on
# either is a broken derivation even when the URL string looks plausible.
_SHIPPED_SYNC_DRIVERS = frozenset({"psycopg", "pysqlite"})

_PG_TAIL = "postgres:postgres@127.0.0.1:5432/vaultspec?sslmode=disable"

# SQLite stores must be absolute — a relative one is refused at construction —
# so the fixtures anchor on this module's own directory rather than a bare name.
_SQLITE_DIR = pathlib.Path(__file__).resolve().parent.as_posix()

_ENV_EXAMPLE = pathlib.Path(__file__).resolve().parents[3].parent / ".env.example"

# The example file marks its Postgres deployment as a commented-out block an
# operator uncomments wholesale. Reading it back is the only way to test what is
# actually shipped rather than what this module would have written.
_POSTGRES_BLOCK_HEADING = "# Uncomment for Postgres production"


def _assert_synchronously_connectable(url: str) -> None:
    """Assert SQLAlchemy builds a synchronous engine on a shipped driver.

    ``create_engine`` imports the DBAPI module eagerly, so this reproduces the
    production failure exactly — without opening a connection to anything.
    """
    engine = create_engine(url)
    try:
        assert engine.dialect.driver in _SHIPPED_SYNC_DRIVERS, (
            f"{url!r} resolved to driver {engine.dialect.driver!r}, which this "
            f"project does not ship; expected one of {sorted(_SHIPPED_SYNC_DRIVERS)}"
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        # The bare scheme is the form the shipped example documented. The old
        # substring replace passed it through untouched.
        (f"postgresql://{_PG_TAIL}", f"postgresql+psycopg://{_PG_TAIL}"),
        (f"postgresql+asyncpg://{_PG_TAIL}", f"postgresql+psycopg://{_PG_TAIL}"),
        # Already synchronous: converting must be idempotent, not doubled.
        (f"postgresql+psycopg://{_PG_TAIL}", f"postgresql+psycopg://{_PG_TAIL}"),
    ],
)
def test_postgres_database_sync_url_names_a_shipped_driver(
    configured: str, expected: str
) -> None:
    """Every admitted Postgres URL form derives a psycopg-driven synchronous URL."""
    with _environment(
        VAULTSPEC_DATABASE_BACKEND="postgres",
        VAULTSPEC_DATABASE_URL=configured,
        VAULTSPEC_CHECKPOINT_BACKEND=None,
        VAULTSPEC_CHECKPOINT_DATABASE_URL=None,
        VAULTSPEC_DESKTOP_APP_HOME=None,
    ):
        derived = Settings(_env_file=None).database_sync_url

    assert derived == expected
    _assert_synchronously_connectable(derived)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (f"postgresql://{_PG_TAIL}", f"postgresql+psycopg://{_PG_TAIL}"),
        (f"postgresql+asyncpg://{_PG_TAIL}", f"postgresql+psycopg://{_PG_TAIL}"),
        (f"postgresql+psycopg://{_PG_TAIL}", f"postgresql+psycopg://{_PG_TAIL}"),
    ],
)
def test_postgres_checkpoint_sync_url_names_a_shipped_driver(
    configured: str, expected: str
) -> None:
    """The dedicated checkpoint URL converts on the same terms as the primary one.

    This is the path ``db clear`` takes, and the one the shipped example broke.
    """
    with _environment(
        VAULTSPEC_DATABASE_BACKEND="postgres",
        VAULTSPEC_DATABASE_URL=f"postgresql+asyncpg://{_PG_TAIL}",
        VAULTSPEC_CHECKPOINT_BACKEND="postgres",
        VAULTSPEC_CHECKPOINT_DATABASE_URL=configured,
        VAULTSPEC_DESKTOP_APP_HOME=None,
    ):
        derived = Settings(_env_file=None).checkpoint_sync_url

    assert derived == expected
    _assert_synchronously_connectable(derived)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (
            f"sqlite+aiosqlite:///{_SQLITE_DIR}/vaultspec.db",
            f"sqlite:///{_SQLITE_DIR}/vaultspec.db",
        ),
        (
            f"sqlite:///{_SQLITE_DIR}/vaultspec.db",
            f"sqlite:///{_SQLITE_DIR}/vaultspec.db",
        ),
        ("sqlite+aiosqlite:///:memory:", "sqlite:///:memory:"),
    ],
)
def test_sqlite_sync_urls_drop_the_asynchronous_driver(
    configured: str, expected: str
) -> None:
    """SQLite URLs lose ``aiosqlite`` and land on the stdlib synchronous driver."""
    with _environment(
        VAULTSPEC_DATABASE_BACKEND="sqlite",
        VAULTSPEC_DATABASE_URL=configured,
        VAULTSPEC_CHECKPOINT_BACKEND=None,
        VAULTSPEC_CHECKPOINT_DATABASE_URL=None,
        VAULTSPEC_DESKTOP_APP_HOME=None,
    ):
        settings = Settings(_env_file=None)
        derived = settings.database_sync_url
        # With no dedicated checkpoint URL the checkpoint store shares the
        # application database, so the same conversion must hold there.
        assert settings.checkpoint_sync_url == expected

    assert derived == expected
    _assert_synchronously_connectable(derived)


def test_conversion_does_not_corrupt_a_password_containing_the_driver_text() -> None:
    """A credential that contains the driver text must survive the conversion.

    Substring replacement rewrites the first match anywhere in the URL. On a URL
    that declares no driver, the first — and only — match is inside the password,
    so the old derivation mangled the credential while leaving the scheme just as
    driverless as it found it. Parsing the URL structurally makes the driver the
    only thing that can change.
    """
    configured = "postgresql://postgres:pw+asyncpg@127.0.0.1:5432/vaultspec"

    with _environment(
        VAULTSPEC_DATABASE_BACKEND="postgres",
        VAULTSPEC_DATABASE_URL=configured,
        VAULTSPEC_CHECKPOINT_BACKEND=None,
        VAULTSPEC_CHECKPOINT_DATABASE_URL=None,
        VAULTSPEC_DESKTOP_APP_HOME=None,
    ):
        derived = Settings(_env_file=None).database_sync_url

    engine = create_engine(derived)
    try:
        assert engine.url.password == "pw+asyncpg"
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()


def test_an_unconvertible_url_fails_at_settings_construction() -> None:
    """A URL with no synchronous equivalent is refused at boot, not at clear-time.

    Left to the call site, the same configuration reaches ``create_engine`` from
    inside a destructive command; refusing it during construction keeps the failure
    away from the data.
    """
    with (
        _environment(
            VAULTSPEC_DATABASE_BACKEND="sqlite",
            VAULTSPEC_DATABASE_URL="not-a-sqlalchemy-url",
            VAULTSPEC_CHECKPOINT_BACKEND=None,
            VAULTSPEC_CHECKPOINT_DATABASE_URL=None,
            VAULTSPEC_DESKTOP_APP_HOME=None,
        ),
        pytest.raises(
            ValueError, match="VAULTSPEC_DATABASE_URL is not a parseable SQLAlchemy URL"
        ),
    ):
        Settings(_env_file=None)


def test_a_backend_without_a_synchronous_driver_fails_at_construction() -> None:
    """A parseable URL naming an unsupported backend is refused with its name."""
    with (
        _environment(
            VAULTSPEC_DATABASE_BACKEND="sqlite",
            VAULTSPEC_DATABASE_URL="sqlite+aiosqlite:///vaultspec.db",
            VAULTSPEC_CHECKPOINT_BACKEND=None,
            VAULTSPEC_CHECKPOINT_DATABASE_URL="mysql+aiomysql://u:p@127.0.0.1/db",
            VAULTSPEC_DESKTOP_APP_HOME=None,
        ),
        pytest.raises(ValueError, match="VAULTSPEC_CHECKPOINT_DATABASE_URL"),
    ):
        Settings(_env_file=None)


def test_the_construction_failure_never_echoes_the_credential() -> None:
    """An unparseable URL may still carry a secret; this message must not repeat it.

    Scoped to the validator's own message. Pydantic's surrounding ``ValidationError``
    envelope renders ``input_value``, which for a model validator is the whole
    settings input mapping — a disclosure surface shared by every validator on this
    model, and one this derivation cannot fix from inside.
    """
    with (
        _environment(
            VAULTSPEC_DATABASE_BACKEND="sqlite",
            VAULTSPEC_DATABASE_URL="::not-a-url::hunter2::",
            VAULTSPEC_CHECKPOINT_BACKEND=None,
            VAULTSPEC_CHECKPOINT_DATABASE_URL=None,
            VAULTSPEC_DESKTOP_APP_HOME=None,
        ),
        pytest.raises(ValidationError) as raised,
    ):
        Settings(_env_file=None)

    messages = [error["msg"] for error in raised.value.errors()]
    assert any("not a parseable SQLAlchemy URL" in message for message in messages)
    assert not any("hunter2" in message for message in messages), messages


def _shipped_postgres_block() -> dict[str, str]:
    """Return the Postgres settings an operator gets by uncommenting the example.

    Collects the commented ``VAULTSPEC_*`` assignments that follow the block's
    heading, stopping at the first line that is not a comment - which is where the
    block ends and the ordinary SQLite-facing settings resume.
    """
    lines = _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if line.startswith(_POSTGRES_BLOCK_HEADING)
    )

    block: dict[str, str] = {}
    for line in lines[start + 1 :]:
        if not line.startswith("#"):
            break
        candidate = line.lstrip("#").strip()
        if candidate.startswith("VAULTSPEC_") and "=" in candidate:
            name, _, value = candidate.partition("=")
            block[name] = value
    return block


def test_the_shipped_postgres_example_yields_working_synchronous_urls() -> None:
    """Uncommenting the example's Postgres block must produce a usable deployment.

    This is the reported defect end to end: the example was copied verbatim, and
    ``db clear`` - a destructive command - died at engine construction because the
    checkpoint URL named no driver. The test reads the shipped file rather than a
    restatement of it, so the example and the derivation cannot drift apart again.
    """
    block = _shipped_postgres_block()

    assert block.keys() >= {
        "VAULTSPEC_DATABASE_BACKEND",
        "VAULTSPEC_CHECKPOINT_BACKEND",
        "VAULTSPEC_DATABASE_URL",
        "VAULTSPEC_CHECKPOINT_DATABASE_URL",
    }, block

    with _environment(VAULTSPEC_DESKTOP_APP_HOME=None, **block):
        settings = Settings(_env_file=None)
        _assert_synchronously_connectable(settings.database_sync_url)
        _assert_synchronously_connectable(settings.checkpoint_sync_url)
        # The LangGraph saver takes the driverless DSN form of the same URL.
        assert settings.checkpoint_connection_string.startswith("postgresql://")
