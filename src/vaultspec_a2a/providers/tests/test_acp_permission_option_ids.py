"""Option-id validity at the ACP ``session/request_permission`` RPC handler.

Real objects, no mocks: the frozen ``AcpModelConfig`` and the real
``on_request_permission``. The permission callback is a genuine collaborator
supplied by the caller (the graph's interrupt gate in production), so a real
async function stands in that slot exactly as production wires it.

Each test here fails on the pre-unification handler, which built its valid-id
set as ``{o.get("optionId") for o in options}`` — unfiltered, camelCase-only.
"""

from __future__ import annotations

import pytest

from .._acp_rpc_handlers import _autonomous_option_id, on_request_permission
from .._acp_types import AcpModelConfig, AcpSessionContext, PermissionCallback
from .._json_contract import JsonObject, JsonValue

# An option dict with no identity field at all — exactly what the unfiltered set
# comprehension turned into a ``None`` member of the "valid" ids.
_MALFORMED: JsonObject = {"label": "Nameless option", "kind": "allow_once"}


def _config(
    *,
    permission_callback: PermissionCallback | None = None,
    acp_family: str = "claude",
) -> AcpModelConfig:
    return AcpModelConfig(
        agent_config=None,
        permission_callback=permission_callback,
        workspace_root=None,
        command=["claude", "acp"],
        env_vars={},
        session_id=None,
        mcp_servers=[],
        use_exec=False,
        provider="claude",
        runtime_authority=None,
        acp_backend="claude_code",
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
        allowed_tools=[],
        acp_family=acp_family,
    )


async def _decide(
    options: list[JsonObject], config: AcpModelConfig, ctx: AcpSessionContext
) -> str:
    params: JsonObject = {
        "toolCall": {"title": "Edit", "rawInput": {}},
        "options": list[JsonValue](options),
    }
    response = await on_request_permission(1, params, ctx, config)
    result = response.get("result")
    assert isinstance(result, dict)
    outcome = result.get("outcome")
    assert isinstance(outcome, dict)
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
) -> None:
    """A callback answer outside the offered ids must be rejected, not echoed.

    The callback interface itself only permits strings. An empty string is still
    an invalid option id, and exercises the same runtime guard without breaking
    the typed collaborator contract.
    """
    options: list[JsonObject] = [{"optionId": "approve"}, _MALFORMED]

    decision = await _decide(
        options, _config(permission_callback=_returning("")), acp_session_context
    )

    assert decision == "approve"
    assert decision is not None


@pytest.mark.asyncio
async def test_a_rejected_answer_falls_back_without_raising_key_error(
    acp_session_context: AcpSessionContext,
) -> None:
    """The fallback for a bad answer must survive the malformed input it exists for.

    With a leading option that carries no id, the old fallback subscripted
    ``options[0]["optionId"]`` and raised ``KeyError`` — inside the very branch
    meant to recover from an invalid answer.
    """
    options: list[JsonObject] = [_MALFORMED, {"optionId": "deny_once"}]

    decision = await _decide(
        options,
        _config(permission_callback=_returning("hostile-option")),
        acp_session_context,
    )

    assert decision == "deny_once"


@pytest.mark.asyncio
async def test_a_snake_case_option_answered_in_kind_is_accepted(
    acp_session_context: AcpSessionContext,
) -> None:
    """A snake_case options list validates its own snake_case answer.

    Previously the valid set was ``{None}``, so the legitimate answer failed the
    guard and the fallback raised ``KeyError``.
    """
    options: list[JsonObject] = [
        {"option_id": "allow_always"},
        {"option_id": "reject_once"},
    ]

    decision = await _decide(
        options,
        _config(permission_callback=_returning("reject_once")),
        acp_session_context,
    )

    assert decision == "reject_once"


@pytest.mark.asyncio
async def test_a_snake_case_option_is_selected_when_no_callback_decides(
    acp_session_context: AcpSessionContext,
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

    decision = await _decide(options, _config(), acp_session_context)

    assert decision == "reject_once"


@pytest.mark.asyncio
async def test_a_leading_option_without_an_id_does_not_crash_the_default_path(
    acp_session_context: AcpSessionContext,
) -> None:
    """No usable id on offer means the conventional refusal literal.

    The literal is the deliberate answer rather than a recovery: an id the agent
    does not recognise makes it decline the call, which is the direction the
    unsupervised path must fail in when it cannot name what it was offered.
    """
    decision = await _decide([_MALFORMED], _config(), acp_session_context)

    assert decision == "reject"


@pytest.mark.asyncio
async def test_a_raising_callback_denies_without_subscripting_a_bad_option(
    acp_session_context: AcpSessionContext,
) -> None:
    """The fail-closed denial path must not itself raise on malformed options."""

    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        raise RuntimeError("the human hung up")

    options: list[JsonObject] = [
        {"optionId": "approve"},
        {"optionId": "deny_always"},
        _MALFORMED,
    ]

    decision = await _decide(
        options, _config(permission_callback=callback), acp_session_context
    )

    assert decision == "deny_always"


@pytest.mark.asyncio
async def test_a_denial_never_slides_onto_an_approval_on_a_bad_last_option(
    acp_session_context: AcpSessionContext,
) -> None:
    """Fail-closed means an unusable id, never the surviving APPROVE id.

    The conventional most-restrictive option is the last one. When it carries no
    id and nothing else names a denial, answering with the literal ``deny`` makes
    the agent decline; scanning back up the list would have answered ``approve``.
    """
    options: list[JsonObject] = [{"optionId": "approve"}, _MALFORMED]

    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        raise RuntimeError("the human hung up")

    decision = await _decide(
        options, _config(permission_callback=callback), acp_session_context
    )

    assert decision == "deny"


def test_the_kimi_autonomous_lane_reads_snake_case_options() -> None:
    """The Kimi read-only enforcement resolves ids through the same rule."""
    options: list[JsonObject] = [
        {"option_id": "approve", "kind": "allow_once"},
        {"option_id": "reject", "kind": "reject_once"},
    ]
    config = _config(acp_family="kimi")

    assert _autonomous_option_id("ReadFile: a.py", config, options) == "approve"
    assert _autonomous_option_id("WriteFile: a.py", config, options) == "reject"
