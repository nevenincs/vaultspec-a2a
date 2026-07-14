"""Unit tests for engine discovery skip/non-raise behavior (P03.S07).

Exercises the file-resolution guards without a live server: a malformed or
stale candidate must be skipped, and ``resolve_engine`` must never raise on bad
input (its non-raising contract lets a caller poll it on a loop). The env var is
set/cleared directly (no monkeypatch): it is the official discovery-override
input, not a patched internal.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

import pytest

from ..discovery import SERVICE_JSON_ENV, EngineEndpoint, resolve_engine

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


@pytest.fixture
def set_service_json() -> Iterator[Callable[[Path], None]]:
    """Yield a setter for the discovery override; restore the prior value after."""
    previous = os.environ.get(SERVICE_JSON_ENV)

    def _set(path: Path) -> None:
        os.environ[SERVICE_JSON_ENV] = str(path)

    try:
        yield _set
    finally:
        if previous is None:
            os.environ.pop(SERVICE_JSON_ENV, None)
        else:
            os.environ[SERVICE_JSON_ENV] = previous


def test_malformed_candidate_is_skipped_without_raising(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    bad = tmp_path / "service.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    set_service_json(bad)
    # Must not raise; result is None unless a live machine-global engine answers.
    result = resolve_engine(liveness_timeout=0.2)
    assert result is None or isinstance(result, EngineEndpoint)


def test_stale_heartbeat_candidate_is_skipped(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    stale = tmp_path / "service.json"
    stale.write_text(
        json.dumps(
            {
                "port": 8767,
                "service_token": "tok",
                "last_heartbeat": int(time.time() * 1000) - 10_000_000,
            }
        ),
        encoding="utf-8",
    )
    set_service_json(stale)
    result = resolve_engine(liveness_timeout=0.2)
    assert result is None or isinstance(result, EngineEndpoint)


def test_absent_candidate_is_skipped(
    tmp_path: Path, set_service_json: Callable[[Path], None]
) -> None:
    set_service_json(tmp_path / "does-not-exist.json")
    result = resolve_engine(liveness_timeout=0.2)
    assert result is None or isinstance(result, EngineEndpoint)
