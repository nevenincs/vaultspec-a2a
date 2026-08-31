"""Selection-freeze and provider-readiness evidence battery.

Live, mock-free evidence that the gateway tests do not already cover. This
battery originally evidenced the retired model-profile contract; each case
either moved with its subject onto the explicit catalog-selection contract or
was retired because the state it guarded is no longer producible:

- A frozen team selection survives a REAL gateway restart (a second app
  instance built on the same durable stores reproduces it byte-for-byte
  without re-dispatching), which is also the catalog-drift immunity evidence:
  the read path consults only the durable record, never a live catalog.
- Launch freezes exactly the SERVED catalog entry: the frozen lane reproduces
  the selection's provider, execution mode, revision, and entry against the
  catalog read the picker consumed, so the picker's truth cannot drift from
  execution's.
- No credential/token material lands in the persisted run metadata DB row.
- A missing provider credential yields an unavailable readiness with a safe
  reason, and a present credential flips it - proven by manipulating REAL
  settings in a spawned process environment, never by monkeypatching the
  running one.
- An eligible declared fallback rescues an unready-but-admissible primary and
  must NOT rescue an unproven one, using the real readiness probe.

Retired with the profile contract, not migrated: the workspace-TOML drift case
(teams no longer carry provider or model policy, and the run envelope is
rebuilt from the durable record alone, so the re-resolution channel it guarded
does not exist) and the discovery/launch shared-resolver case (the profile
resolver is gone; its successor subject is the served-catalog binding above).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from ...database import get_thread
from .conftest import make_app
from .test_gateway_live import _PRESET, _live_server, _run_fields

if TYPE_CHECKING:
    from pathlib import Path

# Provider credential env vars neutralised to force a deterministic
# missing-credential state in the spawned probe. Settings pin their dotenv
# source to the checkout root, so a spawned process cannot escape it by cwd
# alone; each key is instead OVERRIDDEN with an empty value, which outranks the
# dotenv layer in the real settings resolution order.
_CREDENTIAL_ENV_KEYS = (
    "ZHIPU_API_KEY",
    "ZAI_AUTH_TOKEN",
    "ZAI_API_KEY",
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


@pytest.mark.asyncio(loop_scope="function")
async def test_frozen_selection_survives_real_gateway_restart(
    session_factory, checkpointer
) -> None:
    """A frozen team selection persists across a real gateway restart.

    Evidence: restart durably reproduces the frozen execution authority and
    does not re-dispatch. A first app freezes and persists the explicit
    selection; a SECOND app instance - fresh aggregator, circuit breaker, and
    worker, but the same durable DB and checkpointer - serves run-status with
    the byte-identical freeze and dispatches nothing. The second instance
    never consults a catalog on this path, which is the drift-immunity claim
    made concrete: what a run launched with cannot change because the world
    did.
    """
    app1, _agg1, _worker1, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app1) as base1,
        httpx.AsyncClient(base_url=base1, timeout=10.0) as client1,
    ):
        start = await client1.post(
            "/v1/runs",
            json={
                "run_id": "evidence-restart",
                "team_preset": _PRESET,
                "message": "go",
                "autonomous": True,
                **await _run_fields(client1),
            },
        )
        assert start.status_code == 201, start.text
        frozen = start.json()["frozen_assignment"]
        assert frozen, "run-start must disclose the freeze it created"
        assert frozen["assignments"]

    # Second gateway instance on the SAME durable stores: a genuine restart.
    app2, _agg2, worker2, _cp2 = make_app(session_factory, checkpointer)
    async with (
        _live_server(app2) as base2,
        httpx.AsyncClient(base_url=base2, timeout=10.0) as client2,
    ):
        status = await client2.get("/v1/runs/evidence-restart")
        assert status.status_code == 200
        sbody = status.json()
        # The freeze is reproduced verbatim from the durable record.
        assert sbody["frozen_assignment"] == frozen
        # The legacy profile pair stays empty: this run never had a profile.
        assert sbody["profile_id"] is None
        assert sbody["assignments"] == []
        # A restart that only reads status must not re-dispatch the run.
        assert worker2.dispatches == []


@pytest.mark.asyncio(loop_scope="function")
async def test_launch_freezes_the_served_catalog_entry(
    session_factory, checkpointer
) -> None:
    """The freeze reproduces exactly the catalog entry the picker was served.

    Evidence that the picker's truth cannot drift from execution's, restated
    for the selection contract: the catalog read is the picker, and every role
    the launch freezes must name that read's provider, execution mode,
    revision, and entry - with the entry's display name carried through and
    the exact provider model value resolved server-side, present but never
    required from the caller.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        fields = await _run_fields(client)
        selection = cast("dict[str, Any]", fields["selection"])
        metadata = cast("dict[str, Any]", fields["metadata"])
        catalog = await client.get(
            "/v1/provider-catalog",
            params={"workspace_root": metadata["workspace_root"]},
        )
        assert catalog.status_code == 200, catalog.text
        record = next(
            item
            for item in catalog.json()["providers"]
            if item["provider_id"] == selection["provider_id"]
            and item["execution_mode"] == selection["execution_mode"]
        )
        served_revision = record["catalog"]["state"]["revision"]
        entry = next(
            model
            for model in record["catalog"]["models"]
            if model["entry_id"] == selection["entry_id"]
        )

        start = await client.post(
            "/v1/runs",
            json={
                "run_id": "evidence-catalog-binding",
                "team_preset": _PRESET,
                "message": "go",
                "autonomous": True,
                **fields,
            },
        )
        assert start.status_code == 201, start.text
        frozen = start.json()["frozen_assignment"]
        assert frozen["assignments"]
        for role in frozen["assignments"]:
            assert role["provider_id"] == selection["provider_id"]
            assert role["execution_mode"] == selection["execution_mode"]
            assert role["catalog_revision"] == served_revision
            assert role["entry_id"] == selection["entry_id"]
            assert role["model_display_name"] == entry["display_name"]
            # The exact provider value is server-resolved from the entry; it
            # must be present in the freeze without the caller supplying it.
            assert role["model_name"]


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_persists_no_secrets_in_db_row(
    session_factory, checkpointer
) -> None:
    """Actor tokens never land in the persisted run metadata DB row.

    Evidence: run-start receives a real actor-token bundle but must persist
    only the safe frozen selection. The thread's ``thread_metadata`` DB column
    is read back directly and asserted to contain neither the submitted token
    values nor any credential marker, while still carrying the frozen
    selection record a restart reads.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    token_value = "tok-secret-coder-value"
    bearer_value = "bearer-secret-value"
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        start = await client.post(
            "/v1/runs",
            json={
                "run_id": "evidence-no-secrets",
                "team_preset": _PRESET,
                "message": "go",
                "autonomous": True,
                "actor_tokens": {
                    "tokens": {"coder": token_value},
                    "engine_bearer": bearer_value,
                },
                **await _run_fields(client),
            },
        )
        assert start.status_code == 201, start.text
        run_id = start.json()["run_id"]

    async with session_factory() as db:
        thread = await get_thread(db, run_id)
    assert thread is not None
    raw_metadata = thread.thread_metadata or ""

    # The frozen selection record is persisted (restart reads it) ...
    persisted = json.loads(raw_metadata)
    assert persisted["provider_catalog_selection"]["schema_version"] == 1
    assert persisted["provider_catalog_selection"]["roles"]
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
    from vaultspec_a2a.providers.lane_admission import (
        is_lane_admissible,
        lane_admission_reason,
    )
    from vaultspec_a2a.providers.model_profiles import (
        AssignmentSource,
        ProfileAssignment,
        RoleAssignment,
        evaluate_profile_eligibility,
        probe_provider_readiness,
    )

    def _role(agent_id, fallbacks, provider):
        return RoleAssignment(
            role_id=agent_id,
            agent_id=agent_id,
            provider=provider,
            capability=None,
            model_name="",
            fallback_providers=fallbacks,
            provider_source=AssignmentSource.TEAM_DEFAULT,
            capability_source=AssignmentSource.TEAM_DEFAULT,
        )

    zhipu = probe_provider_readiness(Provider.ZHIPU)
    zai = probe_provider_readiness(Provider.ZAI)
    assignment = ProfileAssignment(
        profile_id="probe",
        roles=[
            # Primary lane has NO completed-turn proof; the fallback is ready.
            _role("inadmissible-with-fallback", [Provider.MOCK], Provider.ZHIPU),
            # Primary lane IS proven, but its credential is absent here.
            _role("unready-with-fallback", [Provider.MOCK], Provider.ZAI),
            # The control for the pair above: same lane, no fallback declared, so
            # the only difference between them IS the fallback. On an unproven
            # lane this would be refused by admission instead and prove nothing
            # about fallbacks at all.
            _role("no-fallback", [], Provider.ZAI),
        ],
    )
    elig = evaluate_profile_eligibility(
        assignment, engine_reachable=True, acceptance_gate_passed=True
    )
    by_agent = {r.agent_id: r for r in elig.roles}
    print(json.dumps({
        "zhipu_ready": zhipu.ready,
        "zhipu_reason": zhipu.reason,
        "zhipu_admissible": is_lane_admissible(Provider.ZHIPU),
        "zhipu_admission_reason": lane_admission_reason(Provider.ZHIPU),
        "zai_ready": zai.ready,
        "zai_admissible": is_lane_admissible(Provider.ZAI),
        "inadmissible_with_fallback_eligible": (
            by_agent["inadmissible-with-fallback"].eligible
        ),
        "inadmissible_with_fallback_reason": (
            by_agent["inadmissible-with-fallback"].reason
        ),
        "unready_with_fallback_eligible": by_agent["unready-with-fallback"].eligible,
        "no_fallback_eligible": by_agent["no-fallback"].eligible,
        "no_fallback_reason": by_agent["no-fallback"].reason,
    }))
    """
)


def _run_probe(tmp_path: Path, env: dict[str, str]) -> dict:
    """Run the readiness probe in a spawned process with *env*, return its JSON.

    The spawned interpreter resolves the REAL settings path - process env over
    the checkout-root dotenv - so credential state is controlled entirely by
    the injected environment, never by a monkeypatch of the running
    interpreter.
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
    """The host env with every provider credential overridden to empty.

    Overridden rather than popped: settings pin their dotenv source to the
    checkout root, so a popped key would simply be refilled from that file in
    the spawned process. An empty process-env value outranks the dotenv layer
    and reads as "not configured" to the readiness probe.
    """
    import os

    env = dict(os.environ)
    for key in _CREDENTIAL_ENV_KEYS:
        env[key] = ""
    return env


def test_missing_credential_yields_unavailable_with_safe_reason(tmp_path) -> None:
    """A scrubbed credential env yields an unavailable provider + safe reason.

    Evidence: with every provider credential neutralised in the spawned process
    env, the real ``probe_provider_readiness`` reports Zhipu unready with a
    reason that names what is missing and leaks no secret value.
    """
    env = _scrubbed_env()
    out = _run_probe(tmp_path, env)
    assert out["zhipu_ready"] is False
    assert out["zhipu_reason"] == "no Zhipu API key configured"
    # The reason is safe: it never echoes a credential value.
    assert _DUMMY_ZHIPU_KEY not in json.dumps(out)


def test_present_credential_flips_readiness(tmp_path) -> None:
    """A credential present in the spawned env flips readiness ready.

    Evidence that the probe reads the REAL process settings (not a monkeypatch):
    injecting a Zhipu key into the same scrubbed env flips readiness to ready, and
    the injected value never appears in the probe output.
    """
    env = _scrubbed_env()
    env["ZHIPU_API_KEY"] = _DUMMY_ZHIPU_KEY
    out = _run_probe(tmp_path, env)
    assert out["zhipu_ready"] is True
    assert _DUMMY_ZHIPU_KEY not in json.dumps(out)


def test_a_ready_fallback_does_not_rescue_an_inadmissible_primary(tmp_path) -> None:
    """A healthy fallback must NOT make an unproven lane serveable.

    The safety property, and the reason it needs a test rather than only the
    sentence in ``evaluate_profile_eligibility``: admission and readiness are
    different questions, so a profile that happens to carry a ready fallback must
    not turn a lane with NO completed-turn proof into an eligible one. That would
    be the admission rule defeated by an unrelated field - serving a lane nobody
    has ever completed real work on, because something else in the same profile
    was healthy.

    Zhipu is the primary here precisely because it is unproven. The assertion
    cites the admission reason rather than just the verdict, so the test names WHY
    the lane is refused and fails loudly if the refusal ever starts coming from
    somewhere else (a missing credential, say) that a credential could then undo.
    """
    out = _run_probe(tmp_path, _scrubbed_env())

    assert out["zhipu_admissible"] is False
    assert "no completed-turn proof" in out["zhipu_admission_reason"]

    assert out["inadmissible_with_fallback_eligible"] is False
    assert out["zhipu_admission_reason"] in out["inadmissible_with_fallback_reason"]


def test_a_ready_fallback_does_rescue_an_unready_admissible_primary(tmp_path) -> None:
    """A ready fallback still rescues a primary that is merely UNREADY.

    The companion to the refusal above, and the original property this file
    proved: fallback composition is real, not a hardcoded verdict. It needs its
    own case because the two are one edit apart - a change that made admission
    fallback-rescuable would be caught above, and a change that broke fallback
    rescue entirely would be caught only here.

    Z.ai is the primary because it is the inverse of Zhipu on the axis under test:
    a PROVEN lane whose credential is absent from this scrubbed environment. So
    the only thing standing between it and eligibility is readiness, which is
    exactly what a fallback is allowed to answer.
    """
    out = _run_probe(tmp_path, _scrubbed_env())

    assert out["zai_admissible"] is True
    assert out["zai_ready"] is False

    assert out["unready_with_fallback_eligible"] is True
    assert out["no_fallback_eligible"] is False
    assert "no eligible fallback" in out["no_fallback_reason"]
