"""Core ACP JSON-RPC probe engine.

Exercises the full ACP protocol lifecycle against a subprocess:
    initialize -> session/new -> session/prompt -> session/update stream -> end_turn

Used for manual verification that ACP agents are reachable and responsive.
Each step is logged at DEBUG so that protocol issues are visible without any
additional configuration.
"""

import asyncio
import json
import logging
import os
import time

from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path


__all__ = ["ProbeResult", "run_probe"]

logger = logging.getLogger(__name__)


@dataclass
class ProbeResult:
    """Result of a single ACP probe run."""

    success: bool
    stop_reason: str | None = None
    text_chunks: list[str] = field(default_factory=list)
    error: str | None = None
    elapsed_ms: float = 0.0

    @property
    def full_text(self) -> str:
        """The assembled agent response text."""
        return "".join(self.text_chunks)


class _ProbeSession:
    """Internal state machine for the ACP probe."""

    def __init__(
        self,
        command: list[str],
        env: dict[str, str],
        timeout: float,
        prompt: str,
    ) -> None:
        self.command = command
        self.env = env
        self.timeout = timeout
        self.prompt = prompt
        self.result = ProbeResult(success=False)
        self.request_id = 0
        self.pending: dict[int, str] = {}
        self.session_id: str | None = None
        self.step = "initialize"
        self.t0 = time.monotonic()
        self.process: asyncio.subprocess.Process | None = None

    def send(self, method: str, params: dict) -> int:
        self.request_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params,
        }
        self.process.stdin.write(f"{json.dumps(req)}\n".encode())
        logger.debug("ACP TX [%d] -> %s", self.request_id, method)
        return self.request_id

    async def drain(self) -> None:
        await self.process.stdin.drain()

    async def handle_response(self, rid: int, src: str, msg: dict) -> bool:
        """Handle JSON-RPC response; return True if session complete."""
        error = msg.get("error")
        if error:
            self.result.error = f"[{rid}] {src}: {json.dumps(error)}"
            logger.error("ACP RX [%s] <- error from '%s': %s", rid, src, error)
            return True

        res = msg.get("result", {})
        logger.debug("ACP RX [%s] <- response ok from '%s'", rid, src)

        if self.step == "initialize":
            logger.info(
                "ACP initialized: caps=%s auth=%s",
                res.get("agentCapabilities", {}),
                [a.get("id") for a in res.get("authMethods", [])],
            )
            self.step = "session/new"
            sid = self.send("session/new", {"cwd": str(Path.cwd()), "mcpServers": []})
            self.pending[sid] = "session/new"
        elif self.step == "session/new":
            self.session_id = res.get("sessionId")
            logger.info("ACP session created: %s", self.session_id)
            self.step = "session/prompt"
            pid = self.send(
                "session/prompt",
                {
                    "sessionId": self.session_id,
                    "prompt": [{"type": "text", "text": self.prompt}],
                },
            )
            self.pending[pid] = "session/prompt"
        elif self.step == "session/prompt":
            self.result.success = True
            self.result.stop_reason = res.get("stopReason")
            logger.info(
                "ACP session/prompt complete: stopReason=%s",
                self.result.stop_reason,
            )
            return True
        return False

    async def handle_server_rpc(self, rid: int, method: str) -> None:
        resp = {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32601, "message": f"Not implemented: {method}"},
        }
        self.process.stdin.write(f"{json.dumps(resp)}\n".encode())
        await self.drain()
        logger.debug("ACP RX [%s] <- server RPC %s: rejected", rid, method)

    async def run_loop(self) -> None:
        self.pending[
            self.send(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "vaultspec-probe", "version": "1.0"},
                },
            )
        ] = "initialize"
        await self.drain()

        while True:
            line = await asyncio.wait_for(
                self.process.stdout.readline(), timeout=self.timeout
            )
            if not line:
                self.result.error = "EOF on stdout"
                return

            msg = json.loads(line.decode("utf-8", errors="replace"))
            rid = msg.get("id")
            method = msg.get("method", "")

            if "result" in msg or "error" in msg:
                if await self.handle_response(rid, self.pending.pop(rid, "?"), msg):
                    return
            elif method == "session/update":
                update = msg.get("params", {}).get("update", {})
                if update.get("sessionUpdate") == "agent_message_chunk":
                    chunk = update.get("content", {}).get("text", "")
                    if chunk:
                        self.result.text_chunks.append(chunk)
            elif rid is not None and method:
                await self.handle_server_rpc(rid, method)

    async def read_stderr(self) -> None:
        while line := await self.process.stderr.readline():
            if text := line.decode("utf-8", errors="replace").rstrip():
                logger.debug("ACP STDERR: %s", text)


async def run_probe(
    command: list[str],
    env_overrides: dict[str, str] | None = None,
    prompt: str = "Reply with only the single word 'Hello'.",
    timeout: float = 60.0,
) -> ProbeResult:
    """Run a full ACP protocol probe against the given subprocess command."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    env.pop("CLAUDECODE", None)

    session = _ProbeSession(command, env, timeout, prompt)
    session.process = await asyncio.create_subprocess_shell(
        " ".join(command),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        limit=10 * 1024 * 1024,
    )

    stderr_task = asyncio.create_task(session.read_stderr())
    try:
        await asyncio.wait_for(session.run_loop(), timeout=timeout)
    except TimeoutError:
        session.result.error = f"Timed out after {timeout}s"
    finally:
        stderr_task.cancel()
        with suppress(OSError):
            session.process.terminate()
        if getattr(session.process, "_transport", None):
            session.process._transport.close()  # noqa: SLF001
        with suppress(Exception):
            await asyncio.wait_for(session.process.wait(), timeout=5)

    session.result.elapsed_ms = (time.monotonic() - session.t0) * 1000
    return session.result
