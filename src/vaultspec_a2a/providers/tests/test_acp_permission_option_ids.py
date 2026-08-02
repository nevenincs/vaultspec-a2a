"""Option-id validity at the ACP ``session/request_permission`` RPC handler.

Real objects, no mocks: the frozen ``AcpModelConfig`` and the real
``on_request_permission``. The permission callback is a genuine collaborator
supplied by the caller (the graph's interrupt gate in production), so a real
async function stands in that slot exactly as production wires it.

Each test here fails on the pre-unification handler, which built its valid-id
set as ``{o.get("optionId") for o in options}`` — unfiltered, camelCase-only.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from .._acp_rpc_handlers import _kimi_autonomous_option_id, on_request_permission
from .._acp_types import AcpModelConfig, AcpSessionContext

# An option dict with no identity field at all — exactly what the unfiltered set
# comprehension turned into a ``None`` member of the "valid" ids.
_MALFORMED = {"label": "Nameless option", "kind": "allow_once"}


def _config(*, permission_callback=None, acp_family: str = "claude") -> AcpModelConfig:
    return AcpModelConfig(
        agent_config=None,
        permission_callback=permission_callback,
        workspace_root=None,
        cwd=None,
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


def _ctx() -> AcpSessionContext:
    # The callback-return and no-callback paths never touch the session context.
    return cast("AcpSessionContext", SimpleNamespace())


async def _decide(options: list, config: AcpModelConfig) -> object:
    params = {"toolCall": {"title": "Edit", "rawInput": {}}, "options": options}
    raw = await on_request_permission(1, params, _ctx(), config)
    resp = cast("dict[str, Any]", raw)
    return resp["result"]["outcome"]["optionId"]


def _returning(answer: object):
    async def callback(_name, _args, _options):
        return answer

    return callback


@pytest.mark.asyncio
async def test_a_null_option_id_is_never_serialised_into_the_outcome() -> None:
    """A callback answering ``None`` must be rejected, not echoed to the agent.

    Before unification the malformed option contributed ``None`` to the valid
    set, so ``None in valid_ids`` held and ``None`` rode out in the outcome
    frame — an answer no ACP agent can act on.
    """
    options = [{"optionId": "approve"}, _MALFORMED]

    decision = await _decide(options, _config(permission_callback=_returning(None)))

    assert decision == "approve"
    assert decision is not None


@pytest.mark.asyncio
async def test_a_rejected_answer_falls_back_without_raising_key_error() -> None:
    """The fallback for a bad answer must survive the malformed input it exists for.

    With a leading option that carries no id, the old fallback subscripted
    ``options[0]["optionId"]`` and raised ``KeyError`` — inside the very branch
    meant to recover from an invalid answer.
    """
    options = [_MALFORMED, {"optionId": "deny_once"}]

    decision = await _decide(
        options, _config(permission_callback=_returning("hostile-option"))
    )

    assert decision == "deny_once"


@pytest.mark.asyncio
async def test_a_snake_case_option_answered_in_kind_is_accepted() -> None:
    """A snake_case options list validates its own snake_case answer.

    Previously the valid set was ``{None}``, so the legitimate answer failed the
    guard and the fallback raised ``KeyError``.
    """
    options = [{"option_id": "allow_always"}, {"option_id": "reject_once"}]

    decision = await _decide(
        options, _config(permission_callback=_returning("reject_once"))
    )

    assert decision == "reject_once"


@pytest.mark.asyncio
async def test_a_snake_case_option_is_selected_when_no_callback_decides() -> None:
    """The unsupervised default path reads the leading option in either spelling."""
    decision = await _decide([{"option_id": "allow_always"}], _config())

    assert decision == "allow_always"


@pytest.mark.asyncio
async def test_a_leading_option_without_an_id_does_not_crash_the_default_path() -> None:
    """No id on offer at position zero means the conventional allow-once id."""
    decision = await _decide([_MALFORMED], _config())

    assert decision == "allow_once"


@pytest.mark.asyncio
async def test_a_raising_callback_denies_without_subscripting_a_bad_option() -> None:
    """The fail-closed denial path must not itself raise on malformed options."""

    async def callback(_name, _args, _options):
        raise RuntimeError("the human hung up")

    options = [{"optionId": "approve"}, {"optionId": "deny_always"}, _MALFORMED]

    decision = await _decide(options, _config(permission_callback=callback))

    assert decision == "deny_always"


@pytest.mark.asyncio
async def test_a_denial_never_slides_onto_an_approval_on_a_bad_last_option() -> None:
    """Fail-closed means an unusable id, never the surviving APPROVE id.

    The conventional most-restrictive option is the last one. When it carries no
    id and nothing else names a denial, answering with the literal ``deny`` makes
    the agent decline; scanning back up the list would have answered ``approve``.
    """
    options = [{"optionId": "approve"}, _MALFORMED]

    async def callback(_name, _args, _options):
        raise RuntimeError("the human hung up")

    decision = await _decide(options, _config(permission_callback=callback))

    assert decision == "deny"


def test_the_kimi_autonomous_lane_reads_snake_case_options() -> None:
    """The Kimi read-only enforcement resolves ids through the same rule."""
    options = [
        {"option_id": "approve", "kind": "allow_once"},
        {"option_id": "reject", "kind": "reject_once"},
    ]
    config = _config(acp_family="kimi")

    assert _kimi_autonomous_option_id("ReadFile: a.py", config, options) == "approve"
    assert _kimi_autonomous_option_id("WriteFile: a.py", config, options) == "reject"
