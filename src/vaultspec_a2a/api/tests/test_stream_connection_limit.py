"""The progress stream must be bounded, and bounded cheaply.

Authentication stops a stranger opening a stream; it does not stop an
authenticated caller opening ten thousand. Each subscriber holds a bounded queue
and a delivery path, so an unbounded count is a resource-exhaustion surface even
behind a bearer.

The refusal is decided from process-local state before the thread lookup, because
a flood that exhausts queues would multiply that database round trip too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from fastapi import HTTPException

from vaultspec_a2a.api.routes.thread_stream import build_thread_stream_response
from vaultspec_a2a.control.config import Settings
from vaultspec_a2a.streaming.aggregator import EventAggregator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _aggregator_with(subscribers: int) -> EventAggregator:
    aggregator = EventAggregator()
    for index in range(subscribers):
        aggregator.add_subscriber(f"client-{index}")
    return aggregator


def test_the_limit_has_a_bounded_positive_default() -> None:
    """An absent or zero default would leave the surface unbounded."""
    assert 0 < Settings().max_stream_connections <= 10_000


def test_the_limit_is_operator_overridable() -> None:
    """Deployments differ; the bound must be tunable without a code change."""
    assert Settings(VAULTSPEC_MAX_STREAM_CONNECTIONS=8).max_stream_connections == 8


def test_the_subscriber_count_tracks_registration() -> None:
    """The limit is only as good as the count it reads."""
    aggregator = _aggregator_with(3)

    assert aggregator.subscriber_count() == 3

    aggregator.remove_subscriber("client-1")

    assert aggregator.subscriber_count() == 2


@pytest.mark.asyncio
async def test_a_stream_is_refused_at_capacity_without_touching_the_database() -> None:
    """At capacity the refusal happens first, so no session is required.

    Passing a null database proves the ordering: if the lookup ran before the
    limit, this would raise an attribute error rather than the
    service-unavailable the caller should see. The cast is the honest shape - the
    argument really is absent, and the test asserts it is never reached.
    """
    limit = Settings().max_stream_connections
    aggregator = _aggregator_with(limit)

    with pytest.raises(HTTPException) as raised:
        await build_thread_stream_response(
            db=cast("AsyncSession", None),
            aggregator=aggregator,
            thread_id="any-thread",
        )

    assert raised.value.status_code == 503
    assert raised.value.headers is not None
    assert raised.value.headers.get("Retry-After") == "5"
