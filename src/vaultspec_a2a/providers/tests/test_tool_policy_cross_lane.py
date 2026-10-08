"""One guard order and one set of defaults, asserted on both provider rungs.

The ACP adapters and codex ask different protocols the same question, and both
hand it to the single shared decision. These tests drive the two REAL rungs - the
production ``session/request_permission`` handler and the production Codex
elicitation rung - over the same calls, so the lanes cannot drift into deciding
one call two ways:

- the guards run in one order, the project scope first, on both lanes;
- a rung with no project to measure against refuses rather than skipping;
- a remembered refusal with no once-only refusal on offer is answered as a
  cancelled call rather than forwarded for the CLI to persist as a rule;
- the autonomous path fails closed when a covered call offers it no approval.

Real objects throughout: the frozen ``AcpModelConfig``, the real handler, the
real rung, and a permission callback that is a genuine async collaborator in the
slot production wires the graph's interrupt gate into.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._acp_types import AcpModelConfig, AcpSessionContext, PermissionCallback
from .._codex_permission import DECLINE_ACTION, CodexPermissionRung
from .._project_scope import RunProjectScope
from .._tool_policy import ToolPermissionRequest, decide
from ._permission_outcome import acp_permission_outcome

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from .._json_contract import JsonObject

# A harness tool the registry mounts and never lets a run call. Neither a human
# at the prompt nor an allowlist is the authority that could permit it.
_WITHHELD_SERVER = "vaultspec-core"
_WITHHELD_TOOL = "search"

_CANCELLED: JsonObject = {"outcome": "cancelled"}

_CROSS_PROJECT_REFUSAL = "Refused a cross-project tool call"
_WITHHELD_REFUSAL = "Refused a withheld harness tool"


def _config(
    workspace_root: str,
    *,
    permission_callback: PermissionCallback | None = None,
    allowed_tools: list[str] | None = None,
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
        allowed_tools=allowed_tools if allowed_tools is not None else [],
        acp_family="claude",
    )


def _returning(answer: str) -> PermissionCallback:
    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        return answer

    return callback


def _answering(answer: str) -> Callable[[], Awaitable[str]]:
    """The human rung bound to one call, in the shape the decision takes it."""

    async def ask() -> str:
        return answer

    return ask


async def _codex_action(
    *,
    tool: str,
    arguments: JsonObject,
    allowed: frozenset[tuple[str, str]] = frozenset(),
    permission_callback: PermissionCallback | None = None,
    project_scope: RunProjectScope,
    server: str = _WITHHELD_SERVER,
) -> str:
    """Drive the production Codex rung over an announced call and its approval."""
    rung = CodexPermissionRung(
        allowed_tools=allowed,
        permission_callback=permission_callback,
        project_scope=project_scope,
    )
    rung.observe(
        "item/started",
        {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "item": {
                "type": "mcpToolCall",
                "server": server,
                "tool": tool,
                "arguments": arguments,
            },
        },
    )
    return await rung.decide(
        {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "serverName": server,
            "_meta": {"codex_approval_kind": "mcp_tool_call"},
        }
    )


@pytest.mark.asyncio
async def test_both_lanes_run_the_project_guard_before_the_withheld_guard(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A call tripping both guards is refused by the scope one, on either lane.

    Which guard answers first is observable only in what each lane logs, so the
    same doubly-offending call goes down both paths and the refusal recorded must
    be the same one. Without a single order, the two rungs would attribute one
    call's refusal to two different causes.
    """
    bound = tmp_path / "bound"
    bound.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    qualified = f"mcp__{_WITHHELD_SERVER}__{_WITHHELD_TOOL}"
    arguments: JsonObject = {"project_root": str(foreign)}

    with caplog.at_level("WARNING"):
        acp_outcome = await acp_permission_outcome(
            acp_session_context,
            # A human rung that would approve, so a guard that did not run first
            # would show as an approval rather than a quieter refusal.
            _config(str(bound), permission_callback=_returning("allow")),
            tool_call={"title": qualified, "rawInput": arguments},
            options=[
                {"optionId": "allow", "kind": "allow_once"},
                {"optionId": "reject", "kind": "reject_once"},
            ],
        )
    acp_messages = [record.getMessage() for record in caplog.records]

    caplog.clear()
    with caplog.at_level("WARNING"):
        codex_action = await _codex_action(
            tool=_WITHHELD_TOOL,
            arguments=arguments,
            allowed=frozenset({(_WITHHELD_SERVER, _WITHHELD_TOOL)}),
            permission_callback=_returning("accept"),
            project_scope=RunProjectScope(str(bound)),
        )
    codex_messages = [record.getMessage() for record in caplog.records]

    # Each lane spells the refusal its own way - the ACP rung selects the
    # narrowest refusal on offer, the Codex rung answers its decline action -
    # and both refuse.
    assert acp_outcome == {"outcome": "selected", "optionId": "reject"}
    assert codex_action == DECLINE_ACTION
    for messages in (acp_messages, codex_messages):
        assert any(_CROSS_PROJECT_REFUSAL in message for message in messages), messages
        assert not any(_WITHHELD_REFUSAL in message for message in messages), messages


@pytest.mark.asyncio
async def test_a_withheld_harness_tool_is_refused_over_a_human_approval_on_both_lanes(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    """The second guard also precedes the human rung on both lanes."""
    qualified = f"mcp__{_WITHHELD_SERVER}__{_WITHHELD_TOOL}"

    acp_outcome = await acp_permission_outcome(
        acp_session_context,
        _config(str(tmp_path), permission_callback=_returning("allow")),
        tool_call={"title": qualified, "rawInput": {"query": "anything"}},
        options=[
            {"optionId": "allow", "kind": "allow_once"},
            {"optionId": "reject", "kind": "reject_once"},
        ],
    )
    codex_action = await _codex_action(
        tool=_WITHHELD_TOOL,
        arguments={"query": "anything"},
        allowed=frozenset({(_WITHHELD_SERVER, _WITHHELD_TOOL)}),
        permission_callback=_returning("accept"),
        project_scope=RunProjectScope(str(tmp_path)),
    )

    assert acp_outcome == {"outcome": "selected", "optionId": "reject"}
    assert codex_action == DECLINE_ACTION


@pytest.mark.asyncio
async def test_a_decision_with_no_project_to_measure_against_refuses(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No scope is no authority to permit against, so the call is refused.

    The project scan is the first authority the shared decision consults, and
    the deny-by-default direction for a check that cannot be made is to refuse -
    not to skip the check and let the call through unmeasured. Asserted on the
    decision rather than through a rung, because neither rung can produce this
    call any more: the Codex rung requires the run's project at construction and
    the ACP config derives one from its workspace. This is the floor underneath
    both of them, and it has to hold whatever a future caller does.
    """
    with caplog.at_level("WARNING"):
        decision = await decide(
            ToolPermissionRequest(
                tool=f"mcp__{_WITHHELD_SERVER}__status",
                arguments={"project_root": str(tmp_path)},
                options=[
                    {"optionId": "accept", "kind": "allow_once"},
                    {"optionId": "decline", "kind": "reject_once"},
                ],
            ),
            scope=None,
            covered=lambda: True,
            ask=_answering("accept"),
        )

    assert decision is None
    assert any(
        "no project to measure it against" in record.getMessage()
        for record in caplog.records
    ), [record.getMessage() for record in caplog.records]


@pytest.mark.asyncio
async def test_a_remembered_refusal_with_no_single_use_refusal_refuses_the_call(
    tmp_path: Path,
) -> None:
    """A refusal is never forwarded in a spelling that outlives its own call.

    The CLI persists a remembering answer as a rule in the operator's own
    settings, which no run can retract. Where the session offers no once-only
    refusal to narrow to, the shared decision refuses the call instead of
    handing that spelling back: the human's refusal is honoured and nothing is
    written down. Asserted on the decision itself, because that is where it is
    made - each rung then spells a refusal in its own lane's terms.
    """
    decision = await decide(
        ToolPermissionRequest(
            tool="Edit",
            arguments={},
            options=[
                {"optionId": "allow_once", "kind": "allow_once"},
                {"optionId": "reject_always", "kind": "reject_always"},
            ],
        ),
        scope=RunProjectScope(str(tmp_path)),
        covered=lambda: False,
        ask=_answering("reject_always"),
    )

    assert decision is None


@pytest.mark.asyncio
async def test_a_remembered_refusal_is_narrowed_where_a_single_use_one_is_offered(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    """Refusing is the fallback, not the answer: narrowing still comes first."""
    outcome = await acp_permission_outcome(
        acp_session_context,
        _config(str(tmp_path), permission_callback=_returning("reject_always")),
        tool_call={"title": "Edit", "rawInput": {}},
        options=[
            {"optionId": "reject_always", "kind": "reject_always"},
            {"optionId": "reject_once", "kind": "reject_once"},
        ],
    )

    assert outcome == {"outcome": "selected", "optionId": "reject_once"}


@pytest.mark.asyncio
async def test_a_remembered_approval_with_no_single_use_approval_is_still_forwarded(
    tmp_path: Path,
) -> None:
    """The two polarities part here, and the asymmetry is the decision.

    Refusing a remembered APPROVAL would answer the opposite of what the human
    said, so it is forwarded as chosen and the rule it costs is logged. Only a
    remembered refusal can be honoured by refusing.
    """
    decision = await decide(
        ToolPermissionRequest(
            tool="Edit",
            arguments={},
            options=[
                {"optionId": "allow_always", "kind": "allow_always"},
                {"optionId": "reject_once", "kind": "reject_once"},
            ],
        ),
        scope=RunProjectScope(str(tmp_path)),
        covered=lambda: False,
        ask=_answering("allow_always"),
    )

    assert decision == "allow_always"


@pytest.mark.asyncio
async def test_an_autonomous_covered_call_offered_no_approval_fails_closed(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    """Coverage permits an approval; it does not invent one that was not offered.

    ``Read`` is declared for this config, so the unattended rung would approve
    it - but the one option on offer carries no id to select, so there is nothing
    approvable on the table. Falling back to the conventional approve literal
    answered a grant the provider never offered and could not match to any option
    it had listed; the call is refused instead, and with nothing refusable either
    the lane answers the protocol's own cancelled outcome.
    """
    outcome = await acp_permission_outcome(
        acp_session_context,
        _config(str(tmp_path), allowed_tools=["Read"]),
        tool_call={"title": "Read", "rawInput": {}},
        options=[{"kind": "allow_once", "name": "Allow once"}],
    )

    assert outcome == _CANCELLED


@pytest.mark.asyncio
async def test_an_autonomous_covered_call_offered_nothing_at_all_fails_closed(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    """An empty option list is a malformed request, never a licence to approve."""
    outcome = await acp_permission_outcome(
        acp_session_context,
        _config(str(tmp_path), allowed_tools=["Read"]),
        tool_call={"title": "Read", "rawInput": {}},
        options=[],
    )

    assert outcome == _CANCELLED


@pytest.mark.asyncio
async def test_an_autonomous_covered_call_still_takes_the_narrowest_approval(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    """Failing closed where nothing is offered must not refuse the normal case."""
    outcome = await acp_permission_outcome(
        acp_session_context,
        _config(str(tmp_path), allowed_tools=["Read"]),
        tool_call={"title": "Read", "rawInput": {}},
        options=[
            {"optionId": "allow_always", "kind": "allow_always"},
            {"optionId": "allow_once", "kind": "allow_once"},
        ],
    )

    assert outcome == {"outcome": "selected", "optionId": "allow_once"}
