"""ACP RPC handler implementations.

Extracted from ``acp_chat_model.py``.  Contains permission,
filesystem, and terminal RPC handlers as free functions.  Constants are
placed next to their consumers.
"""

import asyncio
import logging
import re
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from langgraph.errors import GraphBubbleUp

from ..control.config import settings
from ..graph.acp_options import option_id_of, valid_option_ids
from ..utils.process import ProcessContainment, ProcessContainmentError
from ..workspace.environment import resolve_env_vars
from ._acp_mcp import NATIVE_READ_TOOL_NAMES
from ._acp_types import (
    AcpModelConfig,
    AcpRpcId,
    AcpSessionContext,
    require_workspace_root,
)
from ._json_contract import JsonObject, JsonValue
from ._subprocess import attach_process_containment
from ._subprocess import kill_process_tree as _kill_process_tree
from .acp_exceptions import AcpErrorCode

__all__: list[str] = []

logger = logging.getLogger(__name__)

# Allowlist of permitted executable names for terminal/create.
# Only the base name (no path component) is checked so that full paths like
# /usr/bin/python3 or C:\Python313\python.exe are also accepted.
_TERMINAL_COMMAND_ALLOWLIST: frozenset[str] = frozenset(
    {
        "python",
        "python3",
        "python3.13",
        "pip",
        "pip3",
        "git",
        "npm",
        "node",
        "npx",
        "uv",
        "uvicorn",
        "ruff",
        "mypy",
        "pytest",
        "bash",
        "sh",
        "zsh",
        "pwsh",
        "powershell",
        "cmd",
    }
)

# Shell metacharacters that must never appear in command or args strings
# when executing via create_subprocess_exec (defense-in-depth; exec does not
# invoke a shell but these chars indicate injection attempts).
_SHELL_METACHAR_RE = re.compile(r"[|&;`$()<>]")

# Server-side cap for subprocess-supplied terminal wait_for_exit timeout.
_MAX_TERMINAL_TIMEOUT: float = 300.0

# Valid POSIX environment variable name pattern.
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _json_object(value: JsonValue | None) -> JsonObject:
    """Return one JSON object or the empty object for malformed input."""
    return value if isinstance(value, dict) else {}


def _json_object_list(value: JsonValue | None) -> list[JsonObject]:
    """Return only object entries from one untrusted JSON array."""
    return (
        [entry for entry in value if isinstance(entry, dict)]
        if isinstance(value, list)
        else []
    )


def _required_string(params: JsonObject, field: str) -> str:
    """Read one required string field from an ACP RPC payload."""
    value = params.get(field)
    if not isinstance(value, str):
        raise ValueError(f"ACP field {field!r} must be a string")
    return value


def _integer(value: object, *, field: str) -> int:
    """Convert a JSON numeric/string integer field without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"ACP field {field!r} must be an integer")
    return int(value)


def _number(value: object, *, field: str) -> float:
    """Convert a JSON numeric/string field without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"ACP field {field!r} must be numeric")
    return float(value)


def sandbox_path(path: str, config: AcpModelConfig) -> Path:
    """Resolve and sandbox a path to the agent cwd."""
    cwd = require_workspace_root(
        config.workspace_root, surface="agent filesystem sandbox root"
    )
    resolved = (cwd / path).resolve()
    if not resolved.is_relative_to(cwd.resolve()):
        raise ValueError(f"Path {path!r} escapes sandbox")
    return resolved


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
    return any(part.casefold() == ".vault" for part in file_path.parts)


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


# Kimi's native READ tools that mirror the tool-cores read floor (Claude's
# Read/Grep/Glob), enumerated from the installed kimi-cli 1.49.0 source and
# cross-checked against executor-service's P04.S15 verification:
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

# The gemini backend declares an EMPTY native read floor, and the emptiness is
# the declaration, not an oversight. gemini-cli 0.46.0 fills the ACP permission
# request's ``title`` from the invocation's display title, which for its built-in
# tools is a human description (a shortened path, a shell command line) carrying
# no tool name at all; only its MCP tools carry a recoverable identity, through
# the ``"<tool> (<server> MCP Server)"` display name. An exact-name allowlist can
# admit only what it can name, so the lane's own file tools are refused under
# autonomy until the payload can carry an identity to allowlist. That is the
# fail-closed direction: the alternative is approving by tool KIND, which is a
# category rather than a name and is the blanket approval this replaces.
_GEMINI_NATIVE_READ_TOOLS: frozenset[str] = frozenset()

# gemini-cli's MCP display name, the one identity its permission payload carries.
_GEMINI_MCP_TITLE_RE = re.compile(r"^(?P<tool>\S+) \(.+ MCP Server\)$")

# ACP backend discriminator for the gemini lane. It rides ``acp_backend`` rather
# than ``acp_family`` because gemini reuses the claude family for everything
# except the CLI-side allowlist transport, which it does not have.
_GEMINI_ACP_BACKEND = "gemini-cli"


def _is_gemini_backend(config: AcpModelConfig) -> bool:
    """Return whether this lane is served by the gemini command-line backend."""
    return config.acp_backend == _GEMINI_ACP_BACKEND


def _native_read_tools(config: AcpModelConfig) -> frozenset[str]:
    """Return the lane's native read floor - the CLI's own read-only tools.

    Every lane declares one. A lane whose permission payload cannot name its
    native tools declares an empty floor rather than being omitted, so the
    absence is a reviewed answer instead of a gap between ``if`` branches.
    """
    if _is_gemini_backend(config):
        return _GEMINI_NATIVE_READ_TOOLS
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
    - claude-agent-acp 0.19.2 (``dist/tools.js``) hand-writes a label for each
      built-in it knows and falls through to ``title: name`` for everything else,
      which is what makes an MCP tool's title its exact ``mcp__<server>__<tool>``
      name. The label branches are deliberately NOT parsed: a title like
      ``"Read <path>"`` is prose, and matching its leading word would let a
      sub-agent task whose description merely BEGINS with an allowlisted word
      canonicalise into an approval.
    - gemini-cli 0.46.0 carries a tool name only for MCP tools, in its display
      name; anything else reduces to itself and matches no declared name.
    """
    if _is_gemini_backend(config):
        match = _GEMINI_MCP_TITLE_RE.match(title)
        return match.group("tool") if match else title
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

    Positional, never scanning: these call sites pick an option by CONVENTION
    (first is the least restrictive, last the most), so silently sliding to a
    neighbour when the conventional entry is malformed would substitute an
    option with the opposite meaning. Reading the id through the canonical
    extractor instead of subscripting is what keeps a malformed entry from
    raising ``KeyError`` on a path that exists to handle malformed input.
    """
    if not options:
        return default
    return option_id_of(options[index]) or default


def _first_offered_option_id(options: list[JsonObject], *, default: str) -> str:
    """Return the first option id actually offered, or ``default`` if none is.

    Unlike :func:`_option_id_at` this scans, because its caller has already
    established that SOME id is on offer and only needs a real one.
    """
    return next(
        (option_id for option in options if (option_id := option_id_of(option))),
        default,
    )


def _denial_option_id(options: list[JsonObject]) -> str:
    """Return the id of the most restrictive offered option.

    Prefer the first option whose id names a denial; fall back to the last
    option in the list (conventionally the most restrictive), then to the
    literal ``"deny"``. The literal is the deliberate answer when the last
    option is malformed: an id the agent does not recognise makes it decline
    the tool call, whereas scanning back down the list for any usable id could
    hand this fail-closed path an APPROVAL.
    """
    return next(
        (
            option_id
            for option in options
            if (option_id := option_id_of(option)) and "deny" in option_id.lower()
        ),
        _option_id_at(options, -1, default="deny"),
    )


def _approval_option_id(options: list[JsonObject]) -> str:
    """Return the id of the NARROWEST offered approval.

    ``allow_once`` is preferred over ``allow_always`` strictly, never by list
    order. The backends do not agree on ordering - gemini-cli 0.46.0 offers
    ``proceed_always_server`` ("allow all server tools for this session") ahead
    of ``proceed_once`` for an MCP call - so taking the first approval-kind
    option would grant a whole server for a session on the strength of one
    allowlisted tool, re-opening by approval exactly the undeclared verbs the
    allowlist exists to keep unreachable.
    """
    for kind in ("allow_once", "allow_always"):
        for option in options:
            option_id = option_id_of(option)
            if option.get("kind") == kind and option_id:
                return option_id
    return _option_id_at(options, 0, default="approve")


def _rejection_option_id(options: list[JsonObject]) -> str:
    """Return the id of an offered rejection, scanning for a refusal of any spelling."""
    for option in options:
        option_id = option_id_of(option)
        if option_id and (
            option.get("kind") in ("reject_once", "reject_always")
            or "reject" in option_id.lower()
            or "deny" in option_id.lower()
        ):
            return option_id
    return _option_id_at(options, -1, default="reject")


def _autonomous_option_id(
    name: str, config: AcpModelConfig, options: list[JsonObject]
) -> str:
    """Return the option id for an autonomous permission decision, on any lane.

    An autonomous run has no human rung, so this IS the permission decision.
    Every lane gets the same rule: auto-approve EXACTLY the composed tools
    (``config.allowed_tools``, in both the qualified ``mcp__<server>__<tool>``
    spelling a claude title carries and the raw spelling kimi and gemini carry)
    plus the lane's native read floor; reject everything else.

    Rejecting the uncovered case is the point. A permission request only reaches
    here for a call the CLI's own static pre-approval did not cover, and what a
    server MOUNTS is wider than what the registry DECLARES - the search server
    also serves index-rebuild and index-clean verbs beside its three declared
    reads. Approving the uncovered call, which is what the non-kimi lanes did,
    made the declared surface advisory and every unadvertised verb reachable.
    """
    canonical = _canonical_tool_identity(name, config)
    allowed = (
        set(config.allowed_tools)
        | {_strip_mcp_prefix(tool) for tool in config.allowed_tools}
        | _native_read_tools(config)
    )
    if canonical in allowed:
        return _approval_option_id(options)
    return _rejection_option_id(options)


# Tool-call argument keys that name a project to operate on. The search tools a
# run is handed take their root this way - ``project_root`` on every
# vaultspec-rag tool - which is how a scope escape arrives as an ARGUMENT that no
# per-server trust assertion can express. Both the snake_case and camelCase
# spellings are listed because the argument crosses a JSON boundary where either
# convention is admissible.
_PROJECT_ARGUMENT_KEYS: frozenset[str] = frozenset(
    {"project_root", "projectRoot", "workspace_root", "workspaceRoot"}
)

# Depth bound for the argument scan. Tool inputs are flat in practice (the search
# adapter exposes a deliberately flat schema), so this exists only so untrusted,
# deeply nested input cannot turn a permission decision into a recursion.
_MAX_ARGUMENT_SCAN_DEPTH = 6


def _foreign_project_argument(args: JsonObject, config: AcpModelConfig) -> str | None:
    """Return the first argument naming a project outside the run's, or ``None``.

    The escape this closes is argument-borne: the run's grounding tools resolve a
    caller-supplied root against any enrolled workspace on the machine, so a call
    the registry considers entirely read-only and entirely local still returns
    another project's content. The trust boundary is therefore the call, and this
    is where calls already pass.

    A named project that is not the run's is REPORTED, not corrected. Rewriting
    the argument to the bound project would answer a different question than the
    agent asked and hide that it asked it.
    """

    def scan(value: JsonValue, depth: int) -> str | None:
        if depth > _MAX_ARGUMENT_SCAN_DEPTH:
            return None
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key in _PROJECT_ARGUMENT_KEYS
                    and isinstance(item, str)
                    and item.strip()
                    and not config.binds_project_path(item.strip())
                ):
                    return item
                if (found := scan(item, depth + 1)) is not None:
                    return found
            return None
        if isinstance(value, list):
            for item in value:
                if (found := scan(item, depth + 1)) is not None:
                    return found
        return None

    return scan(args, 0)


async def on_request_permission(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle session/request_permission RPC."""
    options = _json_object_list(params.get("options"))
    tool_call = _json_object(params.get("toolCall"))
    name_value = tool_call.get("title")
    name = name_value if isinstance(name_value, str) else "unknown"
    args = _json_object(tool_call.get("rawInput"))

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
    if _foreign_project_argument(args, config) is not None:
        logger.warning(
            "Refused cross-project tool call: tool=%s named a project outside "
            "the run's bound project (bound=%s)",
            name,
            config.bound_project_root(),
        )
        deny_id = _denial_option_id(options)
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"outcome": {"optionId": deny_id, "outcome": "selected"}},
        }

    if config.permission_callback:
        try:
            option_id = await config.permission_callback(name, args, options)
        except GraphBubbleUp as exc:
            ctx.interrupt_exc.append(exc)
            try:
                ctx.chunk_queue.put_nowait(None)
            except asyncio.QueueFull:
                logger.warning("Chunk queue full — dropping interrupt sentinel")
            # H9 fix: return a proper JSON-RPC denial response instead of
            # an empty dict `{}` which would produce a malformed frame.
            deny_id = _denial_option_id(options)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"outcome": {"optionId": deny_id, "outcome": "selected"}},
            }
        except Exception:
            logger.exception(
                "Permission callback raised; denying permission (fail-closed)"
            )
            # TOAD reference pattern: return a denial outcome (not a JSON-RPC
            # error) so the ACP subprocess can cleanly decline the tool call.
            deny_id = _denial_option_id(options)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"outcome": {"optionId": deny_id, "outcome": "selected"}},
            }
    else:
        # Autonomous: no permission_callback means no human rung, on ANY lane.
        # Under autonomy the worker leaves the callback unset, so every
        # permission request the CLI raises - and a request is raised only for a
        # call the CLI's own static pre-approval did not cover - is decided here.
        # This used to fork: kimi enforced an exact-name read allowlist because
        # its CLI carries no config allowlist, and every other lane approved the
        # first offered option unconditionally, which approved an uncovered
        # mutating call exactly like a read. One rule now covers all of them.
        option_id = _autonomous_option_id(name, config, options)

    # M17: validate that option_id is among the offered options before returning.
    # Reject a callback-supplied id that is not in the options list to prevent
    # sending an invalid response to the ACP subprocess. The valid set is built
    # by the canonical predicate, so an option dict missing its id contributes
    # nothing instead of admitting ``None`` as a "valid" answer.
    valid_ids = valid_option_ids(options)
    if valid_ids and option_id not in valid_ids:
        logger.warning(
            "Permission callback returned option_id=%r not in valid options %r; "
            "falling back to first option",
            option_id,
            sorted(valid_ids),
        )
        option_id = _first_offered_option_id(options, default=option_id)

    logger.info("ACP permission decision: tool=%s option=%s", name, option_id)
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {"outcome": {"optionId": option_id, "outcome": "selected"}},
    }


async def on_fs_read_text_file(
    rpc_id: AcpRpcId,
    params: JsonObject,
    _ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle fs/read_text_file RPC.

    Supports optional ``offset`` (byte offset) and ``limit`` (byte count)
    params for partial reads, avoiding loading entire large files into memory.
    Uses asyncio.to_thread so blocking I/O does not stall the event loop.
    """
    try:
        file_path = sandbox_path(_required_string(params, "path"), config)
        offset = _integer(params.get("offset") or 0, field="offset")
        limit: int | None = (
            _integer(params["limit"], field="limit")
            if params.get("limit") is not None
            else None
        )

        # Cap reads at _FS_READ_MAX_BYTES.  When the caller also
        # supplies a limit, honour whichever is smaller.
        effective_limit = settings.acp_fs_read_max_bytes
        if limit is not None:
            effective_limit = min(limit, settings.acp_fs_read_max_bytes)

        def _read() -> str:
            with file_path.open(encoding="utf-8", errors="ignore") as fh:
                if offset:
                    fh.seek(offset)
                return fh.read(effective_limit)

        text = await asyncio.to_thread(_read)
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
    _ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle fs/write_text_file RPC.

    Acquires the global git mutex before writing to prevent races with
    concurrent git operations. Uses asyncio.to_thread so
    blocking I/O does not stall the event loop.
    """
    from ..workspace.concurrency import git_workspace_mutex

    try:
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

        def _write() -> None:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        async with git_workspace_mutex:
            await asyncio.to_thread(_write)
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": str(exc)},
        }


async def on_terminal_create(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/create RPC.

    Validates that the working directory is within the sandbox, logs
    the command for audit purposes, then spawns the subprocess.
    Passes optional ``env`` overrides from params on top of the current
    environment so the subprocess inherits PATH and other required vars.
    """
    try:
        command = _required_string(params, "command")
        raw_args = params.get("args")
        if raw_args is None:
            args: list[str] = []
        elif isinstance(raw_args, list):
            args = [argument for argument in raw_args if isinstance(argument, str)]
            if len(args) != len(raw_args):
                raise ValueError("ACP field 'args' must be a list of strings")
        else:
            raise ValueError("ACP field 'args' must be a list of strings")

        # --- Security: command allowlist validation (C4) ----------------
        # Extract the base name without directory path and .exe suffix so
        # that both "python" and "/usr/bin/python3.13" resolve the same.
        cmd_base = Path(command).stem.lower()
        if cmd_base not in _TERMINAL_COMMAND_ALLOWLIST:
            raise ValueError(
                f"Command {command!r} is not in the terminal allowlist. "
                f"Permitted executables: {sorted(_TERMINAL_COMMAND_ALLOWLIST)}"
            )
        # Reject shell metacharacters in the command or any argument.
        for token in [command, *args]:
            if _SHELL_METACHAR_RE.search(str(token)):
                raise ValueError(
                    f"Shell metacharacter detected in terminal token {token!r}. "
                    "Command injection attempt rejected."
                )
        # ----------------------------------------------------------------

        # Sandbox the terminal cwd: must be within the agent workspace root.
        requested_cwd = params.get("cwd")
        raw_cwd = (
            requested_cwd
            if isinstance(requested_cwd, str) and requested_cwd
            else str(
                require_workspace_root(
                    config.workspace_root, surface="agent terminal cwd"
                )
            )
        )
        sandbox_root = require_workspace_root(
            config.workspace_root, surface="agent terminal sandbox root"
        ).resolve()
        resolved_cwd = Path(raw_cwd).resolve()
        if not resolved_cwd.is_relative_to(sandbox_root):
            raise ValueError(
                f"Terminal cwd {raw_cwd!r} escapes sandbox root {sandbox_root}"
            )

        # Audit log for all terminal commands
        logger.info(
            "terminal/create: command=%r args=%r cwd=%s",
            command,
            args,
            resolved_cwd,
        )

        # Build env: use resolve_env_vars() to scrub API credentials,
        # then apply any agent-supplied overrides from the RPC params.
        terminal_env = resolve_env_vars(resolved_cwd)
        if extra_env := params.get("env"):
            if isinstance(extra_env, list):
                # ACP protocol: env is list[EnvVariable] with name/value keys
                # Validate env variable names before applying
                env_entries = _json_object_list(extra_env)
                if len(env_entries) != len(extra_env):
                    raise ValueError("ACP terminal env entries must be objects")
                validated_env: dict[str, str] = {}
                for entry in env_entries:
                    name = _required_string(entry, "name")
                    value = _required_string(entry, "value")
                    if not _ENV_NAME_RE.match(name):
                        raise ValueError(f"Invalid environment variable name: {name!r}")
                    validated_env[name] = value
                terminal_env.update(validated_env)
            elif isinstance(extra_env, dict):
                validated_env = {}
                for name, value in extra_env.items():
                    if not _ENV_NAME_RE.match(name):
                        raise ValueError(f"Invalid environment variable name: {name!r}")
                    if not isinstance(value, str):
                        raise ValueError(
                            f"ACP terminal env value for {name!r} must be a string"
                        )
                    validated_env[name] = value
                terminal_env.update(validated_env)
        # M12: on Windows, use CREATE_NEW_PROCESS_GROUP so child
        # processes don't become orphans when the terminal is killed.
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        # Seat the terminal child in its own OS containment before it runs, so the
        # whole terminal subtree (a shell and anything it spawns) is reaped as one
        # by `_kill_process_tree` - a POSIX process-group killpg escalation or a
        # Windows Job Object - not a per-pid kill that would orphan a POSIX shell's
        # grandchildren. Without this the terminal child carried no containment and
        # fell back to the single-pid POSIX path.
        containment = ProcessContainment.create()
        # The containment is an OS handle on Windows, allocated before the spawn
        # it contains. Everything from here to the point the terminal is
        # registered can raise - the spawn itself, an unexpected assignment
        # failure - and the outer handler converts any of it into an RPC error
        # the caller sees as a refused terminal. A refused terminal that left a
        # job handle open leaks one per attempt for the life of the session, so
        # the handle is released on the way out, along with any process that did
        # start (which nothing would otherwise reach: it is not yet in
        # ``ctx.terminals``, so terminal/release could never find it).
        try:
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(resolved_cwd),
                env=terminal_env,
                creationflags=creation_flags,
                **containment.spawn_kwargs(),
            )
        except BaseException:
            containment.close()
            raise
        try:
            try:
                containment.assign(process.pid)
            except ProcessContainmentError:
                logger.warning(
                    "Could not seat terminal child PID %d in its OS containment;"
                    " termination will fall back to a per-pid tree kill",
                    process.pid,
                    exc_info=True,
                )
            attach_process_containment(process, containment)
            terminal_id = uuid4().hex[:8]
            ctx.terminals[terminal_id] = process
        except BaseException:
            await containment.terminate(term_timeout=5.0, kill_timeout=5.0)
            raise
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"terminalId": terminal_id},
        }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": str(exc)},
        }


def _resolve_terminal(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
) -> tuple[asyncio.subprocess.Process | None, JsonObject]:
    """Resolve ``params["terminalId"]`` to its live process, or to the refusal.

    Returns ``(process, refusal)``: on a hit the live process and an empty
    refusal, on a miss ``None`` and the ready-to-send JSON-RPC response. The
    caller branches on the process being ``None`` - which is what narrows it for
    the type checker - and returns the refusal verbatim.

    The refusal is protocol error-MAPPING, not framework preamble: its code, its
    message wording and its envelope are all wire contract, so every handler that
    addresses a live terminal by id owes an unknown one the same answer. Built in
    one place, a correction to any part of that contract cannot land in two of the
    three handlers and miss the third. The code comes from the canonical
    :class:`AcpErrorCode` rather than a literal, so the wire value has a single
    definition across the ACP surface.

    ``terminal/release`` is deliberately NOT a caller: releasing a terminal that
    is already gone is idempotent success, not an invalid-params refusal.
    """
    terminal_id_value = params.get("terminalId")
    terminal_id = terminal_id_value if isinstance(terminal_id_value, str) else ""
    process = ctx.terminals.get(terminal_id)
    if process is not None:
        return process, {}
    return None, {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {
            "code": AcpErrorCode.INVALID_PARAMS,
            "message": f"Unknown terminal: {terminal_id}",
        },
    }


def _signal_name(signal_number: int) -> str:
    """Name the signal that killed a process, for the v1 string ``signal`` field.

    ACP v1 types ``signal`` as a STRING, not the raw number the OS reports, so a
    reader is not left decoding platform-specific integers. The number is
    resolved through the stdlib enum where the running platform defines it and
    falls back to the bare digits otherwise - Windows defines only a handful of
    ``Signals`` members, and an unmappable number is still better reported than
    turned into an error on a path describing how a process already died.
    """
    try:
        return signal.Signals(signal_number).name
    except ValueError:
        return str(signal_number)


def _exit_status(process: asyncio.subprocess.Process) -> JsonObject | None:
    """Build the ACP v1 ``TerminalExitStatus`` for a process, or ``None``.

    Returns ``None`` while the process is still running, which is what lets
    ``terminal/output`` omit the optional field rather than assert an exit that
    has not happened.

    The two fields are mutually exclusive by construction. POSIX reports a
    signal death as a NEGATIVE return code, which is not a valid ``exitCode``
    (the schema types it as an unsigned integer), so that case reports a null
    exit code beside the named signal; a normal exit reports the code beside a
    null signal. Emitting the negative number as an ``exitCode`` - the shape
    this replaces - told a reader the process exited with a code it never
    returned.
    """
    returncode = process.returncode
    if returncode is None:
        return None
    if returncode < 0:
        return {"exitCode": None, "signal": _signal_name(-returncode)}
    return {"exitCode": returncode, "signal": None}


async def on_terminal_kill(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/kill RPC.

    Kill stops the command; it does NOT release the terminal. The id stays
    registered in ``ctx.terminals`` so the agent can still collect the output it
    killed the command to inspect and read its exit status. Only
    ``terminal/release`` ends addressability - see :func:`on_terminal_release`.
    """
    process, refusal = _resolve_terminal(rpc_id, params, ctx)
    if process is None:
        return refusal
    await _kill_process_tree(process)
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}


async def on_terminal_output(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/output RPC."""
    process, refusal = _resolve_terminal(rpc_id, params, ctx)
    if process is None:
        return refusal
    stdout_data = b""
    stderr_data = b""
    if process.stdout:
        with suppress(TimeoutError):
            stdout_data = await asyncio.wait_for(
                process.stdout.read(65536), timeout=0.5
            )
    if process.stderr:
        with suppress(TimeoutError):
            stderr_data = await asyncio.wait_for(
                process.stderr.read(65536), timeout=0.5
            )
    output_result: JsonObject = {
        "output": stdout_data.decode("utf-8", errors="replace")
        + stderr_data.decode("utf-8", errors="replace"),
        "truncated": False,
    }
    # The optional exitStatus is present only once the command has completed,
    # and is the v1 status OBJECT rather than a bare return code.
    if (exit_status := _exit_status(process)) is not None:
        output_result["exitStatus"] = exit_status
    return {"jsonrpc": "2.0", "id": rpc_id, "result": output_result}


async def on_terminal_wait_for_exit(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/wait_for_exit RPC."""
    process, refusal = _resolve_terminal(rpc_id, params, ctx)
    if process is None:
        return refusal
    timeout = min(
        _number(params.get("timeout") or 60.0, field="timeout"), _MAX_TERMINAL_TIMEOUT
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": "Timeout waiting for exit"},
        }
    # The wait returned, so the process has exited and the status is never None;
    # the fallback keeps the response well-formed rather than raising on a path
    # that exists to report an outcome.
    exit_result = _exit_status(process) or {"exitCode": None, "signal": None}
    return {"jsonrpc": "2.0", "id": rpc_id, "result": exit_result}


async def on_terminal_release(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/release RPC."""
    terminal_id_value = params.get("terminalId")
    terminal_id = terminal_id_value if isinstance(terminal_id_value, str) else ""
    process = ctx.terminals.pop(terminal_id, None)
    if process is not None and process.returncode is None:
        await _kill_process_tree(process)
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
