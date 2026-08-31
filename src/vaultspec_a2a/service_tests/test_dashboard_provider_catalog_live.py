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

import os
import subprocess
import time
import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from ..lifecycle.discovery import write_service_json
from ..service_tests._live_desktop_gateway import ATTACH_CREDENTIAL, armed_gateway
from ..testing.ports import free_port
from ..utils.process import ProcessContainment
from ._provider_catalog_live import (
    LIVE_PROVIDER_PREREQUISITES,
    selection_from_served_catalog,
)
from .test_engine_broker_lost_ack_live import (
    _engine_command,
    _force_engine_tree_exit,
    _provision_workspace,
    _shutdown_engine,
    _wait_for_engine,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..api.schemas.gateway import ProviderCatalogSelection
_RUN_ID_PREFIX = "live-provider-catalog"
_TERMINAL_DEADLINE_SECONDS = 900.0
_POLL_SECONDS = 2.0
_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_ARRAY = TypeAdapter(list[object])


def _object(value: object, *, source: str) -> dict[str, object]:
    """Require one bounded object projection from a real HTTP response."""
    try:
        return _JSON_OBJECT.validate_python(value, strict=True)
    except ValidationError as exc:
        raise AssertionError(f"{source} must be a JSON object: {exc}") from exc


def _array(value: object, *, source: str) -> list[object]:
    """Require one ordered JSON array without accepting arbitrary iterables."""
    try:
        return _JSON_ARRAY.validate_python(value, strict=True)
    except ValidationError as exc:
        raise AssertionError(f"{source} must be a JSON array: {exc}") from exc


def _engine_envelope(response: httpx.Response, *, source: str) -> dict[str, object]:
    """Extract the verbatim sibling envelope from Dashboard's public response."""
    assert response.status_code == HTTPStatus.OK, f"{source}: {response.text}"
    body = _object(response.json(), source=f"{source} body")
    data = _object(body.get("data"), source=f"{source} data")
    return _object(data.get("envelope"), source=f"{source} envelope")


def _frozen_assignment(
    envelope: dict[str, object], selection: ProviderCatalogSelection
) -> dict[str, object]:
    """Assert A2A froze the current opaque selection for every preset role."""
    frozen = _object(envelope.get("frozen_assignment"), source="frozen assignment")
    assert frozen.get("schema_version") == 1, frozen
    assert isinstance(frozen.get("digest"), str) and frozen["digest"], frozen
    assignments = _array(frozen.get("assignments"), source="frozen assignments")
    assert assignments, frozen
    for assignment in assignments:
        role = _object(assignment, source="frozen role assignment")
        assert role.get("provider_id") == selection.provider_id, role
        assert role.get("execution_mode") == selection.execution_mode, role
        assert role.get("catalog_revision") == selection.catalog_revision, role
        assert role.get("entry_id") == selection.entry_id, role
        assert isinstance(role.get("model_name"), str) and role["model_name"], role
        controls = _array(role.get("controls"), source="frozen role controls")
        control_records = [
            _object(control, source="frozen native control") for control in controls
        ]
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
    frozen: dict[str, object],
    expected_nonce: str,
) -> None:
    """Prove an agent governed by the frozen record returned the unique prompt nonce."""
    history = httpx.get(
        f"{gateway_base}/v1/runs/{run_id}/history",
        headers={"Authorization": auth},
        timeout=30,
    )
    assert history.status_code == HTTPStatus.OK, history.text
    history_body = _object(history.json(), source="completed run history")
    state = _object(history_body.get("state"), source="completed run state")
    messages = [
        _object(message, source="completed run message")
        for message in _array(state.get("messages"), source="completed run messages")
    ]
    frozen_agents: set[str] = set()
    for record in _array(frozen.get("assignments"), source="frozen assignments"):
        assignment = _object(record, source="frozen role assignment")
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
) -> dict[str, object]:
    """Poll the production recovery surface until the one opt-in turn completes."""
    deadline = time.monotonic() + _TERMINAL_DEADLINE_SECONDS
    final: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = httpx.post(
            f"{engine_base}/ops/a2a/run-status",
            headers={"Authorization": f"Bearer {token}"},
            json={"run_id": run_id},
            timeout=30,
        )
        envelope = _engine_envelope(response, source="run-status")
        _frozen_assignment(envelope, selection)
        status = envelope.get("status")
        if status in {"completed", "failed", "cancelled"}:
            final = envelope
            break
        time.sleep(_POLL_SECONDS)
    assert final is not None, (
        f"the configured provider run did not reach a terminal state within "
        f"{_TERMINAL_DEADLINE_SECONDS}s"
    )
    assert final.get("status") == "completed", (
        "the explicitly configured provider turn did not complete: "
        f"status={final.get('status')!r}, reason={final.get('failure_reason')!r}"
    )
    return final


@pytest.mark.service
@pytest.mark.timeout(_TERMINAL_DEADLINE_SECONDS + 300.0)
@pytest.mark.requires_prerequisites(*LIVE_PROVIDER_PREREQUISITES)
def test_dashboard_catalog_selection_completes_and_replays_with_frozen_assignment(
    tmp_path: Path,
) -> None:
    """One explicitly authorized provider turn stays frozen across Dashboard replay."""
    workspace = tmp_path / "dashboard-workspace"
    _provision_workspace(workspace)
    engine_port = free_port()
    engine_base = f"http://127.0.0.1:{engine_port}"
    engine_log = tmp_path / "engine.log"

    run_id = f"{_RUN_ID_PREFIX}-{uuid.uuid4().hex}"
    nonce = f"provider-output-{uuid.uuid4().hex}"

    with armed_gateway(
        tmp_path,
        VAULTSPEC_ENGINE_SERVICE_JSON=str(
            workspace / ".vault" / "data" / "engine-data" / "service.json"
        ),
    ) as (gateway_base, auth):
        discovery_home = tmp_path / "a2a-discovery"
        write_service_json(
            discovery_home / "service.json",
            port=int(gateway_base.rsplit(":", 1)[1]),
            pid=os.getpid(),
            service_token=ATTACH_CREDENTIAL,
        )
        environment = {
            **{
                key: value
                for key, value in os.environ.items()
                if key not in {"VAULTSPEC_APP_HOME", "VAULTSPEC_DESKTOP_APP_HOME"}
            },
            "VAULTSPEC_A2A_HOME": str(discovery_home),
            "VAULTSPEC_APP_HOME": str(tmp_path / "dashboard-product-home"),
        }
        with engine_log.open("wb") as output:
            containment = ProcessContainment.create()
            new_session = bool(containment.spawn_kwargs().get("start_new_session"))
            process: subprocess.Popen[bytes] | None = None
            token: str | None = None
            try:
                process = subprocess.Popen(
                    _engine_command(engine_port, workspace),
                    cwd=workspace,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=new_session,
                )
                containment.assign(process.pid)
                token = _wait_for_engine(workspace, engine_base, process)
                session = httpx.get(
                    f"{engine_base}/session",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                session.raise_for_status()
                session_data = _object(session.json(), source="engine session")
                scope = _object(
                    session_data.get("data"), source="engine session data"
                ).get("active_scope")
                assert isinstance(scope, str) and scope, session_data

                stale_scope = httpx.post(
                    f"{engine_base}/ops/a2a/provider-catalog",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"expected_scope": f"{scope}-stale"},
                    timeout=30,
                )
                assert stale_scope.status_code == HTTPStatus.CONFLICT, stale_scope.text

                catalog = httpx.post(
                    f"{engine_base}/ops/a2a/provider-catalog",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"expected_scope": scope},
                    timeout=30,
                )
                selection = selection_from_served_catalog(
                    _engine_envelope(catalog, source="provider-catalog")
                )
                start_body = {
                    "run_id": run_id,
                    "team_preset": "vaultspec-solo-coder",
                    "message": (
                        f"Return exactly this nonce and no other text: {nonce}"
                    ),
                    "expected_scope": scope,
                    "feature_tag": "live-provider-catalog",
                    "selection": selection.model_dump(mode="json"),
                }
                started = _engine_envelope(
                    httpx.post(
                        f"{engine_base}/ops/a2a/run-start",
                        headers={"Authorization": f"Bearer {token}"},
                        json=start_body,
                        timeout=90,
                    ),
                    source="run-start",
                )
                assert started.get("run_id") == run_id, started
                frozen = _frozen_assignment(started, selection)

                completed = _wait_for_completed_run(
                    engine_base, token, selection, run_id
                )
                assert _frozen_assignment(completed, selection) == frozen
                _assert_completed_provider_output(
                    gateway_base, auth, run_id, frozen, nonce
                )

                replayed = _engine_envelope(
                    httpx.post(
                        f"{engine_base}/ops/a2a/run-start",
                        headers={"Authorization": f"Bearer {token}"},
                        json=start_body,
                        timeout=90,
                    ),
                    source="run-start replay",
                )
                assert replayed.get("run_id") == run_id, replayed
                assert _frozen_assignment(replayed, selection) == frozen
            finally:
                if process is None:
                    containment.close()
                elif token is not None:
                    _shutdown_engine(process, containment, engine_base, token)
                else:
                    _force_engine_tree_exit(process, containment)
