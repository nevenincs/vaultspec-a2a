"""Real-HTTP proof that one worker never gets two contradictory health verdicts.

A worker that answers ``200`` with a body the decoder cannot read is the case
where the gateway's two health readers used to disagree. The watchdog and
``/api/health`` read it through the probe primitive and saw the worker UP; the
boot, adopt, and evict paths read it through the body-returning helper, which
evaluated ``resp.json()`` inside the same ``try`` that caught transport
failures, and so received the identical ``None`` it receives for a DEAD worker.
One live worker was simultaneously up and absent, and the absent reading is the
one that spawns a competitor onto a port that worker still holds.

The occupant here is a real HTTP server in a real subprocess serving a real
malformed ``200`` over a real socket - the condition itself, not a stand-in for
any code under test. Every assertion drives production functions directly.

The contract these pin down is deliberately asymmetric, because the two callers
ask different questions of the same occupant:

- *is a worker up?* - yes; an unreadable body cannot make a healthy worker
  unhealthy;
- *does something hold this port?* - yes, so do not spawn onto it;
- *is that something provably mine?* - no; an unreadable body is the absence of
  evidence, and the provenance check must refuse it under both profiles.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from ..control.config import settings
from ..control.worker_management import (
    _check_worker_health,
    _fetch_worker_health,
    _probe_worker_health,
    _worker_ready_and_ours,
)
from ..tests.gateway_boot import free_port

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# A real server that answers 200 with a body that is emphatically not JSON.
# Content-Type claims JSON so the failure is the DECODE, not content negotiation.
_MALFORMED_WORKER = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[1])
payload = b"<!doctype html><html><body>not json at all</body></html>"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""


@contextlib.contextmanager
def _malformed_worker(tmp_path: Path) -> Iterator[str]:
    """Run a real HTTP server that answers /health 200 with undecodable bytes."""
    port = free_port()
    script = tmp_path / "malformed_worker.py"
    script.write_text(_MALFORMED_WORKER, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(script), str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                with httpx.Client(timeout=1.0) as client:
                    resp = client.get(f"{url}/health")
                if resp.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise AssertionError("the malformed worker never came up")
        yield url
    finally:
        with contextlib.suppress(Exception):
            proc.kill()
            proc.wait(timeout=10)


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unreadable_worker_is_up_present_and_not_ours(
    tmp_path: Path,
) -> None:
    """One live unreadable worker yields three consistent, non-contradictory reads.

    Each assertion is a different production entry point against the SAME live
    occupant, which is what makes the set a split-brain proof rather than three
    unrelated checks.

    Load-bearing: ``_fetch_worker_health`` must not return ``None``. That is the
    value it returns for a dead worker, and returning it here is precisely the
    defect - the spawn path reads ``None`` as "nothing holds this port" and
    spawns a competitor onto a port this live server still owns. Restore the
    decode into the request's own ``except`` and this assertion fails while the
    health verdict above it still passes, which is exactly how the divergence
    stayed invisible.
    """
    # This exercises the LEGACY declared-target branch, the one that reads a
    # missing target as a match - so the refusal asserted last is the explicit
    # guard doing the work, not the armed classifier.
    assert settings.desktop_profile_armed is False, (
        "this proof pins the unarmed lenient branch"
    )

    with _malformed_worker(tmp_path) as url:
        # The health verdict is the status code and nothing else: an unreadable
        # body cannot turn a healthy worker unhealthy.
        healthy, body = await _probe_worker_health(url)
        assert healthy is True, (healthy, body)
        assert body is None, body

        # The watchdog and /api/health agree, through the boolean face.
        assert await _check_worker_health(url) is True

        # LOAD-BEARING: something demonstrably holds this port. Not None - which
        # is reserved for "no healthy worker answered" - so the spawn path
        # cannot mistake a live occupant for a free port.
        occupant = await _fetch_worker_health(url)
        assert occupant is not None, "a live worker was reported as absent"
        assert occupant == {}, occupant

        # And it is still not provably ours: an unreadable body is no evidence,
        # even under the lenient rule that adopts a worker declaring no target.
        assert await _worker_ready_and_ours(url) is False


@pytest.mark.asyncio(loop_scope="function")
async def test_nothing_listening_is_reported_absent(tmp_path: Path) -> None:
    """A port with no server is absent - the reading reserved for a dead worker.

    The counterpart that keeps the proof above honest: ``None`` must still mean
    something, or asserting "not None" for the unreadable worker would be
    vacuous. Port 9 (discard) refuses the connection outright.
    """
    dead = "http://127.0.0.1:9"
    healthy, body = await _probe_worker_health(dead)
    assert healthy is False, (healthy, body)
    assert body is None
    assert await _check_worker_health(dead) is False
    assert await _fetch_worker_health(dead) is None
    assert await _worker_ready_and_ours(dead) is False
