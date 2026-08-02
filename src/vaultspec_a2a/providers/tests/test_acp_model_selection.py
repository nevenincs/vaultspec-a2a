"""Deterministic regression coverage for ACP negotiated model selection.

The live adapter exchange is proved elsewhere against a real agent. This file
is the cost-free floor underneath it: it drives the production selection seam
over genuine OS pipes and pins the two things a live test cannot pin cheaply -
the exact wire shape of the configuration RPC, and that every way the adapter
can decline to honour the requested model raises before a prompt is sent.

No test doubles: the context wraps a real child process's stream reader/writer
pair, so the request frame asserted here is the frame that left the process.
"""

import asyncio
import sys
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from ...graph.enums import MODEL_MAP, Model, Provider
from ...utils.enums import AcpRequestId
from .._acp_session import _select_desired_model
from .._acp_types import AcpModelConfig, AcpSessionContext
from .._json_contract import JsonObject
from ..acp_exceptions import AcpErrorCode, AcpSessionError
from ._acp_frames import read_acp_frame

_DESIRED = MODEL_MAP[Provider.CLAUDE][Model.LOW]
_CONFIG_ID = "model-selection"
_SESSION_ID = "session-under-test"
_TIMEOUT = 10.0

# Echoes each stdin line straight back on stdout, so a frame written to the
# child's stdin is readable from the same context's stdout. A real pipe
# round-trip through a real process, not an in-memory stand-in.
_ECHO_CHILD = (
    "import sys\n"
    "for line in sys.stdin.buffer:\n"
    "    sys.stdout.buffer.write(line)\n"
    "    sys.stdout.buffer.flush()\n"
)


@pytest_asyncio.fixture
async def echo_context() -> AsyncIterator[AcpSessionContext]:
    """Yield a production context bound to a real echoing child process."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _ECHO_CHILD,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    context = AcpSessionContext(
        process=process,
        stdin=process.stdin,
        stdout=process.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
    )
    try:
        yield context
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()


def _config(desired_model: str | None) -> AcpModelConfig:
    """Build the minimal real config the selection seam reads."""
    return AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=None,
        cwd=None,
        command=["echo"],
        env_vars={},
        session_id=None,
        mcp_servers=[],
        use_exec=False,
        provider=None,
        runtime_authority=None,
        acp_backend=None,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
        desired_model=desired_model,
    )


def _advertised(config_id: str = _CONFIG_ID) -> list[JsonObject]:
    """The session's negotiated options, including one selectable model option."""
    return [
        {"id": "thinking-budget", "category": "thinking"},
        {"id": config_id, "category": "model", "currentValue": "some-other-model"},
    ]


def _confirmation(value: str, config_id: str = _CONFIG_ID) -> JsonObject:
    """An adapter result reporting *value* as the option's current selection."""
    return {
        "configOptions": [
            {"id": config_id, "category": "model", "currentValue": value},
        ]
    }


def _resolve(ctx: AcpSessionContext, payload: JsonObject) -> None:
    """Complete the pending selection future the way the stdout loop would."""
    ctx.response_futures[AcpRequestId.SESSION_SET_CONFIG_OPTION].set_result(payload)


@pytest.mark.asyncio
async def test_selection_emits_the_exact_configuration_rpc(
    echo_context: AcpSessionContext,
) -> None:
    """The request carries sessionId, the advertised configId, and the model.

    The adapter authority is the option id it advertised, never an assumed key,
    so the id echoed back here is the one taken from the negotiated surface.
    """
    task = asyncio.create_task(
        _select_desired_model(
            echo_context, _config(_DESIRED), _SESSION_ID, _advertised()
        )
    )
    frame = await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SET_CONFIG_OPTION, timeout=_TIMEOUT
    )

    assert frame["jsonrpc"] == "2.0"
    assert frame["method"] == "session/set_config_option"
    assert frame["params"] == {
        "sessionId": _SESSION_ID,
        "configId": _CONFIG_ID,
        "value": _DESIRED,
    }

    _resolve(echo_context, {"result": _confirmation(_DESIRED)})
    confirmed = await task
    assert confirmed == _confirmation(_DESIRED)["configOptions"]


@pytest.mark.asyncio
async def test_absent_desired_model_leaves_the_session_untouched(
    echo_context: AcpSessionContext,
) -> None:
    """No resolved model means no RPC: nothing to select, nothing to verify."""
    advertised = _advertised()
    returned = await _select_desired_model(
        echo_context, _config(None), _SESSION_ID, advertised
    )
    assert returned == advertised
    assert AcpRequestId.SESSION_SET_CONFIG_OPTION not in echo_context.response_futures


@pytest.mark.asyncio
async def test_session_without_a_model_option_fails_closed(
    echo_context: AcpSessionContext,
) -> None:
    """An adapter that advertises no model option cannot honour the profile."""
    with pytest.raises(AcpSessionError, match="does not advertise"):
        await _select_desired_model(
            echo_context,
            _config(_DESIRED),
            _SESSION_ID,
            [{"id": "thinking-budget", "category": "thinking"}],
        )
    assert AcpRequestId.SESSION_SET_CONFIG_OPTION not in echo_context.response_futures


@pytest.mark.asyncio
async def test_rejected_selection_fails_closed(
    echo_context: AcpSessionContext,
) -> None:
    """A rejected selection is terminal rather than a silent default-model run."""
    task = asyncio.create_task(
        _select_desired_model(
            echo_context, _config(_DESIRED), _SESSION_ID, _advertised()
        )
    )
    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SET_CONFIG_OPTION, timeout=_TIMEOUT
    )
    _resolve(
        echo_context,
        {"error": {"code": AcpErrorCode.INVALID_PARAMS, "message": "unknown model"}},
    )

    with pytest.raises(AcpSessionError, match="unknown model") as caught:
        await task
    assert caught.value.code == AcpErrorCode.INVALID_PARAMS


@pytest.mark.asyncio
async def test_unconfirmed_selection_fails_closed(
    echo_context: AcpSessionContext,
) -> None:
    """Accepting the call is not proof; the reported value must be the one asked for.

    This is the case that would otherwise bill a run at the adapter's default
    tier while the dashboard displayed the frozen low tier.
    """
    task = asyncio.create_task(
        _select_desired_model(
            echo_context, _config(_DESIRED), _SESSION_ID, _advertised()
        )
    )
    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SET_CONFIG_OPTION, timeout=_TIMEOUT
    )
    _resolve(echo_context, {"result": _confirmation("a-much-larger-model")})

    with pytest.raises(AcpSessionError, match="did not select the requested model"):
        await task


@pytest.mark.asyncio
async def test_malformed_confirmation_fails_closed(
    echo_context: AcpSessionContext,
) -> None:
    """A result without usable options proves nothing and must not pass."""
    task = asyncio.create_task(
        _select_desired_model(
            echo_context, _config(_DESIRED), _SESSION_ID, _advertised()
        )
    )
    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SET_CONFIG_OPTION, timeout=_TIMEOUT
    )
    _resolve(echo_context, {"result": {"configOptions": "not-a-list"}})

    with pytest.raises(AcpSessionError, match="malformed configuration options"):
        await task


@pytest.mark.asyncio
async def test_variant_confirmation_of_the_requested_model_is_accepted(
    echo_context: AcpSessionContext,
) -> None:
    """An accepted request confirmed as a bracketed VARIANT of the id passes.

    Observed live on the Claude CLI: requesting ``opus`` is confirmed as
    ``opus[1m]`` - the adapter's canonical context-window variant of the same
    model, not a different model. Refusing it failed every real run whose
    profile named the bare id, so the acceptance is pinned here; an unrelated
    id is still refused (``test_unconfirmed_selection_fails_closed``).
    """
    task = asyncio.create_task(
        _select_desired_model(
            echo_context, _config(_DESIRED), _SESSION_ID, _advertised()
        )
    )
    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SET_CONFIG_OPTION, timeout=_TIMEOUT
    )
    _resolve(echo_context, {"result": _confirmation(f"{_DESIRED}[1m]")})

    confirmed = await task
    assert confirmed == _confirmation(f"{_DESIRED}[1m]")["configOptions"]
