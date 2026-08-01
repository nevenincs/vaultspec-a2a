"""Certify the model assignment the gateway ADVERTISES is the one the worker RUNS.

Provider readiness is agreed in the gateway process: run-start answers a per-role
assignment carrying the provider, the capability and a ``provider_ready`` verdict,
and the preset listing answers the same shape. What actually executes is decided in
a DIFFERENT process. The gateway freezes the assignment into the dispatch envelope,
the worker parses it back and builds each role's model from its own parse.

Agreement across that boundary is asserted nowhere. Readiness settled at admission
is not evidence about dispatch: the envelope's frozen map is typed as free-form
values on the wire, and the worker's parse is deliberately tolerant of drift, so a
value the gateway never intended can be absorbed on the far side and the run will
still execute - on a provider whose readiness was never probed. That is the seam
the live model-resolution defect sat in, and it is upstream of every network call,
so no transport assertion can reach it.

This test drives one real run through the production chain and compares the two
sides for every role: the provider and capability the gateway advertised at
admission, against the provider and capability the executed graph actually used,
read back from the run's own agent metadata. The comparison is per-role and exact.

What turns this test RED, named before it was authored:

- the worker resolving a role to a different provider than the one advertised -
  including the tolerant substitution of a default when a frozen value is not
  recognised, which is the silent form of this failure and the dangerous one,
  because an advertised no-cost provider can become a metered one;
- the worker dropping the advertised capability and running a different one;
- an assignment advertised as ready that the worker cannot build at all, which
  leaves the role absent from the executed graph entirely.

A transport symptom is explicitly NOT the trigger: the run is required to complete
first, so a dispatch failure or an unreachable worker fails as itself rather than
masquerading as a disagreement.

Absence is loud: the scripted model backend is probed over real loopback and a
missing one is a skip naming the substrate and the command that supplies it.
"""

from __future__ import annotations

import os
import socket
import time
import tomllib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import pytest

from ..acceptance import certified_gateway

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


def _tape_server_listening(base: str) -> bool:
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2.0)
        return probe.connect_ex((host, port)) == 0


def _await_terminal(gateway: CertifiedGateway, run_id: str, *, budget: float) -> dict:
    deadline = time.monotonic() + budget
    last: dict = {}
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
    if not _tape_server_listening(tape_server):
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
        with gateway.client(timeout=90.0) as client:
            started = client.post(
                "/v1/runs",
                json={
                    "team_preset": _PRESET,
                    "stage": "start",
                    "run_id": run_id,
                    "message": "Do the task and stop.",
                    "autonomous": True,
                    "actor_tokens": {
                        "tokens": {role: f"tok-{role}" for role in roles},
                        "engine_bearer": "bearer",
                    },
                },
            )
        assert started.status_code == 201, started.text
        advertised_payload = started.json()

        # The run must genuinely execute first, so a transport failure fails as
        # itself instead of being read as a disagreement.
        snapshot = _await_terminal(gateway, run_id, budget=180.0)
        assert snapshot["status"] == "completed", snapshot

        history = gateway.thread_state(run_id)
        assert history.status_code == 200, history.text
        executed_agents = history.json()["state"]["agents"]

    advertised: dict[str, dict[str, Any]] = {
        entry["agent_id"]: entry for entry in advertised_payload["assignments"]
    }
    assert set(advertised) == set(roles), advertised_payload

    executed: dict[str, dict[str, Any]] = {
        agent["agent_id"]: agent for agent in executed_agents
    }

    disagreements: list[str] = []
    for role in roles:
        promise = advertised[role]
        actual = executed.get(role)
        if actual is None:
            disagreements.append(
                f"{role}: advertised provider={promise['provider_id']!r} "
                f"(ready={promise['provider_ready']!r}) but the role never "
                f"appeared in the executed graph"
            )
            continue
        if actual["provider"] != promise["provider_id"]:
            disagreements.append(
                f"{role}: admission advertised provider "
                f"{promise['provider_id']!r} (ready={promise['provider_ready']!r}) "
                f"but the worker executed on {actual['provider']!r}"
            )
        if actual["model"] != promise["capability"]:
            disagreements.append(
                f"{role}: admission advertised capability "
                f"{promise['capability']!r} but the worker executed "
                f"{actual['model']!r}"
            )

    assert not disagreements, (
        "the gateway advertised an assignment the worker did not run:\n  "
        + "\n  ".join(disagreements)
    )
