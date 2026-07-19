"""Worker runtime-log hygiene: eviction cleanup and the orphan startup sweep.

Real files, a real subprocess for the "live" registry record, and a real HTTP
server standing in for a foreign worker being evicted - no mocks. Pins the
retention half of the observability-lanes plan (P02.S03): a killed/evicted
worker's stderr log must not accumulate forever, and a dev-band worker's past
instances must not leave permanent orphans under the runtime dir.
"""

from __future__ import annotations

import http.server
import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.control.config import settings
from vaultspec_a2a.control.worker_management import (
    _evict_stale_worker,
    _worker_stderr_log_path,
    sweep_orphan_worker_logs,
)
from vaultspec_a2a.lifecycle.registry import ProcRecord, now_ms, write_record

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@contextmanager
def _a2a_home(path: Path) -> Iterator[None]:
    """Point ``settings.a2a_home`` at *path* for the duration, then restore it.

    Mirrors the sanctioned direct-attribute-swap seam used across this suite
    (e.g. the ``_internal_token`` override in ``test_worker_provenance.py``) -
    a real attribute on the live settings object, not a mock.
    """
    original = settings.a2a_home
    settings.a2a_home = path
    try:
        yield
    finally:
        settings.a2a_home = original


def _make_handler() -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            """Silence the default access log."""

    return _Handler


@contextmanager
def _foreign_worker() -> Iterator[int]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler())
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_evict_stale_worker_deletes_its_stderr_log_once_freed(
    tmp_path: Path,
) -> None:
    # Scenario 1: the server is still listening, so the port cannot be confirmed
    # free - the log must survive an eviction attempt that does not free it.
    with _a2a_home(tmp_path), _foreign_worker() as still_up_port:
        still_up_log = _worker_stderr_log_path(still_up_port)
        still_up_log.write_text("stale orphan output\n", encoding="utf-8")

        freed = await _evict_stale_worker(
            f"http://127.0.0.1:{still_up_port}", still_up_port, timeout=0.5
        )
        assert freed is False
        assert still_up_log.exists()

    # Scenario 2: the server is torn down (a real freed port), so eviction
    # confirms the port free and deletes the now-genuinely-orphaned log.
    with _a2a_home(tmp_path), _foreign_worker() as torn_down_port:
        torn_down_log = _worker_stderr_log_path(torn_down_port)
        torn_down_log.write_text("stale orphan output\n", encoding="utf-8")
    # The `with` block above has exited (server torn down); the port/path
    # captured from it remain valid identifiers to probe against.
    with _a2a_home(tmp_path):
        freed = await _evict_stale_worker(
            f"http://127.0.0.1:{torn_down_port}", torn_down_port, timeout=1.0
        )
        assert freed is True
        assert not torn_down_log.exists()


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_sweep_orphan_worker_logs_removes_dead_keeps_live_and_current(
    tmp_path: Path,
) -> None:
    registry_home = tmp_path / "registry"
    a2a_home = tmp_path / "a2a-home"

    live_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with _a2a_home(a2a_home):
            orphan_log = _worker_stderr_log_path(18801)
            orphan_log.write_text("dead dev-band instance\n", encoding="utf-8")

            live_log = _worker_stderr_log_path(18802)
            live_log.write_text("still running dev-band instance\n", encoding="utf-8")
            write_record(
                ProcRecord(
                    name="alpha",
                    role="worker-dev",
                    pid=live_proc.pid,
                    port=18802,
                    started_at_ms=now_ms(),
                    last_seen_ms=now_ms(),
                ),
                home=registry_home,
            )

            current_log = _worker_stderr_log_path(18803)
            current_log.write_text("this process's own worker\n", encoding="utf-8")

            removed = sweep_orphan_worker_logs(
                current_worker_port=18803, registry_home=registry_home
            )

            removed_names = {p.name for p in removed}
            assert orphan_log.name in removed_names
            assert live_log.name not in removed_names
            assert current_log.name not in removed_names

            assert not orphan_log.exists()
            assert live_log.exists()
            assert current_log.exists()
    finally:
        live_proc.kill()
        live_proc.wait()


def test_sweep_orphan_worker_logs_ignores_non_matching_files(tmp_path: Path) -> None:
    with _a2a_home(tmp_path / "a2a-home"):
        runtime_dir = _worker_stderr_log_path(1).parent
        runtime_dir.mkdir(parents=True, exist_ok=True)
        stray = runtime_dir / "not-a-worker-log.txt"
        stray.write_text("unrelated file\n", encoding="utf-8")

        removed = sweep_orphan_worker_logs(
            current_worker_port=1, registry_home=tmp_path / "registry"
        )

        assert stray not in removed
        assert stray.exists()
