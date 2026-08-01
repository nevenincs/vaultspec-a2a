"""Admission-gate provider eligibility must gate on credentials, not just commands.

The divergent input is a provider whose launch command resolves on this host
while its credential is absent. A command-only eligibility check calls that
provider eligible, so the staged admission gate admits the run and reserves one
of its bounded slots; the credential-aware gate applied at launch then refuses
it. These tests drive that exact input through a real interpreter with a real
executable on ``PATH`` and a controlled environment - no patching, no fakes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# Resolving the Kimi command additionally requires the CLI's Git-Bash shell.
# Pointing the CLI's own override at a real file keeps the command half of the
# input true on any host, including one without Git installed.
_GIT_BASH_ENV = "KIMI_CLI_GIT_BASH_PATH"
_CREDENTIAL_ENV = "KIMI_API_KEY"

_DRIVER = """
import json
from vaultspec_a2a.control.config import settings
from vaultspec_a2a.control.health import _eligible_provider_names
from vaultspec_a2a.graph.enums import Provider
from vaultspec_a2a.providers.factory import classify_provider_command
from vaultspec_a2a.providers.model_profiles import probe_provider_readiness

try:
    origin = classify_provider_command(Provider.KIMI)["command_origin"]
except Exception as exc:  # noqa: BLE001 - reported verbatim to the assertions
    origin = "RAISED %s: %s" % (type(exc).__name__, exc)

verdict = probe_provider_readiness(Provider.KIMI)
print(json.dumps({
    "credential_configured": settings.kimi_api_key is not None,
    "command_origin": origin,
    "probe_ready": verdict.ready,
    "probe_reason": verdict.reason,
    "eligible": _eligible_provider_names(),
}))
"""


def _stub_cli(directory: Path) -> None:
    """Install a real, resolvable ``kimi`` executable into *directory*.

    A genuine file that ``shutil.which`` finds through real ``PATH`` resolution.
    It is never executed: command classification resolves the path and stops, so
    this exercises the production resolver rather than standing in for it.
    """
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        (directory / "kimi.cmd").write_text("@echo off\n", encoding="utf-8")
        return
    executable = directory / "kimi"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)


def _run_probe(tmp_path: Path, *, credential: str | None) -> dict[str, Any]:
    """Report eligibility from a real interpreter under a controlled environment."""
    bin_dir = tmp_path / "bin"
    _stub_cli(bin_dir)
    git_bash = tmp_path / "bash.exe"
    git_bash.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env[_GIT_BASH_ENV] = str(git_bash)
    if credential is None:
        env.pop(_CREDENTIAL_ENV, None)
    else:
        env[_CREDENTIAL_ENV] = credential

    # Settings load ``.env`` relative to the process working directory, so
    # running from an empty directory keeps the repository's own .env out and
    # leaves this environment the only source of the credential.
    completed = subprocess.run(
        [sys.executable, "-c", _DRIVER],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, (
        f"probe failed ({completed.returncode})\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert isinstance(payload, dict)
    return payload


@pytest.mark.middleware
def test_resolvable_command_without_credential_is_not_eligible(tmp_path: Path) -> None:
    """The divergent input: command resolvable, credential absent, not eligible.

    This is the whole defect. The command half must genuinely resolve - asserted
    here rather than assumed - so a pass cannot come from the provider being
    unresolvable for some unrelated reason.
    """
    result = _run_probe(tmp_path, credential=None)

    assert result["credential_configured"] is False
    # The command half of the divergent input is genuinely true.
    assert result["command_origin"] == "system_path_executable"
    # The credential-aware resolver says no...
    assert result["probe_ready"] is False
    assert result["probe_reason"] == "no Kimi API key configured"
    # ...and admission eligibility must now agree with it.
    assert "kimi" not in result["eligible"]


@pytest.mark.middleware
def test_resolvable_command_with_credential_is_eligible(tmp_path: Path) -> None:
    """The same host with the credential present admits the provider.

    Without this the negative case above would also pass if eligibility simply
    never named the provider, which would be a tautology rather than a fix.
    """
    result = _run_probe(tmp_path, credential="test-kimi-key")

    assert result["credential_configured"] is True
    assert result["command_origin"] == "system_path_executable"
    assert result["probe_ready"] is True
    assert "kimi" in result["eligible"]
