"""Certify the certification harness hands back a ready gateway and frees its log.

The boot helper hands exactly one running gateway back to
:func:`certified_gateway`, which reaps it when the scenario ends. Every other
exit - a child that dies on the bind race, a child that stays alive but never
answers ``/health``, or a run that exhausts its attempts - abandons its process
tree with no other owner; that the helper reaps such a tree is proven against
real processes in ``desktop_tests/test_boot_harness.py``.

The scenarios here drive the real :func:`spawn_until_ready` seam with real
subprocesses - the ``spawn`` callable is a first-class parameter of the
function under test, so passing a real process launcher exercises the seam
rather than substituting for it. The success path is the negative control for
that reaping proof: the same liveness assertion applied to a gateway that DOES
answer ``/health`` yields the opposite result, so the failure-path assertion
discriminates rather than passing trivially.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from ...testing import reap_process, spawn_logged, spawn_until_ready
from ._harness import certified_gateway

if TYPE_CHECKING:
    from pathlib import Path

    from ...testing import WatchedProcess

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


def test_ready_gateway_is_returned_alive(tmp_path: Path) -> None:
    """Negative control: a gateway that answers is handed back still running.

    Proves the reaping proof's liveness assertion is discriminating. The same
    ``poll() is not None`` check applied here would fail, so a reaping bug
    cannot make both scenarios pass, and a helper that killed every child
    indiscriminately would fail this one.
    """
    spawned: list[WatchedProcess] = []

    def _spawn(gateway_port: int, _worker_port: int) -> WatchedProcess:
        child = spawn_logged(
            [sys.executable, "-c", _READY_CHILD, str(gateway_port)],
            name="ready child",
            env=os.environ,
            log_path=tmp_path / "ready-child.log",
        )
        spawned.append(child)
        return child

    try:
        gateway, _gateway_port, _worker_port, base = spawn_until_ready(
            _spawn,
            attempts=3,
            timeout=20.0,
        )
        assert gateway.process.poll() is None, (
            "a ready gateway must be returned running"
        )
        assert base.startswith("http://127.0.0.1:")
    finally:
        for candidate in spawned:
            reap_process(candidate)


def test_failed_boot_releases_the_gateway_log_handle(tmp_path: Path) -> None:
    """A boot that never succeeds closes the log file it opened.

    Discriminating on Windows, where an open handle blocks deletion: a
    ``certified_gateway`` that held the log open across the boot and closed it
    only once the yield returned would leave it locked after a failing boot,
    which never reaches the yield. The child is failed for a real reason - an
    invalid worker port that the production settings model rejects at import -
    so the gateway genuinely exits non-zero on every attempt rather than being
    killed.

    The expectation is the exhausted-attempts ``AssertionError`` rather than
    :class:`GatewayBootError`: the boot helper catches the per-attempt
    ``GatewayBootError`` and only records it as ``last_error``, so the type that
    escapes this path is the plain one. ``match`` pins it to that specific
    failure so an unrelated failing ``assert`` inside the setup cannot satisfy
    the expectation.
    """
    workdir = tmp_path / "failed-boot"
    workdir.mkdir()

    with (
        pytest.raises(AssertionError, match="did not boot within"),
        certified_gateway(
            workdir,
            log_name="gateway.log",
            VAULTSPEC_A2A_WORKER_PORT="not-a-port",
        ),
    ):
        pass  # pragma: no cover - the boot must never yield

    log_path = workdir / "gateway.log"
    assert log_path.is_file(), "the failed boot should still have written a log"
    log_path.unlink()
