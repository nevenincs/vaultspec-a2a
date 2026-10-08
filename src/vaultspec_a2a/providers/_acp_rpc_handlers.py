"""ACP RPC handler implementations.

Extracted from ``acp_chat_model.py``.  Contains permission and filesystem RPC
handlers as free functions; the terminal RPC handlers live in the sibling
``_acp_rpc_terminal_handlers`` module (split for module size), which
re-exports its own public surface. The ``on_terminal_*`` handlers are
re-exported below so every existing import of this facade keeps working.
Constants are placed next to their consumers.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from langgraph.errors import GraphBubbleUp

from ..control.config import settings
from ..control.workspace import configured_workspace_boundary
from ..desktop._filesystem_authority import confined_file_descriptor
from ..graph.acp_options import option_id_of_kind, valid_option_ids
from ..graph.enums import PermissionOptionKind
from ._acp_client_requests import AcpSessionRequest
from ._acp_fs_read import AcpFileReadRange, AcpFileReadRequest, read_text_lines
from ._acp_request import jsonrpc_error, jsonrpc_result
from ._acp_rpc_terminal_handlers import on_terminal_create as on_terminal_create
from ._acp_rpc_terminal_handlers import on_terminal_kill as on_terminal_kill
from ._acp_rpc_terminal_handlers import on_terminal_output as on_terminal_output
from ._acp_rpc_terminal_handlers import on_terminal_release as on_terminal_release
from ._acp_rpc_terminal_handlers import (
    on_terminal_wait_for_exit as on_terminal_wait_for_exit,
)
from ._acp_types import (
    AcpModelConfig,
    AcpRpcId,
    AcpSessionContext,
    require_workspace_root,
)
from ._json_contract import (
    JsonObject,
    lenient_json_object,
    lenient_json_object_list,
)
from ._native_read_tools import NATIVE_READ_TOOL_NAMES
from ._project_scope import path_arguments_in_project
from ._tool_policy import ToolPermissionRequest, decide
from .acp_exceptions import AcpErrorCode

__all__: list[str] = []

logger = logging.getLogger(__name__)


def _required_string(params: JsonObject, field: str) -> str:
    """Read one required string field from an ACP RPC payload."""
    value = params.get(field)
    if not isinstance(value, str):
        raise ValueError(f"ACP field {field!r} must be a string")
    return value


def _non_negative_integer(value: object, *, field: str) -> int:
    """Parse a file range without truncating fractions or accepting booleans."""
    message = f"ACP field {field!r} must be a non-negative integer"
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float, str))
        or (isinstance(value, float) and not value.is_integer())
    ):
        raise ValueError(message)
    try:
        parsed = int(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(message) from exc
    if parsed < 0:
        raise ValueError(message)
    return parsed


def sandbox_path(path: str, config: AcpModelConfig) -> Path:
    """Resolve and sandbox a path to the agent cwd."""
    cwd = require_workspace_root(
        config.workspace_root, surface="agent filesystem sandbox root"
    )
    resolved = (cwd / path).resolve()
    if not resolved.is_relative_to(cwd.resolve()):
        raise ValueError(f"Path {path!r} escapes sandbox")
    return resolved


def _secure_workspace_anchor(config: AcpModelConfig) -> tuple[Path, tuple[str, ...]]:
    """Return the managed anchor and no-follow run-root traversal components."""
    workspace_root = require_workspace_root(
        config.workspace_root, surface="agent filesystem sandbox root"
    ).resolve()
    if not workspace_root.is_dir():
        raise ValueError("agent filesystem sandbox root is not an existing directory")
    boundary = configured_workspace_boundary()
    if boundary is None:
        return workspace_root, ()
    try:
        run_root_parts = workspace_root.relative_to(boundary).parts
    except ValueError as exc:
        raise ValueError(
            "agent filesystem sandbox root escaped its managed boundary"
        ) from exc
    return boundary, run_root_parts


class _VaultWriteDeniedError(ValueError):
    """A final opened-path policy check refused a vault write."""


def _workspace_file_parts(
    path: str, config: AcpModelConfig
) -> tuple[Path, tuple[str, ...]]:
    anchor_root, run_root_parts = _secure_workspace_anchor(config)
    workspace_root = anchor_root.joinpath(*run_root_parts)
    file_path = sandbox_path(path, config)
    try:
        parts = file_path.relative_to(workspace_root).parts
    except ValueError as exc:
        raise ValueError(f"Path {path!r} escapes sandbox") from exc
    return anchor_root, (*run_root_parts, *parts)


def _read_workspace_text(
    path: str, config: AcpModelConfig, *, line: int | None, limit: int | None
) -> str:
    """Read bounded text from a confined file handle on every served profile."""
    ranges = AcpFileReadRange(line=line, limit=limit)
    maximum = _non_negative_integer(
        settings.acp_fs_read_max_bytes, field="acp_fs_read_max_bytes"
    )
    anchor_root, parts = _workspace_file_parts(path, config)
    with (
        confined_file_descriptor(anchor_root, parts) as descriptor,
        os.fdopen(
            descriptor, encoding="utf-8", errors="ignore", closefd=False
        ) as handle,
    ):
        return read_text_lines(handle, ranges, maximum)


def _write_workspace_text(path: str, content: str, config: AcpModelConfig) -> None:
    """Validate and truncate the same confined regular-file object."""
    anchor_root, parts = _workspace_file_parts(path, config)
    if _targets_vault(anchor_root.joinpath(*parts), config):
        raise _VaultWriteDeniedError("Agents may not write .vault/ files directly")
    shared_gid = None
    if sys.platform != "win32" and settings.provider_identity_launcher is not None:
        shared_gid = settings.provider_agent_gid
        if shared_gid is None:
            raise RuntimeError("secure provider callback requires an agent GID")
    with (
        confined_file_descriptor(
            anchor_root, parts, write=True, shared_gid=shared_gid
        ) as descriptor,
        os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle,
    ):
        handle.write(content)


def _targets_vault(file_path: Path, _config: AcpModelConfig) -> bool:
    """Return True if a sandbox-resolved path lies within any ``.vault`` dir.

    Agents may not write the vault corpus through their coding-CLI file
    tools. ``file_path`` is already ``.resolve()``-d and confined to the agent
    cwd by :func:`sandbox_path`, so symlinks and ``..`` traversal are already
    collapsed to a real path under the workspace. We deny if ANY component of
    the resolved ABSOLUTE path is ``.vault`` — compared case-insensitively via
    ``casefold()`` because the Windows/macOS filesystems are case-insensitive (a
    ``.VAULT`` write resolves to the same directory).

    Checking the absolute path (not the workspace-relative one) closes the case
    where the workspace root is ITSELF rooted inside a ``.vault`` ancestor: such
    a workspace makes every write a vault write even though no ``.vault``
    component appears relative to the root. It also still catches a ``.vault``
    dir nested under the workspace.
    """
    return any(
        (part.rstrip(" .") if os.name == "nt" else part).casefold() == ".vault"
        for part in file_path.parts
    )


def _vault_write_denial(rpc_id: AcpRpcId, path: str) -> JsonObject:
    """Build the value-typed ``.vault`` write denial.

    Mirrors the engine's ``forbidden_actor`` 200-value shape (wire-shapes
    reference §2): a value-typed ``result`` carrying a snake_case
    ``denial_kind`` beside a human-readable ``eligibility.reason`` that names
    the authoring tools as the correct path — never a bare JSON-RPC error, so
    the agent is steered rather than left retrying a failed write.
    """
    return jsonrpc_result(
        rpc_id,
        {
            "status": "denied",
            "denial_kind": "forbidden_actor",
            "eligibility": {
                "command": "fs/write_text_file",
                "allowed": False,
                "reason": (
                    "Agents may not write .vault/ files directly. Propose the "
                    "change through the authoring tools (propose_changeset / "
                    "append_draft / replace_draft); a human reviews and applies "
                    "it in the dashboard."
                ),
            },
            "path": path,
        },
    )


# Kimi's native READ tools that mirror the read floor (Claude's Read/Grep/Glob),
# enumerated from the installed kimi-cli 1.49.0 source and cross-checked against
# the executor service's own verification:
#   ReadFile (tools/file/read.py:64), Grep (tools/file/grep_local.py:386),
#   Glob (tools/file/glob.py:56)
# NOTE the name divergence from Claude: Kimi's read tool is `ReadFile`, not `Read`.
# The write tools WriteFile/StrReplaceFile, the bash/shell exec tool, and every
# plan/dmail/agent/todo mutator are NOT listed and are rejected in autonomous mode.
# `ReadMediaFile` (image reads) and the web tools FetchURL/SearchWeb are read-only
# but DELIBERATELY EXCLUDED: neither is part of the text-grounding floor (Kimi has
# no Claude-floor analogue for them), so the conservative posture omits them.
_KIMI_NATIVE_READ_TOOLS: frozenset[str] = frozenset({"ReadFile", "Grep", "Glob"})

# The Claude-family read floor, read from the single place this project declares
# it rather than re-spelled here, so the tools a run auto-permits at composition
# and the tools it auto-approves at the permission rung cannot drift.
_CLAUDE_NATIVE_READ_TOOLS: frozenset[str] = frozenset(NATIVE_READ_TOOL_NAMES)


def _native_read_tools(config: AcpModelConfig) -> frozenset[str]:
    """Return the lane's native read floor - the CLI's own read-only tools.

    Every lane declares one. A lane whose permission payload cannot name its
    native tools declares an empty floor rather than being omitted, so the
    absence is a reviewed answer instead of a gap between ``if`` branches.
    """
    if config.acp_family == "kimi":
        return _KIMI_NATIVE_READ_TOOLS
    return _CLAUDE_NATIVE_READ_TOOLS


def _canonical_tool_identity(title: str, config: AcpModelConfig) -> str:
    """Reduce a permission request's ``title`` to the tool name it names.

    The ACP permission payload has no tool-name field: every backend projects the
    call into a ``title`` meant for a human, and each projects it differently, so
    the reduction is per backend and each spelling is taken from the installed
    adapter rather than assumed.

    - kimi-cli titles are ``"ToolName"`` or ``"ToolName: subtitle"``.
    - claude-agent-acp keeps a reporter per built-in it knows
      (``dist/tool-calls/reporters/``) and falls through to a generic reporter
      that titles the call with the tool's own name, which is what makes an MCP
      tool's title its exact ``mcp__<server>__<tool>`` name. The per-built-in
      reporters are deliberately NOT parsed: their titles are prose - ``Read``
      renders ``"Read <path>"`` and ``Grep`` renders an equivalent grep command
      line - and matching a leading word would let a sub-agent task whose
      description merely BEGINS with an allowlisted word canonicalise into an
      approval.
    """
    if config.acp_family == "kimi":
        return title.split(": ", 1)[0]
    return title


def _strip_mcp_prefix(tool_name: str) -> str:
    """Reduce a Claude-form ``mcp__<server>__<tool>`` allowlist entry to the raw
    tool name Kimi exposes. Kimi registers MCP tools by their RAW ``mcp_tool.name``
    (kimi-cli ``soul/toolset.py`` ``MCPTool.name = mcp_tool.name``), so its
    permission title carries ``search_vault``, not ``mcp__vaultspec-rag__search_vault``.
    """
    if tool_name.startswith("mcp__"):
        return tool_name.split("__", 2)[-1]
    return tool_name


def _selected_outcome(rpc_id: AcpRpcId, option_id: str) -> JsonObject:
    """Build the response frame selecting one offered option."""
    return jsonrpc_result(
        rpc_id, {"outcome": {"optionId": option_id, "outcome": "selected"}}
    )


def _cancelled_outcome(rpc_id: AcpRpcId) -> JsonObject:
    """Build the response frame that abandons one tool call.

    The protocol's own ``cancelled`` outcome carries no option id at all, so it
    cannot be mistaken for a selection, and the adapter aborts the tool use
    without the model being told that anybody decided anything. It is the answer
    wherever there IS no decision to report: a run that suspended to ask a
    person, and a refusal the session can only spell in a way that would outlive
    the call it answered.
    """
    return jsonrpc_result(rpc_id, {"outcome": {"outcome": "cancelled"}})


def _refused_outcome(rpc_id: AcpRpcId, options: list[JsonObject]) -> JsonObject:
    """Build the response frame that refuses one tool call.

    A refusal is expressed by SELECTING the offered ONCE-ONLY refusal, because
    that is the answer the agent can act on: the pinned adapter turns it into a
    denial the model is told about while the turn continues.

    The remembering refusal is deliberately NOT a fallback. The CLI persists
    ``reject_always`` as a permission rule in the operator's own settings, where
    it outlives this call, narrows every later run on the machine - including the
    unattended ones, whose whole posture is that nothing is approved or denied
    for them in advance - and cannot be seen or retracted by any run. The shared
    decision already refuses a remembered answer rather than forward it for that
    reason, so selecting it here would write the exact rule that refusal exists
    to avoid. Where the session offers no once-only refusal the call is ABANDONED
    instead: that costs the model the distinction between "refused" and "not
    decided", and costs the operator nothing.

    Never an approval, and never an empty frame.
    """
    refusal = option_id_of_kind(options, PermissionOptionKind.REJECT_ONCE)
    if refusal is not None:
        return _selected_outcome(rpc_id, refusal)
    return _cancelled_outcome(rpc_id)


def _floor_call_is_confined(
    config: AcpModelConfig, args: JsonObject, locations: list[JsonObject]
) -> bool:
    """Whether a native floor call works only inside the project the run is bound to.

    A floor tool is the one thing this rung approves by NAME alone: the CLI's own
    read built-ins are served by no server and declared in no registry, so the
    name is all the request carries about identity. The name says nothing about
    REACH, and a read is bounded by its path rather than by its tool - a content
    search named ``Grep`` reads whichever file it is pointed at, including every
    file the operator can read.

    So the call has to say where it works, and a call that says nowhere is
    refused with one that says elsewhere: the rung cannot tell a read of the
    project from a read of the host when neither is written down, and a floor
    call that is genuinely inside the project is already pre-approved against
    the workspace before it would ever reach here.
    """
    return path_arguments_in_project(args, locations, config.project_scope).confined


def _composed_surface_covers(
    tool: str,
    config: AcpModelConfig,
    *,
    args: JsonObject,
    locations: list[JsonObject],
) -> bool:
    """Whether an ACP run's composed surface covers one call, on any ACP lane.

    *tool* is the call's canonical identity. Covered are EXACTLY the composed
    tools (``config.allowed_tools``, in both the qualified
    ``mcp__<server>__<tool>`` spelling a Claude title carries and the raw
    spelling Kimi carries), and the lane's native read floor only where the
    call's own path arguments lie inside the bound project.

    The floor is the one branch that reads the ARGUMENTS as well as the name,
    because it is matched by name and its names carry no scope: a title reducing
    to exactly ``Grep`` would otherwise be covered whatever host path the call
    named.
    """
    composed = set(config.allowed_tools) | {
        _strip_mcp_prefix(allowed) for allowed in config.allowed_tools
    }
    if tool in composed:
        return True
    if tool not in _native_read_tools(config):
        return False
    if _floor_call_is_confined(config, args, locations):
        return True
    # The refused path is not logged: a caller-chosen path is agent-supplied
    # payload.
    logger.warning(
        "Refused a native read tool at the autonomous rung: tool=%s named "
        "no path inside the run's bound project (bound=%s)",
        tool,
        config.project_scope.bound_project_root(),
    )
    return False


async def on_request_permission(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle session/request_permission RPC.

    The decision is :func:`._tool_policy.decide`'s. This handler checks the
    session, names the call, says which calls the lane's composed surface
    covers, and spells the answer as an ACP outcome.
    """
    options = lenient_json_object_list(params.get("options"))
    tool_call = lenient_json_object(params.get("toolCall"))
    name_value = tool_call.get("title")
    name = name_value if isinstance(name_value, str) else "unknown"
    args = lenient_json_object(tool_call.get("rawInput"))
    # The adapter's own account of the files this call touches, read beside the
    # raw input rather than instead of it: either half can name a path, and a
    # scope decision that consulted only one would be decided by which half the
    # backend happened to fill in.
    locations = lenient_json_object_list(tool_call.get("locations"))

    # Session ownership precedes every rung, exactly as on the filesystem and
    # terminal callbacks: a request that does not name the active negotiated
    # session carries no authority for a person or an allowlist to decide.
    # Refused rather than errored, so the adapter declines the call cleanly.
    try:
        AcpSessionRequest.model_validate(params).require_active_session(ctx)
    except ValueError:
        logger.warning(
            "Refused a permission request outside the active ACP session: tool=%s",
            name,
        )
        return _refused_outcome(rpc_id, options)

    # Diagnostic (tool name + option ids only, never rawInput/payloads):
    # this handler firing means the SDK's canUseTool rung was reached — i.e. no
    # allow-rule pre-empted the call. Logging it disambiguates which permission
    # rung resolved a bridged authoring tool during headless runs.
    logger.info(
        "ACP permission requested (canUseTool rung): tool=%s options=%s",
        name,
        sorted(valid_option_ids(options)),
    )

    # Under autonomy the worker leaves the callback unset, so no callback means
    # no human rung, on ANY lane.
    callback = config.permission_callback
    request = ToolPermissionRequest(
        tool=_canonical_tool_identity(name, config), arguments=args, options=options
    )
    try:
        option_id = await decide(
            request,
            scope=config.project_scope,
            covered=lambda: _composed_surface_covers(
                request.tool, config, args=args, locations=locations
            ),
            ask=None if callback is None else lambda: callback(name, args, options),
        )
    except GraphBubbleUp as exc:
        # The human rung suspended the run to ask a person. A park does not
        # pause the provider: the turn re-raises the suspension, the session
        # tree is released in its `finally`, and the node re-runs from the top
        # on resume - so whatever this still-open request is answered with is
        # the LAST thing the model is told before its session ends. Answering a
        # refusal would tell it a human said no to a call no human has yet seen,
        # and invite it to act on that denial inside the same turn. The
        # abandonment is answered unconditionally, whatever the request offered:
        # it is what is true, and the option list has no bearing on it.
        ctx.interrupt_exc.append(exc)
        try:
            ctx.chunk_queue.put_nowait(None)
        except asyncio.QueueFull:
            logger.warning("Chunk queue full — dropping interrupt sentinel")
        return _cancelled_outcome(rpc_id)
    if option_id is None:
        # A denial outcome rather than a JSON-RPC error, so the ACP subprocess
        # can cleanly decline the tool call.
        return _refused_outcome(rpc_id, options)
    return _selected_outcome(rpc_id, option_id)


async def on_fs_read_text_file(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle fs/read_text_file RPC.

    Requires the active session and supports one-based ``line`` selection
    and ``limit`` in lines, with an independent UTF-8 response byte cap.
    Uses asyncio.to_thread so blocking I/O does not stall the event loop.
    """
    try:
        if "offset" in params:
            raise ValueError("ACP field 'offset' is unsupported; use 'line'")
        request = AcpFileReadRequest.model_validate(params)
        request.require_active_session(ctx)

        text = await asyncio.to_thread(
            _read_workspace_text,
            request.path,
            config,
            line=request.line,
            limit=request.limit,
        )
        return jsonrpc_result(rpc_id, {"content": text})
    except Exception as exc:
        return jsonrpc_error(rpc_id, AcpErrorCode.INTERNAL_ERROR, str(exc))


async def on_fs_write_text_file(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle fs/write_text_file RPC.

    Holds the run's write lock for the target file, so two writers of one path
    cannot truncate and fill it at the same time while writers of different
    paths stay independent. Uses asyncio.to_thread so blocking I/O does not
    stall the event loop.
    """
    try:
        request = AcpSessionRequest.model_validate(params)
        request.require_active_session(ctx)
        path = _required_string(params, "path")
        file_path = sandbox_path(path, config)

        # Deny agent writes into the vault corpus. Returns a value-typed
        # forbidden_actor denial (not a transport error) so the agent is steered
        # to the authoring tools. Reads (on_fs_read_text_file) stay permitted.
        if _targets_vault(file_path, config):
            logger.info(
                "Denied .vault/ write via ACP fs (forbidden_actor): %r",
                path,
            )
            return _vault_write_denial(rpc_id, path)

        content = _required_string(params, "content")

        async with config.write_lock.hold(file_path):
            request.require_active_session(ctx)
            await asyncio.to_thread(_write_workspace_text, path, content, config)
        return jsonrpc_result(rpc_id, {})
    except _VaultWriteDeniedError:
        return _vault_write_denial(rpc_id, _required_string(params, "path"))
    except Exception as exc:
        return jsonrpc_error(rpc_id, AcpErrorCode.INTERNAL_ERROR, str(exc))
