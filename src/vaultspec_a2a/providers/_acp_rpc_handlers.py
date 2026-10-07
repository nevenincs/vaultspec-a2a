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
from ..graph.acp_options import (
    is_approval,
    is_remembering,
    narrowest_option_id,
    offered_option,
    option_id_of,
    option_id_of_kind,
    valid_option_ids,
)
from ..graph.enums import PermissionOptionKind
from ._acp_client_requests import AcpSessionRequest
from ._acp_fs_read import AcpFileReadRange, AcpFileReadRequest, read_text_lines
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
from ._harness_mcp_registry import harness_tool_is_withheld
from ._json_contract import (
    JsonObject,
    lenient_json_object,
    lenient_json_object_list,
)
from ._native_read_tools import NATIVE_READ_TOOL_NAMES
from ._project_scope import foreign_project_argument, path_arguments_in_project

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
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
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
    }


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


def _option_id_at(options: list[JsonObject], index: int, *, default: str) -> str:
    """Return the id of the option at ``index``, or ``default`` if it has none.

    Positional, never scanning: the caller picks an option by CONVENTION (first
    is the least restrictive), so silently sliding to a neighbour when the
    conventional entry is malformed would substitute an option with the opposite
    meaning. Reading the id through the canonical extractor instead of
    subscripting is what keeps a malformed entry from raising ``KeyError`` on a
    path that exists to handle malformed input.
    """
    if not options:
        return default
    return option_id_of(options[index]) or default


def _selected_outcome(rpc_id: AcpRpcId, option_id: str) -> JsonObject:
    """Build the response frame selecting one offered option."""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {"outcome": {"optionId": option_id, "outcome": "selected"}},
    }


def _refused_outcome(rpc_id: AcpRpcId, options: list[JsonObject]) -> JsonObject:
    """Build the response frame that refuses one tool call.

    A refusal is expressed by SELECTING the narrowest offered refusal wherever
    the request offers one, because that is the answer the agent can act on: the
    pinned adapter turns it into a denial the model is told about while the turn
    continues. Where the request offers nothing to refuse with, the protocol's
    own ``cancelled`` outcome is the answer - it carries no option id at all, so
    it cannot be mistaken for a selection, and the adapter aborts the tool use.
    Never an approval, and never an empty frame.
    """
    refusal = narrowest_option_id(options, approving=False)
    if refusal is not None:
        return _selected_outcome(rpc_id, refusal)
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {"outcome": {"outcome": "cancelled"}},
    }


def _narrowed_to_one_use(option_id: str, options: list[JsonObject]) -> str:
    """Return the once-only spelling of a chosen answer.

    A remembered answer is not this project's to give. The CLI persists it as a
    permission rule in the operator's own settings, outside anything a run can
    see or retract, and a rule written that way widens or narrows every later
    run on that machine - including the unattended ones, whose whole posture is
    that nothing is approved that was not approved for them. A human at the
    prompt is answering for THIS call, so this call is what the answer is
    applied to.

    The answer keeps its polarity: a remembered approval becomes the once-only
    approval and a remembered refusal the once-only refusal, read through the
    same option kinds the autonomous rung answers from, so both rungs answer the
    same way about the same option list. If a session offers no once-only answer
    of that polarity, the choice is left as made rather than converted into one
    the human did not give - and that case is logged, because it is the one
    where an answer outlives its call.
    """
    chosen = offered_option(options, option_id)
    if chosen is None or not is_remembering(chosen):
        return option_id
    once = (
        PermissionOptionKind.ALLOW_ONCE
        if is_approval(chosen)
        else PermissionOptionKind.REJECT_ONCE
    )
    narrowed = option_id_of_kind(options, once)
    if narrowed is None:
        logger.warning(
            "Permission option %r remembers the answer and the session offers "
            "no single-use alternative; the CLI will persist a rule this run "
            "cannot retract",
            option_id,
        )
        return option_id
    logger.info(
        "Narrowed a remembered permission answer to a single use: %r -> %r",
        option_id,
        narrowed,
    )
    return narrowed


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


def _autonomous_option_id(
    name: str,
    config: AcpModelConfig,
    options: list[JsonObject],
    *,
    args: JsonObject,
    locations: list[JsonObject],
) -> str:
    """Return the option id for an autonomous permission decision, on any lane.

    An autonomous run has no human rung, so this IS the permission decision.
    Every lane gets the same rule: auto-approve EXACTLY the composed tools
    (``config.allowed_tools``, in both the qualified ``mcp__<server>__<tool>``
    spelling a Claude title carries and the raw spelling Kimi carries), and the
    lane's native read floor only where the call's own path arguments lie inside
    the bound project; reject everything else.

    Rejecting the uncovered case is the point. A permission request only reaches
    here for a call the CLI's own static pre-approval did not cover, and what a
    server MOUNTS is wider than what the registry DECLARES - the search server
    also serves index-rebuild and index-clean verbs beside its three declared
    reads. Approving the uncovered call, which is what the non-kimi lanes did,
    made the declared surface advisory and every unadvertised verb reachable.

    The floor was the remaining way past that rule, because it is matched by
    name and its names carry no scope: a title reducing to exactly ``Grep`` was
    approved whatever host path the call named. The floor is therefore the one
    branch that reads the ARGUMENTS as well as the name.

    An approval is the NARROWEST offered one: taking the first approval-kind
    option could grant a whole server for a session on the strength of one
    allowlisted tool. A refusal is the narrowest offered refusal, and otherwise
    the literal ``"reject"``. The literal is a deliberate answer rather than a
    gap: an id the agent does not recognise makes it decline the tool call,
    which is the direction a refusal must fail in, while any scan that could
    land on an approval turns one malformed or unusual option list into a grant.
    """
    canonical = _canonical_tool_identity(name, config)
    composed = set(config.allowed_tools) | {
        _strip_mcp_prefix(tool) for tool in config.allowed_tools
    }
    approved = canonical in composed
    if not approved and canonical in _native_read_tools(config):
        approved = _floor_call_is_confined(config, args, locations)
        if not approved:
            # The refused path is not logged, as above: a caller-chosen path is
            # agent-supplied payload.
            logger.warning(
                "Refused a native read tool at the autonomous rung: tool=%s named "
                "no path inside the run's bound project (bound=%s)",
                name,
                config.project_scope.bound_project_root(),
            )
    if approved:
        return narrowest_option_id(options, approving=True) or _option_id_at(
            options, 0, default="approve"
        )
    return narrowest_option_id(options, approving=False) or "reject"


async def on_request_permission(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle session/request_permission RPC."""
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

    # Diagnostic (R7: tool name + option ids only, never rawInput/payloads):
    # this handler firing means the SDK's canUseTool rung was reached — i.e. no
    # allow-rule pre-empted the call. Logging it disambiguates which permission
    # rung resolved a bridged authoring tool during headless runs.
    logger.info(
        "ACP permission requested (canUseTool rung): tool=%s options=%s",
        name,
        sorted(valid_option_ids(options)),
    )

    # Scope enforcement precedes BOTH rungs. A run is bound to one project, and a
    # call naming another is outside what the run was admitted to do, so neither
    # an autonomous allowlist nor a human sitting at the supervised rung is the
    # authority that could permit it. Placing the check first also means the
    # refusal is the same refusal on every lane.
    #
    # The refused ARGUMENT is deliberately not logged, only the fact of the
    # refusal and the run's own bound project: the R7 discipline this handler
    # already follows keeps agent-supplied payload out of the log, and a
    # caller-chosen path is payload.
    scope = config.project_scope
    if foreign_project_argument(args, scope) is not None:
        logger.warning(
            "Refused cross-project tool call: tool=%s named a project outside "
            "the run's bound project (bound=%s)",
            name,
            scope.bound_project_root(),
        )
        return _refused_outcome(rpc_id, options)

    # A withheld harness tool is served by a server the run mounts but is never
    # callable, so it is refused ahead of the human rung as well: a person at the
    # prompt cannot see that the call would send vault text off the host, and
    # the registry's no-egress declaration rests on nobody being asked.
    if harness_tool_is_withheld(_canonical_tool_identity(name, config)):
        logger.warning("Refused a withheld harness tool: tool=%s", name)
        return _refused_outcome(rpc_id, options)

    if config.permission_callback:
        try:
            option_id = _narrowed_to_one_use(
                await config.permission_callback(name, args, options), options
            )
        except GraphBubbleUp as exc:
            ctx.interrupt_exc.append(exc)
            try:
                ctx.chunk_queue.put_nowait(None)
            except asyncio.QueueFull:
                logger.warning("Chunk queue full — dropping interrupt sentinel")
            # H9 fix: return a proper JSON-RPC denial response instead of
            # an empty dict `{}` which would produce a malformed frame.
            return _refused_outcome(rpc_id, options)
        except Exception:
            logger.exception(
                "Permission callback raised; denying permission (fail-closed)"
            )
            # TOAD reference pattern: return a denial outcome (not a JSON-RPC
            # error) so the ACP subprocess can cleanly decline the tool call.
            return _refused_outcome(rpc_id, options)
    else:
        # Autonomous: no permission_callback means no human rung, on ANY lane.
        # Under autonomy the worker leaves the callback unset, so every
        # permission request the CLI raises - and a request is raised only for a
        # call the CLI's own static pre-approval did not cover - is decided here.
        # This used to fork: kimi enforced an exact-name read allowlist because
        # its CLI carries no config allowlist, and every other lane approved the
        # first offered option unconditionally, which approved an uncovered
        # mutating call exactly like a read. One rule now covers all of them.
        option_id = _autonomous_option_id(
            name, config, options, args=args, locations=locations
        )

    # M17: validate that option_id is among the offered options before returning.
    # Reject a callback-supplied id that is not in the options list to prevent
    # sending an invalid response to the ACP subprocess. The valid set is built
    # by the canonical predicate, so an option dict missing its id contributes
    # nothing instead of admitting ``None`` as a "valid" answer.
    valid_ids = valid_option_ids(options)
    if valid_ids and option_id not in valid_ids:
        # An answer naming an option that was never offered is not a decision
        # this handler can carry out, so the call is REFUSED rather than mapped
        # onto a neighbour. Substituting the first offered option was the same
        # bug in two directions: the pinned adapter sorts its options by kind
        # with the approvals first, so a refusal whose id did not match resolved
        # to a grant - and any substitution answers a question the decider was
        # not asked.
        logger.warning(
            "Permission answer option_id=%r is not among the offered options %r; "
            "refusing the tool call rather than substituting one",
            option_id,
            sorted(valid_ids),
        )
        return _refused_outcome(rpc_id, options)

    logger.info("ACP permission decision: tool=%s option=%s", name, option_id)
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
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": text}}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": str(exc)},
        }


async def on_fs_write_text_file(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle fs/write_text_file RPC.

    Acquires the global git mutex before writing to prevent races with
    concurrent git operations. Uses asyncio.to_thread so
    blocking I/O does not stall the event loop.
    """
    from ..workspace.concurrency import git_workspace_mutex

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
                "Denied .vault/ write via ACP fs (R2 forbidden_actor): %r",
                path,
            )
            return _vault_write_denial(rpc_id, path)

        content = _required_string(params, "content")

        async with git_workspace_mutex:
            request.require_active_session(ctx)
            await asyncio.to_thread(_write_workspace_text, path, content, config)
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
    except _VaultWriteDeniedError:
        return _vault_write_denial(rpc_id, _required_string(params, "path"))
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": str(exc)},
        }
