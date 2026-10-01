"""The JSON log lane keeps every record, versions its shape, and redacts secrets.

A real logger writes through the production formatter and filters into a real
stream, and each line is parsed back. The correlation scope is exercised the
way the executor uses it: across an ``await`` and into a task it starts.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from ..logging import LOG_SCHEMA, JSONFormatter, LogContextFilter, log_context

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def lane() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter(service="worker"))
    handler.addFilter(LogContextFilter())
    logger = logging.getLogger(f"vaultspec_a2a.test_logging_contract.{id(stream)}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        yield logger, stream
    finally:
        logger.removeHandler(handler)


def _lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def test_a_value_json_cannot_encode_never_loses_the_record(
    lane: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = lane
    logger.info(
        "odd extras",
        extra={
            "workspace": Path("/tmp/project"),
            "seen": {"a"},
            "at": datetime(2026, 9, 30, tzinfo=UTC),
            "handle": object(),
        },
    )

    (line,) = _lines(stream)
    assert line["message"] == "odd extras"
    assert line["workspace"] == str(Path("/tmp/project"))
    assert line["seen"] == ["a"]
    assert line["at"] == "2026-09-30T00:00:00+00:00"
    assert line["handle"].startswith("<object object")


def test_every_line_carries_the_schema_zone_process_service_and_sequence(
    lane: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = lane
    logger.info("one")
    logger.warning("two")

    first, second = _lines(stream)
    assert first["schema"] == second["schema"] == LOG_SCHEMA
    assert first["timestamp"].endswith("+00:00")
    assert first["pid"] == os.getpid()
    assert first["service"] == "worker"
    assert second["seq"] == first["seq"] + 1


def test_credentials_are_redacted_and_counts_are_not(
    lane: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = lane
    logger.info(
        "calling with Bearer abcdefghijklmnop and sk-live0123456789abcdef",
        extra={
            "api_key": "plain-looking",
            "actor_token": "opaque",
            "input_tokens": 12,
            "token_usage": {"coder": {"input_tokens": 12}},
            "headers": {"Authorization": "Basic Zm9v", "Accept": "text/plain"},
        },
    )

    (line,) = _lines(stream)
    assert "abcdefghijklmnop" not in line["message"]
    assert "sk-live0123456789abcdef" not in line["message"]
    assert line["api_key"] == "[redacted]"
    assert line["actor_token"] == "[redacted]"
    assert line["input_tokens"] == 12
    assert line["token_usage"] == {"coder": {"input_tokens": 12}}
    assert line["headers"] == {"Authorization": "[redacted]", "Accept": "text/plain"}


def test_an_extra_named_like_a_line_field_is_kept_beside_it(
    lane: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = lane
    logger.info("collide", extra={"timestamp": "caller's own"})

    (line,) = _lines(stream)
    assert line["extra_timestamp"] == "caller's own"
    assert line["timestamp"].endswith("+00:00")


@pytest.mark.asyncio
async def test_the_correlation_scope_follows_awaits_and_tasks(
    lane: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = lane

    async def child() -> None:
        await asyncio.sleep(0)
        logger.info("from a task")

    with log_context(thread_id="run-1", dispatch_id="d-1"):
        await asyncio.sleep(0)
        logger.info("after an await")
        await asyncio.create_task(child())
        with log_context(dispatch_id="d-2"):
            logger.info("nested", extra={"thread_id": "caller-wins"})
    logger.info("outside")

    awaited, tasked, nested, outside = _lines(stream)
    assert (awaited["thread_id"], awaited["dispatch_id"]) == ("run-1", "d-1")
    assert (tasked["thread_id"], tasked["dispatch_id"]) == ("run-1", "d-1")
    assert (nested["thread_id"], nested["dispatch_id"]) == ("caller-wins", "d-2")
    assert "thread_id" not in outside and "dispatch_id" not in outside
