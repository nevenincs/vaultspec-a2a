"""What a scope hands a command: credentials by name, settings by file.

A recipe that RUNS the service points it at this checkout's ``.env`` as the
operator's settings file, so a developer's settings arrive whole rather than
through a list of names kept by hand here. A recipe that runs the TEST SUITE
points it at nothing. Both are exercised against a real checkout-shaped
directory and a real child process that reads the settings out of it.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from dev.credentials import (
    ENV_FILE_VARIABLE,
    SCOPES,
    missing_required,
    read_env_file,
    resolve,
)
from dev.process import run_captured
from vaultspec_a2a.control.config import Settings
from vaultspec_a2a.control.settings_base import (
    ENV_FILE_ENV,
    PROJECT_ROOT_ENV,
    env_name,
)

if TYPE_CHECKING:
    from pathlib import Path

#: A setting no credential scope names and no default matches, so its arrival
#: can only be explained by the file having been read as settings.
_SETTING = env_name(Settings, "port")
_VALUE = "17321"

_PROBE = "from vaultspec_a2a.control.config import settings; print(settings.port)"

_TIMEOUT = 300


def _checkout(root: Path) -> Path:
    """Write a checkout-shaped directory: a project marker and a developer's .env."""
    (root / ".vaultspec").mkdir(parents=True, exist_ok=True)
    env_file = root / ".env"
    env_file.write_text(
        f"{_SETTING}={_VALUE}\nVAULTSPEC_A2A_INTERNAL_TOKEN=scope-token\n",
        encoding="utf-8",
    )
    return env_file


def _outside_environment() -> dict[str, str]:
    """This session's environment with every a2a name cleared.

    The suite declares settings of its own; a child that inherited them would
    prove nothing about what the scope handed it.
    """
    return {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("VAULTSPEC_A2A_")
    }


def test_the_name_the_scope_sets_is_the_one_the_settings_read() -> None:
    """Held to the schema, since this module cannot import it to check itself."""
    assert ENV_FILE_VARIABLE == ENV_FILE_ENV


def test_a_service_scope_hands_the_command_the_checkouts_settings(
    tmp_path: Path,
) -> None:
    """A representative non-credential setting reaches a service the scope started."""
    env_file = _checkout(tmp_path)
    base = _outside_environment() | {PROJECT_ROOT_ENV: str(tmp_path)}

    child = resolve(SCOPES["service"], base, read_env_file(env_file), env_file=env_file)
    assert child[ENV_FILE_VARIABLE] == str(env_file)

    completed = run_captured(
        [sys.executable, "-c", _PROBE],
        env=child | {"PYTHONIOENCODING": "utf-8"},
        replace_env=True,
        timeout=_TIMEOUT,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == _VALUE


def test_a_caller_who_named_a_settings_file_keeps_it(tmp_path: Path) -> None:
    """An exported value wins, as it does for every other name a scope grants."""
    env_file = _checkout(tmp_path)
    chosen = tmp_path / "operator.env"
    chosen.write_text("", encoding="utf-8")

    child = resolve(
        SCOPES["service"],
        {ENV_FILE_VARIABLE: str(chosen)},
        read_env_file(env_file),
        env_file=env_file,
    )
    assert child[ENV_FILE_VARIABLE] == str(chosen)


def test_a_settings_file_that_is_not_there_is_never_named(tmp_path: Path) -> None:
    """A file that is not there is not named: the service would refuse it."""
    absent = tmp_path / ".env"
    child = resolve(SCOPES["service"], {}, {}, env_file=absent)
    assert ENV_FILE_VARIABLE not in child


def test_the_test_suite_is_handed_no_settings_file(tmp_path: Path) -> None:
    """A developer's .env never becomes the suite's configuration."""
    env_file = _checkout(tmp_path)
    child = resolve(
        SCOPES["live-tests"], {}, read_env_file(env_file), env_file=env_file
    )
    assert ENV_FILE_VARIABLE not in child
    assert _SETTING not in child


def test_development_fixtures_need_no_application_credentials() -> None:
    """Starting the trace fixture neither requires nor imports service secrets."""
    scope = SCOPES["compose"]
    child = resolve(
        scope,
        {},
        {
            "POSTGRES_PASSWORD": "synthetic-password",
            "VAULTSPEC_A2A_INTERNAL_TOKEN": "synthetic-token",
            "JAEGER_UI_PORT": "18686",
        },
    )
    assert missing_required(scope, child) == []
    assert child == {"JAEGER_UI_PORT": "18686"}
