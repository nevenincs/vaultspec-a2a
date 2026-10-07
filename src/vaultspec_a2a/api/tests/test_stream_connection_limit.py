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

from ...api.thread_stream import ThreadStreamRequest, build_thread_stream_response
from ...domain_config import DomainSettingsConfig, domain_config
from ...streaming import RelayHub

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _aggregator_with(subscribers: int) -> RelayHub:
    aggregator = RelayHub()
    for index in range(subscribers):
        aggregator.add_subscriber(f"client-{index}")
    return aggregator


def test_the_limit_has_a_bounded_positive_default() -> None:
    """An absent or zero default would leave the surface unbounded."""
    assert 0 < domain_config.max_stream_connections <= 10_000


def test_the_limit_is_operator_overridable() -> None:
    """Deployments differ; the bound must be tunable without a code change."""
    assert DomainSettingsConfig(max_stream_connections=8).max_stream_connections == 8


def test_the_subscriber_count_tracks_registration() -> None:
    """The limit is only as good as the count it reads."""
    aggregator = _aggregator_with(3)

    assert aggregator.subscriber_count() == 3

    aggregator.remove_subscriber("client-1")

    assert aggregator.subscriber_count() == 2


@pytest.mark.asyncio
async def test_a_stream_is_refused_at_capacity_without_touching_the_database() -> None:
    """At capacity the refusal happens first, so no session is required.

    Passing a null database and a null session factory proves the ordering: if
    either were reached before the limit, this would raise an attribute error
    rather than the service-unavailable the caller should see. The casts are the
    honest shape - the arguments really are absent, and the test asserts neither
    is reached.
    """
    limit = domain_config.max_stream_connections
    aggregator = _aggregator_with(limit)

    with pytest.raises(HTTPException) as raised:
        await build_thread_stream_response(
            ThreadStreamRequest(
                thread_id="any-thread",
                aggregator=aggregator,
                session_factory=cast("async_sessionmaker[AsyncSession]", None),
            ),
            db=cast("AsyncSession", None),
        )

    assert raised.value.status_code == 503
    assert raised.value.headers is not None
    assert raised.value.headers.get("Retry-After") == "5"
