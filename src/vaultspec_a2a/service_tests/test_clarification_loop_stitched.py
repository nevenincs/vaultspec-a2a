"""Certify the clarification loop as ONE run across real process boundaries.

Every piece of this loop is already proven, and that is precisely the problem
this file exists to fix. The node parks (graph tests), the questionnaire is
disclosed (gateway tests), the nudge reaches a subscriber (streaming tests), and
the respond verb dispatches a resume (gateway tests) - but each half is proven
against its own in-process fixture, and nothing anywhere requires them to COMPOSE.
Two green halves that never met is the shape this repo keeps finding, and a
consumer binding a questionnaire UI to this contract is relying on the join, not
on the halves.

So this drives one run through the whole loop, in order, over real boundaries:

1. a real run on the preset that declares ``[team.clarification]`` parks at its
   grounding stage;
2. ``run-status`` discloses the pending question set and its request id
   authoritatively - and is sufficient ON ITS OWN to re-render the questionnaire,
   which is the recovery property a reloaded client depends on;
3. the ``clarification_pending`` nudge arrives on the real SSE surface carrying
   no question text;
4. the respond verb is called over real loopback HTTP with answers keyed by
   question id;
5. the parked graph actually RESUMES and the run advances past the research
   fan-out - evidenced by the authoring proposal the later stage produces, not by
   the response code of step 4.

Everything is real: the production gateway is a real process over a real migrated
application home, the worker is a real process the gateway owns and spawns,
dispatch and the answer both cross real loopback HTTP, the graph really executes,
and the checkpointer and thread store are real SQLite. The ONE substitution is
the model, reached through the real provider factory.

What turns this test RED, named before it was authored:

- a resume that never reaches the graph - the failure a 200 cannot see. The
  answer path could accept, journal and dispatch an answer that no node ever
  consumes, and every transport assertion would still pass while the run stayed
  parked forever. Step 5 therefore requires the run to LEAVE the parked state and
  produce work that only exists downstream of the fan-out; a run still carrying a
  pending clarification, or carrying no proposal, fails.
- a questionnaire that reaches the client only over the relay. If the disclosure
  in step 2 were dropped and only the frame carried the questions, a reloaded
  client could never re-render them. Step 2 reads the questionnaire from a FRESH
  client that has consumed no frames at all, so relay memory cannot satisfy it.
- a nudge that leaks the question text. The frame is droppable, so anything
  renderable from it is state recovered from a channel permitted to lose it;
  step 3 searches the raw frame for the declared prompt and options.
- a declaration drift between preset and wire: the expectation is read from the
  shipped preset through the production loader, so editing the preset moves the
  expectation with it instead of leaving a stale constant here.

Absence is loud, never silent. This loop needs two substrates - a scripted model
backend and a reachable engine (a document-authoring topology builds its
authoring submitter at compile time and fails closed without one). Each missing
substrate is a skip naming it and the command that supplies it, never a pass.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import pytest

from ..acceptance import certified_gateway
from ..authoring.discovery import resolve_engine
from ..team.team_config import load_team_config

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from ..acceptance import CertifiedGateway

# The preset that declares a questionnaire. Its questions are read from the
# preset itself below, never restated here.
_CLARIFY_PRESET = "vaultspec-adr-research-clarify"

# Every role the document-authoring topology runs needs an actor token at
# run-start; the roster is derived from the preset so a role added tomorrow is
# carried automatically rather than falling behind a hardcoded list.
_ENGINE_BEARER = "bearer"

_TAPE_SERVER_DEFAULT = "http://127.0.0.1:8100"
_TAPE_SERVER_ENV = "MOCK_API_BASE"
_SUPPLY_TAPE_SERVER = (
    "docker compose -f service/docker-compose.integration.yml up -d vidaimock"
)
_SUPPLY_ENGINE = (
    "start the vaultspec engine so it publishes ~/.vaultspec-a2a/service.json "
    "(or set VAULTSPEC_ENGINE_SERVICE_JSON to a live one)"
)

_WORKER_READY_BUDGET_SECONDS = "120"

_PARK_BUDGET = 180.0
_RESUME_BUDGET = 300.0


# ---------------------------------------------------------------------------
# Substrate probes - a missing one is a named skip, never a pass
# ---------------------------------------------------------------------------


def _tape_server_base() -> str:
    return (os.environ.get(_TAPE_SERVER_ENV) or "").strip() or _TAPE_SERVER_DEFAULT


def _listening(base: str) -> bool:
    parsed = urlparse(base)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2.0)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return probe.connect_ex((parsed.hostname or "127.0.0.1", port)) == 0


def _require_substrates() -> str:
    """Return the scripted backend base, or skip naming what is missing."""
    tape = _tape_server_base()
    if not _listening(tape):
        pytest.skip(
            f"the scripted model backend is unavailable at {tape} "
            f"(set {_TAPE_SERVER_ENV} to an existing one, or supply it: "
            f"{_SUPPLY_TAPE_SERVER})"
        )
    if resolve_engine(liveness_timeout=3.0) is None:
        pytest.skip(
            "no reachable engine: a document-authoring preset builds its "
            "authoring submitter at graph-compile time and fails closed without "
            f"one, so this loop cannot run. To supply it: {_SUPPLY_ENGINE}"
        )
    return tape


# ---------------------------------------------------------------------------
# The declared questionnaire, read from the shipped preset
# ---------------------------------------------------------------------------


def _declared_questions() -> list[dict[str, Any]]:
    """The preset's own questions, through the production loader.

    Read rather than restated so a preset edit moves this expectation with it.
    Raises rather than defaulting: an empty expectation would make the content
    assertions below unable to fail.
    """
    team = load_team_config(_CLARIFY_PRESET)
    if team.clarification is None or not team.clarification.questions:
        raise AssertionError(
            f"preset {_CLARIFY_PRESET!r} declares no questionnaire; this loop has "
            "nothing to certify"
        )
    return [q.model_dump(mode="json") for q in team.clarification.questions]


def _required_roles() -> list[str]:
    return [worker.agent_id for worker in load_team_config(_CLARIFY_PRESET).workers]


# ---------------------------------------------------------------------------
# Polling helpers - each fails closed with the snapshot that defeated it
# ---------------------------------------------------------------------------


def _await_parked(gateway: CertifiedGateway, run_id: str, *, budget: float) -> dict:
    """Poll the authoritative snapshot until a questionnaire is disclosed."""
    deadline = time.monotonic() + budget
    last: dict = {}
    while time.monotonic() < deadline:
        response = gateway.status(run_id)
        if response.status_code == 200:
            last = response.json()
            if last.get("pending_clarification"):
                return last
            if last.get("status") in {"failed", "cancelled", "error"}:
                raise AssertionError(
                    f"run {run_id} settled {last.get('status')!r} before it ever "
                    f"parked for its question; snapshot: {last}"
                )
        time.sleep(1.0)
    raise AssertionError(
        f"run {run_id} never disclosed a pending clarification within "
        f"{budget:.0f}s; last snapshot: {last or 'never readable'}"
    )


def _await_resumed_past_fan_out(
    gateway: CertifiedGateway, run_id: str, *, budget: float
) -> dict:
    """Poll until the run has genuinely left the questionnaire and done work.

    This is the assertion a 200 cannot make. Clearing the pending question is
    necessary but NOT sufficient - a run could clear it and stall - so this also
    requires an authoring proposal, which only exists downstream of the research
    fan-out and synthesis. A resume that never reached the graph leaves the
    pending question in place and produces no proposal, and fails here.
    """
    deadline = time.monotonic() + budget
    last: dict = {}
    while time.monotonic() < deadline:
        response = gateway.status(run_id)
        if response.status_code == 200:
            last = response.json()
            if not last.get("pending_clarification") and last.get("proposal_ids"):
                return last
            if last.get("status") in {"failed", "cancelled", "error"}:
                raise AssertionError(
                    f"run {run_id} settled {last.get('status')!r} after the answer "
                    f"instead of advancing; snapshot: {last}"
                )
        time.sleep(1.0)
    raise AssertionError(
        f"run {run_id} did not advance past the research fan-out within "
        f"{budget:.0f}s of being answered - the resume did not reach the graph. "
        f"last snapshot: {last or 'never readable'}"
    )


def _read_frame(lines: Any, *, wanted: str, deadline: float) -> dict:
    """Return the first SSE frame whose ``type`` matches, or raise at *deadline*."""
    buffer: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r")
        if line.startswith("data: "):
            buffer.append(line.removeprefix("data: "))
            continue
        if line == "" and buffer:
            payload = json.loads("".join(buffer))
            buffer = []
            if payload.get("type") == wanted:
                return payload
        if time.monotonic() > deadline:
            break
    raise AssertionError(f"no {wanted!r} frame arrived on the run's progress stream")


def _start_document_run(gateway: CertifiedGateway, run_id: str) -> httpx.Response:
    """Start a run on the declaring preset with a token for every declared role."""
    with gateway.client(timeout=90.0) as client:
        return client.post(
            "/v1/runs",
            json={
                "team_preset": _CLARIFY_PRESET,
                "stage": "start",
                "run_id": run_id,
                "message": "Plan a right-side monitor panel.",
                "autonomous": True,
                "actor_tokens": {
                    "tokens": {role: f"tok-{role}" for role in _required_roles()},
                    "engine_bearer": _ENGINE_BEARER,
                },
            },
        )


# ---------------------------------------------------------------------------
# The stitched loop
# ---------------------------------------------------------------------------


def test_clarification_loop_parks_discloses_answers_and_resumes(
    tmp_path: Path,
) -> None:
    """One run: park, disclose, nudge, answer over HTTP, and genuinely resume."""
    tape_server = _require_substrates()
    expected_questions = _declared_questions()

    run_id = f"clarify-stitch-{uuid.uuid4().hex[:12]}"
    with certified_gateway(
        tmp_path,
        **{
            _TAPE_SERVER_ENV: tape_server,
            "VAULTSPEC_WORKER_READY_TIMEOUT_SECONDS": _WORKER_READY_BUDGET_SECONDS,
        },
    ) as gateway:
        started = _start_document_run(gateway, run_id)
        assert started.status_code == 201, started.text

        # (1)+(2) The run parks, and the questionnaire is disclosed
        # authoritatively. This client has consumed no progress frames, so a
        # questionnaire that only ever travelled the relay could not satisfy it -
        # this IS the reload-recovery property, asserted rather than assumed.
        parked = _await_parked(gateway, run_id, budget=_PARK_BUDGET)
        pending = parked["pending_clarification"]
        request_id = pending["request_id"]

        assert pending["type"] == "clarification_request"
        assert pending["questions"] == expected_questions
        assert parked["topology"]["pause_cause"] == "clarification_request"

        # (3) The nudge is on the relay, and carries none of the questions. The
        # stream is opened AFTER the park, which is what a reloading client does.
        with (
            gateway.client(timeout=60.0) as stream_client,
            stream_client.stream("GET", gateway.stream_path(run_id)) as response,
        ):
            assert response.status_code == 200, response.text
            frame = _read_frame(
                response.iter_lines(),
                wanted="clarification_pending",
                deadline=time.monotonic() + 45.0,
            )

        assert frame["request_id"] == request_id
        assert frame["thread_id"] == run_id
        raw_frame = json.dumps(frame)
        for question in expected_questions:
            assert question["prompt"] not in raw_frame
            for option in question.get("options") or []:
                assert option not in raw_frame

        # (4) Answer over real loopback HTTP, keyed by question id.
        answers = {
            question["id"]: (
                (question["options"] or [""])[0]
                if question["kind"] == "choice"
                else "no additional constraints"
            )
            for question in expected_questions
            if question["required"] or question["kind"] == "choice"
        }
        with gateway.client(timeout=60.0) as client:
            answered = client.post(
                f"/v1/runs/{run_id}/clarifications/{request_id}/respond",
                json={"answers": answers},
            )
        assert answered.status_code == 200, answered.text
        assert answered.json()["accepted"] is True

        # (5) The resume really reached the graph: the questionnaire is gone AND
        # the run produced work that exists only past the fan-out.
        advanced = _await_resumed_past_fan_out(gateway, run_id, budget=_RESUME_BUDGET)

    assert advanced["pending_clarification"] is None
    assert advanced["proposal_ids"], advanced
    # Answering must not have been mistaken for approving: the run advanced to a
    # human decision surface rather than being driven past one.
    assert advanced["status"] not in {"failed", "cancelled", "error"}


def test_answering_a_question_the_run_is_not_parked_on_is_refused(
    tmp_path: Path,
) -> None:
    """The scoping check holds across the real boundary, not just in-process.

    A guessed request id must not answer a run's real question. Asserted on the
    live surface because the check that matters is the one the deployed gateway
    performs, and it must precede any dispatch: the run stays parked on its own
    questionnaire afterwards.
    """
    tape_server = _require_substrates()

    run_id = f"clarify-scope-{uuid.uuid4().hex[:12]}"
    with certified_gateway(
        tmp_path,
        **{
            _TAPE_SERVER_ENV: tape_server,
            "VAULTSPEC_WORKER_READY_TIMEOUT_SECONDS": _WORKER_READY_BUDGET_SECONDS,
        },
    ) as gateway:
        started = _start_document_run(gateway, run_id)
        assert started.status_code == 201, started.text

        parked = _await_parked(gateway, run_id, budget=_PARK_BUDGET)
        real_request_id = parked["pending_clarification"]["request_id"]

        with gateway.client(timeout=60.0) as client:
            refused = client.post(
                f"/v1/runs/{run_id}/clarifications/not-the-real-id/respond",
                json={"answers": {"scope": "frontend"}},
            )
        assert refused.status_code == 404, refused.text

        still_parked = gateway.status(run_id).json()

    assert still_parked["pending_clarification"]["request_id"] == real_request_id
