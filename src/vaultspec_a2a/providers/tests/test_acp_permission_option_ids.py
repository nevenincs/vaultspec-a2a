"""Option-id validity at the ACP ``session/request_permission`` RPC handler.

Real objects, no mocks: the frozen ``AcpModelConfig`` and the real
``on_request_permission``. The permission callback is a genuine collaborator
supplied by the caller (the graph's interrupt gate in production), so a real
async function stands in that slot exactly as production wires it.

Each test here fails on the pre-unification handler, which built its valid-id
set as ``{o.get("optionId") for o in options}`` — unfiltered, camelCase-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._acp_types import AcpModelConfig, AcpSessionContext, PermissionCallback
from ._permission_outcome import acp_permission_outcome

if TYPE_CHECKING:
    from pathlib import Path

    from .._json_contract import JsonObject

# An option dict with no identity field at all — exactly what the unfiltered set
# comprehension turned into a ``None`` member of the "valid" ids.
_MALFORMED: JsonObject = {"label": "Nameless option", "kind": "allow_once"}


def _config(
    workspace_root: str,
    *,
    permission_callback: PermissionCallback | None = None,
    acp_family: str = "claude",
) -> AcpModelConfig:
    return AcpModelConfig(
        agent_config=None,
        permission_callback=permission_callback,
        workspace_root=workspace_root,
        command=["claude", "acp"],
        env_vars={},
        mcp_servers=[],
        use_exec=False,
        provider="claude",
        provider_command=None,
        auth_mode=None,
        allowed_tools=[],
        acp_family=acp_family,
    )


async def _decide(
    options: list[JsonObject],
    config: AcpModelConfig,
    ctx: AcpSessionContext,
    *,
    tool_call: JsonObject | None = None,
) -> str:
    outcome = await acp_permission_outcome(
        ctx, config, options=options, tool_call=tool_call
    )
    option_id = outcome.get("optionId")
    assert isinstance(option_id, str)
    return option_id


def _returning(answer: str) -> PermissionCallback:
    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        return answer

    return callback


@pytest.mark.asyncio
async def test_an_empty_option_id_is_never_serialised_into_the_outcome(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """A callback answer outside the offered ids refuses the call, never echoes it.

    The callback interface itself only permits strings. An empty string is still
    an invalid option id, and exercises the same runtime guard without breaking
    the typed collaborator contract. With nothing refusable on offer the answer
    is the protocol's own cancelled outcome, which carries no option id at all -
    the approval that IS on offer is not a fallback.
    """
    options: list[JsonObject] = [{"optionId": "approve"}, _MALFORMED]

    outcome = await acp_permission_outcome(
        acp_session_context,
        _config(str(tmp_path), permission_callback=_returning("")),
        options=options,
    )

    assert outcome == {"outcome": "cancelled"}
    assert "optionId" not in outcome


@pytest.mark.asyncio
async def test_a_rejected_answer_falls_back_without_raising_key_error(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """The fallback for a bad answer must survive the malformed input it exists for.

    With a leading option that carries no id, the old fallback subscripted
    ``options[0]["optionId"]`` and raised ``KeyError`` — inside the very branch
    meant to recover from an invalid answer.
    """
    options: list[JsonObject] = [_MALFORMED, {"optionId": "deny_once"}]

    decision = await _decide(
        options,
        _config(str(tmp_path), permission_callback=_returning("hostile-option")),
        acp_session_context,
    )

    assert decision == "deny_once"


@pytest.mark.asyncio
async def test_a_snake_case_option_answered_in_kind_is_accepted(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """A snake_case options list validates its own snake_case answer.

    The valid set is built from the snake_case options, so the legitimate answer
    passes the guard rather than failing it and sending the fallback to a
    ``KeyError``.
    """
    options: list[JsonObject] = [
        {"option_id": "allow_always"},
        {"option_id": "reject_once"},
    ]

    decision = await _decide(
        options,
        _config(str(tmp_path), permission_callback=_returning("reject_once")),
        acp_session_context,
    )

    assert decision == "reject_once"


@pytest.mark.asyncio
async def test_a_snake_case_option_is_selected_when_no_callback_decides(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """The unsupervised path reads the id it selects in either spelling.

    ``Edit`` is not a declared tool for this config, so the unsupervised path
    refuses it, and the refusal it selects is offered under the snake_case
    spelling alone.
    """
    options: list[JsonObject] = [
        {"option_id": "allow_always", "kind": "allow_always"},
        {"option_id": "reject_once", "kind": "reject_once"},
    ]

    decision = await _decide(options, _config(str(tmp_path)), acp_session_context)

    assert decision == "reject_once"


@pytest.mark.asyncio
async def test_a_leading_option_without_an_id_abandons_rather_than_inventing_one(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """No usable id on offer means the protocol's own cancelled outcome.

    The unsupervised path names only ids the request listed. Answering the
    conventional refusal literal instead SELECTED an option the agent never
    offered, which it cannot match to anything it put on the table; abandoning
    the call says exactly what is true and still refuses the tool use.
    """
    outcome = await acp_permission_outcome(
        acp_session_context, _config(str(tmp_path)), options=[_MALFORMED]
    )

    assert outcome == {"outcome": "cancelled"}


@pytest.mark.asyncio
async def test_a_raising_callback_denies_without_subscripting_a_bad_option(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """The fail-closed denial path must not itself raise on malformed options.

    The refusal on offer is the once-only one, which is the only refusal a
    denial ever selects: a remembering refusal would have the CLI persist a rule
    this run cannot retract, so it is never reached for, and a list offering only
    that is answered with the cancelled outcome instead.
    """

    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        raise RuntimeError("the human hung up")

    options: list[JsonObject] = [
        {"optionId": "approve"},
        {"optionId": "deny_once"},
        _MALFORMED,
    ]

    decision = await _decide(
        options,
        _config(str(tmp_path), permission_callback=callback),
        acp_session_context,
    )

    assert decision == "deny_once"


@pytest.mark.asyncio
async def test_a_denial_never_slides_onto_an_approval_on_a_bad_last_option(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """Fail-closed means the cancelled outcome, never the surviving APPROVE id.

    The conventional most-restrictive option is the last one. When it carries no
    id and nothing else names a denial, the answer is the protocol's own
    cancelled outcome, which the agent cannot read as a selection; scanning back
    up the list would have answered ``approve``.
    """
    options: list[JsonObject] = [{"optionId": "approve"}, _MALFORMED]

    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        raise RuntimeError("the human hung up")

    outcome = await acp_permission_outcome(
        acp_session_context,
        _config(str(tmp_path), permission_callback=callback),
        options=options,
    )

    assert outcome == {"outcome": "cancelled"}


@pytest.mark.asyncio
async def test_the_kimi_autonomous_lane_reads_snake_case_options(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    """The Kimi read-only enforcement resolves ids through the same rule."""
    options: list[JsonObject] = [
        {"option_id": "approve", "kind": "allow_once"},
        {"option_id": "reject", "kind": "reject_once"},
    ]
    config = _config(str(tmp_path), acp_family="kimi")
    read: JsonObject = {"path": "a.py"}

    assert (
        await _decide(
            options,
            config,
            acp_session_context,
            tool_call={"title": "ReadFile: a.py", "rawInput": read},
        )
        == "approve"
    )
    assert (
        await _decide(
            options,
            config,
            acp_session_context,
            tool_call={"title": "WriteFile: a.py", "rawInput": read},
        )
        == "reject"
    )


@pytest.mark.asyncio
async def test_a_remembered_approval_is_answered_as_a_single_use(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """An "always" answer reaches the CLI as the once-only option it offered.

    The CLI persists a remembered approval as a permission rule in the
    operator's own settings, where it widens later runs this one cannot see.
    """
    options: list[JsonObject] = [
        {"optionId": "allow_always", "kind": "allow_always"},
        {"optionId": "allow_once", "kind": "allow_once"},
        {"optionId": "reject_once", "kind": "reject_once"},
    ]

    decision = await _decide(
        options,
        _config(str(tmp_path), permission_callback=_returning("allow_always")),
        acp_session_context,
    )

    assert decision == "allow_once"


@pytest.mark.asyncio
async def test_a_single_use_approval_is_forwarded_unchanged(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """Narrowing touches only the answers that would outlive their own call."""
    options: list[JsonObject] = [
        {"optionId": "allow_always", "kind": "allow_always"},
        {"optionId": "allow_once", "kind": "allow_once"},
    ]

    decision = await _decide(
        options,
        _config(str(tmp_path), permission_callback=_returning("allow_once")),
        acp_session_context,
    )

    assert decision == "allow_once"


@pytest.mark.asyncio
async def test_an_unoffered_answer_refuses_where_a_refusal_is_offered(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """The adapter's own option list is answered with its reject option.

    Options in the order the pinned adapter offers them: allow_always first. The
    old fallback took the FIRST offered option, so a refusal whose id did not
    match resolved to the broadest grant the request contained.
    """
    options: list[JsonObject] = [
        {"optionId": "allow_always", "kind": "allow_always", "name": "Always Allow"},
        {"optionId": "allow", "kind": "allow_once", "name": "Allow"},
        {"optionId": "reject", "kind": "reject_once", "name": "Reject"},
    ]

    decision = await _decide(
        options,
        _config(str(tmp_path), permission_callback=_returning("no-such-option")),
        acp_session_context,
    )

    assert decision == "reject"


@pytest.mark.asyncio
async def test_an_unoffered_answer_cancels_when_every_option_is_an_approval(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """With only approvals on offer the call is cancelled, not granted."""
    options: list[JsonObject] = [
        {"optionId": "allow_always", "kind": "allow_always"},
        {"optionId": "allow", "kind": "allow_once"},
    ]

    outcome = await acp_permission_outcome(
        acp_session_context,
        _config(str(tmp_path), permission_callback=_returning("no-such-option")),
        options=options,
    )

    assert outcome == {"outcome": "cancelled"}


@pytest.mark.asyncio
async def test_an_uncovered_autonomous_call_is_never_granted_by_position(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
) -> None:
    """The autonomous refusal never lands on an approval either.

    ``Edit`` is not a declared tool for this config, so the unsupervised rung
    refuses it. Every option on offer is an approval, so the positional
    "most restrictive is last" convention would have granted the call.
    """
    options: list[JsonObject] = [
        {"optionId": "allow", "kind": "allow_once"},
        {"optionId": "allow_always", "kind": "allow_always"},
    ]

    outcome = await acp_permission_outcome(
        acp_session_context, _config(str(tmp_path)), options=options
    )

    assert outcome == {"outcome": "cancelled"}
