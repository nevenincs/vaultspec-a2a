"""What the Codex lane is told when a run parks, and how the park gets out.

Two halves of one defect. The app-server gates every MCP tool call behind an
elicitation, and a supervised run answers it from a human rung; when that rung
suspends the graph to ask a person the open elicitation has to be answered at
once - an unanswered frame hangs the turn until the idle backstop fires - and
the answer it used to get was ``decline``. A decline tells the model a user
refused a call no user has yet seen, immediately before the session is killed
and the turn replays from the top. The elicitation contract's own abandon
action, ``cancel``, says what actually happened.

The second half is how the suspension leaves the turn. ``_next_turn_message``
checked ``client.pending_interrupt`` only after its ``try``, so a park that
landed inside a quiet window, or beside a retrying error, or just before the
provider closed its stream was overwritten by a timeout, by the deferred retry
condition, or by an end-of-stream error. A supervised Codex run whose human rung
parked then failed as a timeout instead of parking.

Every case drives the production ``_consume_turn`` and a real
``_CodexAppServerClient`` over real stdio pipes against a real subprocess
app-server stand-in that holds its elicitation open past the idle window, so the
empty notification queue is the genuine state a parked turn produces.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import pytest
from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt
from pydantic import TypeAdapter

from ...testing import settings_override
from .._codex_app_server_client import _CodexAppServerClient
from .._codex_permission import CANCEL_ACTION, DECLINE_ACTION, CodexPermissionRung
from .._codex_protocol import _CodexProtocolError
from .._json_contract import JsonObject
from .._project_scope import RunProjectScope
from .._subprocess import spawn_acp_process
from ..codex_chat_model import CodexChatModel

if TYPE_CHECKING:
    from pathlib import Path

    from .._acp_types import PermissionCallback

#: The recorded answer frame, read through the provider layer's own JSON shape.
_ANSWER_FRAME: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)

_THREAD = "t-park"
_TURN = "u-park"
_SERVER = "vaultspec-authoring"
_TOOL = "propose_changeset"
_ELICITATION_ID = 9101

#: Short enough that the idle backstop fires inside a test, long enough that the
#: elicitation has been decided and answered well before it does.
_IDLE_LIMIT_SECONDS = 2.0

#: How long the human rung takes to suspend. This is what makes these tests
#: discriminating rather than racy: every frame the stand-in queues is drained
#: by the turn BEFORE the suspension exists, so the turn is genuinely sitting in
#: its frame wait when the park lands. Without the delay the suspension could be
#: recorded before the first frame was dequeued, and the pre-fix code's
#: normal-return check would re-raise it - passing against the defect.
_PARK_DELAY_SECONDS = 0.5

#: How long a held stand-in stays alive after answering: far past the idle
#: deadline, so the expiry under test is the production wait rather than the
#: child's exit.
_LINGER_SECONDS = _IDLE_LIMIT_SECONDS * 20

#: The suspension a supervised human rung raises, as the real LangGraph object.
_PARKED = Interrupt(value={"kind": "tool_permission", "tool": _TOOL}, id="req-park-1")

# A real app-server stand-in. On `drive` it announces one MCP tool call and
# raises the elicitation for it, then waits for the client's answer and records
# it, so the answer is read off the wire rather than out of the client.
#
# What it does next is the scenario, and each one is an EXIT from the turn's
# frame wait that used to discard a held suspension:
#   hold   - stay alive and silent, so the wait ends at the idle backstop.
#   eof    - exit, so the wait ends at end-of-stream.
#   retry  - emit a retrying error BEFORE the elicitation and then stay silent,
#            so the wait ends at the idle backstop with a deferred retry
#            condition already recorded. The error has to precede the
#            elicitation: a frame arriving after the park is dequeued by the
#            turn's normal return, which already re-raised a held suspension.
_PARKING_APP_SERVER = r"""
import json, sys, time

ELICITATION_ID = int(sys.argv[1])
SCENARIO = sys.argv[2]
ANSWER_PATH = sys.argv[3]
THREAD, TURN, SERVER, TOOL = sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7]
LINGER = float(sys.argv[8])


def out(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def announce():
    out({
        "method": "item/started",
        "params": {
            "threadId": THREAD,
            "turnId": TURN,
            "item": {
                "type": "mcpToolCall",
                "id": "call-park-1",
                "server": SERVER,
                "tool": TOOL,
                "status": "inProgress",
                "arguments": {"text": "hello"},
            },
        },
    })


def ask():
    out({
        "method": "mcpServer/elicitation/request",
        "id": ELICITATION_ID,
        "params": {
            "threadId": THREAD,
            "turnId": TURN,
            "serverName": SERVER,
            "mode": "form",
            "_meta": {"codex_approval_kind": "mcp_tool_call"},
            "message": 'Allow the server to run tool "%s"?' % TOOL,
            "requestedSchema": {"type": "object", "properties": {}},
        },
    })


def record_answer():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        if message.get("id") == ELICITATION_ID:
            with open(ANSWER_PATH, "w", encoding="utf-8") as handle:
                json.dump(message, handle)
            return


def retrying_error():
    out({
        "method": "error",
        "params": {
            "error": {
                "message": "Reconnecting... 1/5",
                "codexErrorInfo": {
                    "responseStreamConnectionFailed": {"httpStatusCode": 503}
                },
            },
            "willRetry": True,
        },
    })


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    if request.get("method") != "drive":
        if request.get("id") is not None:
            out({"id": request["id"], "result": {}})
        continue
    out({"id": request["id"], "result": {}})
    announce()
    if SCENARIO == "retry":
        retrying_error()
    ask()
    record_answer()
    if SCENARIO != "eof":
        time.sleep(LINGER)
    break
"""


def _parking_callback() -> PermissionCallback:
    """A human rung that suspends the graph to ask a person, as production does.

    It takes :data:`_PARK_DELAY_SECONDS` to decide, which a real rung does too -
    it writes an interrupt through the graph - and which is what puts the park
    strictly after every frame the turn had queued.
    """

    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        await asyncio.sleep(_PARK_DELAY_SECONDS)
        raise GraphInterrupt((_PARKED,))

    return callback


async def _elicitation_client(
    tmp_path: Path, scenario: str, *, permission_callback: PermissionCallback | None
) -> tuple[_CodexAppServerClient, Path]:
    """Spawn the stand-in behind a real client carrying the real rung.

    The allowlist is empty on purpose, so the supervised arms prove the human
    rung decided (an uncovered call the autonomous rung would refuse) and the
    unattended control refuses for its own stated reason.
    """
    answer_path = tmp_path / "elicitation-answer.json"
    process = await spawn_acp_process(
        [
            sys.executable,
            "-c",
            _PARKING_APP_SERVER,
            str(_ELICITATION_ID),
            scenario,
            str(answer_path),
            _THREAD,
            _TURN,
            _SERVER,
            _TOOL,
            str(_LINGER_SECONDS),
        ],
        env={},
        cwd=".",
        use_exec=True,
    )
    client = _CodexAppServerClient(
        process,
        permission_rung=CodexPermissionRung(
            allowed_tools=frozenset(),
            permission_callback=permission_callback,
            project_scope=RunProjectScope(str(tmp_path)),
        ),
    )
    return client, answer_path


async def _drive_until_it_ends(
    tmp_path: Path, scenario: str, *, permission_callback: PermissionCallback | None
) -> tuple[BaseException, Path]:
    """Drive the real turn against *scenario* and return how it ended.

    The three caught types are the three ways this turn can end, and naming them
    is the point: the pre-fix failure mode is a DIFFERENT one of them rather than
    no exception at all, so a test that only asserted "it raised" would pass
    against the defect.
    """
    client, answer_path = await _elicitation_client(
        tmp_path, scenario, permission_callback=permission_callback
    )
    model = CodexChatModel(workspace_root=str(tmp_path))
    ended: BaseException | None = None
    try:
        with settings_override(acp_turn_idle_timeout_seconds=_IDLE_LIMIT_SECONDS):
            await client.request("drive", {})
            try:
                async for _chunk in model._consume_turn(client, _THREAD):
                    pass
            except (GraphInterrupt, TimeoutError, _CodexProtocolError) as exc:
                ended = exc
    finally:
        await client.aclose()
    assert ended is not None, "the turn completed instead of ending on the park"
    return ended, answer_path


async def _parked(tmp_path: Path, scenario: str) -> tuple[BaseException, Path]:
    return await _drive_until_it_ends(
        tmp_path, scenario, permission_callback=_parking_callback()
    )


def _recorded_answer(answer_path: Path) -> JsonObject:
    """Return the elicitation answer the stand-in read off its own stdin."""
    return _ANSWER_FRAME.validate_json(answer_path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_a_parked_turn_answers_the_abandon_action(tmp_path: Path) -> None:
    """The open elicitation is answered ``cancel``, not ``decline``.

    ``cancel`` is the elicitation contract's abandon action on the installed
    binary's own generated schema, and it is what is true: the run suspended, so
    nobody has decided anything. A ``decline`` is the last thing the model hears
    before the session dies and the turn replays, and it invites the model to act
    inside that turn on a denial no person made.
    """
    _ended, answer_path = await _parked(tmp_path, "hold")

    assert _recorded_answer(answer_path) == {
        "id": _ELICITATION_ID,
        "result": {"action": CANCEL_ACTION},
    }


@pytest.mark.asyncio
async def test_a_park_inside_a_quiet_window_raises_the_suspension(
    tmp_path: Path,
) -> None:
    """A held suspension beats the idle backstop.

    Discriminating: the stand-in is alive and silent once it has been answered,
    so the turn's frame wait expires at the idle deadline with a suspension
    already held. The pre-fix ``_next_turn_message`` raised the bare
    ``TimeoutError`` from its ``except`` clause and never looked at
    ``pending_interrupt``, so this supervised run failed as a timeout.
    """
    ended, _answer_path = await _parked(tmp_path, "hold")

    assert isinstance(ended, GraphInterrupt), (
        f"a parked turn ended as {type(ended).__name__}: {ended!r}"
    )
    assert ended.args[0] == (_PARKED,)


@pytest.mark.asyncio
async def test_a_park_beats_a_deferred_retry_condition(tmp_path: Path) -> None:
    """A held suspension beats the retry failure the lane was holding.

    The deferred condition exists so a retry sequence's own description is
    preferred to later silence, and it is raised from the timeout exit. It is
    still not the outcome of a turn that parked: the retry was an attempt, and
    the park is a decision the run is now waiting on.
    """
    ended, _answer_path = await _parked(tmp_path, "retry")

    assert isinstance(ended, GraphInterrupt), (
        f"a parked turn ended as {type(ended).__name__}: {ended!r}"
    )


@pytest.mark.asyncio
async def test_a_park_beats_an_end_of_stream_error(tmp_path: Path) -> None:
    """A held suspension beats the provider's own exit, on the third exit too.

    The stand-in leaves once it has answered, which closes stdout and puts the
    stream-closed sentinel on the notification queue. The pre-fix code raised
    the end-of-stream protocol error there, which describes the provider rather
    than the run - and on a park the session ending is expected.
    """
    ended, _answer_path = await _parked(tmp_path, "eof")

    assert isinstance(ended, GraphInterrupt), (
        f"a parked turn ended as {type(ended).__name__}: {ended!r}"
    )


@pytest.mark.asyncio
async def test_an_unparked_quiet_turn_still_ends_at_the_idle_deadline(
    tmp_path: Path,
) -> None:
    """Inverted control: with nothing held, the backstop still governs.

    Without this arm the precedence rule above would be satisfied by a function
    that raised whatever interrupt it was handed and never timed out at all.
    Here no human rung is attached, so the rung decides against the composed
    surface, nothing is held, and the quiet turn must still end at the idle
    deadline - with the refusal spelled as a decline, because the abandon action
    belongs to a suspension rather than to every refusal.
    """
    ended, answer_path = await _drive_until_it_ends(
        tmp_path, "hold", permission_callback=None
    )

    assert isinstance(ended, TimeoutError), (
        f"an unparked quiet turn ended as {type(ended).__name__}: {ended!r}"
    )
    assert _recorded_answer(answer_path)["result"] == {"action": DECLINE_ACTION}
