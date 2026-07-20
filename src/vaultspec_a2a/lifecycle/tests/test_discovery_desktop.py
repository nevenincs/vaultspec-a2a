"""Certify the versioned, secret-free desktop discovery record.

Exercises the real filesystem: atomic publication, round-trip parsing,
freshness and malformation classification, process-liveness with the singleton's
start fingerprint, and — most load-bearing — that no credential value ever
reaches the published bytes. A real reader thread races a repeated writer to
prove the temp-and-rename publication is atomic. No mock, monkeypatch, stub,
skip, or expected failure is used.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import TYPE_CHECKING

from vaultspec_a2a.lifecycle.discovery import (
    DESKTOP_DISCOVERY_VERSION,
    DesktopDiscoveryState,
    classify_desktop_discovery,
    desktop_record_process_is_live,
    read_desktop_discovery,
    write_desktop_discovery,
)

if TYPE_CHECKING:
    from pathlib import Path

_STALE_MS = 120_000


def test_round_trip_preserves_every_field(tmp_path: Path) -> None:
    """A published record reads back field-for-field with no bearer value."""
    path = tmp_path / "service.json"
    reference = str(tmp_path / "credentials" / "attach-control.cred")
    written = write_desktop_discovery(
        path,
        generation="gen-2026-07-19-abc123",
        port=8123,
        owner="alice",
        credential_reference=reference,
        protocol_min=1,
        protocol_max=1,
    )
    read = read_desktop_discovery(path)
    assert read is not None
    assert read == written
    assert read.version == DESKTOP_DISCOVERY_VERSION
    assert read.profile == "desktop"
    assert read.generation == "gen-2026-07-19-abc123"
    assert read.port == 8123
    assert read.owner == "alice"
    assert read.credential_reference == reference
    assert read.base_url == "http://127.0.0.1:8123"
    assert read.pid == os.getpid()


def test_published_bytes_contain_no_credential_value(tmp_path: Path) -> None:
    """No secret from the environment or a credential file reaches discovery bytes.

    The record only names the credential file by path. A real secret is planted in
    the environment and in the referenced file; the published bytes must contain
    neither, and must carry no bearer-bearing key.
    """
    secret = "s3cr3t-attach-bearer-DEADBEEF"
    creds_dir = tmp_path / "credentials"
    creds_dir.mkdir()
    credential_file = creds_dir / "attach-control.cred"
    credential_file.write_text(secret, encoding="utf-8")

    prior = os.environ.get("VAULTSPEC_TEST_SECRET")
    os.environ["VAULTSPEC_TEST_SECRET"] = secret
    try:
        path = tmp_path / "service.json"
        write_desktop_discovery(
            path,
            generation="gen-1",
            port=8124,
            owner="alice",
            credential_reference=str(credential_file),
        )
        raw = path.read_bytes()
    finally:
        if prior is None:
            os.environ.pop("VAULTSPEC_TEST_SECRET", None)
        else:
            os.environ["VAULTSPEC_TEST_SECRET"] = prior

    # The credential value — planted in the environment and written into the
    # referenced file during publication — must never reach the published bytes;
    # the record names the credential only by path.
    assert credential_file.read_text(encoding="utf-8") == secret
    assert secret.encode("utf-8") not in raw
    payload = json.loads(raw)
    for forbidden in ("service_token", "token", "bearer", "secret"):
        assert forbidden not in payload
    # The reference names the file by path; the path is present, the secret is not.
    assert payload["credential_reference"] == str(credential_file)


def test_classification_fresh_stale_absent_malformed(tmp_path: Path) -> None:
    """The desktop classifier reports each filesystem state distinctly."""
    path = tmp_path / "service.json"
    assert classify_desktop_discovery(path)[0] is DesktopDiscoveryState.ABSENT

    write_desktop_discovery(path, generation="g", port=8125, owner="alice")
    state, record = classify_desktop_discovery(path)
    assert state is DesktopDiscoveryState.FRESH
    assert record is not None and record.port == 8125

    old = int(time.time() * 1000) - _STALE_MS - 5_000
    write_desktop_discovery(path, generation="g", port=8125, owner="alice", now_ms=old)
    assert classify_desktop_discovery(path)[0] is DesktopDiscoveryState.STALE

    path.write_text("{ not valid json", encoding="utf-8")
    assert classify_desktop_discovery(path)[0] is DesktopDiscoveryState.MALFORMED


def test_legacy_record_is_malformed_to_the_desktop_classifier(tmp_path: Path) -> None:
    """An unversioned Compose record is not a valid desktop record."""
    path = tmp_path / "service.json"
    path.write_text(
        json.dumps({"port": 8000, "pid": 4321, "last_heartbeat": 1}),
        encoding="utf-8",
    )
    assert classify_desktop_discovery(path)[0] is DesktopDiscoveryState.MALFORMED
    assert read_desktop_discovery(path) is None


def test_process_liveness_uses_recorded_identity(tmp_path: Path) -> None:
    """A live recording reads live; a dead pid reads dead."""
    path = tmp_path / "service.json"
    live = write_desktop_discovery(path, generation="g", port=8126, owner="alice")
    assert desktop_record_process_is_live(live) is True

    dead = write_desktop_discovery(
        path, generation="g", port=8126, owner="alice", pid=2**31 - 1
    )
    assert desktop_record_process_is_live(dead) is False


def test_publication_is_atomic_under_a_racing_reader(tmp_path: Path) -> None:
    """A reader racing repeated writes never observes a partial or malformed record."""
    path = tmp_path / "service.json"
    write_desktop_discovery(path, generation="g0", port=8127, owner="alice")

    stop = threading.Event()
    failures: list[str] = []

    def _reader() -> None:
        # os.replace is atomic, so a reader sees either the old or the new complete
        # file — never a partial one. On Windows an open can be transiently denied
        # (sharing violation) mid-replace; that is retried, not a torn record. A
        # JSON parse error, by contrast, would mean a partial file was observed.
        while not stop.is_set():
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except ValueError:
                failures.append(f"torn record: {raw[:48]!r}")
                return
            endpoint = payload.get("endpoint")
            if not isinstance(endpoint, dict) or endpoint.get("port") != 8127:
                failures.append(f"wrong record: {payload!r}")
                return

    reader = threading.Thread(target=_reader)
    reader.start()
    try:
        for index in range(400):
            write_desktop_discovery(
                path, generation=f"g{index}", port=8127, owner="alice"
            )
    finally:
        stop.set()
        reader.join(timeout=10)

    assert not failures, f"racing reader saw a torn record: {failures}"
    assert not list(tmp_path.glob("service.json.*.tmp"))
