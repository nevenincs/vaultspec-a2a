"""Configured database URLs are refused at construction when they cannot work.

A URL SQLAlchemy cannot parse, or one naming a backend this project ships no
driver for, is refused while ``Settings`` is built rather than at the first engine
created from it, and the refusal never repeats the credential the URL may carry.
The shipped ``.env.example`` Postgres block must still construct, and the Postgres
drivers stay in their own dependency profile, out of the frozen binary.

These tests drive the real ``Settings`` construction seam through the real
environment variables, and read the shipped files rather than a restatement of
them.
"""

from __future__ import annotations

import ast
import pathlib
import tomllib
from typing import cast

import pytest
from packaging.requirements import Requirement
from pydantic import ValidationError

from ...testing import armed_environment as _environment
from ...testing.factories import build_settings

_ENV_EXAMPLE = pathlib.Path(__file__).resolve().parents[3].parent / ".env.example"
_PROJECT_ROOT = _ENV_EXAMPLE.parent
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"
_FREEZE_SPEC = _PROJECT_ROOT / "packaging/pyinstaller/vaultspec-a2a.spec"

# The example file marks its Postgres deployment as a commented-out block an
# operator uncomments wholesale. Reading it back is the only way to test what is
# actually shipped rather than what this module would have written.
_POSTGRES_BLOCK_HEADING = "# Uncomment for Postgres production"


def _literal_list_assignment(path: pathlib.Path, name: str) -> set[str]:
    """Read one literal module-list assignment without executing a build spec."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            raw_value: object = ast.literal_eval(statement.value)
            assert isinstance(raw_value, list)
            return set(cast("list[str]", raw_value))
    raise AssertionError(f"{path} has no literal {name} assignment")


def test_postgres_server_profile_is_separate_from_the_sqlite_binary_profile() -> None:
    """Keep Postgres drivers in one profile and out of the freeze closure."""
    metadata = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    project = metadata["project"]
    groups = metadata["dependency-groups"]
    server = {
        Requirement(requirement).name.lower().replace("_", "-")
        for requirement in project["optional-dependencies"]["server"]
    }
    base = {
        Requirement(requirement).name.lower().replace("_", "-")
        for requirement in project["dependencies"]
    }
    freeze = {
        Requirement(requirement).name.lower().replace("_", "-")
        for requirement in groups["freeze"]
        if isinstance(requirement, str)
    }

    assert {"asyncpg", "psycopg", "langgraph-checkpoint-postgres"} <= server
    assert {"asyncpg", "psycopg", "langgraph-checkpoint-postgres"}.isdisjoint(base)
    assert {"asyncpg", "psycopg", "langgraph-checkpoint-postgres"}.isdisjoint(freeze)
    assert {
        "asyncpg",
        "psycopg",
        "langgraph.checkpoint.postgres",
    } <= _literal_list_assignment(_FREEZE_SPEC, "excludes")


def test_an_unconvertible_url_fails_at_settings_construction() -> None:
    """A URL SQLAlchemy cannot parse is refused at boot, not at first use.

    Left to the call site, the same configuration reaches the first engine built
    from it; refusing it during construction keeps the failure at boot, where the
    operator is looking.
    """
    with (
        _environment(
            VAULTSPEC_A2A_DATABASE_BACKEND="sqlite",
            VAULTSPEC_A2A_DATABASE_URL="not-a-sqlalchemy-url",
            VAULTSPEC_A2A_CHECKPOINT_BACKEND=None,
            VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL=None,
            VAULTSPEC_A2A_DESKTOP_APP_HOME=None,
        ),
        pytest.raises(
            ValueError,
            match="VAULTSPEC_A2A_DATABASE_URL is not a parseable SQLAlchemy URL",
        ),
    ):
        build_settings(env_file=None)


def test_a_backend_without_a_synchronous_driver_fails_at_construction() -> None:
    """A parseable URL naming an unsupported backend is refused with its name."""
    with (
        _environment(
            VAULTSPEC_A2A_DATABASE_BACKEND="sqlite",
            VAULTSPEC_A2A_DATABASE_URL="sqlite+aiosqlite:///vaultspec.db",
            VAULTSPEC_A2A_CHECKPOINT_BACKEND=None,
            VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL="mysql+aiomysql://u:p@127.0.0.1/db",
            VAULTSPEC_A2A_DESKTOP_APP_HOME=None,
        ),
        pytest.raises(ValueError, match="VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL"),
    ):
        build_settings(env_file=None)


def test_the_construction_failure_never_echoes_the_credential() -> None:
    """An unparseable URL may still carry a secret; this message must not repeat it.

    Scoped to the validator's own message. Pydantic's surrounding ``ValidationError``
    envelope renders ``input_value``, which for a model validator is the whole
    settings input mapping — a disclosure surface shared by every validator on this
    model, and one this derivation cannot fix from inside.
    """
    with (
        _environment(
            VAULTSPEC_A2A_DATABASE_BACKEND="sqlite",
            VAULTSPEC_A2A_DATABASE_URL="::not-a-url::hunter2::",
            VAULTSPEC_A2A_CHECKPOINT_BACKEND=None,
            VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL=None,
            VAULTSPEC_A2A_DESKTOP_APP_HOME=None,
        ),
        pytest.raises(ValidationError) as raised,
    ):
        build_settings(env_file=None)

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


def test_the_shipped_postgres_example_constructs_valid_settings() -> None:
    """Uncommenting the example's Postgres block must produce a usable deployment.

    The example was once copied verbatim into a deployment whose checkpoint URL
    named no driver. The test reads the shipped file rather than a restatement of
    it, so the example and the construction checks cannot drift apart again.
    """
    block = _shipped_postgres_block()

    assert block.keys() >= {
        "VAULTSPEC_A2A_DATABASE_BACKEND",
        "VAULTSPEC_A2A_CHECKPOINT_BACKEND",
        "VAULTSPEC_A2A_DATABASE_URL",
        "VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL",
    }, block

    with _environment(VAULTSPEC_A2A_DESKTOP_APP_HOME=None, **block):
        settings = build_settings(env_file=None)
        assert settings.resolved_database_backend == "postgres"
        assert settings.resolved_checkpoint_backend == "postgres"
        # The LangGraph saver takes the driverless DSN form of the same URL.
        assert settings.checkpoint_connection_string.startswith("postgresql://")
