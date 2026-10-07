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

Absence is loud: the in-process deterministic lane is resolved from the
gateway's own served catalog, and a missing lane is a skip naming it and what
supplies it - because a run frozen on any OTHER served lane would execute a real
external provider, which this deterministic certification must never do.
"""

from __future__ import annotations

import tomllib
import uuid
from pathlib import Path
from typing import Any

from ..acceptance.tests._harness import certified_gateway
from ..graph.enums import Provider
from ..testing import ok_body, wait_for_run_status

# A star preset, so the run crosses the supervisor's routing turns as well as its
# worker's; agreement is asserted for every role the freeze discloses.
_PRESET = "deterministic-supervisor-routing"
_PRESET_PATH = (
    Path(__file__).resolve().parents[1]
    / "team"
    / "presets"
    / "teams"
    / f"{_PRESET}.toml"
)

# The in-process lane the preset runs on. The shared selection never returns a
# lane that bills, so a host holding a live provider session cannot turn this
# deterministic certification into spend.
_PRESET_LANE = Provider.DETERMINISTIC.value

_WORKER_READY_BUDGET_SECONDS = "120"


def _preset_roles() -> list[str]:
    """The preset's declared worker ids, read from the bundled preset itself."""
    preset = tomllib.loads(_PRESET_PATH.read_text(encoding="utf-8"))
    roles = [worker["agent_id"] for worker in preset["team"]["workers"]]
    if not roles:
        raise AssertionError(f"preset {_PRESET} declares no workers")
    return roles


def test_advertised_assignment_is_the_assignment_the_worker_executes(
    tmp_path: Path,
) -> None:
    """Every role executes on the provider and capability admission advertised."""
    roles = _preset_roles()

    run_id = f"assignment-agreement-{uuid.uuid4().hex[:12]}"
    with certified_gateway(
        tmp_path,
        VAULTSPEC_A2A_WORKER_READY_TIMEOUT_SECONDS=_WORKER_READY_BUDGET_SECONDS,
    ) as gateway:
        workspace_root = str(tmp_path)
        selection = gateway.served_in_process_selection(
            workspace_root, prefer_provider_id=_PRESET_LANE
        )
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
        snapshot = wait_for_run_status(
            lambda: ok_body(gateway.status(run_id)),
            timeout=180.0,
            label=f"run {run_id}",
        )
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
        # model_name, not model: the freeze names a concrete catalog identifier
        # and `model` carries a four-value capability tier, so comparing them
        # asserted that two different vocabularies were equal and could never
        # hold. A frozen run resolves no tier at all, which is why `model` reads
        # back empty here and why this field had to exist to compare at all.
        if actual["model_name"] != promise["model_name"]:
            disagreements.append(
                f"{role}: the freeze named model "
                f"{promise['model_name']!r} but the worker executed "
                f"{actual['model_name']!r}"
            )

    assert not disagreements, (
        "the gateway froze an assignment the worker did not run:\n  "
        + "\n  ".join(disagreements)
    )
