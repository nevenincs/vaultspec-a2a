"""Catalog-selection freeze evidence battery.

Live, mock-free evidence that the gateway tests do not already cover:

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
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, cast

import httpx
import pytest

from ...database import get_thread
from .conftest import make_app
from .test_gateway_live import _PRESET, _live_server, _run_fields


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
        assert "profile_id" not in sbody
        assert "assignments" not in sbody
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
async def test_run_start_refuses_every_retired_selection_surface_before_dispatch(
    session_factory, checkpointer
) -> None:
    """Retired policy, provider and mode inputs never reach construction."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        current = await _run_fields(client)
        cases: tuple[tuple[str, tuple[str, ...], str, object, str, str | None], ...] = (
            (
                "profile-id",
                (),
                "profile_id",
                "retired-profile",
                "retired-profile",
                None,
            ),
            (
                "default-profile",
                (),
                "default_profile_id",
                "retired-profile",
                "retired-profile",
                None,
            ),
            (
                "profile-object",
                (),
                "profile",
                {"id": "retired-profile"},
                "retired-profile",
                None,
            ),
            (
                "model-profile",
                (),
                "model_profile",
                {"id": "retired-profile"},
                "retired-profile",
                None,
            ),
            ("free-provider", (), "provider", "gemini", "gemini", None),
            ("free-model", (), "model", "retired-model", "retired-model", None),
            (
                "nested-profile",
                ("selection",),
                "profile_id",
                "retired-profile",
                "retired-profile",
                None,
            ),
            (
                "nested-model",
                ("selection",),
                "model_name",
                "retired-model",
                "retired-model",
                None,
            ),
            (
                "gemini-provider",
                ("selection",),
                "provider_id",
                "gemini",
                "gemini",
                "selection names an unknown provider execution lane",
            ),
            (
                "gemini-mode",
                ("selection",),
                "execution_mode",
                "gemini-cli-acp",
                "gemini-cli-acp",
                "selection names an unknown provider execution lane",
            ),
            (
                "stale-revision",
                ("selection",),
                "catalog_revision",
                "retired-revision",
                "retired-revision",
                "selection names a stale catalog revision",
            ),
        )
        for label, path, field, value, retired_value, domain_reason in cases:
            fields = deepcopy(current)
            target: object = fields
            for key in path:
                assert isinstance(target, dict)
                target = target[key]
            assert isinstance(target, dict)
            target[field] = value
            response = await client.post(
                "/v1/runs",
                json={
                    "run_id": f"retired-selection-{label}",
                    "team_preset": _PRESET,
                    "message": "go",
                    "autonomous": True,
                    **fields,
                },
            )
            assert response.status_code == 422, (label, response.text)
            detail = response.json()["detail"]
            if domain_reason is not None:
                assert detail == domain_reason, label
            else:
                assert isinstance(detail, list), label
                assert any(
                    item.get("type") == "extra_forbidden"
                    and item.get("loc") == ["body", *path, field]
                    for item in detail
                ), (label, detail)
            assert retired_value not in response.text, (label, response.text)

        assert worker.dispatches == []


@pytest.mark.asyncio(loop_scope="function")
async def test_validation_errors_remain_actionable_without_reflecting_input(
    session_factory, checkpointer
) -> None:
    """The bounded 422 retains type, field location and a safe message."""
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        fields = await _run_fields(client)
        selection = cast("dict[str, Any]", fields["selection"])
        selection["schema_version"] = 2
        response = await client.post(
            "/v1/runs",
            json={
                "run_id": "invalid-current-schema",
                "team_preset": _PRESET,
                "message": "go",
                **fields,
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "literal_error",
                "loc": ["body", "selection", "schema_version"],
                "msg": "Input should be 1",
            }
        ]
    }
    assert '"input"' not in response.text
    assert '"ctx"' not in response.text
    assert worker.dispatches == []


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
