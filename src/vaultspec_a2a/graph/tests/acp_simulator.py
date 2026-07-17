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
    """Dump the spawned subprocess's isolated CLI home and authoring env.

    Written for the S18 real-seam composition test: the subprocess reads its OWN
    ``CLAUDE_CONFIG_DIR`` (what ``AcpChatModel`` actually wrote to disk) and its
    OWN environment (what the model hoisted into the spawn env), so a test can
    assert the placeholders live on disk while the real tokens live only in the
    process environment.
    """
    home = os.environ.get("CLAUDE_CONFIG_DIR")
    payload: dict[str, object] = {
        "config_home": home,
        "claude_json": None,
        "authoring_env": {
            k: v for k, v in os.environ.items() if k.startswith("VAULTSPEC_AUTHORING_")
        },
    }
    if home:
        cfg = os.path.join(home, ".claude.json")
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8") as fh:
                payload["claude_json"] = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def main() -> None:
    """Run a minimal ACP protocol simulator for integration tests."""
    parser = argparse.ArgumentParser(description="ACP Protocol Simulator")
    parser.add_argument(
        "--response", default="FINISH", help="Text to return in agent_message_chunk"
    )
    parser.add_argument(
        "--session-id", default="sim-sess-123", help="Session ID to return"
    )
    parser.add_argument(
        "--error", help="If set, return this error message for session/prompt"
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
        "--record-config-home",
        help="If set, dump the subprocess CLAUDE_CONFIG_DIR/.claude.json and "
        "authoring env to this JSON file on initialize",
    )
    args = parser.parse_args()

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
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"sessionId": args.session_id},
            }
        elif method == "session/prompt":
            if args.error:
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32000, "message": args.error},
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
                            "content": {"text": args.response},
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
