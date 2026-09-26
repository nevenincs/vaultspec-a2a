"""Where a setting may come from, and where a credential may come from.

Every case runs against real directories and real files. The gate that opens a
project's ``.env`` turns on which interpreter is running, so the two cases that
exercise it build a real interpreter inside the workspace and read the settings
in that process rather than describing the condition to the one running the
suite.
"""

import json
import os
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path
from typing import Protocol, cast

import pytest
import vaultspec_core
from vaultspec_core.config import ConfigurationError

from ...testing import armed_environment
from ..config import Settings
from ..env_registry import CREDENTIAL_VARIABLES
from ..settings_base import ENV_FILE_ENV, PROJECT_ROOT_ENV, field_env_names

#: The source root of the package under test, as this file's own location
#: reports it: src/vaultspec_a2a/control/tests/.
_SOURCE_ROOT = Path(__file__).parents[3]

#: A value no provider would accept, so a lane cannot be reached even if one
#: of these workspaces outlived the test.
_SENTINEL = "workspace-dotenv-sentinel"

#: The credential name and the setting name written side by side into every
#: workspace ``.env`` below, so each case proves what the file does supply and
#: what it does not in one reading.
_CREDENTIAL_NAME = "VAULTSPEC_A2A_OPENAI_API_KEY"
_SETTING_NAME = "VAULTSPEC_A2A_PORT"
_SETTING_VALUE = "12345"

_DEFAULT_PORT = 18000

_PROBE = """
import json
import sys

from vaultspec_a2a.control.config import Settings

configured = Settings()
print(
    json.dumps(
        {
            "credential_supplied": configured.openai_api_key == sys.argv[1],
            "port": configured.port,
        }
    )
)
"""


class _SettingsEnvFileFactory(Protocol):
    """``Settings`` called with pydantic-settings' private ``_env_file`` argument."""

    def __call__(self, *, _env_file: Path) -> Settings: ...


def _workspace_dotenv(root: Path) -> None:
    """Write a project ``.env`` carrying one credential and one setting."""
    (root / ".env").write_text(
        f"{_CREDENTIAL_NAME}={_SENTINEL}\n{_SETTING_NAME}={_SETTING_VALUE}\n",
        encoding="utf-8",
    )


def _declare_dev_mode(root: Path) -> Path:
    """Declare that the workspace runs this package from its own environment."""
    declaration = root / ".vaultspec" / "workspace.json"
    declaration.parent.mkdir(parents=True, exist_ok=True)
    declaration.write_text(
        json.dumps(
            {
                "schema_version": "2.2",
                "packages": {"vaultspec-a2a": {"install_mode": "dev"}},
            }
        ),
        encoding="utf-8",
    )
    return declaration


def _interpreter_inside(root: Path) -> Path:
    """Create a real virtual environment in *root* and return its interpreter."""
    builder = venv.EnvBuilder(with_pip=False)
    builder.create(root / ".venv")
    context = builder.ensure_directories(root / ".venv")
    return Path(context.env_exe)


def _read_settings_with(interpreter: Path, root: Path) -> dict[str, object]:
    """Build the settings in *interpreter* against *root* and report the outcome."""
    probe = root / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    # The interpreter is a bare environment, so the packages under test and
    # their dependencies are named on the path rather than installed again.
    path = (
        sysconfig.get_paths()["purelib"],
        str(_SOURCE_ROOT),
        str(Path(vaultspec_core.__file__).parents[1]),
    )
    completed = subprocess.run(
        [str(interpreter), str(probe), _SENTINEL],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
        env={
            "PATH": str(interpreter.parent),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHONPATH": ";".join(path) if sys.platform == "win32" else ":".join(path),
            "PYTHONIOENCODING": "utf-8",
            PROJECT_ROOT_ENV: str(root),
        },
    )
    assert completed.returncode == 0, completed.stderr
    return cast("dict[str, object]", json.loads(completed.stdout))


def test_the_workspace_dotenv_supplies_no_setting(tmp_path: Path) -> None:
    _workspace_dotenv(tmp_path)
    with armed_environment(
        **{PROJECT_ROOT_ENV: str(tmp_path), _SETTING_NAME: None, ENV_FILE_ENV: None}
    ):
        configured = Settings()
    assert configured.port == _DEFAULT_PORT


def test_the_workspace_dotenv_reaches_no_outside_interpreter(tmp_path: Path) -> None:
    """The suite's own interpreter lives outside the workspace, so the gate is shut."""
    _workspace_dotenv(tmp_path)
    _declare_dev_mode(tmp_path)
    with armed_environment(
        **{
            PROJECT_ROOT_ENV: str(tmp_path),
            _CREDENTIAL_NAME: None,
            "OPENAI_API_KEY": None,
            ENV_FILE_ENV: None,
        }
    ):
        configured = Settings()
    assert configured.openai_api_key is None


def test_the_gate_admits_the_workspaces_own_interpreter(tmp_path: Path) -> None:
    """A dev-mode workspace read from its own interpreter supplies the credential.

    And only the credential: the setting beside it in the same file is ignored
    on both sides of the gate.
    """
    _workspace_dotenv(tmp_path)
    declaration = _declare_dev_mode(tmp_path)
    interpreter = _interpreter_inside(tmp_path)

    opened = _read_settings_with(interpreter, tmp_path)

    declaration.unlink()
    closed = _read_settings_with(interpreter, tmp_path)

    assert opened == {"credential_supplied": True, "port": _DEFAULT_PORT}
    assert closed == {"credential_supplied": False, "port": _DEFAULT_PORT}


def test_an_operator_file_the_environment_names_supplies_settings(
    tmp_path: Path,
) -> None:
    operator = tmp_path / "operator.env"
    operator.write_text(f"{_SETTING_NAME}={_SETTING_VALUE}\n", encoding="utf-8")
    with armed_environment(
        **{
            PROJECT_ROOT_ENV: str(tmp_path),
            ENV_FILE_ENV: str(operator),
            _SETTING_NAME: None,
        }
    ):
        configured = Settings()
    assert configured.port == int(_SETTING_VALUE)


def test_the_operator_file_is_resolved_against_the_project_root(
    tmp_path: Path,
) -> None:
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "operator.env").write_text(
        f"{_SETTING_NAME}={_SETTING_VALUE}\n", encoding="utf-8"
    )
    with armed_environment(
        **{
            PROJECT_ROOT_ENV: str(tmp_path),
            ENV_FILE_ENV: "deploy/operator.env",
            _SETTING_NAME: None,
        }
    ):
        configured = Settings()
    assert configured.port == int(_SETTING_VALUE)


def test_the_process_environment_outranks_the_operator_file(tmp_path: Path) -> None:
    operator = tmp_path / "operator.env"
    operator.write_text(f"{_SETTING_NAME}={_SETTING_VALUE}\n", encoding="utf-8")
    with armed_environment(
        **{
            PROJECT_ROOT_ENV: str(tmp_path),
            ENV_FILE_ENV: str(operator),
            _SETTING_NAME: "19000",
        }
    ):
        configured = Settings()
    assert configured.port == 19000


def test_an_operator_file_that_is_not_there_is_refused(tmp_path: Path) -> None:
    absent = tmp_path / "absent.env"
    with (
        armed_environment(
            **{PROJECT_ROOT_ENV: str(tmp_path), ENV_FILE_ENV: str(absent)}
        ),
        pytest.raises(ConfigurationError) as refusal,
    ):
        Settings()
    assert ENV_FILE_ENV in str(refusal.value)
    assert str(absent) in str(refusal.value)


def test_a_file_the_construction_call_names_that_is_not_there_is_refused(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "absent.env"
    with (
        armed_environment(**{PROJECT_ROOT_ENV: str(tmp_path), ENV_FILE_ENV: None}),
        pytest.raises(ConfigurationError) as refusal,
    ):
        cast("_SettingsEnvFileFactory", Settings)(_env_file=absent)
    assert str(absent) in str(refusal.value)


def test_every_declared_credential_is_spelled_by_its_field(tmp_path: Path) -> None:
    """The schema stays the one declaration of what a credential is called."""
    declared = {
        field: tuple(entry.env_name for entry in entries)
        for field, entries in CREDENTIAL_VARIABLES.items()
    }
    assert declared == {
        field: field_env_names(Settings, field) for field in CREDENTIAL_VARIABLES
    }
