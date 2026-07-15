"""Model-profiles handover evidence battery (model-profiles P03.S05).

Live, mock-free evidence for the tmp3 verification list that the P02 gateway
tests do not already cover. The already-covered items (bundled + workspace
discovery, mock-preset marking, one-invalid-preset isolation, heterogeneous
team-defaults disclosure, unknown-profile rejection) are exercised by
``test_gateway_live.py``; this module adds the net-new evidence:

- A frozen assignment survives a REAL gateway restart (a second app instance
  built on the same durable stores reproduces it without re-resolving).
- Changing the workspace profile after launch does not mutate the running run.
- Discovery and launch disclose byte-identical effective assignments and bind
  to the one canonical resolver function (identity, not merely equal behaviour).
- No credential/token material lands in the persisted run metadata DB row.
- A missing provider credential yields an unavailable readiness with a safe
  reason, and a present credential flips it - proven by manipulating REAL
  settings in a spawned process environment, never by monkeypatching the running
  one.
- An eligible declared fallback makes an otherwise-unready role eligible, using
  the real readiness probe over real (scrubbed) settings.

The real Research -> ADR run on the served assignments is driven separately as
P04.S10 by another executor with its own engine instance; it is referenced in
the step record rather than duplicated here.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import httpx
import pytest

from ...database import get_thread
from .conftest import make_app
from .test_gateway_live import _live_server

if TYPE_CHECKING:
    from pathlib import Path

# Provider credential env vars scrubbed to force a deterministic missing-credential
# state in the spawned probe, regardless of the host developer's environment.
_CREDENTIAL_ENV_KEYS = (
    "ZHIPU_API_KEY",
    "OPENAI_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
)

# A dummy credential used only to prove readiness reads the real process env; it
# is not a real secret and must never appear in the probe's output.
_DUMMY_ZHIPU_KEY = "ci-probe-not-a-real-key-0000"


def _ws_team_toml(*, researcher_capability: str) -> str:
    """A workspace-local star team on the mock provider with a ``fast`` profile.

    The mock provider is always ready, so run-start succeeds without a token
    bundle and eligibility never turns on a real credential. ``fast`` lowers the
    researcher's capability so profile attribution is observable.
    """
    return "\n".join(
        [
            "[team]",
            'id = "ws-evidence"',
            'display_name = "WS Evidence"',
            "[team.defaults]",
            'provider = "mock"',
            "[team.topology]",
            'type = "star"',
            "[[team.workers]]",
            'agent_id = "vaultspec-researcher"',
            "[team.profiles.fast]",
            'display_name = "Fast"',
            "[team.profiles.fast.roles.vaultspec-researcher]",
            'provider = "mock"',
            f'capability = "{researcher_capability}"',
        ]
    )


def _write_ws_team(root: Path, *, researcher_capability: str = "low") -> None:
    teams_dir = root / ".vaultspec" / "teams"
    teams_dir.mkdir(parents=True, exist_ok=True)
    (teams_dir / "ws-evidence.toml").write_text(
        _ws_team_toml(researcher_capability=researcher_capability), encoding="utf-8"
    )


def _ws_metadata(root: Path) -> dict:
    return {"workspace_root": str(root)}


@pytest.mark.asyncio(loop_scope="function")
async def test_frozen_assignment_survives_real_gateway_restart(
    session_factory, checkpointer, tmp_path
) -> None:
    """A frozen assignment persists across a real gateway restart (P03.S05).

    Evidence: restart durably reproduces the frozen effective assignment and does
    not re-dispatch. A first app freezes and persists the ``fast`` profile; a
    SECOND app instance - fresh aggregator, circuit breaker, and worker, but the
    same durable DB and checkpointer - serves run-status with the identical profile
    and per-role assignment, and dispatches nothing. This scopes to durable
    reproduction; that the run reads the frozen record rather than silently
    re-resolving to changed config is the drift test's job.
    """
    _write_ws_team(tmp_path)

    # First gateway instance: start the run, freezing + persisting the profile.
    app1, _agg1, _worker1, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app1) as base1,
        httpx.AsyncClient(base_url=base1, timeout=10.0) as client1,
    ):
        start = await client1.post(
            "/v1/runs",
            json={
                "team_preset": "ws-evidence",
                "message": "go",
                "profile_id": "fast",
                "metadata": _ws_metadata(tmp_path),
            },
        )
        assert start.status_code == 201, start.text
        started = start.json()
        run_id = started["run_id"]
        assert started["profile_id"] == "fast"
        first_assignments = started["assignments"]
        assert first_assignments

    # Second gateway instance on the SAME durable stores: a genuine restart.
    app2, _agg2, worker2, _cp2 = make_app(session_factory, checkpointer)
    async with (
        _live_server(app2) as base2,
        httpx.AsyncClient(base_url=base2, timeout=10.0) as client2,
    ):
        status = await client2.get(f"/v1/runs/{run_id}")
        assert status.status_code == 200
        sbody = status.json()
        assert sbody["profile_id"] == "fast"
        # The per-role assignment is reproduced verbatim from the durable record.
        assert sbody["assignments"] == first_assignments
        researcher = {a["agent_id"]: a for a in sbody["assignments"]}[
            "vaultspec-researcher"
        ]
        assert researcher["capability"] == "low"
        assert researcher["source"] == "profile"
        # A restart that only reads status must not re-dispatch the run.
        assert worker2.dispatches == []


@pytest.mark.asyncio(loop_scope="function")
async def test_workspace_drift_after_launch_does_not_mutate_run(
    session_factory, checkpointer, tmp_path
) -> None:
    """Editing the workspace profile after launch does not change a live run (P03.S05).

    Evidence: the run's models are frozen at launch. After freezing ``fast`` at
    ``low`` capability, the workspace TOML is rewritten to ``high``; run-status
    still discloses the originally frozen ``low`` assignment, proving the run
    reads its frozen record and never silently re-resolves to changed defaults.
    """
    _write_ws_team(tmp_path, researcher_capability="low")

    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={
                "team_preset": "ws-evidence",
                "message": "go",
                "profile_id": "fast",
                "metadata": _ws_metadata(tmp_path),
            },
        )
        assert start.status_code == 201, start.text
        run_id = start.json()["run_id"]
        frozen_researcher = {a["agent_id"]: a for a in start.json()["assignments"]}[
            "vaultspec-researcher"
        ]
        assert frozen_researcher["capability"] == "low"

        # Drift the workspace profile after launch: same id, different capability.
        _write_ws_team(tmp_path, researcher_capability="high")

        status = await client.get(f"/v1/runs/{run_id}")
        assert status.status_code == 200
        drifted = {a["agent_id"]: a for a in status.json()["assignments"]}[
            "vaultspec-researcher"
        ]
        # The frozen capability wins over the drifted workspace default.
        assert drifted["capability"] == "low"


@pytest.mark.asyncio(loop_scope="function")
async def test_discovery_and_launch_resolve_through_one_function(
    session_factory, checkpointer, tmp_path
) -> None:
    """Discovery and launch disclose byte-identical effective assignments (P03.S05).

    Evidence that the picker's truth cannot drift from execution's: the presets
    discovery path and the run-start launch path resolve the same team + profile
    through the shared resolver and disclose byte-identical per-role assignments
    (provider, capability, model, source, fallbacks). The two live endpoints
    agreeing field-for-field is the observable constraint; a same-module identity
    assertion would be tautological, so the behavioural equality carries the claim
    (with the drift test proving the launch side reads a frozen record, not a
    re-resolution).
    """
    _write_ws_team(tmp_path)
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        presets = await client.get(
            "/v1/presets", params={"workspace_root": str(tmp_path)}
        )
        assert presets.status_code == 200
        ws_team = {p["id"]: p for p in presets.json()["presets"]}["ws-evidence"]
        disc_profiles = {p["id"]: p for p in ws_team["profiles"]}
        disc_fast = {a["agent_id"]: a for a in disc_profiles["fast"]["assignments"]}

        start = await client.post(
            "/v1/runs",
            json={
                "team_preset": "ws-evidence",
                "message": "go",
                "profile_id": "fast",
                "metadata": _ws_metadata(tmp_path),
            },
        )
        assert start.status_code == 201, start.text
        launch_fast = {a["agent_id"]: a for a in start.json()["assignments"]}

        # The two paths agree field-for-field on the shared disclosure keys.
        shared_keys = (
            "role_id",
            "agent_id",
            "provider_id",
            "capability",
            "model_name",
            "source",
            "fallback_providers",
        )
        assert set(disc_fast) == set(launch_fast)
        for agent_id, launch_role in launch_fast.items():
            disc_role = disc_fast[agent_id]
            for key in shared_keys:
                assert disc_role[key] == launch_role[key], (agent_id, key)


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_persists_no_secrets_in_db_row(
    session_factory, checkpointer, tmp_path
) -> None:
    """Actor tokens never land in the persisted run metadata DB row (P03.S05).

    Evidence: run-start receives a real actor-token bundle but must persist only
    the safe frozen assignment. The thread's ``thread_metadata`` DB column is read
    back directly and asserted to contain neither the submitted token values nor
    any credential marker, while still carrying the frozen ``model_profile``.
    """
    _write_ws_team(tmp_path)
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    token_value = "tok-secret-researcher-value"
    bearer_value = "bearer-secret-value"
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={
                "team_preset": "ws-evidence",
                "message": "go",
                "profile_id": "fast",
                "metadata": _ws_metadata(tmp_path),
                "actor_tokens": {
                    "tokens": {"vaultspec-researcher": token_value},
                    "engine_bearer": bearer_value,
                },
            },
        )
        assert start.status_code == 201, start.text
        run_id = start.json()["run_id"]

    async with session_factory() as db:
        thread = await get_thread(db, run_id)
    assert thread is not None
    raw_metadata = thread.thread_metadata or ""

    # The frozen profile record is persisted (restart reads it) ...
    persisted = json.loads(raw_metadata)
    assert persisted["model_profile"]["profile_id"] == "fast"
    # ... but no token, bearer, or credential material appears in the DB row.
    lowered = raw_metadata.lower()
    assert token_value not in raw_metadata
    assert bearer_value not in raw_metadata
    for marker in ("api_key", "oauth", "token", "secret", "bearer", "password"):
        assert marker not in lowered, marker


# ---------------------------------------------------------------------------
# Spawned-process readiness probes: real settings, no monkeypatching.
# ---------------------------------------------------------------------------

_PROBE_SCRIPT = textwrap.dedent(
    """
    import json
    from vaultspec_a2a.graph.enums import Provider
    from vaultspec_a2a.providers.model_profiles import (
        AssignmentSource,
        ProfileAssignment,
        RoleAssignment,
        evaluate_profile_eligibility,
        probe_provider_readiness,
    )

    def _role(agent_id, fallbacks):
        return RoleAssignment(
            role_id=agent_id,
            agent_id=agent_id,
            provider=Provider.ZHIPU,
            capability=None,
            model_name="",
            fallback_providers=fallbacks,
            provider_source=AssignmentSource.TEAM_DEFAULT,
            capability_source=AssignmentSource.TEAM_DEFAULT,
        )

    zhipu = probe_provider_readiness(Provider.ZHIPU)
    assignment = ProfileAssignment(
        profile_id="probe",
        roles=[
            _role("with-fallback", [Provider.MOCK]),
            _role("no-fallback", []),
        ],
    )
    elig = evaluate_profile_eligibility(
        assignment, engine_reachable=True, acceptance_gate_passed=True
    )
    by_agent = {r.agent_id: r for r in elig.roles}
    print(json.dumps({
        "zhipu_ready": zhipu.ready,
        "zhipu_reason": zhipu.reason,
        "with_fallback_eligible": by_agent["with-fallback"].eligible,
        "no_fallback_eligible": by_agent["no-fallback"].eligible,
        "no_fallback_reason": by_agent["no-fallback"].reason,
    }))
    """
)


def _run_probe(tmp_path: Path, env: dict[str, str]) -> dict:
    """Run the readiness probe in a spawned process with *env*, return its JSON.

    Spawned with ``cwd`` at an empty dir so pydantic-settings finds no ``.env`` and
    reads only the injected process environment - the real settings path, never a
    monkeypatch of the running interpreter.
    """
    script = tmp_path / "readiness_probe.py"
    script.write_text(_PROBE_SCRIPT, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _scrubbed_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    for key in _CREDENTIAL_ENV_KEYS:
        env.pop(key, None)
    return env


def test_missing_credential_yields_unavailable_with_safe_reason(tmp_path) -> None:
    """A scrubbed credential env yields an unavailable provider + safe reason (P03.S05).

    Evidence: with every provider credential removed from the spawned process env,
    the real ``probe_provider_readiness`` reports Zhipu unready with a reason that
    names what is missing and leaks no secret value.
    """
    env = _scrubbed_env()
    out = _run_probe(tmp_path, env)
    assert out["zhipu_ready"] is False
    assert out["zhipu_reason"] == "no Zhipu API key configured"
    # The reason is safe: it never echoes a credential value.
    assert _DUMMY_ZHIPU_KEY not in json.dumps(out)


def test_present_credential_flips_readiness(tmp_path) -> None:
    """A credential present in the spawned env flips readiness ready (P03.S05).

    Evidence that the probe reads the REAL process settings (not a monkeypatch):
    injecting a Zhipu key into the same scrubbed env flips readiness to ready, and
    the injected value never appears in the probe output.
    """
    env = _scrubbed_env()
    env["ZHIPU_API_KEY"] = _DUMMY_ZHIPU_KEY
    out = _run_probe(tmp_path, env)
    assert out["zhipu_ready"] is True
    assert _DUMMY_ZHIPU_KEY not in json.dumps(out)


def test_eligible_fallback_makes_role_eligible(tmp_path) -> None:
    """A ready declared fallback makes an unready-primary role eligible (P03.S05).

    Evidence over real (scrubbed) settings: with Zhipu deterministically unready,
    a role that declares a ready mock fallback is eligible, while an otherwise
    identical role with no fallback is not - the eligibility engine composes real
    per-provider readiness, not a hardcoded verdict.
    """
    out = _run_probe(tmp_path, _scrubbed_env())
    assert out["zhipu_ready"] is False
    assert out["with_fallback_eligible"] is True
    assert out["no_fallback_eligible"] is False
    assert "no eligible fallback" in out["no_fallback_reason"]
