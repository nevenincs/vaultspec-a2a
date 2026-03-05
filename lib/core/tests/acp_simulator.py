"""ACP Protocol Simulator for high-fidelity integration testing.

This script implements a minimal ACP-compliant agent that communicates via 
JSON-RPC over stdin/stdout. It is used by integration tests as a real 
subprocess to verify the full protocol lifecycle without hitting a live LLM.
"""

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="ACP Protocol Simulator")
    parser.add_argument("--response", default="FINISH", help="Text to return in agent_message_chunk")
    parser.add_argument("--session-id", default="sim-sess-123", help="Session ID to return")
    parser.add_argument("--error", help="If set, return this error message for session/prompt")
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
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "agentCapabilities": {"streaming": True},
                    "authMethods": [],
                },
            }
        elif method == "session/new":
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
                            "content": {"text": args.response}
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
                "error": {"code": -32601, "message": f"Method {method} not implemented"},
            }

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
