"""Live tests for the machine-global service discovery contract.

Real filesystem, real process-liveness, and a real ``/health`` server on a real
socket — no mocks. Covers the four things this contract demands: freshness
classification, stale-pid (Crashed) detection, single-resident semantics, and
health-while-degraded still counting as a live resident.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

if TYPE_CHECKING:
    from types import TracebackType

from ..discovery import (
    DiscoveryState,
    _windows_file_is_restricted,
    another_resident_is_live,
    classify_discovery,
    is_pid_alive,
    port_has_listener,
    read_resident_service,
    remove_service_json_if_owned,
    service_json_path,
    write_service_json,
)


def test_port_has_listener_true_on_a_real_listener_false_on_a_free_port() -> None:
    """The shared connect-probe: a real listener answers, a free port does not."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    bound_port = sock.getsockname()[1]
    try:
        assert port_has_listener(bound_port, timeout=1.0) is True
    finally:
        sock.close()
    # Once closed, the same port no longer accepts a connect.
    assert port_has_listener(bound_port, timeout=0.5) is False


class _HealthServer:
    """A real uvicorn server exposing only ``/health`` on an ephemeral port."""

    def __init__(self, *, ready: bool = True) -> None:
        app = FastAPI()

        @app.get("/health")
        async def _health() -> dict[str, object]:
            return {"status": "ok", "ready": ready, "pid": os.getpid()}

        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self.port = 0

    def __enter__(self) -> _HealthServer:
        self._thread.start()
        for _ in range(500):
            if self._server.started and self._server.servers:
                break
            time.sleep(0.01)
        if not (self._server.started and self._server.servers):
            raise RuntimeError("health server did not start")
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)


def test_classifier_covers_absent_fresh_stale_malformed(tmp_path) -> None:
    path = service_json_path(tmp_path)
    assert classify_discovery(path)[0] is DiscoveryState.ABSENT

    write_service_json(path, port=8000, pid=os.getpid(), service_token="s3cr3t-abc")
    state, info = classify_discovery(path)
    assert state is DiscoveryState.FRESH
    assert info is not None and info.port == 8000 and info.pid == os.getpid()
    # Discovery is secret-free; the resolved token comes only from the bounded
    # owner handoff file.
    assert "s3cr3t-abc" not in repr(info)
    record = json.loads(path.read_text())
    assert "service_token" not in record
    handoff = Path(record["handoff_reference"])
    assert handoff == path.with_name("service.token").resolve()
    assert handoff.read_text(encoding="utf-8") == "s3cr3t-abc"
    assert info.service_token == "s3cr3t-abc"
    if os.name == "posix":
        assert handoff.stat().st_mode & 0o077 == 0
    elif os.name == "nt":
        assert _windows_file_is_restricted(path.parent)
        acl = subprocess.run(
            ["icacls.exe", str(handoff)],
            check=True,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        assert "(I)" not in acl

    old = int(time.time() * 1000) - 10_000_000
    write_service_json(
        path, port=8000, pid=os.getpid(), now_ms=old, allow_tokenless=True
    )
    assert classify_discovery(path)[0] is DiscoveryState.STALE

    path.write_text("{ not json", encoding="utf-8")
    assert classify_discovery(path)[0] is DiscoveryState.MALFORMED


def test_token_publication_refuses_preexisting_link(tmp_path: Path) -> None:
    """A planted handoff link cannot redirect credential publication."""
    path = service_json_path(tmp_path)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("must-survive", encoding="utf-8")
    handoff = path.with_name("service.token")
    handoff.symlink_to(outside)

    with pytest.raises(OSError, match="link-like"):
        write_service_json(
            path,
            port=8000,
            pid=os.getpid(),
            service_token="replacement-secret",
        )

    assert outside.read_text(encoding="utf-8") == "must-survive"
    assert handoff.is_symlink()
    assert not path.exists()


def test_credential_reader_rejects_permissions_without_repair(tmp_path: Path) -> None:
    """Filesystem-only discovery never repairs an untrusted handoff file."""
    path = service_json_path(tmp_path)
    handoff = path.with_name("service.token")
    handoff.write_text("untrusted-secret", encoding="utf-8")
    path.write_text(
        json.dumps(
            {
                "port": 8000,
                "pid": os.getpid(),
                "last_heartbeat": int(time.time() * 1000),
                "handoff_reference": str(handoff.resolve()),
            }
        ),
        encoding="utf-8",
    )
    if os.name == "posix":
        handoff.chmod(0o644)
        before: object = handoff.stat().st_mode
    else:
        subprocess.run(
            ["icacls.exe", str(handoff), "/grant", "*S-1-1-0:F"],
            check=True,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        before = subprocess.run(
            ["icacls.exe", str(handoff)],
            check=True,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout

    state, info = classify_discovery(path)

    assert state is DiscoveryState.FRESH
    assert info is not None and info.service_token is None
    if os.name == "posix":
        assert handoff.stat().st_mode == before
    else:
        after = subprocess.run(
            ["icacls.exe", str(handoff)],
            check=True,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        assert after == before


def test_writer_replaces_preexisting_broad_directory_authority(tmp_path: Path) -> None:
    """Publication replaces, rather than layers grants onto, a shared parent."""
    home = tmp_path / "shared-home"
    home.mkdir()
    if os.name == "posix":
        home.chmod(0o777)
    else:
        subprocess.run(
            ["icacls.exe", str(home), "/grant", "*S-1-1-0:(OI)(CI)F"],
            check=True,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    path = service_json_path(home)
    write_service_json(
        path,
        port=8000,
        pid=os.getpid(),
        service_token="private-after-replacement",
    )
    state, info = classify_discovery(path)

    assert state is DiscoveryState.FRESH
    assert info is not None
    assert info.service_token == "private-after-replacement"
    if os.name == "posix":
        assert home.stat().st_mode & 0o077 == 0
    else:
        assert _windows_file_is_restricted(home)
        assert _windows_file_is_restricted(home / "service.token")


def test_pid_liveness_and_ownership(tmp_path) -> None:
    assert is_pid_alive(os.getpid()) is True
    assert is_pid_alive(2**31 - 1) is False
    assert is_pid_alive(None) is False

    path = service_json_path(tmp_path)
    write_service_json(path, port=8000, pid=os.getpid(), allow_tokenless=True)
    # A file owned by another pid is never reclaimed by us.
    write_service_json(path, port=8000, pid=424242, allow_tokenless=True)
    assert remove_service_json_if_owned(path, os.getpid()) is False
    assert path.exists()
    # Our own record is dropped on exit.
    write_service_json(path, port=8000, pid=os.getpid(), allow_tokenless=True)
    assert remove_service_json_if_owned(path, os.getpid()) is True
    assert not path.exists()


def test_stale_pid_is_not_a_live_resident(tmp_path) -> None:
    """A fresh heartbeat with a dead pid reads as Crashed, not a live resident."""
    path = service_json_path(tmp_path)
    # Fresh heartbeat (now) but a pid that does not exist -> attach-never-own.
    write_service_json(path, port=8000, pid=2**31 - 1, allow_tokenless=True)
    state, _info = classify_discovery(path)
    assert state is DiscoveryState.FRESH  # heartbeat is fresh...
    assert another_resident_is_live(tmp_path) is False  # ...but the pid is dead.


def test_single_resident_true_only_when_fresh_live_and_healthy(tmp_path) -> None:
    with _HealthServer() as server:
        path = service_json_path(tmp_path)
        write_service_json(
            path, port=server.port, pid=os.getpid(), allow_tokenless=True
        )
        # Fresh record + our (live) pid + a real answering /health = live resident.
        assert another_resident_is_live(tmp_path) is True

        state, info = read_resident_service(tmp_path)
        assert state is DiscoveryState.FRESH
        assert info is not None and info.port == server.port

    # Server stopped: the /health probe now fails, so no live resident.
    assert another_resident_is_live(tmp_path) is False


def test_health_while_degraded_still_counts_as_resident(tmp_path) -> None:
    """A degraded gateway (ready=false) is still a live resident: /health answers."""
    with _HealthServer(ready=False) as server:
        path = service_json_path(tmp_path)
        write_service_json(
            path, port=server.port, pid=os.getpid(), allow_tokenless=True
        )
        body = httpx.get(f"http://127.0.0.1:{server.port}/health", timeout=2.0).json()
        assert body["ready"] is False
        assert another_resident_is_live(tmp_path) is True


def test_absent_file_licenses_a_start(tmp_path) -> None:
    """Only Absent means no resident — the caller may start and publish."""
    assert another_resident_is_live(tmp_path) is False
    assert read_resident_service(tmp_path)[0] is DiscoveryState.ABSENT


def test_tokenless_publication_is_refused_by_default(tmp_path) -> None:
    """A tokenless publish must raise rather than silently downgrade the record.

    The destructive shape is what matters: without the refusal, this call would
    strip the handoff reference and unlink the credential beside it, leaving a
    record any reader resolves with no bearer.
    """
    path = service_json_path(tmp_path)
    write_service_json(path, port=8000, pid=os.getpid(), service_token="live-secret")
    credential = path.parent / "service.token"
    assert credential.exists()

    with pytest.raises(ValueError, match="without a service token"):
        write_service_json(path, port=8000, pid=os.getpid())

    # The healthy record and its credential survive the refused call.
    assert credential.read_text(encoding="utf-8") == "live-secret"
    assert "handoff_reference" in json.loads(path.read_text(encoding="utf-8"))


def test_deliberate_unpublish_still_clears_the_credential(tmp_path) -> None:
    """The opt-in keeps the un-publish case available for callers that mean it."""
    path = service_json_path(tmp_path)
    write_service_json(path, port=8000, pid=os.getpid(), service_token="live-secret")
    credential = path.parent / "service.token"
    assert credential.exists()

    write_service_json(path, port=8000, pid=os.getpid(), allow_tokenless=True)

    assert not credential.exists()
    assert "handoff_reference" not in json.loads(path.read_text(encoding="utf-8"))


def test_removing_a_malformed_record_also_clears_its_credential(tmp_path) -> None:
    """A malformed record must not strand the credential beside it.

    An unreadable record can never again reference its token, so a token left
    behind is one no reader can reach and no exit path would ever collect.
    """
    path = service_json_path(tmp_path)
    write_service_json(path, port=8000, pid=os.getpid(), service_token="stranded")
    credential = path.parent / "service.token"
    assert credential.exists()
    path.write_text("{ not json", encoding="utf-8")

    assert remove_service_json_if_owned(path, os.getpid()) is True

    assert not path.exists()
    assert not credential.exists()


def test_credential_removal_refuses_a_link_like_destination(tmp_path) -> None:
    """A symlink where the credential belongs must not be followed on removal.

    Otherwise anyone able to write the discovery directory could redirect the
    unlink at a file of their choosing.
    """
    path = service_json_path(tmp_path)
    write_service_json(path, port=8000, pid=os.getpid(), allow_tokenless=True)
    outsider = tmp_path / "outside.txt"
    outsider.write_text("must-survive", encoding="utf-8")
    link = path.parent / "service.token"
    try:
        link.symlink_to(outsider)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"host cannot create symlinks: {exc}")

    assert remove_service_json_if_owned(path, os.getpid()) is True

    assert outsider.read_text(encoding="utf-8") == "must-survive"
    assert link.is_symlink()
