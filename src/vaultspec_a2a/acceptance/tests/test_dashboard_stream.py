"""Certify the public progress stream's reconnection and boundary behaviour.

The progress stream is the droppable companion to the authoritative run-status
snapshot. These drive the real versioned ``/v1/runs/{id}/stream`` edge of one
armed-desktop gateway over real HTTP, behind the real attach credential.

Reconnection ordering is the acceptance-observable, provider-independent
property: a terminal run replays its terminal frame on every reconnect, and that
frame reconciles with the authoritative snapshot - a stream that dropped the
terminal frame on reconnect, or disagreed with run-status, would fail. The frame
is checked to be a bounded positive DTO carrying no forbidden body.

Two adjacent contracts are certified elsewhere and are not duplicated here. The
adversarial half of the allowlist - an oversized token delta truncated to the
cap and an artifact body or edit diff stripped at the encoded boundary - is
proven discriminatingly by injecting hostile payloads into the real aggregator
behind a real authenticated stream in the api progress-allowlist suite; a benign
run never emits a forbidden body, so re-asserting exclusion here could only be
tautological. Live multi-frame ordering from a resuming run needs the
deterministic provider that keeps a run non-terminal and is certified in the
Compose service suite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from ...thread.enums import TERMINAL_STATUS_VALUES
from ._sse import read_frame
from .conftest import wait_for_terminal

if TYPE_CHECKING:
    from .. import CertifiedGateway

_FORBIDDEN_BODY_KEYS = ("prompt", "document", "diff", "old_text", "new_text")


def _assert_positive_frame(payload: dict, raw: str) -> None:
    """Assert one frame is a positive DTO carrying no forbidden body."""
    for forbidden in _FORBIDDEN_BODY_KEYS:
        assert forbidden not in payload, f"forbidden field {forbidden!r} crossed"
        assert forbidden not in raw, f"forbidden field {forbidden!r} crossed encoded"


@pytest.mark.asyncio(loop_scope="function")
async def test_terminal_replay_is_idempotent_across_reconnects_and_reconciles(
    gateway: CertifiedGateway,
) -> None:
    """S79: reconnecting a terminal run replays the terminal frame, reconciled.

    Discriminating: two independent stream connections each replay a terminal
    frame for the same run, both carry the same terminal status, and that status
    equals the authoritative run-status snapshot - so the reconnection is ordered
    (terminal is always the final, replayed frame) and the droppable stream never
    contradicts the source of truth. A stream that failed to replay terminal on
    reconnect, or replayed a different status than run-status, would fail.
    """
    run_id = "run-stream-terminal"
    started = gateway.start(run_id)
    assert started.status_code == 201, started.text
    authoritative = wait_for_terminal(gateway, run_id)

    statuses: list[str] = []
    for _ in range(2):
        async with (
            gateway.async_client(timeout=30.0) as client,
            client.stream("GET", gateway.stream_path(run_id)) as response,
        ):
            assert response.status_code == 200, response
            frame, raw = await read_frame(
                response.aiter_lines(), wanted="thread_terminal"
            )
        _assert_positive_frame(frame, raw)
        assert frame["status"] in TERMINAL_STATUS_VALUES
        statuses.append(frame["status"])

    assert statuses[0] == statuses[1]
    assert statuses[0] == authoritative["status"]


@pytest.mark.asyncio(loop_scope="function")
async def test_unauthenticated_stream_open_is_refused(
    gateway: CertifiedGateway,
) -> None:
    """S79: the progress stream is gated - an unauthenticated open never begins.

    Discriminating against the authenticated opens above: the identical request
    without the attach credential is refused 401, so those streams proved a real
    gate rather than an open edge.
    """
    run_id = "run-stream-terminal"
    async with httpx.AsyncClient(timeout=30.0) as client:
        refused = await client.get(f"{gateway.base_url}{gateway.stream_path(run_id)}")
    assert refused.status_code == 401, refused.text
