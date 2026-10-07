"""Live proof for a catalog-selected provider turn through Dashboard and Rust.

The provider catalog itself deliberately has no generic cost signal.  A real
turn is therefore opt-in: the operator supplies opaque identifiers for one
currently advertised low-cost native option, this test validates every one
against the catalog that A2A serves through the Dashboard/Rust boundary, then
starts exactly one small run.  It never chooses from catalog order, display
text, a static provider/model id, or a provider-native control kind.

The completed turn proves that the prompt crossed the Dashboard -> Rust -> A2A
process boundary.  The frozen assignment on start, status, and idempotent
replay proves the exact served entry/control identity A2A resolved for that
turn.  Provider-native execution values remain A2A-owned: the public catalog
does not expose them, and the frozen record is the only safe historical
projection.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx
import pytest

from ..providers.team_selection import FROZEN_SELECTION_SCHEMA_VERSION
from ..service_tests._live_desktop_gateway import armed_gateway
from ..testing import (
    LIVE_PROVIDER_PREREQUISITES,
    free_port,
    json_object,
    json_object_list,
    selection_from_served_catalog,
    wait_for_run_status,
)
from ..utils import bearer_header
from ._dashboard_engine import dashboard_engine, provision_workspace

if TYPE_CHECKING:
    from pathlib import Path

    from ..api.schemas.gateway import ProviderCatalogSelection
    from ..providers import JsonObject
_RUN_ID_PREFIX = "live-provider-catalog"
_TERMINAL_DEADLINE_SECONDS = 900.0
_POLL_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class _DashboardScenario:
    """Inputs shared by the provider-catalog engine lifecycle."""

    workspace: Path
    engine_port: int
    engine_base: str
    engine_log: Path
    run_id: str
    nonce: str


def _engine_envelope(response: httpx.Response, *, source: str) -> JsonObject:
    """Extract the verbatim sibling envelope from Dashboard's public response."""
    assert response.status_code == HTTPStatus.OK, f"{source}: {response.text}"
    body = json_object(response.json(), at=f"{source} body")
    data = json_object(body.get("data"), at=f"{source} data")
    return json_object(data.get("envelope"), at=f"{source} envelope")


def _frozen_assignment(
    envelope: JsonObject, selection: ProviderCatalogSelection
) -> JsonObject:
    """Assert A2A froze the current opaque selection for every preset role."""
    frozen = json_object(envelope.get("frozen_assignment"), at="frozen assignment")
    assert frozen.get("schema_version") == FROZEN_SELECTION_SCHEMA_VERSION, frozen
    assert isinstance(frozen.get("digest"), str) and frozen["digest"], frozen
    assignments = json_object_list(frozen.get("assignments"), at="frozen assignments")
    assert assignments, frozen
    for role in assignments:
        assert role.get("provider_id") == selection.provider_id, role
        assert role.get("execution_mode") == selection.execution_mode, role
        assert role.get("catalog_revision") == selection.catalog_revision, role
        assert role.get("entry_id") == selection.entry_id, role
        assert isinstance(role.get("model_name"), str) and role["model_name"], role
        control_records = json_object_list(
            role.get("controls"), at="frozen role controls"
        )
        selected_controls = [
            control
            for control in control_records
            if control.get("control_id") in selection.controls
        ]
        assert len(selected_controls) == len(selection.controls), role
        for control_id, option_id in selection.controls.items():
            matching = [
                control
                for control in selected_controls
                if control.get("control_id") == control_id
                and control.get("option_id") == option_id
            ]
            assert len(matching) == 1, role
            assert (
                isinstance(matching[0].get("provider_value"), str)
                and matching[0]["provider_value"]
            ), matching[0]
    return frozen


def _assert_completed_provider_output(
    gateway_base: str,
    auth: str,
    run_id: str,
    frozen: JsonObject,
    expected_nonce: str,
) -> None:
    """Prove an agent governed by the frozen record returned the unique prompt nonce."""
    history = httpx.get(
        f"{gateway_base}/v1/runs/{run_id}/history",
        headers={"Authorization": auth},
        timeout=30,
    )
    assert history.status_code == HTTPStatus.OK, history.text
    history_body = json_object(history.json(), at="completed run history")
    state = json_object(history_body.get("state"), at="completed run state")
    messages = json_object_list(state.get("messages"), at="completed run messages")
    frozen_agents: set[str] = set()
    for assignment in json_object_list(
        frozen.get("assignments"), at="frozen assignments"
    ):
        agent_id = assignment.get("agent_id")
        if isinstance(agent_id, str) and agent_id:
            frozen_agents.add(agent_id)
    assert frozen_agents, "the frozen record did not identify any executing agents"
    provider_turns = [
        message
        for message in messages
        if message.get("role") == "assistant"
        and message.get("agent_id") in frozen_agents
    ]
    assert provider_turns, (
        "the run completed without an assistant turn from a frozen catalog agent: "
        f"frozen_agents={sorted(frozen_agents)!r}, messages={messages!r}"
    )
    output = provider_turns[-1].get("content")
    assert output == expected_nonce, (
        "the frozen catalog agent did not return the exact prompt nonce: "
        f"expected_nonce={expected_nonce!r}, output={output!r}"
    )


def _wait_for_completed_run(
    engine_base: str,
    token: str,
    selection: ProviderCatalogSelection,
    run_id: str,
) -> JsonObject:
    """Poll the production recovery surface until the one opt-in turn completes."""

    def _read_status() -> JsonObject:
        response = httpx.post(
            f"{engine_base}/ops/a2a/run-status",
            headers=bearer_header(token),
            json={"run_id": run_id},
            timeout=30,
        )
        envelope = _engine_envelope(response, source="run-status")
        _frozen_assignment(envelope, selection)
        return envelope

    final = wait_for_run_status(
        _read_status,
        timeout=_TERMINAL_DEADLINE_SECONDS,
        interval=_POLL_SECONDS,
        label=f"run {run_id}",
    )
    assert final.get("status") == "completed", (
        "the explicitly configured provider turn did not complete: "
        f"status={final.get('status')!r}, reason={final.get('failure_reason')!r}"
    )
    return final


def _dashboard_scenario(tmp_path: Path) -> _DashboardScenario:
    workspace = tmp_path / "dashboard-workspace"
    provision_workspace(workspace)
    engine_port = free_port()
    return _DashboardScenario(
        workspace=workspace,
        engine_port=engine_port,
        engine_base=f"http://127.0.0.1:{engine_port}",
        engine_log=tmp_path / "engine.log",
        run_id=f"{_RUN_ID_PREFIX}-{uuid.uuid4().hex}",
        nonce=f"provider-output-{uuid.uuid4().hex}",
    )


def _run_dashboard_turn(
    scenario: _DashboardScenario,
    gateway_base: str,
    auth: str,
    token: str,
) -> None:
    session = httpx.get(
        f"{scenario.engine_base}/session",
        headers=bearer_header(token),
        timeout=10,
    )
    session.raise_for_status()
    session_data = json_object(session.json(), at="engine session")
    scope = json_object(session_data.get("data"), at="engine session data").get(
        "active_scope"
    )
    assert isinstance(scope, str) and scope, session_data

    stale_scope = httpx.post(
        f"{scenario.engine_base}/ops/a2a/provider-catalog",
        headers=bearer_header(token),
        json={"expected_scope": f"{scope}-stale"},
        timeout=30,
    )
    assert stale_scope.status_code == HTTPStatus.CONFLICT, stale_scope.text

    catalog = httpx.post(
        f"{scenario.engine_base}/ops/a2a/provider-catalog",
        headers=bearer_header(token),
        json={"expected_scope": scope},
        timeout=30,
    )
    selection = selection_from_served_catalog(
        _engine_envelope(catalog, source="provider-catalog")
    )
    start_body = {
        "run_id": scenario.run_id,
        "team_preset": "vaultspec-solo-coder",
        "message": f"Return exactly this nonce and no other text: {scenario.nonce}",
        "expected_scope": scope,
        "feature_tag": "live-provider-catalog",
        "selection": selection.model_dump(mode="json"),
    }
    started = _engine_envelope(
        httpx.post(
            f"{scenario.engine_base}/ops/a2a/run-start",
            headers=bearer_header(token),
            json=start_body,
            timeout=90,
        ),
        source="run-start",
    )
    assert started.get("run_id") == scenario.run_id, started
    frozen = _frozen_assignment(started, selection)

    completed = _wait_for_completed_run(
        scenario.engine_base, token, selection, scenario.run_id
    )
    assert _frozen_assignment(completed, selection) == frozen
    _assert_completed_provider_output(
        gateway_base, auth, scenario.run_id, frozen, scenario.nonce
    )

    replayed = _engine_envelope(
        httpx.post(
            f"{scenario.engine_base}/ops/a2a/run-start",
            headers=bearer_header(token),
            json=start_body,
            timeout=90,
        ),
        source="run-start replay",
    )
    assert replayed.get("run_id") == scenario.run_id, replayed
    assert _frozen_assignment(replayed, selection) == frozen


@pytest.mark.service
@pytest.mark.timeout(_TERMINAL_DEADLINE_SECONDS + 300.0)
@pytest.mark.requires_prerequisites(*LIVE_PROVIDER_PREREQUISITES)
def test_dashboard_catalog_selection_completes_and_replays_with_frozen_assignment(
    tmp_path: Path,
) -> None:
    """One explicitly authorized provider turn stays frozen across Dashboard replay."""
    scenario = _dashboard_scenario(tmp_path)

    with (
        armed_gateway(
            tmp_path,
            VAULTSPEC_A2A_ENGINE_SERVICE_JSON=str(
                scenario.workspace / ".vault" / "data" / "engine-data" / "service.json"
            ),
        ) as (gateway_base, auth),
        dashboard_engine(
            tmp_path,
            workspace=scenario.workspace,
            engine_port=scenario.engine_port,
            engine_log=scenario.engine_log,
            a2a_port=int(gateway_base.rsplit(":", 1)[1]),
        ) as token,
    ):
        _run_dashboard_turn(scenario, gateway_base, auth, token)
