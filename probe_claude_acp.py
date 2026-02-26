"""
Raw ACP probe for claude-agent-acp.

Sends raw JSON-RPC over stdio and prints every line received verbatim.
No Python module wrappers -- purely subprocess + json to isolate protocol issues.
"""

import asyncio
import json
import os
import time
from pathlib import Path


def _load_token() -> str:
    env_file = Path(__file__).parent / ".env"
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        k, _, v = raw.partition("=")
        if k.strip() == "VAULTSPEC_CLAUDE_CODE_OAUTH_TOKEN" and v:
            return v.strip()
    raise RuntimeError("VAULTSPEC_CLAUDE_CODE_OAUTH_TOKEN not found in .env")


T0 = time.monotonic()


def log(msg: str) -> None:
    print(f"[+{time.monotonic()-T0:6.2f}s] {msg}", flush=True)


async def probe() -> None:
    token = _load_token()
    log(f"Token loaded ({len(token)} chars)")

    env = os.environ.copy()
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    env.pop("CLAUDECODE", None)  # Prevent nested-session guard from blocking us

    PIPE = asyncio.subprocess.PIPE
    proc = await asyncio.create_subprocess_shell(
        "claude-agent-acp",
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
        env=env,
        limit=10 * 1024 * 1024,
    )
    log(f"Process spawned pid={proc.pid}")

    request_id = 0

    def send(method: str, params: dict) -> int:
        nonlocal request_id
        request_id += 1
        req = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        proc.stdin.write(f"{json.dumps(req)}\n".encode("utf-8"))
        log(f"TX [{request_id}] {method}")
        return request_id

    async def flush() -> None:
        await proc.stdin.drain()

    # Drain stderr in background so it doesn't block the process
    async def read_stderr() -> None:
        while line := await proc.stderr.readline():
            log(f"STDERR | {line.decode('utf-8','replace').rstrip()}")

    stderr_task = asyncio.create_task(read_stderr())
    pending: dict[int, str] = {}
    session_id: str | None = None

    try:
        # --- Step 1: initialize ---
        iid = send("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False},
                "terminal": False,
            },
            "clientInfo": {"name": "probe", "version": "0.1"},
        })
        pending[iid] = "initialize"
        await flush()

        step = "initialize"
        log("Waiting for initialize response...")

        while True:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            if not raw:
                log("EOF on stdout")
                return

            text = raw.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue

            log(f"RX raw | {text[:300]}")

            try:
                msg = json.loads(text)
            except Exception as exc:
                log(f"JSON parse error: {exc}")
                continue

            rid = msg.get("id")
            method = msg.get("method", "")
            result = msg.get("result")
            error = msg.get("error")

            if result is not None or error is not None:
                src = pending.pop(rid, "?")
                if error:
                    log(f"RX [{rid}] ERROR from '{src}': {json.dumps(error)}")
                    log(f"PROBE FAILED at step={step}")
                    return

                log(f"RX [{rid}] ok from '{src}', keys={list(result) if isinstance(result, dict) else '?'}")

                if step == "initialize":
                    caps = result.get("agentCapabilities", {})
                    auth = [a.get("id") for a in result.get("authMethods", [])]
                    log(f"  caps: {json.dumps(caps)}")
                    log(f"  auth: {auth}")
                    step = "session/new"

                    sid = send("session/new", {
                        "cwd": str(Path.cwd()),
                        "mcpServers": [],
                    })
                    pending[sid] = "session/new"
                    await flush()
                    log("Waiting for session/new response...")

                elif step == "session/new":
                    session_id = result.get("sessionId")
                    log(f"  sessionId: {session_id}")
                    step = "session/prompt"

                    pid = send("session/prompt", {
                        "sessionId": session_id,
                        "prompt": [{"type": "text", "text": "Reply with only the single word 'Hello'."}],
                    })
                    pending[pid] = "session/prompt"
                    await flush()
                    log("Waiting for session/prompt response...")

                elif step == "session/prompt":
                    stop = result.get("stopReason")
                    log(f"  stopReason: {stop}")
                    log("PROBE PASSED")
                    return

            elif method:
                params = msg.get("params", {})
                if rid is not None:
                    log(f"RX [{rid}] server RPC: {method} -- responding method_not_found")
                    resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Not implemented: {method}"}}
                    proc.stdin.write(f"{json.dumps(resp)}\n".encode("utf-8"))
                    await flush()
                else:
                    if method == "session/update":
                        upd = params.get("update", {})
                        utype = upd.get("sessionUpdate", "?")
                        preview = ""
                        c = upd.get("content", {})
                        if isinstance(c, dict):
                            preview = repr(c.get("text", "")[:80])
                        log(f"RX notif session/update type={utype} text={preview}")
                    else:
                        log(f"RX notif {method}")

    except TimeoutError:
        log(f"TIMED OUT waiting at step={step}")
    finally:
        stderr_task.cancel()
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3)
        except Exception:
            pass


asyncio.run(probe())
