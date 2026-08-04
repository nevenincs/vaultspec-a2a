"""Certify the model assignment the gateway ADVERTISES is the one the worker RUNS.

The assignment is agreed in the gateway process: run-start freezes the explicit
catalog selection and answers it as the run's ``frozen_assignment``. What
actually executes is decided in a DIFFERENT process. The gateway renders the
freeze into the dispatch envelope, the worker parses it back and builds each
role's model from its own parse.

Agreement across that boundary is asserted nowhere. A selection validated at
admission is not evidence about dispatch: the envelope's frozen map is typed as
free-form values on the wire, and the worker's parse is deliberately tolerant of
drift, so a value the gateway never intended can be absorbed on the far side and
the run will still execute - on a provider the caller never selected. That is
the seam the live model-resolution defect sat in, and it is upstream of every
network call, so no transport assertion can reach it.

This test drives one real run through the production chain and compares the two
sides for every role: the provider and exact model value the gateway froze and
disclosed at admission, against the provider and model the executed graph
actually used, read back from the run's own agent metadata. The comparison is
per-role and exact.

What turns this test RED, named before it was authored:

- the worker resolving a role to a different provider than the one frozen -
  including the tolerant substitution of a default when a frozen value is not
  recognised, which is the silent form of this failure and the dangerous one,
  because a selected no-cost provider can become a metered one;
- the worker dropping the frozen model value and running a different one;
- a frozen role the worker cannot build at all, which leaves the role absent
  from the executed graph entirely.

A transport symptom is explicitly NOT the trigger: the run is required to complete
first, so a dispatch failure or an unreachable worker fails as itself rather than
masquerading as a disagreement.

Absence is loud: the scripted model backend is probed over real loopback, the
in-process lane is resolved from the gateway's own served catalog, and a
missing substrate is a skip naming it and what supplies it - because a run
frozen on any OTHER served lane would execute a real external provider, which
this deterministic certification must never do.
"""

from __future__ import annotations

import os
import time
import tomllib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from ..acceptance import certified_gateway
from ..testing.catalog_selection import (
    NoSelectableLaneError,
    in_process_selection,
    preset_in_process_provider,
)
from ._net import tape_server_listening

if TYPE_CHECKING:
    from ..acceptance import CertifiedGateway

_TAPE_SERVER_DEFAULT = "http://127.0.0.1:8100"
_TAPE_SERVER_ENV = "MOCK_API_BASE"
_SUPPLY_TAPE_SERVER = (
    "docker compose -f service/docker-compose.integration.yml up -d vidaimock"
)

# A multi-role preset, so agreement is asserted across several roles in one run
# rather than generalised from a single worker.
_PRESET = "mock-success-multi"
_PRESET_PATH = (
    Path(__file__).resolve().parents[1]
    / "team"
    / "presets"
    / "teams"
    / f"{_PRESET}.toml"
)

_WORKER_READY_BUDGET_SECONDS = "120"
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "error"})


def _preset_roles() -> list[str]:
    """The preset's declared worker ids, read from the bundled preset itself."""
    preset = tomllib.loads(_PRESET_PATH.read_text(encoding="utf-8"))
    roles = [worker["agent_id"] for worker in preset["team"]["workers"]]
    if not roles:
        raise AssertionError(f"preset {_PRESET} declares no workers")
    return roles


def _tape_server_base() -> str:
    return (os.environ.get(_TAPE_SERVER_ENV) or "").strip() or _TAPE_SERVER_DEFAULT


def _served_in_process_selection(
    gateway: CertifiedGateway, workspace_root: str
) -> dict[str, Any]:
    """Resolve the served in-process lane's selection, or skip naming the gap.

    A deterministic certification run must freeze the in-process lane: the
    freeze wins outright at compilation, so a selection naming any other served
    lane would hand every role to a real external provider. Keeping a billable
    lane out is the shared mechanism's own guarantee - it will not hand one back
    even when it is the only selectable thing this stack serves - so what remains
    local is the shape of the refusal: a loud skip naming the missing serving,
    never a run that quietly spends on whichever external lane the host happens
    to have installed.
    """
    with gateway.client(timeout=120.0) as client:
        response = client.get(
            "/v1/provider-catalog", params={"workspace_root": workspace_root}
        )
    assert response.status_code == 200, response.text
    try:
        return in_process_selection(
            response.json(), prefer_provider_id=preset_in_process_provider(_PRESET)
        )
    except NoSelectableLaneError as exc:
        pytest.skip(f"a deterministic certification run cannot be selected here: {exc}")


def _await_terminal(
    gateway: CertifiedGateway, run_id: str, *, budget: float
) -> dict[str, Any]:
    deadline = time.monotonic() + budget
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = gateway.status(run_id)
        if response.status_code == 200:
            last = response.json()
            if last.get("status") in _TERMINAL_STATUSES:
                return last
        time.sleep(1.0)
    raise AssertionError(
        f"run {run_id} never reached a terminal state within {budget:.0f}s; "
        f"last status snapshot: {last or 'never readable'}"
    )


def test_advertised_assignment_is_the_assignment_the_worker_executes(
    tmp_path: Path,
) -> None:
    """Every role executes on the provider and capability admission advertised."""
    roles = _preset_roles()

    tape_server = _tape_server_base()
    if not tape_server_listening(tape_server):
        pytest.skip(
            f"the scripted model backend is unavailable at {tape_server} "
            f"(set {_TAPE_SERVER_ENV} to an existing one, or supply it: "
            f"{_SUPPLY_TAPE_SERVER})"
        )

    run_id = f"assignment-agreement-{uuid.uuid4().hex[:12]}"
    with certified_gateway(
        tmp_path,
        **{
            _TAPE_SERVER_ENV: tape_server,
            "VAULTSPEC_WORKER_READY_TIMEOUT_SECONDS": _WORKER_READY_BUDGET_SECONDS,
        },
    ) as gateway:
        workspace_root = str(tmp_path)
        selection = _served_in_process_selection(gateway, workspace_root)
        with gateway.client(timeout=90.0) as client:
            started = client.post(
                "/v1/runs",
                json={
                    "team_preset": _PRESET,
                    "stage": "start",
                    "run_id": run_id,
                    "message": "Do the task and stop.",
                    "autonomous": True,
                    "selection": selection,
                    "metadata": {"workspace_root": workspace_root},
                    "actor_tokens": {
                        "tokens": {role: f"tok-{role}" for role in roles},
                        "engine_bearer": "bearer",
                    },
                },
            )
        assert started.status_code == 201, started.text
        frozen = started.json()["frozen_assignment"]
        assert frozen, "run-start must disclose the freeze it dispatched"

        # The run must genuinely execute first, so a transport failure fails as
        # itself instead of being read as a disagreement.
        snapshot = _await_terminal(gateway, run_id, budget=180.0)
        assert snapshot["status"] == "completed", snapshot

        history = gateway.thread_state(run_id)
        assert history.status_code == 200, history.text
        executed_agents = history.json()["state"]["agents"]

    advertised: dict[str, dict[str, Any]] = {
        entry["role_id"]: entry for entry in frozen["assignments"]
    }
    assert set(advertised) == set(roles), frozen

    executed: dict[str, dict[str, Any]] = {
        agent["agent_id"]: agent for agent in executed_agents
    }

    disagreements: list[str] = []
    for role in roles:
        promise = advertised[role]
        actual = executed.get(role)
        if actual is None:
            disagreements.append(
                f"{role}: the freeze named provider={promise['provider_id']!r} "
                f"model={promise['model_name']!r} but the role never "
                f"appeared in the executed graph"
            )
            continue
        if actual["provider"] != promise["provider_id"]:
            disagreements.append(
                f"{role}: the freeze named provider "
                f"{promise['provider_id']!r} "
                f"but the worker executed on {actual['provider']!r}"
            )
        if actual["model"] != promise["model_name"]:
            disagreements.append(
                f"{role}: the freeze named model "
                f"{promise['model_name']!r} but the worker executed "
                f"{actual['model']!r}"
            )

    assert not disagreements, (
        "the gateway froze an assignment the worker did not run:\n  "
        + "\n  ".join(disagreements)
    )
