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
import shutil
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from .._subprocess import kill_process_tree as _kill_process_tree
from .._subprocess import spawn_acp_process as _spawn_acp_process

__all__ = ["ProbeResult", "run_probe"]

logger = logging.getLogger(__name__)
_ACP_UNAUTHENTICATED_CODE = -32000


@dataclass
class ProbeResult:
    """Result of a single ACP probe run."""

    success: bool
    stop_reason: str | None = None
    text_chunks: list[str] = field(default_factory=list)
    error: str | None = None
    elapsed_ms: float = 0.0
    rate_limit_events: list[dict] = field(default_factory=list)

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
        auth_timeout: float = 900.0,
    ) -> None:
        self.command = command
        self.env = env
        self.timeout = timeout
        self.auth_timeout = auth_timeout
        self.prompt = prompt
        self.result = ProbeResult(success=False)
        self.request_id = 0
        self.pending: dict[int, str] = {}
        self.auth_methods: list[str] = []
        self.session_id: str | None = None
        self.step = "initialize"
        self.t0 = time.monotonic()
        self.process: asyncio.subprocess.Process | None = None
        self.stdin: asyncio.StreamWriter | None = None
        self.stdout: asyncio.StreamReader | None = None
        self.stderr: asyncio.StreamReader | None = None
        # PROV-H4: serialise stdin writes so concurrent handle_server_rpc()
        # and run_loop() calls cannot interleave JSON-RPC frames.
        self.stdin_lock = asyncio.Lock()

    def _current_step_timeout(self) -> float:
        """Return the watchdog timeout for the current ACP step."""
        if self.step == "authenticate":
            return self.auth_timeout
        return self.timeout

    async def send(self, method: str, params: dict) -> int:
        """Send a JSON-RPC request and drain the write buffer.

        H8: combined write+drain to prevent interleaved frames and ensure
        the data is flushed to the subprocess.
        PROV-H4: stdin_lock serialises concurrent writes.
        """
        self.request_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params,
        }
        if self.stdin is None:
            raise RuntimeError("send() called before process stdin was initialised")
        async with self.stdin_lock:
            self.stdin.write(f"{json.dumps(req)}\n".encode())
            await self.stdin.drain()
        logger.debug("ACP TX [%d] -> %s", self.request_id, method)
        return self.request_id

    def _select_auth_method_id(self) -> str:
        """Select the best advertised ACP auth method for the current env."""
        if not self.auth_methods:
            return "oauth"
        if self.env.get("GEMINI_API_KEY") and "gemini-api-key" in self.auth_methods:
            return "gemini-api-key"
        if (
            self.env.get("GOOGLE_GENAI_USE_VERTEXAI") == "true"
            or self.env.get("GOOGLE_APPLICATION_CREDENTIALS")
            or self.env.get("GOOGLE_API_KEY")
        ) and "vertex-ai" in self.auth_methods:
            return "vertex-ai"
        if (
            self.env.get("GOOGLE_GENAI_USE_GCA") == "true"
            or self.env.get("GEMINI_CLI_HOME")
        ) and "oauth-personal" in self.auth_methods:
            return "oauth-personal"
        return self.auth_methods[0]

    @staticmethod
    def _is_auth_required_error(error: object) -> bool:
        """Return True when the ACP error indicates auth is required."""
        if not isinstance(error, dict):
            return False
        err = cast("dict[str, Any]", error)
        message = str(err.get("message", "")).lower()
        return bool(
            err.get("code") == _ACP_UNAUTHENTICATED_CODE
            or "authrequired" in message
            or "authentication required" in message
            or "unauthenticated" in message
            or "not authenticated" in message
        )

    async def authenticate(self) -> int:
        """Send an ACP authenticate request using the advertised method."""
        method_id = self._select_auth_method_id()
        params: dict[str, object] = {"methodId": method_id}
        request_id = self.request_id + 1
        req: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "authenticate",
            "params": params,
        }
        api_key = self.env.get("GEMINI_API_KEY") or self.env.get("GOOGLE_API_KEY")
        if api_key and method_id in {"gemini-api-key", "vertex-ai"}:
            req["_meta"] = {"api-key": api_key}
        self.request_id = request_id
        if self.stdin is None:
            raise RuntimeError(
                "authenticate() called before process stdin was initialised"
            )
        async with self.stdin_lock:
            self.stdin.write(f"{json.dumps(req)}\n".encode())
            await self.stdin.drain()
        logger.debug("ACP TX [%d] -> authenticate", self.request_id)
        return request_id

    async def handle_response(self, rid: int, src: str, msg: dict) -> bool:
        """Handle JSON-RPC response; return True if session complete."""
        error = msg.get("error")
        if error:
            if (
                src == "session/new"
                and self.auth_methods
                and self._is_auth_required_error(error)
            ):
                logger.info(
                    "ACP session/new requires authenticate; retrying with %s",
                    self._select_auth_method_id(),
                )
                self.step = "authenticate"
                aid = await self.authenticate()
                self.pending[aid] = "authenticate"
                return False
            self.result.error = f"[{rid}] {src}: {json.dumps(error)}"
            logger.error("ACP RX [%s] <- error from '%s': %s", rid, src, error)
            return True

        res = msg.get("result", {})
        logger.debug("ACP RX [%s] <- response ok from '%s'", rid, src)

        if self.step == "initialize":
            self.auth_methods = [
                auth_method.get("id")
                for auth_method in res.get("authMethods", [])
                if isinstance(auth_method, dict)
                and isinstance(auth_method.get("id"), str)
            ]
            logger.info(
                "ACP initialized: caps=%s auth=%s",
                res.get("agentCapabilities", {}),
                self.auth_methods,
            )
            self.step = "session/new"
            sid = await self.send(
                "session/new", {"cwd": str(Path.cwd()), "mcpServers": []}
            )
            self.pending[sid] = "session/new"
        elif self.step == "authenticate":
            self.step = "session/new"
            sid = await self.send(
                "session/new", {"cwd": str(Path.cwd()), "mcpServers": []}
            )
            self.pending[sid] = "session/new"
        elif self.step == "session/new":
            self.session_id = res.get("sessionId")
            logger.info("ACP session created: %s", self.session_id)
            self.step = "session/prompt"
            pid = await self.send(
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

    async def send_response(self, response: dict) -> None:
        """Send a JSON-RPC response (reply to a server-initiated RPC).

        Routes all stdin writes through a single path with stdin_lock so
        concurrent handle_server_rpc() calls cannot interleave frames
        (PROV-H4, PROV-M5).
        """
        if self.stdin is None:
            raise RuntimeError(
                "send_response() called before process stdin was initialised"
            )
        async with self.stdin_lock:
            self.stdin.write(f"{json.dumps(response)}\n".encode())
            await self.stdin.drain()

    async def handle_server_rpc(self, rid: int, method: str) -> None:
        resp = {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32601, "message": f"Not implemented: {method}"},
        }
        await self.send_response(resp)
        logger.debug("ACP RX [%s] <- server RPC %s: rejected", rid, method)

    async def _heartbeat(self, interval: float = 10.0) -> None:
        """Log a heartbeat every *interval* seconds during long blocking steps.

        Helps diagnose the 60-second black hole during session/new startup by
        confirming the probe is alive and not silently stuck (PROBE-M1).
        """
        elapsed = 0.0
        while True:
            await asyncio.sleep(interval)
            elapsed += interval
            logger.info(
                "ACP probe waiting for '%s' response (%.0fs elapsed)…",
                self.step,
                elapsed,
            )

    async def run_loop(self) -> None:
        self.pending[
            await self.send(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                        # ACP-AUTH-002: required by claude-agent-acp ≥0.20.2
                        # gateway auth check (zed-industries/claude-agent-acp#380).
                        "_meta": {
                            "terminal-auth": True,
                            "terminal_output": True,
                        },
                    },
                    "clientInfo": {"name": "vaultspec-probe", "version": "1.0"},
                },
            )
        ] = "initialize"

        if self.stdout is None:
            raise RuntimeError("run_loop(): stdout not initialised")
        heartbeat_task = asyncio.create_task(self._heartbeat())
        try:
            while True:
                try:
                    line = await asyncio.wait_for(
                        self.stdout.readline(),
                        timeout=self._current_step_timeout(),
                    )
                except TimeoutError:
                    current_timeout = self._current_step_timeout()
                    self.result.error = (
                        f"Timed out after {current_timeout}s during {self.step}"
                    )
                    return
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
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def read_stderr(self) -> None:
        """Drain stderr, parsing rate_limit_event JSON lines.

        rate_limit_event objects emitted by the Claude SDK appear on stderr
        when ANTHROPIC_LOG=debug is set.  We parse them here so callers can
        inspect quota/overage state without needing a separate log scraper.

        Severity rules (PROBE-H1):
        - overageStatus == "blocked"   → mark probe failed + set error
        - overageStatus == "rejected"  → warn, keep going (soft throttle)
        - any other rate_limit_event   → debug only
        """
        if self.stderr is None:
            return
        while line := await self.stderr.readline():
            text = line.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue
            # Try to parse as JSON — rate_limit_event lines are JSON objects.
            parsed: dict | None = None
            if text.startswith("{"):
                with suppress(json.JSONDecodeError):
                    parsed = json.loads(text)
            if parsed is not None and parsed.get("type") == "rate_limit_event":
                self.result.rate_limit_events.append(parsed)
                overage = parsed.get("overageStatus", "")
                if overage == "blocked":
                    logger.error("ACP rate limit BLOCKED: quota exhausted — %s", parsed)
                    if not self.result.error:
                        self.result.error = (
                            f"rate_limit_event: overageStatus=blocked — {parsed}"
                        )
                    self.result.success = False
                elif overage == "rejected":
                    logger.warning(
                        "ACP rate limit REJECTED (soft throttle): %s", parsed
                    )
                else:
                    logger.debug("ACP rate_limit_event: %s", parsed)
            else:
                logger.debug("ACP STDERR: %s", text)


async def run_probe(
    command: list[str],
    env_overrides: dict[str, str] | None = None,
    prompt: str = "Reply with only the single word 'Hello'.",
    timeout: float = 120.0,
    auth_timeout: float = 900.0,
    *,
    debug: bool = False,
) -> ProbeResult:
    """Run a full ACP protocol probe against the given subprocess command.

    Args:
        command: Subprocess command to spawn (the ACP gateway binary).
        env_overrides: Additional environment variables to overlay.
        prompt: Prompt text to send to the agent.
        timeout: Step watchdog timeout in seconds for non-auth ACP steps.
        auth_timeout: Backstop timeout in seconds for interactive auth steps.
        debug: When True, sets ``ANTHROPIC_LOG=debug`` in the subprocess
            environment to enable verbose SDK output on stderr.  Useful for
            diagnosing the cold-start black hole during ``session/new``.
    """
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    # ACP-ENV-005: always scrub ANTHROPIC_LOG from the inherited environment first.
    # When set in the parent process, it causes the Anthropic SDK (inside the ACP
    # gateway) to emit debug text to stdout, corrupting the JSON-RPC stream and
    # triggering -32603 parse errors.  Re-inject only when debug=True was explicitly
    # requested by the caller.
    env.pop("ANTHROPIC_LOG", None)
    if debug:
        env["ANTHROPIC_LOG"] = "debug"
        logger.info("ACP probe running with ANTHROPIC_LOG=debug")
    # ADR-002 §2: strip ANTHROPIC_API_KEY when OAuth is active to prevent
    # claude-agent-acp from using pay-as-you-go billing.
    if "CLAUDE_CODE_OAUTH_TOKEN" in env:
        env.pop("ANTHROPIC_API_KEY", None)
    # ADR-002 §5.1: bypass bundled cli.js — use system
    # claude binary (native PE32+ Bun exe)
    _system_claude = shutil.which("claude")
    if "CLAUDE_CODE_OAUTH_TOKEN" in env and _system_claude:
        env["CLAUDE_CODE_EXECUTABLE"] = _system_claude
    env.pop("CLAUDECODE", None)
    # ACP-ENV-004: scrub all CLAUDE_CODE_* keys that are not explicitly
    # re-injected below, so that a nested probe subprocess does not inherit the
    # parent Claude Code session identity and trigger nested-session detection.
    # Allowlist: CLAUDE_CODE_OAUTH_TOKEN (auth) and CLAUDE_CODE_EXECUTABLE
    # (binary override) — both are set above from the resolved environment.
    _claude_code_allowlist = frozenset(
        {
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CODE_EXECUTABLE",
            "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        }
    )
    for _k in [
        k
        for k in env
        if k.startswith("CLAUDE_CODE_") and k not in _claude_code_allowlist
    ]:
        del env[_k]
    # ACP-ENV-006: suppress interactive prompts that stall
    # non-interactive ACP subprocesses.
    env["CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY"] = "1"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

    session = _ProbeSession(command, env, timeout, prompt, auth_timeout)
    session.process = await _spawn_acp_process(command, env, str(Path.cwd()))
    proc = session.process
    if proc.stdin is None or proc.stdout is None or proc.stderr is None:
        raise RuntimeError("ACP subprocess streams not available after spawn")
    session.stdin = proc.stdin
    session.stdout = proc.stdout
    session.stderr = proc.stderr

    stderr_task = asyncio.create_task(session.read_stderr())
    try:
        await session.run_loop()
    finally:
        stderr_task.cancel()
        await _kill_process_tree(session.process)

    session.result.elapsed_ms = (time.monotonic() - session.t0) * 1000
    return session.result
