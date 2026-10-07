"""The agent side of the Agent Client Protocol over stdio, and its wire frames.

Run as a script this is a minimal ACP v1 agent: a real subprocess that answers
``initialize``, ``session/new`` and ``session/prompt`` as JSON-RPC lines on stdin
and stdout, so a test drives the full protocol lifecycle without a live model.
Imported, it supplies the launch command for that subprocess, the frame builders
the agent writes with, and the reader a client-side test uses to pull one
response off an agent's stdout.

Only the standard library is imported at runtime. The agent is launched by path
and has to start without the package's settings stack, so the typing-only
imports below never execute.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..providers._json_contract import JsonObject, JsonValue

__all__ = [
    "ACP_SIMULATOR_PATH",
    "read_acp_frame",
    "request_permission_request",
    "simulator_command",
]

#: The file a test launches as the agent. Absolute, because a runtime identity
#: record names the adapter entry it was started from and refuses anything else.
ACP_SIMULATOR_PATH = Path(__file__).resolve()

_SEEN_FRAME_LIMIT = 500


def simulator_command(*args: str) -> list[str]:
    """Return the argv that starts the simulated agent with *args*."""
    return [sys.executable, str(ACP_SIMULATOR_PATH), *args]


# ---------------------------------------------------------------------------
# Wire frames
# ---------------------------------------------------------------------------


def _request(rpc_id: JsonValue, method: str, params: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


def _notification(method: str, params: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def _result(rpc_id: JsonValue, result: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _error(
    rpc_id: JsonValue, code: int, message: str, data: JsonObject | None = None
) -> JsonObject:
    error: JsonObject = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": error}


def _session_update(session_id: str, update: JsonObject) -> JsonObject:
    return _notification("session/update", {"sessionId": session_id, "update": update})


def request_permission_request(
    rpc_id: int | str, session_id: str, *, title: str = "Edit"
) -> JsonObject:
    """Build the agent's ``session/request_permission`` request for *session_id*.

    The request names the session it is asked for, and a client refuses one that
    does not name its active session, so the id is required rather than defaulted.
    """
    return _request(
        rpc_id,
        "session/request_permission",
        {
            "sessionId": session_id,
            "toolCall": {
                "toolCallId": "tool-call-1",
                "title": title,
                "kind": "edit",
                "status": "pending",
                "rawInput": {},
            },
            "options": [
                {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
            ],
        },
    )


async def read_acp_frame(
    stdout: asyncio.StreamReader, want_id: int, timeout: float, *, max_frames: int = 60
) -> JsonObject:
    """Return the first JSON-RPC frame from *stdout* whose ``id`` is *want_id*.

    Skips interleaved notifications and malformed lines. Raises
    ``AssertionError`` naming everything the stream carried if no matching frame
    arrives within *max_frames* lines or the stream closes first.
    """
    seen: list[str] = []
    for _ in range(max_frames):
        raw = await asyncio.wait_for(stdout.readline(), timeout=timeout)
        if not raw:
            break
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        seen.append(text[:_SEEN_FRAME_LIMIT])
        try:
            frame: JsonValue = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(frame, dict) and frame.get("id") == want_id:
            return frame
    raise AssertionError(f"no frame with id {want_id}; the stream carried {seen}")


# ---------------------------------------------------------------------------
# The simulated agent
# ---------------------------------------------------------------------------


def _record_config_home(path: str) -> None:
    """Dump the spawned subprocess's config surfaces and authoring env.

    Written for the real-seam composition tests: the subprocess reads its OWN
    ``CLAUDE_CONFIG_DIR`` (when one is set), its OWN cwd's projected
    ``.mcp.json`` and ``.claude/settings.local.json`` (what ``AcpChatModel``
    actually wrote into the run workspace), and its OWN environment (what the
    model hoisted into the spawn env), so a test can assert the placeholders
    live on disk while the real tokens live only in the process environment.
    """
    home = os.environ.get("CLAUDE_CONFIG_DIR")
    payload: dict[str, object] = {
        "config_home": home,
        "claude_json": None,
        "workspace_mcp_json": None,
        "workspace_settings_json": None,
        "authoring_env": {
            k: v
            for k, v in os.environ.items()
            if k.startswith("VAULTSPEC_A2A_AUTHORING_")
        },
    }
    if home:
        cfg = os.path.join(home, ".claude.json")
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8") as fh:
                payload["claude_json"] = fh.read()
    for key, relative in (
        ("workspace_mcp_json", ".mcp.json"),
        ("workspace_settings_json", os.path.join(".claude", "settings.local.json")),
    ):
        candidate = os.path.join(os.getcwd(), relative)
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as fh:
                payload[key] = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _record_params(path: str | None, req: JsonObject) -> None:
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(req.get("params", {}), fh)


# The permission modes a session advertises, copied from the pinned adapter's
# own session result (claude-agent-acp, SessionModeManager.buildAvailableModes)
# rather than invented: the ids, names and descriptions are what a real lane
# reports, and "default" is current because that is where a session with no
# ambient settings sources lands. A client pins an unattended run to a mode and
# verifies it against this list, so a simulator that reports nothing here is a
# lane whose permission posture cannot be established at all.
#
# This is the catalog of a session that has DECLINED the permission bypass
# capability, which is every session this project opens. A session that keeps
# it also reports "bypassPermissions"; none here does. The adapter withdrew
# "dontAsk" from the catalog while still accepting the spelling in its parser,
# so a simulator that advertised it would offer a mode no real lane will set.
_AVAILABLE_MODES: list[JsonObject] = [
    {
        "id": "default",
        "name": "Manual",
        "description": "Always ask before making changes",
    },
    {
        "id": "acceptEdits",
        "name": "Accept edits",
        "description": "Automatically accept all file edits",
    },
    {
        "id": "plan",
        "name": "Plan",
        "description": "Create a plan before making changes",
    },
    {
        "id": "auto",
        "name": "Auto",
        "description": "Claude handles permission decisions",
    },
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ACP Protocol Simulator")
    parser.add_argument(
        "--response", default="FINISH", help="Text to return in agent_message_chunk"
    )
    parser.add_argument(
        "--response-file",
        help="If set, read the agent_message_chunk text from this UTF-8 file "
        "instead of --response. Multi-line or shell-hostile agent prose cannot "
        "ride argv: the Windows spawn path goes through cmd.exe.",
    )
    parser.add_argument(
        "--session-id", default="sim-sess-123", help="Session ID to return"
    )
    parser.add_argument(
        "--advertise-model",
        action="append",
        default=None,
        metavar="MODEL_ID",
        help="Advertise a model selector on session/new, repeatable. The real "
        "adapter emits one unconditionally, and the served catalog builds its "
        "entries from it - so a simulator that returns only a sessionId cannot "
        "be reached through the gateway at all: with no catalog entry there is "
        "no selection to name, and run creation is refused before admission. "
        "Omitted by default, so every existing caller is unaffected.",
    )
    parser.add_argument(
        "--advertise-commands",
        nargs="*",
        default=None,
        metavar="NAME",
        help="After session/new, send an available_commands_update advertising "
        "these native commands. Given with no names it advertises an empty "
        "catalog, which is how an agent says it offers none; omitted, no update "
        "is sent at all.",
    )
    parser.add_argument(
        "--omit-modes",
        action="store_true",
        help="Answer session/new with no modes block. The pinned adapter always "
        "advertises its permission modes, so this is the shape of another agent "
        "speaking the same protocol - a lane whose permission posture an "
        "unattended run cannot pin or verify.",
    )
    parser.add_argument(
        "--expect-prompt",
        help="If set, refuse a session/prompt whose prompt is not exactly one "
        "text block carrying this text, with an invalid-params error.",
    )
    parser.add_argument(
        "--prompt-delay",
        type=float,
        default=0.0,
        help="Seconds to wait before answering session/prompt, so a second "
        "request can arrive while the first is still in flight.",
    )
    parser.add_argument(
        "--die-after-session",
        action="store_true",
        help="Once a session is open, answer the first session/prompt by writing "
        "the --stderr-file lines to stderr and exiting without a reply - the "
        "shape every startup failure and refused login takes on a real lane.",
    )
    parser.add_argument(
        "--stderr-file",
        help="UTF-8 file whose lines --die-after-session writes to stderr.",
    )
    parser.add_argument(
        "--error", help="If set, return this error message for session/prompt"
    )
    parser.add_argument(
        "--error-kind",
        help="If set with --error, attach this adapter error kind to the error "
        "frame's data. The real adapter puts a categorical kind there precisely "
        "so a client can dispatch on it, and it is the discriminator a condition "
        "is resolved from; without it a simulated refusal can only ever exercise "
        "the code fallback.",
    )
    parser.add_argument(
        "--error-code",
        type=int,
        default=-32000,
        help="JSON-RPC code for the --error frame. Defaults to the adapter's "
        "authentication-required code, which is what a bare --error has always "
        "returned.",
    )
    parser.add_argument(
        "--record-session-new",
        help="If set, write the received session/new params to this JSON file",
    )
    parser.add_argument(
        "--record-initialize",
        help="If set, write the received initialize params to this JSON file",
    )
    parser.add_argument(
        "--record-session-prompt",
        help="If set, write the received session/prompt params to this JSON file",
    )
    parser.add_argument(
        "--record-config-home",
        help="If set, dump the subprocess CLAUDE_CONFIG_DIR/.claude.json and "
        "authoring env to this JSON file on initialize",
    )
    return parser


def _response_text(args: argparse.Namespace) -> str:
    response_text = args.response
    if args.response_file:
        with open(args.response_file, encoding="utf-8") as fh:
            response_text = fh.read()
    return response_text


def _initialize_frames(
    args: argparse.Namespace, req: JsonObject, msg_id: JsonValue
) -> list[JsonObject]:
    _record_params(args.record_initialize, req)
    if args.record_config_home:
        _record_config_home(args.record_config_home)
    return [
        _result(
            msg_id,
            {
                "protocolVersion": 1,
                "agentInfo": {"name": "acp-simulator", "version": "1.0.0"},
                "agentCapabilities": {"loadSession": False},
                "authMethods": [],
            },
        )
    ]


def _available_command(name: str) -> JsonObject:
    return {
        "name": name,
        "description": f"Simulated {name} command.",
        "input": {"hint": "optional focus"},
    }


def _session_new_frames(
    args: argparse.Namespace, req: JsonObject, msg_id: JsonValue
) -> list[JsonObject]:
    _record_params(args.record_session_new, req)
    session_result: JsonObject = {"sessionId": args.session_id}
    if not args.omit_modes:
        session_result["modes"] = {
            "currentModeId": "default",
            "availableModes": [dict(mode) for mode in _AVAILABLE_MODES],
        }
    if args.advertise_model:
        # The real adapter's shape: one select whose category is "model",
        # carrying the ids it will accept. The catalog reads its entries
        # from exactly this, so the shape is copied rather than invented.
        session_result["configOptions"] = [
            {
                "id": "model",
                "category": "model",
                "type": "select",
                "currentValue": args.advertise_model[0],
                "options": [
                    {"value": model_id, "name": model_id}
                    for model_id in args.advertise_model
                ],
            }
        ]
    frames = [_result(msg_id, session_result)]
    if args.advertise_commands is not None:
        frames.append(
            _session_update(
                args.session_id,
                {
                    "sessionUpdate": "available_commands_update",
                    "availableCommands": [
                        _available_command(name) for name in args.advertise_commands
                    ],
                },
            )
        )
    return frames


def _die_after_session(args: argparse.Namespace) -> None:
    if args.stderr_file:
        with open(args.stderr_file, encoding="utf-8") as fh:
            for line in fh.read().splitlines():
                sys.stderr.write(line + "\n")
    sys.stderr.flush()
    raise SystemExit(0)


def _prompt_is_expected(args: argparse.Namespace, req: JsonObject) -> bool:
    params = req.get("params")
    prompt = params.get("prompt") if isinstance(params, dict) else None
    return prompt == [{"type": "text", "text": args.expect_prompt}]


def _session_prompt_frames(
    args: argparse.Namespace, req: JsonObject, msg_id: JsonValue, response_text: str
) -> list[JsonObject]:
    _record_params(args.record_session_prompt, req)
    if args.die_after_session:
        _die_after_session(args)
    if args.expect_prompt is not None and not _prompt_is_expected(args, req):
        return [_error(msg_id, -32602, "unexpected prompt")]
    if args.error:
        data: JsonObject | None = (
            {"errorKind": args.error_kind} if args.error_kind else None
        )
        return [_error(msg_id, args.error_code, args.error, data)]
    if args.prompt_delay:
        time.sleep(args.prompt_delay)
    return [
        _session_update(
            args.session_id,
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": response_text},
            },
        ),
        _result(msg_id, {"stopReason": "end_turn"}),
    ]


def _handle_request(
    args: argparse.Namespace, req: JsonObject, response_text: str
) -> list[JsonObject]:
    method = req.get("method")
    msg_id = req.get("id")

    if msg_id is None:
        return []
    if method == "initialize":
        return _initialize_frames(args, req, msg_id)
    if method == "session/new":
        return _session_new_frames(args, req, msg_id)
    if method == "session/prompt":
        return _session_prompt_frames(args, req, msg_id, response_text)
    return [_error(msg_id, -32601, f"Method {method} not implemented")]


def _serve_requests(args: argparse.Namespace, response_text: str) -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        for frame in _handle_request(args, req, response_text):
            sys.stdout.write(json.dumps(frame) + "\n")
            sys.stdout.flush()


def main() -> None:
    """Run the simulated agent until its stdin closes."""
    args = _build_parser().parse_args()
    _serve_requests(args, _response_text(args))


if __name__ == "__main__":
    main()
