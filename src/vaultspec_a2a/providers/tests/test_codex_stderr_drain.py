"""Codex standard error must be drained continuously and retained redacted.

An undrained pipe is a hang, not merely lost diagnostics: the operating system
buffer fills and the child blocks on its next write. The subprocess helper opens
stderr as a pipe, so something has to read it for the whole session.

What is retained is bounded and redacted, because provider subprocesses report
their configuration when they fail and configuration is where credentials live.
"""

from __future__ import annotations

import asyncio
import sys
from collections import deque

import pytest

from ..codex_chat_model import (
    CLEANUP_TIMEOUT_SECONDS,
    STDERR_TAIL_LINES,
    drain_stderr_into,
)


async def _drain_lines(lines: list[bytes]) -> list[str]:
    """Drive the real drain against a real stream fed with real bytes."""
    reader = asyncio.StreamReader()
    for line in lines:
        reader.feed_data(line)
    reader.feed_eof()
    tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)

    await drain_stderr_into(reader, tail)

    return list(tail)


def test_an_absent_stream_is_tolerated() -> None:
    """A child without a stderr pipe must not fail the session."""
    tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)

    asyncio.run(drain_stderr_into(None, tail))

    assert not tail


def test_drained_lines_are_retained_redacted() -> None:
    """The drain reads real bytes off a real stream and redacts what it keeps."""
    kept = asyncio.run(
        _drain_lines([b"starting\n", b"API_KEY=supersecret\n", b"ready\n"])
    )

    assert kept[0] == "starting"
    assert "supersecret" not in kept[1]
    assert kept[2] == "ready"


@pytest.mark.parametrize(
    ("line", "must_not_contain"),
    [
        ("ANTHROPIC_AUTH_TOKEN=sk-ant-secret", "sk-ant-secret"),
        ("Authorization: Bearer sk-live-9f8e7d", "sk-live-9f8e7d"),
        ("OPENAI_API_KEY: sk-proj-zzz", "sk-proj-zzz"),
        ("my_password = hunter2", "hunter2"),
        ("VAULTSPEC_A2A_GATEWAY_TOKEN=abc123", "abc123"),
    ],
)
def test_credential_shapes_are_masked_on_the_way_into_the_tail(
    line: str, must_not_contain: str
) -> None:
    """Every shape is masked BY THE DRAIN, not merely by a helper it could drop.

    Asserted through the retained tail rather than against the redactor itself:
    the redactor now lives in a shared home with its own tests, so a check there
    would keep passing if this lane stopped calling it.
    """
    (kept,) = asyncio.run(_drain_lines([line.encode() + b"\n"]))

    assert must_not_contain not in kept
    assert "<redacted>" in kept


@pytest.mark.parametrize(
    "line",
    [
        "connecting to 127.0.0.1:8766",
        "error: failed to start app-server",
        "plain diagnostic line with no secret",
    ],
)
def test_ordinary_diagnostics_survive_the_drain_untouched(line: str) -> None:
    """Over-redaction would destroy the value the buffer exists to provide."""
    assert asyncio.run(_drain_lines([line.encode() + b"\n"])) == [line]


def test_the_retained_tail_is_bounded() -> None:
    """A chatty child must not grow the buffer without limit."""
    noisy = [f"line-{index}\n".encode() for index in range(STDERR_TAIL_LINES + 50)]

    kept = asyncio.run(_drain_lines(noisy))

    assert len(kept) == STDERR_TAIL_LINES
    assert kept[-1] == f"line-{STDERR_TAIL_LINES + 49}"


def test_the_cleanup_deadline_is_bounded_and_positive() -> None:
    """A zero or absent deadline would reintroduce the unbounded wait.

    The stronger property - that close abandons a task which ignores
    cancellation - is deliberately not asserted here. Constructing a genuinely
    uncancellable task to prove it leaves that task alive, and the loop shutdown
    at the end of the test then blocks on it: the test hangs the suite while
    proving the code does not hang. Verifying it needs a subprocess that can be
    killed, which is a live-process test rather than a unit one.
    """
    assert 0 < CLEANUP_TIMEOUT_SECONDS <= 30


@pytest.mark.asyncio
async def test_drain_relieves_a_real_subprocess_stderr_backpressure() -> None:
    """A real child flooding stderr past the OS pipe buffer exits only because the
    drain consumes it concurrently.

    This is the live-process backpressure property the in-memory drains above
    cannot exercise: feeding a StreamReader never fills an OS pipe. The child
    writes far more than any pipe buffer and then exits; without a concurrent
    reader it would block on the overflowing write and never reach exit, so the
    gather would blow the deadline. Its clean completion IS the proof the drain
    relieved the backpressure - not merely that some bytes were read.
    """
    line = "d" * 240
    count = 4000  # ~4000 * 241 bytes ~= 960 KB, far past any OS pipe buffer.
    code = (
        "import sys\n"
        "w = sys.stderr.write\n"
        f"for _ in range({count}):\n"
        f"    w({line!r} + chr(10))\n"
        "sys.stderr.flush()\n"
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stderr is not None
    tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)

    # A generous deadline a deadlocked child would blow through, while a child
    # whose stderr is being drained finishes in well under it.
    await asyncio.wait_for(
        asyncio.gather(drain_stderr_into(proc.stderr, tail), proc.wait()),
        timeout=30.0,
    )

    assert proc.returncode == 0
    # The whole flood was consumed (the child reached exit) and only the bounded
    # window is retained, redaction leaving the plain lines intact.
    assert len(tail) == STDERR_TAIL_LINES
    assert all(retained == line for retained in tail)
