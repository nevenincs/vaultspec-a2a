"""Credential readiness is necessary but never sufficient for served eligibility.

A lane whose credential is present and whose launch command resolves is READY.
Readiness is not admission: the lane is served for execution only once a live
test has completed a real turn on it and the resolved launcher reports a version
the recorded proof admits. Kimi is the installed lane that proves the two
verdicts stay apart - it resolves, it configures, it has handshake coverage
only - so a run of the production readiness path must report it ready and refuse
it as ineligible, under both of its configuration modes.

The readiness path runs in a real child interpreter over a real Kimi install so
the settings it reads are the ones a served gateway would read, with the lane's
whole environment declared per case. Nothing is patched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING, Any, cast

import pytest

from ...testing import inherited_environment

if TYPE_CHECKING:
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule

_DRIVER = """
import json
from vaultspec_a2a.control.config import settings
from vaultspec_a2a.control.health import _eligible_provider_names
from vaultspec_a2a.graph.enums import Provider
from vaultspec_a2a.providers._factory_commands import classify_provider_command
from vaultspec_a2a.providers.lane_admission import (
    PROVEN_TURN_LANES,
    served_lane_eligible,
)
from vaultspec_a2a.providers.provider_readiness import probe_provider_readiness

try:
    origin = classify_provider_command(Provider.KIMI).command_origin
except Exception as exc:
    origin = "RAISED %s" % type(exc).__name__

verdict = probe_provider_readiness(Provider.KIMI)
print(json.dumps({
    "temporary_key_configured": settings.kimi_api_key is not None,
    "command_origin": origin,
    "probe_ready": verdict.ready,
    "probe_reason": verdict.reason,
    "proven": Provider.KIMI in PROVEN_TURN_LANES,
    "served_eligible": served_lane_eligible(Provider.KIMI),
    "eligible": _eligible_provider_names(),
    "proven_names": sorted(lane.value for lane in PROVEN_TURN_LANES),
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


def _run_probe(
    tmp_path: Path,
    definition: dict[str, str],
    external_prerequisite: ExternalPrerequisiteRule,
) -> dict[str, Any]:
    """Run the production readiness path with the installed Kimi executable."""
    external_prerequisite("kimi-cli")
    completed = subprocess.run(
        [sys.executable, "-c", _DRIVER],
        env=inherited_environment(
            {
                **dict.fromkeys(_KIMI_NAMES),
                **definition,
                "KIMI_CODE_HOME": str(tmp_path / "kimi-home"),
            }
        ),
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
def test_a_credentialed_resolvable_lane_without_turn_proof_is_ineligible(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """A complete temporary definition reaches readiness and stops at admission.

    The credential is configured, the launcher resolves, and the lane is still
    refused: eligibility asks whether a live test completed a turn here, which
    for this lane nothing has. The lane stays supported throughout - it
    classifies a command and answers ready - so what is withheld is being
    SERVED, not being runnable.
    """
    result = _run_probe(
        tmp_path,
        {
            "KIMI_MODEL_NAME": "configured-alias",
            "KIMI_MODEL_API_KEY": "temporary-secret",
            "KIMI_MODEL_BASE_URL": "https://kimi.example.invalid/v1",
        },
        external_prerequisite,
    )

    assert result["temporary_key_configured"] is True
    assert result["command_origin"] == "system_path_executable"
    assert result["probe_ready"] is True
    assert result["probe_reason"] is None
    assert result["proven"] is False
    assert result["served_eligible"] is False
    assert "kimi" not in result["eligible"]
    assert "temporary-secret" not in repr(result)


@pytest.mark.middleware
def test_persisted_config_mode_is_ready_and_still_unproven(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """The persisted-config mode reaches command readiness and no further."""
    result = _run_probe(tmp_path, {}, external_prerequisite)

    assert result["temporary_key_configured"] is False
    assert result["command_origin"] == "system_path_executable"
    assert result["probe_ready"] is True
    assert result["probe_reason"] is None
    assert result["served_eligible"] is False
    assert "kimi" not in result["eligible"]


@pytest.mark.middleware
def test_partial_temporary_definition_fails_readiness_before_admission(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """An incomplete definition is refused by readiness, ahead of any proof check."""
    result = _run_probe(tmp_path, {"KIMI_MODEL_API_KEY": "key"}, external_prerequisite)

    assert result["command_origin"] == "system_path_executable"
    assert result["probe_ready"] is False
    assert result["probe_reason"] == (
        "incomplete Kimi temporary model definition; set KIMI_MODEL_NAME, "
        "KIMI_MODEL_API_KEY, and KIMI_MODEL_BASE_URL together"
    )
    assert result["served_eligible"] is False
    assert "kimi" not in result["eligible"]


@pytest.mark.middleware
def test_every_eligible_provider_carries_completed_turn_proof(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Whatever this host serves is a subset of what a live turn has proven.

    Host-independent, and the invariant the credential-only derivation broke: a
    lane could be named eligible on a resolvable command and a present
    credential alone, so a host with Claude or Kimi installed served lanes no
    test had ever completed work on.
    """
    result = _run_probe(tmp_path, {}, external_prerequisite)

    assert set(result["eligible"]) <= set(result["proven_names"])
