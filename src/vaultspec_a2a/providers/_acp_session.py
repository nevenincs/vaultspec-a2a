"""ACP session lifecycle RPCs: initialize, setup, and prompt.

Extracted from the original monolithic ``_acp_session.py``.
Data carriers live in ``_acp_types``, auth logic in ``_acp_auth``.
"""

import logging
from pathlib import Path

from ..control.config import settings
from ..utils.enums import AcpRequestId
from ..workspace.environment import resolve_env_vars
from ._acp_auth import (
    auth_hint,
    authenticate_rpc,
    is_auth_required_error,
    runtime_log_extra,
)
from ._acp_authoring import AUTHORING_MCP_SERVER_NAME
from ._acp_mcp import require_declared_surface
from ._acp_request import await_response, issue_request
from ._acp_types import (
    AcpModelConfig,
    AcpResponseFuture,
    AcpSessionContext,
    InitializeResult,
    SessionSetupResult,
    require_workspace_root,
)
from ._json_contract import JsonObject, JsonValue, lenient_json_object
from .acp_exceptions import AcpErrorCode, AcpSessionError

__all__: list[str] = []

logger = logging.getLogger(__name__)


def is_strict_claude_session(config: AcpModelConfig) -> bool:
    """Whether this session speaks to the Claude CLI's own session option surface.

    True for the claude family (Claude/Z.ai share the claude adapter and CLI)
    and false for the kimi family and for the gemini backend, which reuses the
    claude family default while running a different agent that has no
    ``claudeCode`` option namespace and no strict-MCP flag.
    """
    return config.acp_family == "claude" and config.acp_backend != "gemini-cli"


# System-prompt addendum for an armed strict session. The CLI connects MCP
# servers asynchronously and does not hold the first turn for them, so a
# declared server that takes a few seconds to start (a cold package runner, an
# index-backed search service) can miss the first tool snapshot; the CLI ships
# the WaitForMcpServers builtin as the model-side remedy. Without this note a
# model concludes the declared grounding tools do not exist and silently falls
# back to native tools - grounding absent, run green.
MCP_READINESS_NOTE = (
    "This session declares MCP tools (tool names starting with 'mcp__'). MCP "
    "servers finish mounting a few seconds after the session starts, so a "
    "declared MCP tool may be missing from your first tool listing. Before "
    "concluding a declared MCP tool is unavailable, call WaitForMcpServers "
    "(or retry the tool call once) - never silently substitute a different "
    "tool for work the declared MCP tools exist to ground."
)


def claude_session_options(config: AcpModelConfig) -> JsonObject:
    """Compose the ``_meta.claudeCode.options`` block for a claude-family session.

    ``strictMcpConfig`` is UNCONDITIONAL, armed or not: the CLI's own
    ``--strict-mcp-config`` mode drops every ambient MCP registration scope -
    enterprise managed config, user-global ``mcpServers``, project ``.mcp.json``,
    local scope, plugin servers, and the account's claude.ai remote connectors -
    and admits only the dynamic set carried by the session injection. That makes
    the spawned agent's MCP surface EXACTLY the injected set (empty on a plain
    run), enforced by the CLI itself rather than by config-home or workspace
    file manipulation, while the child still runs as the operator's own
    identity. ``allowedTools`` rides the same block for headless runs so the
    composed tool names are auto-permitted without a local prompt.
    """
    options: JsonObject = {"strictMcpConfig": True}
    if config.allowed_tools:
        options["allowedTools"] = list[JsonValue](config.allowed_tools)
    return options


def session_surface_mcp_servers(config: AcpModelConfig) -> list[JsonValue]:
    """Shape ``config.mcp_servers`` into the ``session/new`` advertisement.

    Two normalizations, both load-bearing:

    - Every stdio spec carries an explicit ``env`` list (empty when it has no
      environment). The ACP schema models ``env`` as a required field of the
      stdio server shape, and the migrated adapter's validator silently DROPS a
      spec without it - the mechanism previously misread as a registration-scope
      gate on session injection.
    - On the strict claude lane, env VALUES are replaced with ``${NAME}``
      placeholder references and the declared-surface allowlist is enforced
      (:func:`require_declared_surface`). The adapter forwards the session set
      into the SDK's dynamic MCP config, which is serialized onto the spawned
      CLI's command line - visible to any local process enumerator - so real
      values must never ride the spec. The CLI expands ``${NAME}`` from its own
      process environment at config parse time; the caller hoists the real
      values into the spawn environment from the same source the placeholders
      are derived from, so a reference cannot dangle.

    Non-claude families keep their env values verbatim: their agents mount the
    injected servers themselves (no CLI argv serialization is involved) and no
    placeholder-expansion contract exists there.
    """
    strict = is_strict_claude_session(config)
    if strict:
        require_declared_surface(
            config.mcp_servers, bridge_name=AUTHORING_MCP_SERVER_NAME
        )
    surface: list[JsonValue] = []
    for spec in config.mcp_servers:
        shaped = dict(spec)
        env = shaped.get("env")
        if not isinstance(env, list):
            env = []
        if strict:
            placeholders: list[JsonValue] = []
            for item in env:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    placeholders.append(
                        {"name": item["name"], "value": f"${{{item['name']}}}"}
                    )
                else:
                    placeholders.append(item)
            env = placeholders
        shaped["env"] = env
        surface.append(shaped)
    return surface


def _config_options(result: JsonObject, *, operation: str) -> list[JsonObject]:
    """Return advertised session configuration options, tolerating absence.

    ``configOptions`` is an optional part of the session surface: an agent that
    advertises none simply offers nothing to configure, so absence maps to an
    empty list rather than a refusal. What IS refused is malformed data - a
    non-dict entry means the surface cannot be trusted. The strictness that
    matters (a lane that REQUESTS a model but cannot verify its selection)
    lives in :func:`_select_desired_model`, which still fails loud when a
    desired model is set and no model option is advertised.
    """
    raw_options = result.get("configOptions")
    if raw_options is None:
        return []
    if not isinstance(raw_options, list):
        raise AcpSessionError(
            f"ACP {operation} returned malformed configuration options",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    options: list[JsonObject] = []
    for option in raw_options:
        if not isinstance(option, dict):
            raise AcpSessionError(
                f"ACP {operation} returned a malformed configuration option",
                code=AcpErrorCode.INTERNAL_ERROR,
            )
        options.append(option)
    return options


def _model_config_id(config_options: list[JsonObject]) -> str:
    """Read the model option identifier from the adapter's negotiated surface."""
    for option in config_options:
        if option.get("category") != "model":
            continue
        config_id = option.get("id")
        if isinstance(config_id, str) and config_id:
            return config_id
        break
    raise AcpSessionError(
        "ACP session does not advertise a selectable model configuration option",
        code=AcpErrorCode.INVALID_PARAMS,
    )


def _selected_model(
    config_options: list[JsonObject], config_id: str, *, operation: str
) -> str:
    """Read the adapter-confirmed current value for the negotiated model option."""
    for option in config_options:
        if option.get("id") != config_id:
            continue
        current_value = option.get("currentValue")
        if isinstance(current_value, str) and current_value:
            return current_value
        break
    raise AcpSessionError(
        f"ACP {operation} did not report a current selected model",
        code=AcpErrorCode.INTERNAL_ERROR,
    )


async def _select_desired_model(
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    session_id: str,
    config_options: list[JsonObject],
) -> list[JsonObject]:
    """Apply and verify the profile-resolved ACP model before any prompt."""
    desired_model = config.desired_model
    if not desired_model:
        return config_options

    config_id = _model_config_id(config_options)
    return await _select_config_option(
        ctx,
        session_id,
        config_options,
        config_id=config_id,
        desired_value=desired_model,
        label="model",
        allow_bracketed_variant=True,
    )


async def _select_config_option(
    ctx: AcpSessionContext,
    session_id: str,
    config_options: list[JsonObject],
    *,
    config_id: str,
    desired_value: str,
    label: str,
    allow_bracketed_variant: bool = False,
) -> list[JsonObject]:
    """Apply and verify one adapter-advertised session configuration value."""
    if not any(option.get("id") == config_id for option in config_options):
        raise AcpSessionError(
            f"ACP session does not advertise requested {label} configuration option",
            code=AcpErrorCode.INVALID_PARAMS,
        )
    rpc_id = AcpRequestId.SESSION_SET_CONFIG_OPTION
    future = await issue_request(
        ctx.response_futures,
        stdin=ctx.stdin,
        stdin_lock=ctx.stdin_lock,
        rpc_id=rpc_id,
        method="session/set_config_option",
        params={
            "sessionId": session_id,
            "configId": config_id,
            "value": desired_value,
        },
    )
    response = await await_response(
        future, timeout=settings.acp_startup_timeout_seconds
    )
    if "error" in response:
        error = lenient_json_object(response["error"])
        message = str(error.get("message", response["error"]))
        raise AcpSessionError(
            f"ACP session/set_config_option failed: {message}",
            code=_error_code(response["error"]),
        )
    result = response.get("result")
    if not isinstance(result, dict):
        raise AcpSessionError(
            "ACP session/set_config_option succeeded without an object result",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    confirmed_options = _config_options(result, operation="session/set_config_option")
    selected_value = _selected_model(
        confirmed_options, config_id, operation="session/set_config_option"
    )
    # The adapter ACCEPTED the request (no error above), so the confirmed value
    # is its canonical form of what was asked for - which may be a variant of
    # the requested id rather than the id verbatim. Observed live on the Claude
    # CLI: requesting 'opus' is confirmed as 'opus[1m]', the bracketed
    # context-window variant of the same model. Accept the exact id or a
    # bracketed variant of it; anything else means the adapter selected a
    # DIFFERENT model than requested, which stays a loud failure.
    is_variant_of_desired = allow_bracketed_variant and selected_value.startswith(
        f"{desired_value}["
    )
    if selected_value != desired_value and not is_variant_of_desired:
        raise AcpSessionError(
            f"ACP session/set_config_option did not select the requested {label} "
            f"{desired_value!r}; adapter reported {selected_value!r}",
            code=AcpErrorCode.INVALID_PARAMS,
        )
    return confirmed_options


async def _select_desired_config_options(
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    session_id: str,
    config_options: list[JsonObject],
) -> list[JsonObject]:
    """Apply frozen non-model ACP controls in canonical control-id order."""
    selected = config_options
    for config_id, desired_value in sorted(config.desired_config_options.items()):
        selected = await _select_config_option(
            ctx,
            session_id,
            selected,
            config_id=config_id,
            desired_value=desired_value,
            label="native control",
        )
    return selected


def _error_code(value: JsonValue | None) -> int:
    """Read one numeric JSON-RPC error code with the standard fallback."""
    code = lenient_json_object(value).get("code")
    return (
        code
        if isinstance(code, int) and not isinstance(code, bool)
        else AcpErrorCode.INTERNAL_ERROR
    )


async def initialize_session(
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> InitializeResult:
    """Send ACP initialize request and return capabilities + auth methods."""
    rpc_id = AcpRequestId.INITIALIZE
    future = await issue_request(
        ctx.response_futures,
        stdin=ctx.stdin,
        stdin_lock=ctx.stdin_lock,
        rpc_id=rpc_id,
        method="initialize",
        params={
            "protocolVersion": 1,
            "clientCapabilities": {
                "fs": {
                    "readTextFile": (
                        config.agent_config.capabilities.filesystem_read
                        if config.agent_config is not None
                        else False
                    ),
                    "writeTextFile": (
                        config.agent_config.capabilities.filesystem_write
                        if config.agent_config is not None
                        else False
                    ),
                },
                "terminal": (
                    config.agent_config.capabilities.terminal
                    if config.agent_config is not None
                    else False
                ),
                # Signal support for terminal-based auth and
                # terminal output to claude-agent-acp >=0.20.2.  Without
                # these flags the agent refuses to authenticate via the
                # subprocess stdin/stdout channel (gateway auth check added
                # in v0.20.2 via zed-industries/claude-agent-acp#380).
                "_meta": {
                    "terminal-auth": True,
                    "terminal_output": True,
                },
            },
            "clientInfo": {"name": "vaultspec", "version": "1.0.0"},
        },
    )
    resp = await await_response(
        future,
        timeout=settings.acp_startup_timeout_seconds,
        on_timeout=lambda: logger.error(
            "ACP initialize timed out",
            extra=runtime_log_extra(
                config,
                process=ctx.process,
                handshake_step="initialize",
                timeout_seconds=settings.acp_startup_timeout_seconds,
                stderr_event_count=ctx.stderr_event_count,
            ),
        ),
    )
    if "error" in resp:
        # M22: use domain exception with explicit cause information
        logger.error(
            "ACP initialize returned an error",
            extra=runtime_log_extra(
                config,
                process=ctx.process,
                handshake_step="initialize",
                timeout_seconds=settings.acp_startup_timeout_seconds,
                stderr_event_count=ctx.stderr_event_count,
            ),
        )
        raise AcpSessionError(
            f"ACP initialize failed: {resp['error']}",
            code=_error_code(resp.get("error")),
        )
    res = resp.get("result")
    result = lenient_json_object(res)
    capabilities = result.get("agentCapabilities")
    auth_methods = result.get("authMethods")
    return InitializeResult(
        agent_capabilities=lenient_json_object(capabilities),
        auth_methods=[method for method in auth_methods if isinstance(method, dict)]
        if isinstance(auth_methods, list)
        else [],
    )


async def setup_session(
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    agent_capabilities: JsonObject,
    auth_methods: list[JsonObject],
) -> SessionSetupResult:
    """Create or load an ACP session.

    Returns a ``SessionSetupResult`` with the session id and agent modes.
    Writes session-scoped mutables (``tool_calls``, ``agent_modes``) to
    ``ctx`` internally.
    """
    working_dir = str(
        require_workspace_root(config.workspace_root, surface="ACP session cwd")
    )
    # Opening a session here makes the CLI partition its config home by this cwd
    # and persist a transcript into the OPERATOR's home - the run-side creating
    # seam for acp-cli-session-transcript (declared in ``acp_chat_model``). The
    # catalog probe in ``acp_catalog`` is the other. Nothing here may reclaim it.
    method = "session/new"
    mcp_servers = session_surface_mcp_servers(config)
    params: JsonObject = {"cwd": working_dir, "mcpServers": mcp_servers}
    if is_strict_claude_session(config):
        # Claude family only (Claude/Z.ai): the claudeCode options block is
        # emitted on EVERY session. strictMcpConfig bounds the agent's MCP
        # surface to exactly the injected set (see claude_session_options);
        # allowedTools additionally serializes the headless auto-permit
        # allowlist so the CLI can invoke the composed tools without a local
        # prompt. That is a recorded approval policy, not a bypass — the real
        # human gate is the engine review lane, and the .vault deny policy
        # still blocks fs writes.
        #
        # The kimi family OMITS this _meta: Kimi has no claudeCode namespace,
        # so the SAME composed names (still carried in config.allowed_tools)
        # are enforced at our session/request_permission handler as an
        # exact-name auto-approve set (P03.S10) instead.
        session_meta: JsonObject = {
            "claudeCode": {"options": claude_session_options(config)}
        }
        if config.mcp_servers:
            # Armed session: append the MCP-readiness note so the model waits
            # for the declared servers to mount rather than silently working
            # ungrounded (the CLI connects MCP asynchronously and does not hold
            # the first turn for it).
            session_meta["systemPrompt"] = {"append": MCP_READINESS_NOTE}
        params["_meta"] = session_meta
        if config.allowed_tools:
            logger.info(
                "ACP auto-permitting bridged authoring tools (headless): %s",
                config.allowed_tools,
                extra=runtime_log_extra(config, process=ctx.process),
            )
    if config.session_id and agent_capabilities.get("loadSession") is True:
        method = "session/load"
        params["sessionId"] = config.session_id

    env = resolve_env_vars(Path(working_dir))
    env.update(config.env_vars)
    attempted_auth = False
    while True:
        rpc_id = AcpRequestId.SESSION_SETUP
        future = await issue_request(
            ctx.response_futures,
            stdin=ctx.stdin,
            stdin_lock=ctx.stdin_lock,
            rpc_id=rpc_id,
            method=method,
            params=params,
        )
        resp = await await_response(
            future,
            timeout=settings.acp_startup_timeout_seconds,
            on_timeout=lambda: logger.error(
                "ACP session setup timed out",
                extra=runtime_log_extra(
                    config,
                    process=ctx.process,
                    handshake_step=method,
                    timeout_seconds=settings.acp_startup_timeout_seconds,
                    stderr_event_count=ctx.stderr_event_count,
                ),
            ),
        )
        if "error" not in resp:
            break
        err = resp["error"]
        err_code = _error_code(err)
        error = lenient_json_object(err)
        err_msg = str(error.get("message", err)) if error else str(err)
        if not attempted_auth and auth_methods and is_auth_required_error(err):
            attempted_auth = True
            await authenticate_rpc(
                ctx=ctx,
                config=config,
                env=env,
                auth_methods=auth_methods,
                stdin=ctx.stdin,
                stdin_lock=ctx.stdin_lock,
                response_futures=ctx.response_futures,
                process=ctx.process,
                stderr_event_count=ctx.stderr_event_count,
                auth_url=ctx.auth_url,
            )
            continue
        if is_auth_required_error(err):
            logger.error(
                "ACP session setup requires authentication",
                extra=runtime_log_extra(
                    config,
                    process=ctx.process,
                    handshake_step=method,
                    timeout_seconds=settings.acp_startup_timeout_seconds,
                    stderr_event_count=ctx.stderr_event_count,
                ),
            )
            hint = auth_hint(config)
            raise AcpSessionError(
                f"ACP {method} failed — authentication required. {hint}",
                code=err_code,
            )
        logger.error(
            "ACP session setup returned an error",
            extra=runtime_log_extra(
                config,
                process=ctx.process,
                handshake_step=method,
                timeout_seconds=settings.acp_startup_timeout_seconds,
                stderr_event_count=ctx.stderr_event_count,
            ),
        )
        raise AcpSessionError(
            f"ACP {method} failed: {err_msg}",
            code=err_code,
        )
    result = resp.get("result")
    if not isinstance(result, dict):
        raise AcpSessionError(
            f"ACP {method} succeeded without an object result",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    session_id = result.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise AcpSessionError(
            f"ACP {method} succeeded without a sessionId",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    config_options = _config_options(result, operation=method)
    config_options = await _select_desired_model(
        ctx, config, session_id, config_options
    )
    config_options = await _select_desired_config_options(
        ctx, config, session_id, config_options
    )
    agent_modes: JsonObject = {}
    if modes := result.get("modes"):
        if not isinstance(modes, dict):
            modes = {}
        agent_modes = {
            "currentModeId": modes.get("currentModeId"),
            "availableModes": modes.get("availableModes", []),
        }
    ctx.tool_calls = {}
    ctx.agent_modes = agent_modes
    ctx.config_options = config_options
    return SessionSetupResult(
        session_id=session_id,
        agent_modes=agent_modes,
        config_options=config_options,
    )


async def setup_prompt(
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
    blocks: list[JsonObject],
    active_session_id: str,
) -> AcpResponseFuture:
    """Send the initial prompt."""
    rpc_id = AcpRequestId.SESSION_PROMPT
    prompt = list[JsonValue](blocks)
    future = await issue_request(
        ctx.response_futures,
        stdin=ctx.stdin,
        stdin_lock=ctx.stdin_lock,
        rpc_id=rpc_id,
        method="session/prompt",
        params={"sessionId": active_session_id, "prompt": prompt},
    )
    ctx.prompt_id_ref.append(rpc_id)
    return future
