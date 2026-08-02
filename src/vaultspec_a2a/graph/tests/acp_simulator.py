"""ACP Protocol Simulator for high-fidelity integration testing.

This script implements a minimal ACP-compliant agent that communicates via
JSON-RPC over stdin/stdout. It is used by integration tests as a real
subprocess to verify the full protocol lifecycle without hitting a live LLM.
"""

import argparse
import json
import os
import sys


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
            k: v for k, v in os.environ.items() if k.startswith("VAULTSPEC_AUTHORING_")
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


def main() -> None:
    """Run a minimal ACP protocol simulator for integration tests."""
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
    args = parser.parse_args()

    response_text = args.response
    if args.response_file:
        with open(args.response_file, encoding="utf-8") as fh:
            response_text = fh.read()

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        msg_id = req.get("id")

        if msg_id is None:
            continue

        if method == "initialize":
            if args.record_initialize:
                with open(args.record_initialize, "w", encoding="utf-8") as fh:
                    json.dump(req.get("params", {}), fh)
            if args.record_config_home:
                _record_config_home(args.record_config_home)
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "agentCapabilities": {"streaming": True},
                    "authMethods": [],
                },
            }
        elif method == "session/new":
            if args.record_session_new:
                with open(args.record_session_new, "w", encoding="utf-8") as fh:
                    json.dump(req.get("params", {}), fh)
            session_result: dict[str, object] = {"sessionId": args.session_id}
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
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": session_result,
            }
        elif method == "session/prompt":
            if args.record_session_prompt:
                with open(args.record_session_prompt, "w", encoding="utf-8") as fh:
                    json.dump(req.get("params", {}), fh)
            if args.error:
                error_body = {"code": args.error_code, "message": args.error}
                if args.error_kind:
                    error_body["data"] = {"errorKind": args.error_kind}
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": error_body,
                }
            else:
                # Send a chunk notification first
                update = {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": args.session_id,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"text": response_text},
                        },
                    },
                }
                sys.stdout.write(json.dumps(update) + "\n")
                sys.stdout.flush()

                # Then the result
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"stopReason": "end_turn"},
                }
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method {method} not implemented",
                },
            }

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
