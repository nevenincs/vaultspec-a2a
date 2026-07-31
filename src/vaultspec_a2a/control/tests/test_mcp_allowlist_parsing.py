"""Environment parsing for the MCP transport-security allowlists.

These are the first env-aliased ``list[str]`` settings in the config, and
pydantic-settings decodes such a field as JSON before any validator sees it.
The obvious operator spelling - ``a,b`` - therefore raised ``SettingsError``
while the module was still importing and took the process down before it could
serve anything.

That failure mode is process startup, so it is tested at process startup: each
case launches a REAL interpreter with a REAL environment and imports the REAL
settings module. No mocks, and no in-process environment patching that would
prove only that a validator runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_HOSTS = "VAULTSPEC_MCP_ALLOWED_HOSTS"
_ORIGINS = "VAULTSPEC_MCP_ALLOWED_ORIGINS"

# Reads both allowlists back out of a freshly imported settings module and
# prints them as JSON, so the assertion sees what a booting service would.
_PROGRAM = (
    "import json;"
    "from vaultspec_a2a.control.config import settings;"
    "print(json.dumps({"
    "'hosts': settings.mcp_allowed_hosts,"
    "'origins': settings.mcp_allowed_origins}))"
)


def _boot(cwd: Path, **env_extra: str) -> dict[str, list[str]]:
    """Import the settings module in a fresh process and return the allowlists.

    Runs from an empty directory: ``env_file`` is the literal ``.env`` resolved
    against the working directory, so a repository ``.env`` would otherwise
    decide the answer instead of the case under test.
    """
    env = {k: v for k, v in os.environ.items() if k not in (_HOSTS, _ORIGINS)}
    env.update(env_extra)

    completed = subprocess.run(
        [sys.executable, "-c", _PROGRAM],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=cwd,
        check=False,
    )
    assert completed.returncode == 0, (
        f"settings import failed (rc={completed.returncode}):\n{completed.stderr}"
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_comma_separated_values_boot(tmp_path: Path) -> None:
    """The documented ``.env`` spelling must boot rather than crash."""
    result = _boot(
        tmp_path,
        **{
            _HOSTS: "localhost:*, mcp.internal:*",
            _ORIGINS: "http://localhost:*,https://ide.internal",
        },
    )

    assert result["hosts"] == ["localhost:*", "mcp.internal:*"]
    assert result["origins"] == ["http://localhost:*", "https://ide.internal"]


def test_json_array_is_still_honoured(tmp_path: Path) -> None:
    """A JSON array must not be shredded into malformed comma items."""
    result = _boot(tmp_path, **{_HOSTS: '["a.internal:*", "b.internal:*"]'})

    assert result["hosts"] == ["a.internal:*", "b.internal:*"]


def test_single_value_needs_no_separator(tmp_path: Path) -> None:
    result = _boot(tmp_path, **{_HOSTS: "only.internal:*"})

    assert result["hosts"] == ["only.internal:*"]


def test_defaults_admit_loopback_only(tmp_path: Path) -> None:
    """An unset environment must not widen the allowlist beyond loopback."""
    result = _boot(tmp_path)

    assert result["hosts"] == ["localhost:*", "127.0.0.1:*"]
    assert result["origins"] == ["http://localhost:*", "http://127.0.0.1:*"]


@pytest.mark.parametrize(
    "hostile",
    ["attacker.example", "attacker.example:*", "*"],
    ids=["bare-host", "wildcard-port", "everything"],
)
def test_default_allowlist_excludes_public_hosts(hostile: str, tmp_path: Path) -> None:
    """The shipped default must not already contain a non-loopback entry.

    Guards the direction that matters: a future edit widening the default would
    disable rebinding protection everywhere without any test turning red.
    """
    assert hostile not in _boot(tmp_path)["hosts"]
