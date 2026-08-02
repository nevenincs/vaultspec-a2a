"""Kimi command eligibility follows its current configuration contract."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_DRIVER = """
import json
from vaultspec_a2a.control.config import settings
from vaultspec_a2a.control.health import _eligible_provider_names
from vaultspec_a2a.graph.enums import Provider
from vaultspec_a2a.providers.factory import classify_provider_command
from vaultspec_a2a.providers.model_profiles import probe_provider_readiness

try:
    origin = classify_provider_command(Provider.KIMI)["command_origin"]
except Exception as exc:
    origin = "RAISED %s" % type(exc).__name__

verdict = probe_provider_readiness(Provider.KIMI)
print(json.dumps({
    "temporary_key_configured": settings.kimi_api_key is not None,
    "command_origin": origin,
    "probe_ready": verdict.ready,
    "probe_reason": verdict.reason,
    "eligible": _eligible_provider_names(),
}))
"""

_KIMI_NAMES = (
    "KIMI_API_KEY",
    "KIMI_BASE_URL",
    "KIMI_MODEL_API_KEY",
    "KIMI_MODEL_BASE_URL",
    "KIMI_MODEL_NAME",
    "KIMI_MODEL_MAX_CONTEXT_SIZE",
    "KIMI_MODEL_CAPABILITIES",
)


def _run_probe(tmp_path: Path, definition: dict[str, str]) -> dict[str, Any]:
    """Run the production readiness path with the installed Kimi executable."""
    if shutil.which("kimi") is None:
        pytest.fail("Kimi Code CLI is not installed")
    env = dict(os.environ)
    for name in _KIMI_NAMES:
        env.pop(name, None)
    env.update(definition)
    env["KIMI_CODE_HOME"] = str(tmp_path / "kimi-home")
    completed = subprocess.run(
        [sys.executable, "-c", _DRIVER],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert isinstance(payload, dict)
    return cast("dict[str, Any]", payload)


@pytest.mark.middleware
def test_persisted_config_mode_reaches_command_eligibility(
    tmp_path: Path,
) -> None:
    result = _run_probe(tmp_path, {})

    assert result["temporary_key_configured"] is False
    assert result["command_origin"] == "system_path_executable"
    assert result["probe_ready"] is True
    assert result["probe_reason"] is None
    assert "kimi" in result["eligible"]


@pytest.mark.middleware
def test_complete_temporary_definition_reaches_command_eligibility(
    tmp_path: Path,
) -> None:
    result = _run_probe(
        tmp_path,
        {
            "KIMI_MODEL_NAME": "configured-alias",
            "KIMI_MODEL_API_KEY": "temporary-secret",
            "KIMI_MODEL_BASE_URL": "https://kimi.example.invalid/v1",
        },
    )

    assert result["temporary_key_configured"] is True
    assert result["command_origin"] == "system_path_executable"
    assert result["probe_ready"] is True
    assert result["probe_reason"] is None
    assert "kimi" in result["eligible"]
    assert "temporary-secret" not in repr(result)


@pytest.mark.middleware
def test_partial_temporary_definition_fails_readiness(tmp_path: Path) -> None:
    result = _run_probe(tmp_path, {"KIMI_MODEL_API_KEY": "key"})

    assert result["command_origin"] == "system_path_executable"
    assert result["probe_ready"] is False
    assert result["probe_reason"] == (
        "incomplete Kimi temporary model definition; set KIMI_MODEL_NAME, "
        "KIMI_MODEL_API_KEY, and KIMI_MODEL_BASE_URL together"
    )
    assert "kimi" not in result["eligible"]
