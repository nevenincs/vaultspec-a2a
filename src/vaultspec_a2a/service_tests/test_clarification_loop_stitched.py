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
   fan-out - evidenced by the synthesis turn the joined stage produces, not by
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
  pending clarification, or carrying no synthesis turn, fails. What the engine
  then does with that document is the AUTHORING loop's contract and is certified
  separately - asserting it here would report an authoring fault as a broken
  clarification loop, which is the miscategorisation this file exists to avoid.
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

Absence is loud, never silent. This loop needs ONE substrate - a reachable
engine, because a document-authoring topology builds its authoring submitter at
compile time and fails closed without one. Its absence is a skip naming it and
the command that supplies it, never a pass.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from ..acceptance import certified_gateway
from ..authoring.discovery import SERVICE_JSON_ENV, resolve_engine_with_retry
from ..team.team_config import load_team_config

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..acceptance import CertifiedGateway

# The preset that declares a questionnaire. Its questions are read from the
# preset itself below, never restated here.
_CLARIFY_PRESET = "vaultspec-adr-research-clarify"

# Every role the document-authoring topology runs needs an actor token at
# run-start; the roster is derived from the preset so a role added tomorrow is
# carried automatically rather than falling behind a hardcoded list.
_ENGINE_BEARER = "bearer"

# A document-authoring preset is refused at the eligibility gate without a target
# feature tag, before the graph is ever compiled. Naming it here keeps the run
# reaching the machinery this file exists to certify.
_FEATURE_TAG = "clarification-loop"

# The workspace the run resolves its rules and agent harness against. The checkout
# is used because it is genuinely provisioned - the same shape a real user's
# workspace has - and the gate refuses an unprovisioned one before the graph
# compiles. Nothing here writes to it: the run parks before any authoring, and
# documents move through the engine's proposal path rather than the filesystem.
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

# The ENGINE's discovery record, which is NOT a2a's own gateway record: the
# engine publishes ~/.vaultspec/service.json, while ~/.vaultspec-a2a/service.json
# is this product's gateway record. Naming the wrong one sends a reader to a file
# that exists, looks healthy, and has nothing to do with the missing substrate.
_ENGINE_RECORD = Path.home() / ".vaultspec" / "service.json"
_SUPPLY_ENGINE = (
    f"start the vaultspec engine so it publishes {_ENGINE_RECORD} "
    f"(or point {SERVICE_JSON_ENV} at a live record)"
)

_WORKER_READY_BUDGET_SECONDS = "120"

_PARK_BUDGET = 180.0
_RESUME_BUDGET = 300.0
_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])
_TEXT_LIST = TypeAdapter(list[str])


def _json_object(value: object, *, at: str) -> dict[str, object]:
    """Narrow one real wire value to an object, or fail at that boundary."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError as exc:
        raise TypeError(f"expected an object at {at}: {exc}") from exc


def _json_object_list(value: object, *, at: str) -> list[dict[str, object]]:
    """Narrow one real wire value to an object list, or fail at that boundary."""
    try:
        return _JSON_OBJECT_LIST.validate_python(value)
    except ValidationError as exc:
        raise TypeError(f"expected an object list at {at}: {exc}") from exc


def _response_object(response: httpx.Response, *, at: str) -> dict[str, object]:
    """Decode an HTTP response before its contract fields are inspected."""
    decoded: object = response.json()
    return _json_object(decoded, at=at)


def _required_object(
    body: dict[str, object], field: str, *, at: str
) -> dict[str, object]:
    """Read a required object field from a certified wire response."""
    if field not in body:
        raise AssertionError(f"{at} did not contain required field {field!r}")
    return _json_object(body[field], at=f"{at}.{field}")


def _required_text(body: dict[str, object], field: str, *, at: str) -> str:
    """Read a required text field from a certified wire response."""
    value = body.get(field)
    if not isinstance(value, str):
        raise AssertionError(f"{at}.{field} was not text: {value!r}")
    return value


def _required_bool(body: dict[str, object], field: str, *, at: str) -> bool:
    """Read a required boolean field from a certified wire response."""
    value = body.get(field)
    if not isinstance(value, bool):
        raise AssertionError(f"{at}.{field} was not boolean: {value!r}")
    return value


def _optional_text_list(body: dict[str, object], field: str, *, at: str) -> list[str]:
    """Read an optional list of text values without accepting malformed options."""
    value = body.get(field)
    if value is None:
        return []
    try:
        return _TEXT_LIST.validate_python(value, strict=True)
    except ValidationError as exc:
        raise AssertionError(f"{at}.{field} was not a text list: {value!r}") from exc


# ---------------------------------------------------------------------------
# Substrate probes - a missing one is a named skip, never a pass
# ---------------------------------------------------------------------------


def _require_substrates() -> None:
    """Skip, naming the substrate, when the loop cannot honestly run.

    Only ONE substrate is needed. The preset runs the in-process deterministic
    provider, so no model container is involved - the tape corpus carries no
    turns for this topology's document roles anyway, and depending on a container
    would narrow the lane on the hosts least able to run one.
    """
    # The bounded poll production itself uses at this decision point, not a
    # single probe: the engine has measured multi-second stall windows (its scope
    # watcher rebuilding), during which one 3s probe misses a healthy engine. A
    # single probe therefore turns a stall into a skip, and a skip that comes and
    # goes is indistinguishable from a pass that comes and goes. A genuinely dead
    # engine still skips - it simply has to be dead for the whole window.
    if resolve_engine_with_retry(attempts=3, delay_seconds=2.0) is None:
        pytest.skip(
            "no reachable engine: a document-authoring preset builds its "
            "authoring submitter at graph-compile time and fails closed without "
            f"one, so this loop cannot run. To supply it: {_SUPPLY_ENGINE}"
        )


# ---------------------------------------------------------------------------
# The declared questionnaire, read from the shipped preset
# ---------------------------------------------------------------------------


def _declared_questions() -> list[dict[str, object]]:
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
    return _json_object_list(
        [q.model_dump(mode="json") for q in team.clarification.questions],
        at="declared clarification questions",
    )


def _required_roles() -> list[str]:
    return [worker.agent_id for worker in load_team_config(_CLARIFY_PRESET).workers]


# ---------------------------------------------------------------------------
# Polling helpers - each fails closed with the snapshot that defeated it
# ---------------------------------------------------------------------------


def _await_parked(
    gateway: CertifiedGateway, run_id: str, *, budget: float
) -> dict[str, object]:
    """Poll the authoritative snapshot until a questionnaire is disclosed."""
    deadline = time.monotonic() + budget
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = gateway.status(run_id)
        if response.status_code == 200:
            last = _response_object(response, at="run-status while awaiting park")
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


def _transcript_tail(gateway: CertifiedGateway, run_id: str, *, keep: int = 4) -> str:
    """Return the run's last few turns, for a failure that needs the why.

    A settled-failed snapshot names the outcome but not the cause, and the
    gateway is still alive at the point the assertion fires, so the wide read is
    still available. Best-effort by design: a diagnostic that could itself raise
    would replace the real failure with its own.
    """
    try:
        history = gateway.thread_state(run_id)
        if history.status_code != 200:
            return f"<history unavailable: HTTP {history.status_code}>"
        history_body = _response_object(history, at="thread history transcript")
        state = _required_object(history_body, "state", at="thread history transcript")
        messages = _json_object_list(
            state.get("messages"), at="thread history messages"
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return f"<history unreadable: {type(exc).__name__}>"
    if not messages:
        return "<no turns recorded - the graph produced nothing>"
    return " | ".join(
        f"{message.get('agent_id') or message.get('role')}: "
        f"{str(message.get('content'))[:160]}"
        for message in messages[-keep:]
    )


def _has_synthesis_turn(gateway: CertifiedGateway, run_id: str) -> bool:
    """Whether the run has produced the synthesis node's own turn.

    The synthesis node sits immediately after the research fan-out joins, so its
    turn cannot exist unless the resume reached the graph AND the diverge stage
    ran to completion. That makes it the narrowest honest evidence of "advanced
    past the fan-out" - narrower, and therefore truer, than an authoring proposal,
    which additionally requires the engine to accept a document.
    """
    try:
        history = gateway.thread_state(run_id)
        if history.status_code != 200:
            return False
        history_body = _response_object(history, at="thread history synthesis check")
        state = _required_object(
            history_body, "state", at="thread history synthesis check"
        )
        messages = _json_object_list(
            state.get("messages"), at="thread history messages"
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return False
    return any(
        str(message.get("agent_id") or "") == "synthesis"
        and str(message.get("content") or "").strip()
        for message in messages
    )


def _await_resumed_past_fan_out(
    gateway: CertifiedGateway, run_id: str, *, budget: float
) -> dict[str, object]:
    """Poll until the run has genuinely left the questionnaire and done work.

    This is the assertion a 200 cannot make. Clearing the pending question is
    necessary but NOT sufficient - a run could clear it and stall - so advancing
    is evidenced by the SYNTHESIS turn, work that exists only after the research
    fan-out has run and joined. A resume that never reached the graph leaves the
    pending question in place and produces no such turn.

    What is deliberately NOT asserted here is the authoring outcome. An earlier
    version required a proposal id, and that conflated two subsystems: whether the
    answered run advanced through the graph, and whether the engine accepted the
    document it then produced. The second is the authoring loop's contract, has
    its own certification, and its failure would report here as "the clarification
    loop is broken" while the clarification loop had in fact worked perfectly.
    The narrower claim is the true one.
    """
    deadline = time.monotonic() + budget
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = gateway.status(run_id)
        if response.status_code == 200:
            last = _response_object(response, at="run-status while awaiting resume")
            if not last.get("pending_clarification") and _has_synthesis_turn(
                gateway, run_id
            ):
                return last
            if last.get("status") in {"failed", "cancelled", "error"}:
                topology = _required_object(
                    last, "topology", at="failed run-status after clarification answer"
                )
                raise AssertionError(
                    f"run {run_id} settled {last.get('status')!r} after the answer "
                    f"instead of advancing.\n"
                    f"semantic_phase={last.get('semantic_phase')!r} "
                    f"pause_cause={topology.get('pause_cause')!r} "
                    f"degraded={last.get('degraded_reasons')}\n"
                    f"transcript tail: {_transcript_tail(gateway, run_id)}"
                )
        time.sleep(1.0)
    raise AssertionError(
        f"run {run_id} did not advance past the research fan-out within "
        f"{budget:.0f}s of being answered - the resume did not reach the graph. "
        f"last snapshot: {last or 'never readable'}"
    )


def _read_frame(
    lines: Iterable[str], *, wanted: str, deadline: float
) -> dict[str, object]:
    """Return the first SSE frame whose ``type`` matches, or raise at *deadline*.

    The failure message is deliberately specific about what has ALREADY been
    established by the time this runs: the park is asserted from ``run-status``
    first, so an absent frame here cannot be read as "the run never parked". It
    can only mean the nudge did not reach a subscriber that was attached before
    the park - an emission or relay gap, which is a product defect rather than a
    timing artefact of this test.
    """
    buffer: list[str] = []
    seen: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r")
        if line.startswith("data: "):
            buffer.append(line.removeprefix("data: "))
            continue
        if line == "" and buffer:
            decoded: object = json.loads("".join(buffer))
            payload = _json_object(decoded, at="clarification SSE frame")
            buffer = []
            kind = str(payload.get("type") or payload.get("event_type") or "<untyped>")
            if kind not in seen:
                seen.append(kind)
            if payload.get("type") == wanted:
                return payload
        if time.monotonic() > deadline:
            break
    raise AssertionError(
        f"no {wanted!r} frame reached a subscriber attached BEFORE the park, "
        f"though run-status has already confirmed the run parked. This is an "
        f"emission or relay gap, not a missed park and not a subscribe race. "
        f"Frame types actually seen on the stream: {seen or ['<none>']}"
    )


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
                "feature_tag": _FEATURE_TAG,
                "metadata": {
                    "feature_tag": _FEATURE_TAG,
                    "workspace_root": str(_WORKSPACE_ROOT),
                },
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
    _require_substrates()
    expected_questions = _declared_questions()

    run_id = f"clarify-stitch-{uuid.uuid4().hex[:12]}"
    with certified_gateway(
        tmp_path,
        VAULTSPEC_WORKER_READY_TIMEOUT_SECONDS=_WORKER_READY_BUDGET_SECONDS,
    ) as gateway:
        started = _start_document_run(gateway, run_id)
        assert started.status_code == 201, started.text

        # The subscription is established BEFORE the run can park, so the nudge
        # cannot be missed by attaching late. The stream is not read yet: holding
        # the connection open is what makes the subscriber exist, and the
        # gateway queues this subscriber's frames until they are drained.
        with (
            gateway.client(timeout=_PARK_BUDGET + 120.0) as stream_client,
            stream_client.stream("GET", gateway.stream_path(run_id)) as response,
        ):
            assert response.status_code == 200, response.text

            # (1)+(2) AUTHORITATIVE FIRST. The park is proven from run-status,
            # which is the contract's source of truth and is replay-safe, and it
            # is read by a client that has consumed no frames at all - so a
            # questionnaire that only ever travelled the relay could not satisfy
            # it. This is the reload-recovery property the consumer binds to.
            # Ordering it ahead of the frame is what makes a later frame failure
            # diagnostic: it can no longer mean "the run never parked".
            parked = _await_parked(gateway, run_id, budget=_PARK_BUDGET)
            pending = _required_object(
                parked, "pending_clarification", at="parked run-status"
            )
            request_id = _required_text(
                pending, "request_id", at="parked pending clarification"
            )

            assert (
                _required_text(pending, "type", at="parked pending clarification")
                == "clarification_request"
            )
            assert (
                _json_object_list(
                    pending.get("questions"),
                    at="parked pending clarification.questions",
                )
                == expected_questions
            )
            topology = _required_object(parked, "topology", at="parked run-status")
            assert (
                _required_text(topology, "pause_cause", at="parked topology")
                == "clarification_request"
            )

            # (3) Only now the relay. This assertion deliberately carries LESS
            # weight than the one above: the progress channel is droppable by
            # contract, so a consumer must never depend on it for the questions.
            # What is asserted is narrower and still meaningful - that a
            # subscriber attached before the park does receive the nudge, and
            # that the nudge carries none of the question material.
            frame = _read_frame(
                response.iter_lines(),
                wanted="clarification_pending",
                deadline=time.monotonic() + 90.0,
            )

        assert frame["thread_id"] == run_id
        assert frame["request_id"] == request_id
        raw_frame = json.dumps(frame)
        for question in expected_questions:
            assert (
                _required_text(question, "prompt", at="declared question")
                not in raw_frame
            )
            for option in _optional_text_list(
                question, "options", at="declared question"
            ):
                assert option not in raw_frame

        # (4) Answer over real loopback HTTP, keyed by question id.
        answers: dict[str, str] = {}
        for question in expected_questions:
            question_id = _required_text(question, "id", at="declared question")
            kind = _required_text(question, "kind", at="declared question")
            required = _required_bool(question, "required", at="declared question")
            options = _optional_text_list(question, "options", at="declared question")
            if kind == "choice":
                answers[question_id] = options[0] if options else ""
            elif required:
                answers[question_id] = "no additional constraints"
        with gateway.client(timeout=60.0) as client:
            answered = client.post(
                f"/v1/runs/{run_id}/clarifications/{request_id}/respond",
                json={"answers": answers},
            )
        assert answered.status_code == 200, answered.text
        assert (
            _response_object(answered, at="clarification response").get("accepted")
            is True
        )

        # (5) The resume really reached the graph: the questionnaire is gone AND
        # the run produced the synthesis turn, which exists only after the
        # research fan-out ran and joined.
        advanced = _await_resumed_past_fan_out(gateway, run_id, budget=_RESUME_BUDGET)
        answered_transcript = _transcript_tail(gateway, run_id, keep=8)

    assert advanced.get("pending_clarification") is None
    # The evidence is the work itself, not a status code: a resume that never
    # reached the graph produces no synthesis turn however cleanly it was
    # accepted. What happens to that document afterwards - whether the engine
    # accepts the proposal - is the authoring loop's contract and is certified
    # separately; asserting it here would report an authoring fault as a broken
    # clarification loop.
    assert "synthesis" in answered_transcript, answered_transcript


def test_answering_a_question_the_run_is_not_parked_on_is_refused(
    tmp_path: Path,
) -> None:
    """The scoping check holds across the real boundary, not just in-process.

    A guessed request id must not answer a run's real question. Asserted on the
    live surface because the check that matters is the one the deployed gateway
    performs, and it must precede any dispatch: the run stays parked on its own
    questionnaire afterwards.
    """
    _require_substrates()

    run_id = f"clarify-scope-{uuid.uuid4().hex[:12]}"
    with certified_gateway(
        tmp_path,
        VAULTSPEC_WORKER_READY_TIMEOUT_SECONDS=_WORKER_READY_BUDGET_SECONDS,
    ) as gateway:
        started = _start_document_run(gateway, run_id)
        assert started.status_code == 201, started.text

        parked = _await_parked(gateway, run_id, budget=_PARK_BUDGET)
        pending = _required_object(
            parked, "pending_clarification", at="parked run-status"
        )
        real_request_id = _required_text(
            pending, "request_id", at="parked pending clarification"
        )

        with gateway.client(timeout=60.0) as client:
            refused = client.post(
                f"/v1/runs/{run_id}/clarifications/not-the-real-id/respond",
                json={"answers": {"scope": "frontend"}},
            )
        assert refused.status_code == 404, refused.text

        still_parked = _response_object(
            gateway.status(run_id), at="run-status after refused answer"
        )

    still_pending = _required_object(
        still_parked, "pending_clarification", at="run-status after refused answer"
    )
    assert (
        _required_text(
            still_pending, "request_id", at="still-parked pending clarification"
        )
        == real_request_id
    )
