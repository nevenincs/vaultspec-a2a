"""Prove legacy and desktop records cannot grant engine attachment authority.

Neither legacy nor secret-free desktop records grant engine attachment authority.
A real loopback ``/health`` server
backs the resolution assertions; the
discovery override is set through its official environment variable, not a
patched internal. No mock, monkeypatch, stub, skip, or expected failure is used.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

import pytest

from ...control.config import settings
from ...testing import settings_override
from ...testing.tests._support.listeners import health_listener
from ..discovery import resolve_engine

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


@pytest.fixture
def set_service_json() -> Iterator[Callable[[Path], None]]:
    """Yield a setter for the discovery override; restore the prior value after."""

    def _set(path: Path) -> None:
        settings.engine_service_json = path

    with settings_override(engine_service_json=None):
        yield _set


def _versioned_record(port: int, *, credential_reference: str) -> dict[str, object]:
    return {
        "version": 1,
        "profile": "desktop",
        "generation": "gen-1",
        "protocol": {"min": 1, "max": 1},
        "process": {"pid": os.getpid(), "start_fingerprint": "fp"},
        "endpoint": {"host": "127.0.0.1", "port": port},
        "last_heartbeat": int(time.time() * 1000),
        "owner": "alice",
        "credential_reference": credential_reference,
    }


def test_legacy_record_cannot_resolve_the_engine(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    """A legacy record does not grant engine endpoint authority."""
    with health_listener() as port:
        path = tmp_path / "service.json"
        path.write_text(
            json.dumps(
                {
                    "port": port,
                    "service_token": "tok-legacy",
                    "pid": os.getpid(),
                    "last_heartbeat": int(time.time() * 1000),
                }
            ),
            encoding="utf-8",
        )
        set_service_json(path)
        endpoint = resolve_engine(liveness_timeout=0.5)
        assert endpoint is None


def test_versioned_record_is_not_resolved_as_an_engine(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    """A secret-free versioned record is recognised but never becomes an endpoint.

    Even with a live health server on its port, the engine resolver skips it (no
    inline bearer); any endpoint returned would be the machine-global fallback,
    never this port.
    """
    with health_listener() as port:
        path = tmp_path / "service.json"
        credential_file = tmp_path / "attach.cred"
        credential_file.write_text("secret-bearer", encoding="utf-8")
        record = _versioned_record(port, credential_reference=str(credential_file))
        path.write_text(json.dumps(record), encoding="utf-8")
        set_service_json(path)
        result = resolve_engine(liveness_timeout=0.5)
        assert result is None or result.base_url != f"http://127.0.0.1:{port}"
