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


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def test_load_registry_returns_empty_when_file_missing(tmp_path: Path) -> None:
    """_load_registry returns the empty sentinel when no file exists."""
    result = _load_registry(tmp_path)
    assert result == {"services": {}}


def test_save_and_load_registry_round_trip(tmp_path: Path) -> None:
    """Saved registry can be read back with the same structure."""
    data: dict = {
        "services": {"gateway": {"pid": 1234, "host": "127.0.0.1", "port": 8000}}
    }
    _save_registry(data, tmp_path)
    loaded = _load_registry(tmp_path)
    assert loaded == data


def test_write_service_record_stores_entry(tmp_path: Path) -> None:
    """_write_service_record persists pid/host/port/log_path to the registry."""
    _write_service_record(
        "gateway",
        pid=9001,
        host="127.0.0.1",
        port=8000,
        log_path=tmp_path / "gateway.log",
        runtime_dir=tmp_path,
    )
    record = _get_service_record("gateway", tmp_path)
    assert record is not None
    assert record["pid"] == 9001
    assert record["host"] == "127.0.0.1"
    assert record["port"] == 8000
    assert "started_at" in record
    assert "launch_mode" in record


def test_clear_service_record_removes_entry(tmp_path: Path) -> None:
    """_clear_service_record removes the named entry while leaving others."""
    _write_service_record(
        "gateway",
        pid=9001,
        host="127.0.0.1",
        port=8000,
        log_path=tmp_path / "gateway.log",
        runtime_dir=tmp_path,
    )
    _write_service_record(
        "worker",
        pid=9002,
        host="127.0.0.1",
        port=8001,
        log_path=tmp_path / "worker.log",
        runtime_dir=tmp_path,
    )
    _clear_service_record("gateway", tmp_path)
    assert _get_service_record("gateway", tmp_path) is None
    assert _get_service_record("worker", tmp_path) is not None


def test_get_service_record_returns_none_when_absent(tmp_path: Path) -> None:
    """_get_service_record returns None when no record is present."""
    result = _get_service_record("gateway", tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------


def test_service_status_stopped_when_no_record(tmp_path: Path) -> None:
    """Status is 'stopped' and tracked=False when no registry entry exists."""
    status = _service_status("gateway", tmp_path)
    assert status["status"] == "stopped"
    assert status["tracked"] is False
    assert status["pid"] is None


def test_service_status_pid_stale_when_process_dead(tmp_path: Path) -> None:
    """Status is 'pid-stale' when the recorded PID is no longer running."""
    # PID 1 is always running on Linux; on Windows we need a dead PID.
    # Use a PID that is guaranteed to not be a real process: 2^22-1 (Linux max).
    dead_pid = 4194303
    _write_service_record(
        "gateway",
        pid=dead_pid,
        host="127.0.0.1",
        port=8099,
        log_path=tmp_path / "gateway.log",
        runtime_dir=tmp_path,
    )
    # Verify the PID is actually dead on this machine before asserting.
    if _is_pid_running(dead_pid):
        pytest.skip(f"PID {dead_pid} is unexpectedly alive on this machine")

    status = _service_status("gateway", tmp_path)
    assert status["status"] == "pid-stale"
    assert status["tracked"] is True
    assert status["pid"] == dead_pid


# ---------------------------------------------------------------------------
# Stop service (registry-only path — no live process)
# ---------------------------------------------------------------------------


def test_stop_service_returns_not_tracked_when_no_record(tmp_path: Path) -> None:
    """_stop_service returns 'not-tracked' when the registry has no entry."""
    result = _stop_service("gateway", runtime_dir=tmp_path)
    assert result == "not-tracked"


def test_stop_service_clears_stale_pid_record(tmp_path: Path) -> None:
    """_stop_service clears a stale PID entry and returns 'pid-stale'."""
    dead_pid = 4194303
    _write_service_record(
        "worker",
        pid=dead_pid,
        host="127.0.0.1",
        port=8099,
        log_path=tmp_path / "worker.log",
        runtime_dir=tmp_path,
    )
    if _is_pid_running(dead_pid):
        pytest.skip(f"PID {dead_pid} is unexpectedly alive on this machine")

    result = _stop_service("worker", runtime_dir=tmp_path)
    assert result == "pid-stale"
    # Registry entry must be cleared after a stale-pid stop.
    assert _get_service_record("worker", tmp_path) is None


# ---------------------------------------------------------------------------
# Registry JSON format
# ---------------------------------------------------------------------------


def test_registry_file_is_valid_json(tmp_path: Path) -> None:
    """The persisted registry file is valid JSON readable by the stdlib."""
    _write_service_record(
        "gateway",
        pid=42,
        host="0.0.0.0",
        port=8000,
        log_path=tmp_path / "gw.log",
        runtime_dir=tmp_path,
    )
    raw = (tmp_path / "services.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert "services" in parsed
    assert "gateway" in parsed["services"]
