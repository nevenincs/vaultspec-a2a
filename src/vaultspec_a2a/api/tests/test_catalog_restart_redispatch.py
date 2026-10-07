"""Durable restart proof for the current provider-catalog authority."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from ...control.accepted_input import freeze_accepted_input
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.dispatch import redispatch_reconciling_threads
from ...control.dispatch_receipts import prepare_graph_action_receipt
from ...database import (
    close_db,
    create_control_action,
    get_session_factory,
    get_thread,
    init_db,
)
from ...database.thread_repository import create_thread
from ...graph.enums import Provider
from ...ipc.schemas import DispatchRequest
from ...providers.provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    ControlKind,
    HealthState,
    ModelCatalogEntry,
    NativeControl,
    NativeControlOption,
    ProviderCatalog,
    ProviderCatalogKey,
    ProviderHealthAxes,
    ProviderRecord,
    SelectionReference,
    StructuredProviderHealth,
)
from ...providers.provider_catalog_service import stamp_catalog_expiry
from ...providers.team_selection import (
    FrozenTeamSelection,
    freeze_team_selection,
    model_assignment_digest,
)
from ...team.team_config import load_team_config
from ...testing import (
    DEFAULT_ATTACH_CREDENTIAL,
    DEFAULT_REQUIRED_ROLE,
    DEFAULT_TEAM_PRESET,
    RunVerbs,
    adopted_spawner,
    booted_gateway,
    broker_gateway_env,
    fetch_in_process_selection,
    gateway_script,
    in_process_lane_selection,
    log_tail,
    seat_app_home,
    wait_for_run_status,
)
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ...thread.idempotency import thread_create_action_key
from ..schemas.gateway import FrozenTeamAssignmentSummary
from .conftest import _InProcessWorker

if TYPE_CHECKING:
    from pathlib import Path


def _current_metadata(
    workspace: Path,
    *,
    catalog_revision: str | None = None,
    model_value: str = "deterministic",
) -> tuple[dict[str, object], FrozenTeamSelection]:
    served, _reference = in_process_lane_selection(Provider.DETERMINISTIC)
    now = datetime.now(UTC)
    catalog = served.catalog
    if model_value != catalog.models[0].provider_value:
        catalog = replace(
            catalog,
            models=(
                replace(
                    catalog.models[0],
                    provider_value=model_value,
                    display_name=f"Historical {model_value}",
                ),
            ),
        )
    if catalog_revision is not None:
        catalog = replace(
            catalog, state=replace(catalog.state, revision=catalog_revision)
        )
    record = replace(served, catalog=catalog)
    model = record.catalog.models[0]
    codex_key = ProviderCatalogKey("codex", "codex-app-server")
    codex_revision = "frozen-unused-codex-fallback"
    codex_record = ProviderRecord(
        provider_id=codex_key.provider_id,
        display_name="Codex",
        execution_mode=codex_key.execution_mode,
        health=StructuredProviderHealth.derive(
            axes=ProviderHealthAxes(
                configured=HealthState.AVAILABLE,
                transport=HealthState.AVAILABLE,
                authentication=AuthenticationState.AUTHENTICATED,
                catalog=CatalogStatus.AVAILABLE,
                admission=AdmissionState.ADMITTED,
            ),
            checked_at=now,
        ),
        catalog=stamp_catalog_expiry(
            ProviderCatalog(
                key=codex_key,
                state=CatalogState(
                    status=CatalogStatus.AVAILABLE,
                    checked_at=now,
                    revision=codex_revision,
                ),
                models=(
                    ModelCatalogEntry(
                        entry_id="unused-codex-entry",
                        provider_value="unused-codex-model",
                        display_name="Unused Codex fallback",
                        native_control_ids=("reasoning_effort",),
                    ),
                ),
                native_controls=(
                    NativeControl(
                        control_id="reasoning_effort",
                        kind=ControlKind.THOUGHT_LEVEL,
                        display_name="Reasoning effort",
                        options=(
                            NativeControlOption(
                                option_id="medium",
                                provider_value="medium",
                                display_name="Medium",
                            ),
                        ),
                        default_option_id="medium",
                    ),
                ),
            )
        ),
    )
    primary = SelectionReference(
        provider_id=record.provider_id,
        execution_mode=record.execution_mode,
        catalog_revision=record.catalog.state.revision or "",
        entry_id=model.entry_id,
    )
    frozen = freeze_team_selection(
        selection=primary,
        overrides={DEFAULT_REQUIRED_ROLE: primary},
        fallbacks=(
            SelectionReference(
                provider_id=codex_key.provider_id,
                execution_mode=codex_key.execution_mode,
                catalog_revision=codex_revision,
                entry_id="unused-codex-entry",
            ),
        ),
        required_roles=(DEFAULT_REQUIRED_ROLE,),
        records=(record, codex_record),
    )
    return (
        {
            "workspace_root": str(workspace),
            "provider_catalog_selection": frozen.to_record(),
        },
        frozen,
    )


@dataclass(frozen=True)
class _RestartCase:
    app_home: Path
    workspace: Path
    attach: str
    database_path: Path
    frozen_revision: str
    metadata: dict[str, object]
    frozen_selection: FrozenTeamSelection
    exact_record: dict[str, Any]
    exact_wire_disclosure: dict[str, Any]
    exact_assignment_digest: str
    other_metadata: dict[str, object]
    other_frozen_selection: FrozenTeamSelection
    other_assignment_digest: str


def _prepare_restart_case(tmp_path: Path) -> _RestartCase:
    app_home = tmp_path / "app-home"
    attach = DEFAULT_ATTACH_CREDENTIAL
    state = seat_app_home(app_home, attach=attach)
    workspace = state.workspaces_root / "project"
    workspace.mkdir(parents=True)
    database_path = state.database_path
    frozen_revision = "frozen-revision-no-longer-served"
    metadata, frozen_selection = _current_metadata(
        workspace, catalog_revision=frozen_revision
    )
    exact_record = frozen_selection.to_record()
    exact_wire_disclosure = FrozenTeamAssignmentSummary.model_validate(
        frozen_selection.disclosure()
    ).model_dump(mode="json")
    exact_assignment_digest = model_assignment_digest(frozen_selection.compiler_map())
    other_metadata, other_frozen_selection = _current_metadata(
        workspace,
        catalog_revision="other-frozen-revision",
        model_value="deterministic-other",
    )
    other_assignment_digest = model_assignment_digest(
        other_frozen_selection.compiler_map()
    )
    assert other_assignment_digest != exact_assignment_digest
    fallback = exact_record["fallbacks"][0]
    assert fallback["defaulted_control_ids"] == ["reasoning_effort"]
    assert fallback["controls"] == [
        {
            "control_id": "reasoning_effort",
            "option_id": "medium",
            "provider_value": "medium",
            "display_name": "Reasoning effort",
            "option_display_name": "Medium",
        }
    ]
    return _RestartCase(
        app_home=app_home,
        workspace=workspace,
        attach=attach,
        database_path=database_path,
        frozen_revision=frozen_revision,
        metadata=metadata,
        frozen_selection=frozen_selection,
        exact_record=exact_record,
        exact_wire_disclosure=exact_wire_disclosure,
        exact_assignment_digest=exact_assignment_digest,
        other_metadata=other_metadata,
        other_frozen_selection=other_frozen_selection,
        other_assignment_digest=other_assignment_digest,
    )


async def _seed_restart_case(case: _RestartCase) -> None:
    await close_db()
    await init_db(str(case.database_path))
    try:
        async with get_session_factory()() as session:
            definition = freeze_graph_definition(
                load_team_config(DEFAULT_TEAM_PRESET, workspace_root=case.workspace),
                workspace_root=case.workspace,
            )
            for thread_id, thread_metadata, selection in (
                ("current-schema-restart", case.metadata, case.frozen_selection),
                ("same-assignment-restart", case.metadata, case.frozen_selection),
                (
                    "other-assignment-restart",
                    case.other_metadata,
                    case.other_frozen_selection,
                ),
            ):
                authority = make_test_write_authority()
                await create_thread(
                    session,
                    write_authority=authority,
                    thread_id=thread_id,
                    status=ThreadStatus.RECONCILING,
                    team_preset=DEFAULT_TEAM_PRESET,
                    metadata=json.dumps(thread_metadata),
                )
                dispatch = DispatchRequest(
                    action="ingest",
                    thread_id=thread_id,
                    content="recover after restart",
                    workspace_root=str(case.workspace),
                    recursion_limit=25,
                    team_preset=DEFAULT_TEAM_PRESET,
                    graph_definition=definition,
                    model_assignment=selection.compiler_map(),
                )
                await create_control_action(
                    session,
                    thread_id=thread_id,
                    action_type=authority.action_type,
                    idempotency_key=thread_create_action_key(thread_id),
                    dispatch_id=authority.action_receipt_id,
                    recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
                    payload=freeze_accepted_input(
                        dispatch, intent={"content": "recover after restart"}
                    ),
                )
                assert (
                    await prepare_graph_action_receipt(
                        session,
                        thread_id=thread_id,
                        dispatch_id=authority.action_receipt_id,
                    )
                    is not None
                )
            await session.commit()
    finally:
        await close_db()


def _await_terminal(
    client: httpx.Client, run_id: str, log_path: Path
) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        response = client.get(f"/v1/runs/{run_id}")
        assert response.status_code == 200, response.text
        return cast("dict[str, Any]", response.json())

    try:
        return wait_for_run_status(
            _read, timeout=30.0, interval=0.1, label=f"run {run_id}"
        )
    except AssertionError as stalled:
        raise AssertionError(
            f"{stalled}\ngateway log tail: {log_tail(log_path, limit=8000)}"
        ) from stalled


def _assert_restart_runs(
    client: httpx.Client, case: _RestartCase, log_path: Path
) -> None:
    live_selection = fetch_in_process_selection(client, str(case.workspace))
    assert live_selection["catalog_revision"] != case.frozen_revision

    # A real start is the production dispatch-demand edge. It starts the
    # worker and releases the gateway's deferred startup recovery only
    # after the worker has answered its readiness probe.
    trigger = RunVerbs(
        base_url=str(client.base_url),
        authorization=client.headers["Authorization"],
        team_preset=DEFAULT_TEAM_PRESET,
        workspace_root=str(case.workspace),
        selection=lambda _workspace: live_selection,
    ).start("restart-demand", message="release startup recovery")
    assert trigger.status_code == 201, trigger.text

    snapshot = _await_terminal(client, "current-schema-restart", log_path)
    assert snapshot["status"] == "completed", (
        snapshot,
        log_tail(log_path, limit=8000),
    )
    # Semantic object equality covers every nested identity and value;
    # JSON object key order is deliberately not part of the contract.
    assert snapshot["frozen_assignment"] == case.exact_wire_disclosure
    assert snapshot["frozen_assignment"]["digest"] == case.exact_record["digest"]

    history = client.get("/v1/runs/current-schema-restart/history")
    assert history.status_code == 200, history.text
    agents = history.json()["state"]["agents"]
    assert agents
    assert all(agent["provider"] == "deterministic" for agent in agents)
    assert all(agent["model_name"] == "deterministic" for agent in agents)
    assert all(agent["thread_id"] == "current-schema-restart" for agent in agents)
    assert history.json()["state"]["model_assignment_digest"] == (
        case.exact_assignment_digest
    )
    same_snapshot = _await_terminal(client, "same-assignment-restart", log_path)
    other_snapshot = _await_terminal(client, "other-assignment-restart", log_path)
    assert same_snapshot["status"] == "completed"
    assert other_snapshot["status"] == "completed"

    same_history = client.get("/v1/runs/same-assignment-restart/history")
    other_history = client.get("/v1/runs/other-assignment-restart/history")
    assert same_history.status_code == 200, same_history.text
    assert other_history.status_code == 200, other_history.text
    assert same_history.json()["state"]["model_assignment_digest"] == (
        case.exact_assignment_digest
    )
    assert other_history.json()["state"]["model_assignment_digest"] == (
        case.other_assignment_digest
    )
    assert {agent["thread_id"] for agent in same_history.json()["state"]["agents"]} == {
        "same-assignment-restart"
    }
    assert {
        agent["thread_id"] for agent in other_history.json()["state"]["agents"]
    } == {"other-assignment-restart"}
    assert {agent["provider"] for agent in other_history.json()["state"]["agents"]} == {
        "deterministic"
    }
    assert {
        agent["model_name"] for agent in other_history.json()["state"]["agents"]
    } == {"deterministic-other"}


def _assert_stored_restart_metadata(case: _RestartCase) -> None:
    # Read the production database through an independent read-only
    # connection while the gateway still owns it. Recovery must not
    # rewrite any byte-relevant value in the accepted frozen record.
    with sqlite3.connect(
        f"file:{case.database_path.as_posix()}?mode=ro", uri=True
    ) as connection:
        stored_json = connection.execute(
            "SELECT thread_metadata FROM threads WHERE id = ?",
            ("current-schema-restart",),
        ).fetchone()
    assert stored_json is not None
    assert json.loads(stored_json[0])["provider_catalog_selection"] == (
        case.exact_record
    )


def _retired_record(
    current: dict[str, object],
    *,
    original_digest: object,
    path: tuple[str, ...],
    field: str,
    value: object,
) -> dict[str, object]:
    record = deepcopy(current)
    target = record
    for key in path:
        nested = target[key]
        assert isinstance(nested, dict)
        target = cast("dict[str, object]", nested)
    target[field] = value
    assert record["digest"] == original_digest
    return record


def test_current_schema_restart_reaches_a_fresh_production_worker(
    tmp_path: Path,
) -> None:
    """Production startup consumes an exact freeze whose catalog has drifted."""
    case = _prepare_restart_case(tmp_path)
    asyncio.run(_seed_restart_case(case))
    log_path = tmp_path / "gateway.log"
    headers = {"Authorization": f"Bearer {case.attach}"}
    with (
        booted_gateway(
            broker_gateway_env(case.app_home, gateway_token=case.attach),
            log_path=log_path,
            script=gateway_script(log_level="info"),
            detached=True,
        ) as gateway,
        httpx.Client(
            base_url=gateway.base_url, headers=headers, timeout=240.0
        ) as client,
    ):
        _assert_restart_runs(client, case, log_path)
        _assert_stored_restart_metadata(case)


@pytest.mark.asyncio
async def test_retired_durable_state_is_terminal_before_worker_contact(
    tmp_path: Path,
) -> None:
    """All retired durable authority shapes fail closed during startup recovery."""
    await close_db()
    await init_db(str(tmp_path / "retired-restart.db"))
    worker = _InProcessWorker(None)
    retired_cases: tuple[tuple[str, tuple[str, ...], str, object], ...] = (
        ("root-profile-id", (), "profile_id", "retired"),
        ("root-default-profile", (), "default_profile_id", "retired"),
        ("root-profile", (), "profile", {"id": "retired"}),
        ("selection-model-profile", ("selection",), "model_profile", "retired"),
        ("selection-model", ("selection",), "model", "retired-model"),
        ("selection-profile", ("selection",), "profile_id", "retired"),
        ("retired-provider", ("selection",), "provider_id", "gemini"),
        ("retired-mode", ("selection",), "execution_mode", "gemini-cli-acp"),
    )
    try:
        metadata, _assignment = _current_metadata(tmp_path)
        current_raw = metadata["provider_catalog_selection"]
        assert isinstance(current_raw, dict)
        current = cast("dict[str, object]", current_raw)
        original_digest = current["digest"]
        session_factory = get_session_factory()
        async with session_factory() as session:
            for label, path, field, value in retired_cases:
                record = _retired_record(
                    current,
                    original_digest=original_digest,
                    path=path,
                    field=field,
                    value=value,
                )
                authority = make_test_write_authority()
                thread_id = f"retired-durable-{label}"
                await create_thread(
                    session,
                    write_authority=authority,
                    thread_id=thread_id,
                    status=ThreadStatus.RECONCILING,
                    team_preset=DEFAULT_TEAM_PRESET,
                    metadata=json.dumps(
                        {
                            "workspace_root": str(tmp_path),
                            "provider_catalog_selection": record,
                        }
                    ),
                )
                await create_control_action(
                    session,
                    thread_id=thread_id,
                    action_type=authority.action_type,
                    idempotency_key=thread_create_action_key(thread_id),
                    dispatch_id=authority.action_receipt_id,
                    recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            authority = make_test_write_authority()
            await create_thread(
                session,
                write_authority=authority,
                thread_id="retired-durable-model-profile-sentinel",
                status=ThreadStatus.RECONCILING,
                team_preset=DEFAULT_TEAM_PRESET,
                metadata=json.dumps(
                    {
                        "workspace_root": str(tmp_path),
                        "model_profile": {"provider": "gemini", "model": "secret"},
                    }
                ),
            )
            await create_control_action(
                session,
                thread_id="retired-durable-model-profile-sentinel",
                action_type=authority.action_type,
                idempotency_key=thread_create_action_key(
                    "retired-durable-model-profile-sentinel"
                ),
                dispatch_id=authority.action_receipt_id,
                recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            await session.commit()

        contacts: list[float] = []
        spawner = adopted_spawner("http://test-worker:8001")
        await redispatch_reconciling_threads(
            worker.client,
            WorkerCircuitBreaker(failure_threshold=1, recovery_timeout=30.0),
            spawner,
            record_worker_contact=contacts.append,
        )

        assert worker.dispatches == []
        assert contacts == []
        async with session_factory() as session:
            for label, *_rest in retired_cases:
                thread = await get_thread(session, f"retired-durable-{label}")
                assert thread is not None
                assert thread.status == ThreadStatus.FAILED.value
                assert thread.failure_reason == (
                    "stored execution authority is incompatible (corrupt)"
                )
            sentinel = await get_thread(
                session, "retired-durable-model-profile-sentinel"
            )
            assert sentinel is not None
            assert sentinel.status == ThreadStatus.FAILED.value
            assert sentinel.failure_reason == (
                "stored execution authority is incompatible (retired)"
            )
    finally:
        await worker.client.aclose()
        await close_db()
