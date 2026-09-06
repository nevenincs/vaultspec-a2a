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

from ...utils.enums import AcpRequestId
from .._acp_session import (
    _select_desired_config_options,
    _select_desired_model,
    _session_wire_error,
    initialize_session,
)
from .._acp_types import AcpModelConfig, AcpSessionContext, InitializeResult
from .._json_contract import JsonObject, JsonValue
from ..acp_exceptions import AcpErrorCode, AcpSessionError
from ..conditions import ProviderCondition
from ._acp_frames import read_acp_frame

# An opaque model identifier standing for the value frozen into a run's role
# assignment. Deliberately a literal rather than a lookup: an external lane's
# models are named by the catalog that lane serves, so the selection seam must
# carry whatever string it is handed. Reading a repository-authored name here
# would test the adapter against a vocabulary no provider actually speaks.
_DESIRED = "opaque-catalog-model-id"
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


def _config(
    desired_model: str | None,
    *,
    session_id: str | None = None,
) -> AcpModelConfig:
    """Build the minimal real config the selection seam reads."""
    return AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=None,
        command=["echo"],
        env_vars={},
        session_id=session_id,
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


@pytest.mark.asyncio
async def test_native_control_uses_its_advertised_session_option_id(
    echo_context: AcpSessionContext,
) -> None:
    config = _config(None)
    config.desired_config_options["thinking-budget"] = "brief-wire"
    advertised: list[JsonObject] = [
        {
            "id": "thinking-budget",
            "category": "thought",
            "currentValue": "deep-wire",
        }
    ]
    task = asyncio.create_task(
        _select_desired_config_options(echo_context, config, _SESSION_ID, advertised)
    )
    frame = await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SET_CONFIG_OPTION, timeout=_TIMEOUT
    )
    assert frame["params"] == {
        "sessionId": _SESSION_ID,
        "configId": "thinking-budget",
        "value": "brief-wire",
    }
    _resolve(
        echo_context,
        {
            "result": {
                "configOptions": [
                    {
                        "id": "thinking-budget",
                        "category": "thought",
                        "currentValue": "brief-wire",
                    }
                ]
            }
        },
    )
    confirmed = await task
    assert confirmed[0]["currentValue"] == "brief-wire"


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


async def _initialize(
    ctx: AcpSessionContext, config: AcpModelConfig, result: JsonValue
) -> InitializeResult:
    """Drive one real initialize frame and deliver the supplied peer result."""
    task = asyncio.create_task(initialize_session(ctx, config))
    frame = await read_acp_frame(ctx.stdout, AcpRequestId.INITIALIZE, timeout=_TIMEOUT)
    assert frame["method"] == "initialize"
    params = frame.get("params")
    assert isinstance(params, dict) and params.get("protocolVersion") == 1
    ctx.response_futures[AcpRequestId.INITIALIZE].set_result({"result": result})
    return await task


@pytest.mark.asyncio
async def test_initialize_accepts_only_the_requested_protocol_version(
    echo_context: AcpSessionContext,
) -> None:
    accepted = await _initialize(
        echo_context,
        _config(None),
        {"protocolVersion": 1, "agentCapabilities": {}, "authMethods": []},
    )
    assert accepted.agent_capabilities == {}

    with pytest.raises(AcpSessionError, match="unsupported protocol version") as caught:
        await _initialize(
            echo_context,
            _config(None),
            {"protocolVersion": 2, "agentCapabilities": {}, "authMethods": []},
        )
    assert caught.value.code == AcpErrorCode.INVALID_PARAMS


@pytest.mark.asyncio
async def test_initialize_wire_condition_survives_session_error(
    echo_context: AcpSessionContext,
) -> None:
    task = asyncio.create_task(initialize_session(echo_context, _config(None)))
    await read_acp_frame(echo_context.stdout, AcpRequestId.INITIALIZE, timeout=_TIMEOUT)
    wire_data: JsonObject = {"errorKind": "authentication_failed"}
    echo_context.response_futures[AcpRequestId.INITIALIZE].set_result(
        {
            "error": {
                "code": AcpErrorCode.INTERNAL_ERROR,
                "message": "credential rejected",
                "data": wire_data,
            }
        }
    )
    with pytest.raises(AcpSessionError) as caught:
        await task
    assert caught.value.condition is ProviderCondition.UNAUTHENTICATED
    assert caught.value.data == wire_data


def test_session_authentication_code_is_not_reported_unknown() -> None:
    error = _session_wire_error(
        "ACP session/new failed",
        {
            "code": AcpErrorCode.UNAUTHENTICATED,
            "message": "authentication required",
        },
    )
    assert error.condition is ProviderCondition.UNAUTHENTICATED


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol_version", [None, "1", True])
async def test_initialize_rejects_missing_or_malformed_protocol_version(
    echo_context: AcpSessionContext, protocol_version: JsonValue
) -> None:
    with pytest.raises(AcpSessionError, match="malformed protocolVersion"):
        await _initialize(
            echo_context,
            _config(None),
            {
                "protocolVersion": protocol_version,
                "agentCapabilities": {},
                "authMethods": [],
            },
        )


@pytest.mark.asyncio
async def test_initialize_refuses_resume_without_negotiated_support(
    echo_context: AcpSessionContext,
) -> None:
    config = _config(None, session_id="existing-session")
    with pytest.raises(AcpSessionError, match="does not advertise loadSession"):
        await _initialize(
            echo_context,
            config,
            {"protocolVersion": 1, "agentCapabilities": {}, "authMethods": []},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "message"),
    [
        ([], "without an object result"),
        (
            {"protocolVersion": 1, "agentCapabilities": [], "authMethods": []},
            "malformed agentCapabilities",
        ),
        (
            {"protocolVersion": 1, "agentCapabilities": {}, "authMethods": [1]},
            "malformed authMethods",
        ),
    ],
)
async def test_initialize_rejects_malformed_negotiated_surface(
    echo_context: AcpSessionContext, result: JsonValue, message: str
) -> None:
    with pytest.raises(AcpSessionError, match=message):
        await _initialize(echo_context, _config(None), result)


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
    with pytest.raises(AcpSessionError, match="does not advertise") as caught:
        await _select_desired_model(
            echo_context,
            _config(_DESIRED),
            _SESSION_ID,
            [{"id": "thinking-budget", "category": "thinking"}],
        )
    assert caught.value.condition is ProviderCondition.INVALID_REQUEST
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
    assert caught.value.condition is ProviderCondition.INVALID_REQUEST


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

    with pytest.raises(
        AcpSessionError, match="did not select the requested model"
    ) as caught:
        await task
    assert caught.value.condition is ProviderCondition.INVALID_REQUEST


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
