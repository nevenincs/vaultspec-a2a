"""The CLI resolves this lane's permission rules the way the lane writes them.

A permission rule is a string handed to another program, so its meaning is that
program's to decide. The rules here are therefore driven through the installed
Claude CLI itself: a real binary, run against a real local endpoint speaking the
Anthropic messages API, asked for one real ``Read`` tool call. What is asserted
is the tool result the CLI sent back - the file's contents when the rule
admitted the read, and a refusal when it did not.

The endpoint is scripted rather than a model: this is a test of the CLI's
permission matcher, and a real model would make the one thing under test
(whether a named path is read) depend on what the model decided to do.

The contrast each test draws is between the spelling the lane writes and the
spelling it used to write. The CLI reads a single leading slash as relative to
the session's primary working directory, so a rule that LOOKS like an absolute
path names a directory beneath the workspace, and the rule matches nothing at
the path it appears to name.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from ...graph.enums import Provider
from .._claude_tool_policy import claude_rule_path, workspace_scoped_tool_rule
from ..cli_resolution import resolve_provider_cli_executable

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule
    from .._json_contract import JsonObject

_SECRET = "the-file-the-rule-decides-about"
_CLI_TIMEOUT_SECONDS = 120.0
_TOOL_USE_ID = "toolu_rule_probe"


@dataclass(slots=True)
class _Turn:
    """One scripted turn: read this path, and keep what the CLI answered."""

    read_path: Path
    tool_results: list[JsonObject] = field(default_factory=list)


def _sse(event: str, payload: JsonObject) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


def _message(identifier: str) -> JsonObject:
    return {
        "id": identifier,
        "type": "message",
        "role": "assistant",
        "model": "claude-rule-probe",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _tool_call_stream(read_path: Path) -> list[bytes]:
    """The frames that ask for one ``Read`` of *read_path* and stop there."""
    return [
        _sse("message_start", {"type": "message_start", "message": _message("msg-1")}),
        _sse(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": _TOOL_USE_ID,
                    "name": "Read",
                    "input": {},
                },
            },
        ),
        _sse(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": json.dumps({"file_path": str(read_path)}),
                },
            },
        ),
        _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
        ),
        _sse("message_stop", {"type": "message_stop"}),
    ]


def _closing_stream() -> list[bytes]:
    """The frames that end the turn once the tool result has been received."""
    return [
        _sse("message_start", {"type": "message_start", "message": _message("msg-2")}),
        _sse(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        _sse(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "done"},
            },
        ),
        _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
        ),
        _sse("message_stop", {"type": "message_stop"}),
    ]


def _tool_results_in(body: JsonObject) -> list[JsonObject]:
    """Return every tool result the CLI reported in one request body."""
    found: list[JsonObject] = []
    messages = body.get("messages")
    for message in messages if isinstance(messages, list) else []:
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                found.append(block)
    return found


def _handler_for(turn: _Turn) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            """Keep the endpoint silent; the test reports what matters."""
            del format, args

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length)
            if not self.path.startswith("/v1/messages"):
                self.send_error(404)
                return
            body = json.loads(raw or b"{}")
            results = _tool_results_in(body)
            turn.tool_results.extend(results)
            frames = _closing_stream() if results else _tool_call_stream(turn.read_path)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            # Chunked, as a streaming endpoint answers: with a kept-alive
            # connection and no framing the client cannot tell the body ended.
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            for frame in frames:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(frame), frame))
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

    return _Handler


@contextmanager
def _scripted_endpoint(read_path: Path) -> Iterator[tuple[str, _Turn]]:
    """Serve the scripted turn on a real loopback socket for one CLI run."""
    turn = _Turn(read_path=read_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(turn))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", turn
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _child_environment(home: Path, base_url: str) -> dict[str, str]:
    """The environment the CLI runs under: this endpoint, and nobody's home."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
    env["ANTHROPIC_BASE_URL"] = base_url
    env["ANTHROPIC_API_KEY"] = "rule-probe"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    # The endpoint is on this machine, so no proxy may stand between them.
    for proxy in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(proxy, None)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    return env


def _read_under_rules(
    *,
    cli: str,
    workspace: Path,
    home: Path,
    target: Path,
    allowed: str,
    denied: str | None = None,
) -> JsonObject:
    """Return the tool result the real CLI produced for one Read under *allowed*."""
    with _scripted_endpoint(target) as (base_url, turn):
        command = [
            cli,
            "--print",
            "--bare",
            "--permission-mode",
            "default",
            "--allowedTools",
            allowed,
        ]
        if denied is not None:
            command += ["--disallowedTools", denied]
        # The rule flags are variadic, so a flag has to close the list before
        # the prompt - otherwise the prompt is read as one more rule and the
        # CLI exits saying it was given no input at all.
        command += ["--model", "claude-rule-probe"]
        completed = subprocess.run(
            [*command, "read the file"],
            cwd=str(workspace),
            env=_child_environment(home, base_url),
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_SECONDS,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr
    assert len(turn.tool_results) == 1, turn.tool_results
    return turn.tool_results[0]


def _answered(result: JsonObject) -> str:
    return str(result.get("content"))


@pytest.fixture
def claude_cli(external_prerequisite: ExternalPrerequisiteRule) -> str:
    """The CLI this service resolves, or a named missing prerequisite."""
    executable = resolve_provider_cli_executable(Provider.CLAUDE)
    if executable is None:
        external_prerequisite.absent(
            "claude-cli",
            "the permission matcher under test belongs to the CLI, so there is "
            "nothing to drive the rules against",
        )
    return executable


@pytest.fixture
def probe_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A workspace, an isolated home, and one real file outside the workspace."""
    workspace = tmp_path / "project"
    home = tmp_path / "home"
    elsewhere = tmp_path / "elsewhere"
    for directory in (workspace, home, elsewhere):
        directory.mkdir()
    target = elsewhere / "target.txt"
    target.write_text(f"{_SECRET}\n", encoding="utf-8")
    return workspace, home, target


def test_the_scope_rule_this_lane_writes_admits_the_path_it_names(
    claude_cli: str, probe_paths: tuple[Path, Path, Path]
) -> None:
    """The rendered workspace scope is a grant the CLI actually resolves."""
    workspace, home, target = probe_paths

    granted = _read_under_rules(
        cli=claude_cli,
        workspace=workspace,
        home=home,
        target=target,
        allowed=workspace_scoped_tool_rule("Read", str(target.parent)),
    )

    assert _SECRET in _answered(granted)
    assert granted.get("is_error") is not True


def test_a_single_slash_scope_rule_admits_nothing_at_the_path_it_names(
    claude_cli: str, probe_paths: tuple[Path, Path, Path]
) -> None:
    """The spelling this lane used to write grants nothing, and says so silently.

    Same run, same path, one slash fewer. The rule is accepted, the read is
    refused, and nothing anywhere reports that the grant named a directory
    under the workspace instead of the one in the rule.
    """
    workspace, home, target = probe_paths

    refused = _read_under_rules(
        cli=claude_cli,
        workspace=workspace,
        home=home,
        target=target,
        allowed=f"Read({target.parent.as_posix()}/**)",
    )

    assert _SECRET not in _answered(refused)
    assert refused.get("is_error") is True


def test_the_deny_spelling_this_lane_writes_blocks_a_granted_read(
    claude_cli: str, probe_paths: tuple[Path, Path, Path]
) -> None:
    """A deny rendered by the lane beats an allow over the same absolute path.

    The allow is proven live in this same test before the deny is added, so
    the refusal can only be the deny: a run where the allow silently matched
    nothing would refuse the read too, and would look identical.
    """
    workspace, home, target = probe_paths
    scope = workspace_scoped_tool_rule("Read", str(target.parent))

    granted = _read_under_rules(
        cli=claude_cli, workspace=workspace, home=home, target=target, allowed=scope
    )
    blocked = _read_under_rules(
        cli=claude_cli,
        workspace=workspace,
        home=home,
        target=target,
        allowed=scope,
        denied=f"Read({claude_rule_path(str(target))})",
    )

    assert _SECRET in _answered(granted)
    assert _SECRET not in _answered(blocked)
    assert blocked.get("is_error") is True


def test_a_single_slash_deny_rule_blocks_nothing_at_the_path_it_names(
    claude_cli: str, probe_paths: tuple[Path, Path, Path]
) -> None:
    """The spelling the deny list used to carry is a deny that never fires.

    This is the same shape the credential and process-tree denies were written
    in, which is why they are rendered through one anchor with the scope rule:
    a deny that misses reads exactly like a deny that holds.
    """
    workspace, home, target = probe_paths

    not_blocked = _read_under_rules(
        cli=claude_cli,
        workspace=workspace,
        home=home,
        target=target,
        allowed=workspace_scoped_tool_rule("Read", str(target.parent)),
        denied=f"Read({target.as_posix()})",
    )

    assert _SECRET in _answered(not_blocked)
