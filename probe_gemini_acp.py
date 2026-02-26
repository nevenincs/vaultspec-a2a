"""
Minimal probe: sends ACP initialize, session/new, session/prompt to Gemini
and prints every raw line received on stdout. Used to diagnose what Gemini
actually sends back and when it stops.
"""

import asyncio
import json
import sys

from lib.providers.gemini_auth import refresh_gemini_token


async def probe():
    print("==> Refreshing Gemini OAuth token...", flush=True)
    refresh_gemini_token()
    print("==> Token OK. Spawning gemini --experimental-acp ...", flush=True)

    PIPE = asyncio.subprocess.PIPE
    process = await asyncio.create_subprocess_shell(
        "gemini --experimental-acp",
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
        limit=10 * 1024 * 1024,
    )

    assert process.stdin is not None
    assert process.stdout is not None

    request_id = 0

    def send(method: str, params: dict) -> int:
        nonlocal request_id
        request_id += 1
        req = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        body = json.dumps(req).encode("utf-8")
        process.stdin.write(b"%s\n" % body)
        print(f"  --> [{request_id}] {method} {json.dumps(params)[:120]}", flush=True)
        return request_id

    def send_notif(method: str, params: dict) -> None:
        req = {"jsonrpc": "2.0", "method": method, "params": params}
        body = json.dumps(req).encode("utf-8")
        process.stdin.write(b"%s\n" % body)
        print(f"  --> [notif] {method}", flush=True)

    # Step 1: initialize
    send("initialize", {
        "protocolVersion": 1,
        "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False},
            "terminal": False,
        },
        "clientInfo": {"name": "probe", "version": "0.1"},
    })
    await process.stdin.drain()

    session_id: str | None = None
    init_done = False

    async def read_all():
        nonlocal session_id, init_done
        assert process.stdout is not None
        while line := await process.stdout.readline():
            if not line.strip():
                continue
            try:
                text = line.decode("utf-8").rstrip()
            except Exception:
                print(f"  <-- [decode error] {line!r}", flush=True)
                continue

            try:
                data = json.loads(text)
            except Exception:
                print(f"  <-- [json error] {text[:200]}", flush=True)
                continue

            method = data.get("method", "")
            rid = data.get("id")
            result = data.get("result")
            error = data.get("error")

            if result is not None or error is not None:
                print(f"  <-- RESPONSE id={rid}: {json.dumps(data)[:300]}", flush=True)

                # If this is initialize response, send session/new
                if rid == 1 and not init_done:
                    init_done = True
                    send("session/new", {"cwd": ".", "mcpServers": []})
                    await process.stdin.drain()

                # If this is session/new response, extract sessionId and send prompt
                elif rid == 2 and result is not None:
                    session_id = result.get("sessionId")
                    print(f"==> Got session_id: {session_id}", flush=True)
                    if session_id:
                        send("session/prompt", {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": "Reply with the single word 'Hello'. No other text."}],
                        })
                        await process.stdin.drain()

                # If this is session/prompt response, we're done
                elif rid == 3 and result is not None:
                    stop_reason = result.get("stopReason")
                    print(f"==> session/prompt complete, stopReason={stop_reason}", flush=True)
                    return

            elif method:
                # Server-to-client RPC or notification
                params = data.get("params", {})
                if rid is not None:
                    # Server RPC — respond
                    print(f"  <-- SERVER RPC id={rid} method={method}: {json.dumps(params)[:200]}", flush=True)
                    # For now just ack unknown methods
                    resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Not handled: {method}"}}
                    process.stdin.write(b"%s\n" % json.dumps(resp).encode())
                    await process.stdin.drain()
                else:
                    # Notification
                    update = params.get("update", {})
                    update_type = update.get("sessionUpdate", "?")
                    content_text = update.get("content", {}).get("text", "") if isinstance(update.get("content"), dict) else ""
                    print(f"  <-- NOTIF method={method} type={update_type} text={content_text[:80]!r}", flush=True)
            else:
                print(f"  <-- UNKNOWN: {json.dumps(data)[:200]}", flush=True)

    try:
        await asyncio.wait_for(read_all(), timeout=60)
    except TimeoutError:
        print("==> TIMED OUT after 60s", flush=True)
    finally:
        try:
            process.terminate()
        except Exception:
            pass


asyncio.run(probe())
