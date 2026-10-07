"""Real ACP context fixtures for providers/tests/."""

import asyncio
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from .._acp_rpc_terminal_handlers import release_owned_terminal
from .._acp_types import AcpSessionContext
from .._factory_commands import claude_acp_entry

# ``claude_acp_entry()`` is install_root/node_modules/@agentclientprotocol/
# claude-agent-acp/dist/index.js; the package root one level above ``dist`` is
# what ``npm install`` places, and everything the Node ACP lane reads - the
# entry point itself, the adapter's own bundled source, its SDK dependency's
# type declarations - lives under it or beside it in the same install.

# Echoes each stdin line straight back on stdout, so a frame written to the
# child's stdin is readable from the same context's stdout.
_ECHO_CHILD = (
    "import sys\n"
    "for line in sys.stdin.buffer:\n"
    "    sys.stdout.buffer.write(line)\n"
    "    sys.stdout.buffer.flush()\n"
)


@pytest.fixture
def installed_acp_adapter() -> Path:
    """Fail up front, naming the missing package, when the Node lane isn't installed.

    A checkout that has never run ``npm install`` fails every test exercising the
    Node ACP adapter anyway - ``_classify_acp_command`` raises its own
    ``ConfigError`` a few frames into command resolution, and a test reading the
    adapter's shipped source directly hits a bare ``FileNotFoundError`` - but
    each lands at a different depth with a different shape. Requesting this
    fixture states the one shared cause before either point is reached, so a
    bare worktree's result reads as a missing prerequisite rather than a
    regression.
    """
    entry = claude_acp_entry()
    package_root = entry.parents[1]
    install_root = entry.parents[4]
    if not package_root.is_dir():
        pytest.fail(
            "missing prerequisite: @agentclientprotocol/claude-agent-acp is not "
            f"installed at {package_root}; run 'npm install' in "
            f"{install_root} to install it"
        )
    return package_root


@dataclass(frozen=True, slots=True)
class _AcpChildStreams:
    """The immutable, module-owned process fields shared by handler tests."""

    process: asyncio.subprocess.Process
    stdin: asyncio.StreamWriter
    stdout: asyncio.StreamReader


def _fresh_acp_session_context(child: _AcpChildStreams) -> AcpSessionContext:
    """Seat new mutable ACP state around one otherwise-idle real child."""

    return AcpSessionContext(
        process=child.process,
        stdin=child.stdin,
        stdout=child.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
        session_id="test-acp-session",
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def _acp_child_streams() -> AsyncIterator[_AcpChildStreams]:
    """Own one idle ACP-shaped child on the module fixture event loop."""

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.stdin.read()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        yield _AcpChildStreams(
            process=process,
            stdin=process.stdin,
            stdout=process.stdout,
        )
    finally:
        process.stdin.close()
        await process.stdin.wait_closed()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()


@pytest_asyncio.fixture
async def acp_session_context(
    _acp_child_streams: _AcpChildStreams,
) -> AsyncIterator[AcpSessionContext]:
    """Yield fresh per-test state over module-owned subprocess streams.

    Permission, filesystem, and terminal handler tests intentionally call the
    production handlers directly. Their otherwise-idle process fields remain
    real, but those fields are never read or written by these consumers, so one
    child can safely serve the module while every mutable session field remains
    function-scoped and loop-local.
    """
    context = _fresh_acp_session_context(_acp_child_streams)
    try:
        yield context
    finally:
        for terminal_id in tuple(context.terminals):
            await release_owned_terminal(terminal_id, context)


@pytest_asyncio.fixture
async def echo_context() -> AsyncIterator[AcpSessionContext]:
    """Yield a production context bound to a real echoing child process.

    The child writes every line it reads on stdin straight back on stdout, so a
    frame a production seam wrote is readable from the same context - a real pipe
    round-trip through a real process, and the seam under test is the production
    one. Shared here because both the session-configuration tests and the
    permission-posture tests drive session setup this way.
    """
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _ECHO_CHILD,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    context = AcpSessionContext(
        process=process,
        stdin=process.stdin,
        stdout=process.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
    )
    try:
        yield context
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()
