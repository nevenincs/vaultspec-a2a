"""Certify the dashboard-facing public run contract against a real stack.

Every scenario drives the versioned public surface of one real armed-desktop
gateway - a real gateway process, a real gateway-owned worker, and real SQLite
control and checkpoint stores - behind the real attach-control credential. None
uses the test-only authentication bypass.

These certify the provider-INDEPENDENT gateway contract: run admission, run
creation and addressability, the status snapshot's shape, cancellation routing,
and authentication all hold whether a run ultimately completes or fails, so they
need no deterministic provider backend. Each pairs its positive assertion with a
discriminator so an empty or mis-authenticated response cannot pass:

- prepare reserves capacity WITHOUT creating a run or accepting a token, and an
  unauthenticated prepare is refused - so the reservation cannot be an artefact
  of a disabled gate;
- start creates a durable dispatched run that status then discovers, the
  discriminator that separates start (durable) from prepare (no run);
- status returns a coherent snapshot naming the launched preset and role for a
  real run and a real 404 for an absent one, so a blanket 200 cannot pass;
- cancel routes through the versioned verb: an absent run is a real 404 and an
  unauthenticated cancel is refused;
- the authenticated progress channel opens and relays the run's bounded
  lifecycle frame while refusing an unauthenticated open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from ...thread.enums import (
    TERMINAL_STATUS_VALUES,
    TERMINAL_STATUSES,
    ThreadStatus,
)
from .. import DEFAULT_REQUIRED_ROLE, DEFAULT_TEAM_PRESET
from ._sse import read_frame
from .conftest import wait_for_terminal

if TYPE_CHECKING:
    from .. import CertifiedGateway


def test_authenticated_prepare_reserves_without_run_or_token(
    gateway: CertifiedGateway,
) -> None:
    """S78: a prepare reserves capacity but mints neither run nor token.

    Discriminating: the response carries a reservation, a non-secret lease, and
    the validated required-role set, but NO run id and NO actor tokens, and
    active-run discovery stays empty - so no durable run was created. An
    unauthenticated prepare is refused 401, proving the reservation above passed
    a real gate rather than a disabled one.
    """
    run_id = "run-contract-prepare"
    response = gateway.prepare(run_id)
    assert response.status_code == 201, response.text
    body = response.json()

    # Permitted coordination identity is present...
    assert body["stage"] == "prepared"
    assert body["reservation_id"]
    assert body["lease_id"].startswith("lease-")
    assert body["required_roles"] == [DEFAULT_REQUIRED_ROLE]
    # ...while a durable run and any token are absent by construction.
    assert "run_id" not in body
    assert "actor_tokens" not in body

    discovered = gateway.active_runs()
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["runs"] == []

    # The gate is real: an unauthenticated prepare never reaches admission.
    unauth = httpx.post(
        f"{gateway.base_url}/v1/runs",
        json={
            "team_preset": DEFAULT_TEAM_PRESET,
            "stage": "prepare",
            "run_id": "run-contract-prepare-unauth",
            "autonomous": True,
        },
        timeout=30.0,
    )
    assert unauth.status_code == 401, unauth.text

    # Keep the shared gateway's bounded capacity clean for later scenarios.
    released = gateway.release(run_id, body["reservation_id"])
    assert released.status_code == 201, released.text
    assert released.json()["released"] is True


def test_authenticated_start_creates_a_dispatched_run(
    gateway: CertifiedGateway,
) -> None:
    """S170: a one-shot start creates a durable run that discovery then finds.

    Discriminating against the prepare above: start returns a run id and that run
    is immediately addressable through run-status (HTTP 200), whereas a prepare
    created nothing addressable. An unauthenticated start is refused 401.
    """
    run_id = "run-contract-start"
    response = gateway.start(run_id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["api_version"] == "v1"
    assert body["run_id"] == run_id
    assert body["eligible"] is True
    assert body["status"]

    # The one execution authority a start discloses is the frozen assignment; the
    # retired profile pair is deliberately absent from this response rather than
    # served empty, so asserting a `profile_id` here would demand a field the
    # contract removed. What must hold is that every required role was frozen to
    # the lane this stack selected - the in-process one, which cannot spend.
    assert "profile_id" not in body
    frozen = body["frozen_assignment"]
    assert frozen["digest"]
    assignments = frozen["assignments"]
    assert {item["role_id"] for item in assignments} == {DEFAULT_REQUIRED_ROLE}
    assert all(
        item["provider_id"] == gateway.selected_provider_id for item in assignments
    )

    # The durable run exists (unlike a prepare) - status resolves it.
    status = gateway.status(run_id)
    assert status.status_code == 200, status.text
    assert status.json()["run_id"] == run_id

    unauth = httpx.post(
        f"{gateway.base_url}/v1/runs",
        json={
            "team_preset": DEFAULT_TEAM_PRESET,
            "stage": "start",
            "run_id": "run-contract-start-unauth",
            "message": "unauthenticated",
            "autonomous": True,
        },
        timeout=30.0,
    )
    assert unauth.status_code == 401, unauth.text


def test_authenticated_status_snapshot_is_coherent_or_a_real_not_found(
    gateway: CertifiedGateway,
) -> None:
    """S171: status is a coherent snapshot for a real run and a real 404 otherwise.

    Discriminating on snapshot SHAPE, which is independent of a run's eventual
    outcome: a real run resolves to a snapshot whose run id, topology preset, and
    per-role identity match what was launched and whose status parses as a valid
    lifecycle status, while an unrelated run id returns 404 - so a blanket 200, an
    empty body, or a snapshot for the wrong run cannot satisfy this. The terminal
    status is validated against the production status enum, never a copied
    literal.
    """
    run_id = "run-contract-status"
    started = gateway.start(run_id)
    assert started.status_code == 201, started.text

    snapshot = wait_for_terminal(gateway, run_id)
    assert snapshot["run_id"] == run_id
    assert snapshot["topology"]["team_preset"] == DEFAULT_TEAM_PRESET
    assert any(role["agent_id"] == DEFAULT_REQUIRED_ROLE for role in snapshot["roles"])
    # The status parses as a real lifecycle status and the run reached a terminal
    # one; the checkpoint cursor is a coherent integer, not a placeholder.
    assert ThreadStatus(snapshot["status"]) in TERMINAL_STATUSES
    assert isinstance(snapshot["last_sequence"], int)

    missing = gateway.status("run-contract-status-absent")
    assert missing.status_code == 404, missing.text


def test_cancel_verb_routes_authenticated_and_reports_real_not_found(
    gateway: CertifiedGateway,
) -> None:
    """S172: the versioned cancel verb is attach-gated and 404s an absent run.

    Discriminating on the provider-independent half of the cancel contract: an
    authenticated cancel of an unrelated run id returns a real 404 (not a blanket
    acceptance), and the identical cancel without the attach credential is refused
    401 - so the verb is genuinely routed and gated. Driving a live run all the
    way to a terminal CANCELLED status needs a run held non-terminal by the
    deterministic provider and is certified in the Compose service suite.
    """
    absent = gateway.cancel("run-contract-cancel-absent", idempotency_key="cancel-1")
    assert absent.status_code == 404, absent.text

    unauth = httpx.post(
        f"{gateway.base_url}/v1/runs/run-contract-cancel-absent/cancel", timeout=30.0
    )
    assert unauth.status_code == 401, unauth.text


async def _open_terminal_frame(
    gateway: CertifiedGateway, run_id: str
) -> tuple[dict, str]:
    async with (
        gateway.async_client(timeout=30.0) as client,
        client.stream("GET", gateway.stream_path(run_id)) as response,
    ):
        assert response.status_code == 200, response
        assert response.headers["content-type"].startswith("text/event-stream")
        return await read_frame(response.aiter_lines(), wanted="thread_terminal")


@pytest.mark.asyncio(loop_scope="function")
async def test_authenticated_progress_stream_relays_bounded_lifecycle_frame(
    gateway: CertifiedGateway,
) -> None:
    """S173: the authenticated progress channel opens, is gated, and relays a frame.

    Discriminating: an unauthenticated stream open is refused 401; the
    authenticated open returns 200 with the SSE media type and relays the run's
    lifecycle terminal frame carrying the run id and a valid lifecycle status
    (permitted identity present) while no forbidden body field - a prompt,
    document, artifact body, or edit diff - appears in the encoded frame, so an
    empty frame cannot pass.
    """
    run_id = "run-contract-progress"
    started = gateway.start(run_id)
    assert started.status_code == 201, started.text
    wait_for_terminal(gateway, run_id)

    # The gate is real: an unauthenticated stream open never begins.
    unauth = httpx.get(f"{gateway.base_url}{gateway.stream_path(run_id)}", timeout=30.0)
    assert unauth.status_code == 401, unauth.text

    frame, raw = await _open_terminal_frame(gateway, run_id)

    # Permitted identity present...
    assert frame["thread_id"] == run_id
    assert frame["status"] in TERMINAL_STATUS_VALUES
    # ...forbidden bodies absent from the encoded frame.
    for forbidden in ("content", "prompt", "document", "diff", "old_text", "new_text"):
        assert forbidden not in raw, f"forbidden field {forbidden!r} crossed the edge"
