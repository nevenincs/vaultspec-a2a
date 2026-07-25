"""Certify the certification harness reaps a gateway that never becomes ready.

The boot helper hands exactly one running gateway back to
:func:`certified_gateway`, whose ``finally`` reaps it. Every other exit - a
child that dies on the bind race, a child that stays alive but never answers
``/health``, or a run that exhausts its attempts - abandons its process tree
with no other owner. A tree abandoned there is not merely leaked: the gateway
spawns its own worker, so the orphan keeps holding the worker port, and the
next boot meets its own leftover there and refuses it as an unidentified
occupant. An incomplete reap wedges the port band rather than merely leaking.

These scenarios drive the real :func:`_spawn_until_ready` seam with real
subprocesses - the ``spawn`` callable is a first-class parameter of the
function under test, so passing a real process launcher exercises the seam
rather than substituting for it. The success path is the negative control: the
same liveness assertion applied to a gateway that DOES answer ``/health``
yields the opposite result, so the failure-path assertion discriminates rather
than passing trivially.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from .._harness import _reap, _spawn_until_ready, certified_gateway

if TYPE_CHECKING:
    from pathlib import Path

# A real process that binds nothing and never answers, so the readiness poll
# runs to its deadline with the child still alive - the branch that leaked.
_SILENT_CHILD = "import time; time.sleep(300)"

# A real HTTP server answering 200 on every path, so readiness genuinely passes.
_READY_CHILD = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""


def _launcher(script: str, spawned: list[subprocess.Popen[bytes]], *, pass_port: bool):
    """Return a real ``spawn`` callable recording every child it launches."""

    def _spawn(gateway_port: int, _worker_port: int) -> subprocess.Popen[bytes]:
        command = [sys.executable, "-c", script]
        if pass_port:
            command.append(str(gateway_port))
        proc = subprocess.Popen(command)
        spawned.append(proc)
        return proc

    return _spawn


def test_gateway_that_never_becomes_ready_is_reaped_not_orphaned() -> None:
    """A live-but-unready gateway is reaped before the readiness failure raises.

    Discriminating: the child is a real process that stays alive for the whole
    readiness window, so the pre-fix helper propagated the deadline
    ``AssertionError`` straight out of the loop with the tree still running and
    no owner left to reap it. Asserting the child is dead after the raise fails
    against that implementation and passes only once the helper reaps on the
    way out.
    """
    spawned: list[subprocess.Popen[bytes]] = []
    try:
        with pytest.raises(AssertionError, match="never became ready"):
            _spawn_until_ready(
                _launcher(_SILENT_CHILD, spawned, pass_port=False),
                log_path=None,
                attempts=1,
                timeout=2.0,
            )

        assert spawned, "the boot helper must have spawned a real child"
        for proc in spawned:
            assert proc.poll() is not None, (
                f"gateway pid {proc.pid} survived a readiness failure; "
                "the tree was orphaned instead of reaped"
            )
    finally:
        for proc in spawned:
            _reap(proc)


def test_ready_gateway_is_returned_alive() -> None:
    """Negative control: a gateway that answers is handed back still running.

    Proves the liveness assertion above is discriminating. The same
    ``poll() is not None`` check applied here would fail, so a reaping bug
    cannot make both scenarios pass, and a helper that killed every child
    indiscriminately would fail this one.
    """
    spawned: list[subprocess.Popen[bytes]] = []
    try:
        proc, _gateway_port, _worker_port, base = _spawn_until_ready(
            _launcher(_READY_CHILD, spawned, pass_port=True),
            log_path=None,
            attempts=3,
            timeout=20.0,
        )
        assert proc.poll() is None, "a ready gateway must be returned running"
        assert base.startswith("http://127.0.0.1:")
    finally:
        for candidate in spawned:
            _reap(candidate)


def test_failed_boot_releases_the_gateway_log_handle(tmp_path: Path) -> None:
    """A boot that never succeeds closes the log file it opened.

    Discriminating on Windows, where an open handle blocks deletion: the
    pre-fix ``certified_gateway`` opened the log before calling the boot helper
    but closed it only in the ``finally`` guarding the yield, which a failing
    boot never reaches. The child is failed for a real reason - an invalid
    worker port that the production settings model rejects at import - so the
    gateway genuinely exits non-zero on every attempt rather than being killed.
    """
    workdir = tmp_path / "failed-boot"
    workdir.mkdir()

    with (
        pytest.raises(AssertionError),
        certified_gateway(
            workdir,
            log_name="gateway.log",
            VAULTSPEC_WORKER_PORT="not-a-port",
        ),
    ):
        pass  # pragma: no cover - the boot must never yield

    log_path = workdir / "gateway.log"
    assert log_path.is_file(), "the failed boot should still have written a log"
    log_path.unlink()
