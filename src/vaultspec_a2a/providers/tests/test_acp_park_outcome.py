"""What the ACP lane is told when a run parks, and when a refusal is refused.

A park does not pause the provider. The human rung's suspension is held for the
turn to re-raise, the still-open ``session/request_permission`` is answered
immediately, and the session tree is released in the turn's ``finally`` - so
whatever that request is answered with is the last thing the model is told
before its session ends. Answering it with a refusal tells the model a human
said no to a call no human has yet seen, and invites it to act on that denial
inside the same turn. The protocol's ``cancelled`` outcome is the abandonment it
actually is: it carries no option id, so it cannot be read as a selection, and
the adapter aborts the tool use.

The second rule here is about what a refusal may be SPELLED as. A remembering
refusal (``reject_always``) is persisted by the CLI as a permission rule in the
operator's own settings, outside anything a run can see or retract, and it
narrows every later run on that machine - including the unattended ones. So a
refusal selects a once-only refusal or it answers ``cancelled``; it never
reaches for the remembering one just because that is the only refusal offered.

Every case drives the real dispatch over real pipes: a real subprocess agent
writes the shared ``session/request_permission`` frame from
:mod:`vaultspec_a2a.testing` onto its stdout, the production
``process_stdout_loop`` reads it off that pipe and dispatches it to the
production ``on_request_permission``, and the agent records the reply it
receives on its own stdin. The assertions are therefore about the bytes a real
agent would read.
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, cast

import pytest
from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt

from ...testing import REQUEST_PERMISSION_METHOD, acp_request, request_permission_params
from .._acp_protocol import process_stdout_loop
from .._acp_rpc_handlers import on_request_permission
from .._acp_types import AcpModelConfig, AcpSessionContext, PermissionCallback

if TYPE_CHECKING:
    from pathlib import Path

    from .._json_contract import JsonObject

_SESSION = "park-outcome-session"
_RPC_ID = 7001

#: The suspension a supervised human rung raises, as the real LangGraph object.
_PARKED = Interrupt(value={"kind": "tool_permission", "tool": "Edit"}, id="req-park-1")

# A real agent: it writes one server-initiated permission request, blocks on its
# own stdin for the client's reply, records that reply verbatim, and exits. An
# empty line (the client going silent) is recorded as such rather than as a
# reply, so silence is distinguishable from an answer.
_AGENT = r"""
import sys
sys.stdout.write(REQUEST_LINE + "\n")
sys.stdout.flush()
line = sys.stdin.readline()
with open(REPLY_PATH, "w", encoding="utf-8") as handle:
    handle.write(line)
"""


def _agent_source(request: JsonObject, reply_path: Path) -> str:
    """Inline the frame and the record path, so neither rides a shell argv."""
    return _AGENT.replace("REQUEST_LINE", repr(json.dumps(request))).replace(
        "REPLY_PATH", repr(str(reply_path))
    )


def _config(
    workspace_root: Path, *, permission_callback: PermissionCallback | None
) -> AcpModelConfig:
    """The production config, carrying the run's project and its human rung."""
    return AcpModelConfig(
        agent_config=None,
        permission_callback=permission_callback,
        workspace_root=str(workspace_root),
        command=["claude", "acp"],
        env_vars={},
        mcp_servers=[],
        use_exec=False,
        provider="claude",
        provider_command=None,
        auth_mode=None,
        allowed_tools=[],
    )


async def _answered_outcome(
    tmp_path: Path,
    config: AcpModelConfig,
    options: list[JsonObject],
) -> tuple[JsonObject, AcpSessionContext]:
    """Return the outcome a real agent read back, and the session that answered.

    The context is returned beside the outcome because the suspension the rung
    held for the turn is session state, and a park that answered correctly while
    dropping the interrupt would be a worse failure than a wrong outcome.
    """
    reply_path = tmp_path / "reply.json"
    request = acp_request(
        _RPC_ID,
        REQUEST_PERMISSION_METHOD,
        request_permission_params(
            _SESSION,
            tool_call={"toolCallId": "call-1", "title": "Edit", "rawInput": {}},
            options=options,
        ),
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _agent_source(request, reply_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    ctx = AcpSessionContext(
        process=process,
        stdin=process.stdin,
        stdout=process.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
        session_id=_SESSION,
    )
    handlers = {REQUEST_PERMISSION_METHOD: on_request_permission}
    loop_task = asyncio.create_task(process_stdout_loop(ctx, config, handlers))
    try:
        await asyncio.wait_for(process.wait(), timeout=20.0)
    finally:
        loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await loop_task
        if process.returncode is None:
            process.kill()
            await process.wait()

    recorded = reply_path.read_text(encoding="utf-8").strip()
    assert recorded, "the agent received no reply at all before it exited"
    reply = json.loads(recorded)
    assert reply["id"] == _RPC_ID
    outcome = reply["result"]["outcome"]
    assert isinstance(outcome, dict)
    return cast("JsonObject", outcome), ctx


def _parking() -> PermissionCallback:
    """A human rung that suspends the run to ask a person, as production does."""

    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        raise GraphInterrupt((_PARKED,))

    return callback


def _raising() -> PermissionCallback:
    """A human rung that fails, which is a genuine refusal rather than a park."""

    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        raise RuntimeError("the human rung is unreachable")

    return callback


@pytest.mark.asyncio
async def test_a_parked_run_abandons_the_open_request(tmp_path: Path) -> None:
    """A park answers ``cancelled`` even with a once-only refusal on offer.

    Discriminating: ``reject_once`` is offered, so the refusal path has a
    perfectly good option to select and selecting it is exactly what must not
    happen. The pre-fix handler answered this request with
    ``{"outcome": "selected", "optionId": "reject_once"}`` - telling the model a
    human refused a call no human had seen yet, immediately before the session
    was killed and the turn replayed.
    """
    options: list[JsonObject] = [
        {"optionId": "allow_once", "kind": "allow_once"},
        {"optionId": "reject_once", "kind": "reject_once"},
    ]

    outcome, ctx = await _answered_outcome(
        tmp_path, _config(tmp_path, permission_callback=_parking()), options
    )

    assert outcome == {"outcome": "cancelled"}
    assert "optionId" not in outcome
    assert len(ctx.interrupt_exc) == 1, (
        "the suspension must still be held for the turn to re-raise; an "
        "abandoned request with no held interrupt loses the park entirely"
    )
    assert ctx.interrupt_exc[0] is not None
    assert isinstance(ctx.interrupt_exc[0], GraphInterrupt)


@pytest.mark.asyncio
async def test_a_park_is_abandoned_even_where_only_approvals_are_offered(
    tmp_path: Path,
) -> None:
    """The abandonment does not depend on the option list at all.

    The inverse control of the case above: with nothing refusable on offer the
    old handler already reached ``cancelled``, so this arm would pass either
    way on its own. It is here to show the new answer is unconditional rather
    than a second option-list rule.
    """
    options: list[JsonObject] = [
        {"optionId": "allow_once", "kind": "allow_once"},
        {"optionId": "allow_always", "kind": "allow_always"},
    ]

    outcome, _ctx = await _answered_outcome(
        tmp_path, _config(tmp_path, permission_callback=_parking()), options
    )

    assert outcome == {"outcome": "cancelled"}


@pytest.mark.asyncio
async def test_a_genuine_policy_denial_still_selects_the_once_only_refusal(
    tmp_path: Path,
) -> None:
    """The refusal branch survives for the decisions that really are refusals.

    A human rung that raised approved nothing, so the call is refused - and a
    refusal the agent can act on is the once-only option, because the turn is
    continuing. Without this arm the park fix would be indistinguishable from
    deleting the refusal path.
    """
    options: list[JsonObject] = [
        {"optionId": "allow_once", "kind": "allow_once"},
        {"optionId": "reject_once", "kind": "reject_once"},
    ]

    outcome, ctx = await _answered_outcome(
        tmp_path, _config(tmp_path, permission_callback=_raising()), options
    )

    assert outcome == {"outcome": "selected", "optionId": "reject_once"}
    assert ctx.interrupt_exc == []


@pytest.mark.asyncio
async def test_a_refusal_never_falls_back_to_a_remembering_refusal(
    tmp_path: Path,
) -> None:
    """With only a remembering refusal offered, the answer is ``cancelled``.

    ``reject_always`` is the one refusal on offer, and selecting it has the CLI
    write a permission rule into the operator's own settings that no run can
    retract and that narrows every later run on the machine. The pre-fix
    handler selected it, which also undid the shared decision's own rule: a
    remembered refusal is refused rather than forwarded precisely so no rule is
    written, and the rung then wrote one anyway.
    """
    options: list[JsonObject] = [
        {"optionId": "allow_once", "kind": "allow_once"},
        {"optionId": "reject_always", "kind": "reject_always"},
    ]

    outcome, _ctx = await _answered_outcome(
        tmp_path, _config(tmp_path, permission_callback=_raising()), options
    )

    assert outcome == {"outcome": "cancelled"}
    assert "optionId" not in outcome
