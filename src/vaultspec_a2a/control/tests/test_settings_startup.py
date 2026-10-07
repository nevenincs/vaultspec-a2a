"""What a refused configuration does: where it surfaces, and how it reads.

The settings refuse two kinds of mistake - a settings file named but absent,
and a value of the wrong shape. Both belong to the process that starts the
service, so they are exercised here through real child processes started the
way an operator starts one, rather than by reading the resolution code back.
"""

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from vaultspec_core.config import ConfigurationError

from ...domain_config import DomainSettingsConfig
from ...testing import armed_environment, inherited_environment, run_child, run_cli
from ..config import Settings
from ..settings_base import ENV_FILE_ENV, PROJECT_ROOT_ENV, read_configuration

#: A file name nothing creates, so naming it is always a refusal.
_ABSENT = "no-such-operator-file.env"


def _child_environment(root: Path, **named: str) -> dict[str, str | None]:
    """The environment overlay for a child, with this session's own names cleared.

    The session declares settings of its own; a child started from inside it
    would inherit them and prove nothing about the value under test.
    """
    session = dict.fromkeys(
        name for name in os.environ if name.startswith("VAULTSPEC_A2A_")
    )
    return {
        **session,
        "PYTHONIOENCODING": "utf-8",
        PROJECT_ROOT_ENV: str(root),
        **named,
    }


def _run(
    arguments: list[str], overlay: Mapping[str, str | None]
) -> subprocess.CompletedProcess[str]:
    """Run this interpreter with *arguments* and report the whole outcome."""
    return run_child(
        [sys.executable, *arguments],
        what=f"python {' '.join(arguments[:2])}",
        env=inherited_environment(overlay),
    )


def test_importing_the_domain_module_survives_a_settings_file_that_is_not_there(
    tmp_path: Path,
) -> None:
    """The singleton is built at the first read, so no importer wears the refusal."""
    completed = _run(
        ["-c", "import vaultspec_a2a.domain_config"],
        _child_environment(tmp_path, **{ENV_FILE_ENV: _ABSENT}),
    )
    assert completed.returncode == 0, completed.stderr
    assert "Traceback" not in completed.stderr


def test_the_service_entry_point_reports_one_named_error(tmp_path: Path) -> None:
    """Starting the service names the variable and the file, once, with no traceback."""
    completed = run_cli(
        "serve", env=_child_environment(tmp_path, **{ENV_FILE_ENV: _ABSENT})
    )
    reported = completed.stderr
    assert completed.returncode != 0
    assert "Traceback" not in reported
    assert reported.count("Error:") == 1
    assert ENV_FILE_ENV in reported
    assert str(tmp_path / _ABSENT) in reported


def test_every_rejected_value_is_named_with_its_variable_and_shape(
    tmp_path: Path,
) -> None:
    """Two mistakes are reported together, each as variable, shape and value."""
    with (
        armed_environment(
            **{
                PROJECT_ROOT_ENV: str(tmp_path),
                ENV_FILE_ENV: None,
                "VAULTSPEC_A2A_PORT": "notaport",
                "VAULTSPEC_A2A_WORKER_PORT": "lots",
            }
        ),
        pytest.raises(ConfigurationError) as refusal,
    ):
        read_configuration(Settings)

    reported = str(refusal.value)
    assert "VAULTSPEC_A2A_PORT must be int, got 'notaport'" in reported
    assert "VAULTSPEC_A2A_WORKER_PORT must be int, got 'lots'" in reported
    # The field names pydantic would have reported instead say nothing about
    # which variable to edit, so they are not what an operator is handed.
    assert "\nport " not in reported


def test_a_rejected_domain_value_is_named_with_its_variable_and_shape(
    tmp_path: Path,
) -> None:
    """The behavioural knobs are refused through the same one-line contract."""
    with (
        armed_environment(
            **{
                PROJECT_ROOT_ENV: str(tmp_path),
                ENV_FILE_ENV: None,
                "VAULTSPEC_A2A_MAX_CONCURRENT_THREADS": "lots",
            }
        ),
        pytest.raises(ConfigurationError) as refusal,
    ):
        read_configuration(DomainSettingsConfig)

    assert "VAULTSPEC_A2A_MAX_CONCURRENT_THREADS must be int, got 'lots'" in str(
        refusal.value
    )


def test_a_rejected_credential_is_named_without_its_value(tmp_path: Path) -> None:
    """A refusal that reaches a credential field reports the name, never the secret."""
    with (
        armed_environment(
            **{
                PROJECT_ROOT_ENV: str(tmp_path),
                ENV_FILE_ENV: None,
                "VAULTSPEC_A2A_INTERNAL_TOKEN": "s3cr3t-value",
            }
        ),
        pytest.raises(ConfigurationError) as refusal,
    ):
        read_configuration(Settings, internal_token=["not", "a", "token"])

    assert (
        str(refusal.value)
        == "VAULTSPEC_A2A_INTERNAL_TOKEN must be str, got a redacted value"
    )


def test_the_worker_entry_point_reports_one_named_error(tmp_path: Path) -> None:
    """The worker is its own startup site: the gateway spawns it as its own process.

    Its import chain reaches the telemetry module and the provider factory,
    both of which used to read settings while being imported - so a refusal
    arrived as a traceback from inside the settings library, in a process
    whose stderr the gateway forwards to an operator.
    """
    completed = _run(
        ["-m", "vaultspec_a2a.worker"],
        _child_environment(tmp_path, **{ENV_FILE_ENV: _ABSENT}),
    )
    reported = completed.stderr
    assert completed.returncode == 1
    assert "Traceback" not in reported
    assert reported.count("Error:") == 1
    assert ENV_FILE_ENV in reported
    assert str(tmp_path / _ABSENT) in reported


def test_importing_the_worker_survives_a_settings_file_that_is_not_there(
    tmp_path: Path,
) -> None:
    """Nothing on the worker's import chain reads a setting while being imported."""
    completed = _run(
        ["-c", "import vaultspec_a2a.worker.app"],
        _child_environment(tmp_path, **{ENV_FILE_ENV: _ABSENT}),
    )
    assert completed.returncode == 0, completed.stderr
    assert "Traceback" not in completed.stderr
