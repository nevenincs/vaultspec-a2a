"""Tests for local service lifecycle tracking.

All tests exercise real code without monkeypatching. The internal helpers
accept an optional ``runtime_dir`` parameter so tests can supply an isolated
temporary directory instead of relying on the process working directory.

Tests that involve actually spawning subprocesses (start, stop) are integration
concerns covered by the session-scoped smoke tests in
``src/vaultspec_a2a/tests/test_smoke.py``.
"""

from __future__ import annotations

import json

from pathlib import Path
from uuid import uuid4

import pytest

from ...cli._service import (
    _clear_service_record,
    _get_service_record,
    _is_pid_running,
    _load_registry,
    _save_registry,
    _service_status,
    _stop_service,
    _write_service_record,
)


def _non_running_pid() -> int:
    """Return a PID value that the current host reports as not running."""
    candidate = 1_000_000
    while candidate < 1_010_000:
        if not _is_pid_running(candidate):
            return candidate
        candidate += 1
    msg = "Could not find a non-running PID in the probe window"
    raise AssertionError(msg)


@pytest.fixture
def runtime_dir() -> Path:
    """Return a repo-local runtime dir instead of pytest's temp root."""
    root = Path.cwd() / ".tmp" / "cli-test-runtime" / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def test_load_registry_returns_empty_when_file_missing(runtime_dir: Path) -> None:
    """_load_registry returns the empty sentinel when no file exists."""
    result = _load_registry(runtime_dir)
    assert result == {"services": {}}


def test_save_and_load_registry_round_trip(runtime_dir: Path) -> None:
    """Saved registry can be read back with the same structure."""
    data: dict = {
        "services": {"gateway": {"pid": 1234, "host": "127.0.0.1", "port": 8000}}
    }
    _save_registry(data, runtime_dir)
    loaded = _load_registry(runtime_dir)
    assert loaded == data


def test_write_service_record_stores_entry(runtime_dir: Path) -> None:
    """_write_service_record persists pid/host/port/log_path to the registry."""
    _write_service_record(
        "gateway",
        pid=9001,
        host="127.0.0.1",
        port=8000,
        log_path=runtime_dir / "gateway.log",
        runtime_dir=runtime_dir,
    )
    record = _get_service_record("gateway", runtime_dir)
    assert record is not None
    assert record["pid"] == 9001
    assert record["host"] == "127.0.0.1"
    assert record["port"] == 8000
    assert "started_at" in record
    assert "launch_mode" in record


def test_clear_service_record_removes_entry(runtime_dir: Path) -> None:
    """_clear_service_record removes the named entry while leaving others."""
    _write_service_record(
        "gateway",
        pid=9001,
        host="127.0.0.1",
        port=8000,
        log_path=runtime_dir / "gateway.log",
        runtime_dir=runtime_dir,
    )
    _write_service_record(
        "worker",
        pid=9002,
        host="127.0.0.1",
        port=8001,
        log_path=runtime_dir / "worker.log",
        runtime_dir=runtime_dir,
    )
    _clear_service_record("gateway", runtime_dir)
    assert _get_service_record("gateway", runtime_dir) is None
    assert _get_service_record("worker", runtime_dir) is not None


def test_get_service_record_returns_none_when_absent(runtime_dir: Path) -> None:
    """_get_service_record returns None when no record is present."""
    result = _get_service_record("gateway", runtime_dir)
    assert result is None


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------


def test_service_status_stopped_when_no_record(runtime_dir: Path) -> None:
    """Status is 'stopped' and tracked=False when no registry entry exists."""
    status = _service_status("gateway", runtime_dir)
    assert status["status"] == "stopped"
    assert status["tracked"] is False
    assert status["pid"] is None


def test_service_status_pid_stale_when_process_dead(runtime_dir: Path) -> None:
    """Status is 'pid-stale' when the recorded PID is no longer running."""
    dead_pid = _non_running_pid()
    _write_service_record(
        "gateway",
        pid=dead_pid,
        host="127.0.0.1",
        port=8099,
        log_path=runtime_dir / "gateway.log",
        runtime_dir=runtime_dir,
    )

    status = _service_status("gateway", runtime_dir)
    assert status["status"] == "pid-stale"
    assert status["tracked"] is True
    assert status["pid"] == dead_pid


# ---------------------------------------------------------------------------
# Stop service (registry-only path — no live process)
# ---------------------------------------------------------------------------


def test_stop_service_returns_not_tracked_when_no_record(runtime_dir: Path) -> None:
    """_stop_service returns 'not-tracked' when the registry has no entry."""
    result = _stop_service("gateway", runtime_dir=runtime_dir)
    assert result == "not-tracked"


def test_stop_service_clears_stale_pid_record(runtime_dir: Path) -> None:
    """_stop_service clears a stale PID entry and returns 'pid-stale'."""
    dead_pid = _non_running_pid()
    _write_service_record(
        "worker",
        pid=dead_pid,
        host="127.0.0.1",
        port=8099,
        log_path=runtime_dir / "worker.log",
        runtime_dir=runtime_dir,
    )

    result = _stop_service("worker", runtime_dir=runtime_dir)
    assert result == "pid-stale"
    # Registry entry must be cleared after a stale-pid stop.
    assert _get_service_record("worker", runtime_dir) is None


# ---------------------------------------------------------------------------
# Registry JSON format
# ---------------------------------------------------------------------------


def test_registry_file_is_valid_json(runtime_dir: Path) -> None:
    """The persisted registry file is valid JSON readable by the stdlib."""
    _write_service_record(
        "gateway",
        pid=42,
        host="0.0.0.0",
        port=8000,
        log_path=runtime_dir / "gw.log",
        runtime_dir=runtime_dir,
    )
    raw = (runtime_dir / "services.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert "services" in parsed
    assert "gateway" in parsed["services"]
