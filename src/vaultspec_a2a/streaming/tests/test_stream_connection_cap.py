"""The subscriber registry must be globally bounded wherever a caller enters it.

The gateway admits stream subscribers from two places - the SSE progress route
and the event WebSocket - and both register against one shared registry. A limit
checked inside one route is therefore not a limit at all: the other path admits
subscribers that check never observes. The SSE route's own pre-check is weaker
still, because it runs while building the response and the registration it
authorises does not happen until the client starts reading the body.

So the bound has to hold at the registry itself. These drive the real aggregator
at its real shipped default rather than a tuned-down cap, so the limit under test
is the value operators actually run.
"""

from __future__ import annotations

import pytest

from ...control.config import Settings
from ...domain_config import domain_config
from ...telemetry.aggregator_hook import OTelAggregatorHook
from ...thread.errors import EventAggregatorError
from ..aggregator import EventAggregator


@pytest.fixture
def aggregator() -> EventAggregator:
    """Return a fresh EventAggregator for each test."""
    return EventAggregator()


def _fill(aggregator: EventAggregator, count: int, *, prefix: str = "client") -> None:
    for index in range(count):
        aggregator.add_subscriber(f"{prefix}-{index}")


def test_the_limit_has_a_bounded_positive_default() -> None:
    """An absent or zero default would leave the registry unbounded."""
    assert 0 < domain_config.max_stream_connections <= 10_000


def test_the_domain_and_infrastructure_views_report_one_limit() -> None:
    """Both layers must read a single value, not two that can drift apart.

    The registry enforces the bound and the SSE route pre-checks it, so the two
    reads have to be the same number. Declaring the field twice would satisfy
    every other test here while letting the enforced limit and the advertised one
    diverge, which is precisely the failure this guards.
    """
    assert Settings().max_stream_connections == domain_config.max_stream_connections


def test_the_registry_admits_subscribers_up_to_the_cap(
    aggregator: EventAggregator,
) -> None:
    """The limit admits exactly its configured number, not one fewer."""
    limit = domain_config.max_stream_connections

    _fill(aggregator, limit)

    assert aggregator.subscriber_count() == limit


def test_the_subscriber_past_the_cap_is_refused(aggregator: EventAggregator) -> None:
    """One past the limit raises rather than silently extending the registry."""
    limit = domain_config.max_stream_connections
    _fill(aggregator, limit)

    with pytest.raises(EventAggregatorError, match="global limit"):
        aggregator.add_subscriber("one-client-too-many")


def test_a_refused_subscriber_leaves_the_registry_unchanged(
    aggregator: EventAggregator,
) -> None:
    """A refusal must not half-register the caller.

    A client left in the registry without a usable queue would consume a slot for
    a stream nobody is reading, so the refusal has to be complete.
    """
    limit = domain_config.max_stream_connections
    _fill(aggregator, limit)

    with pytest.raises(EventAggregatorError):
        aggregator.add_subscriber("one-client-too-many")

    assert aggregator.subscriber_count() == limit
    assert aggregator.get_subscriber_queue("one-client-too-many") is None


def test_the_cap_is_global_rather_than_per_client(
    aggregator: EventAggregator,
) -> None:
    """Distinct client identities share one bound.

    The sibling subscription cap is deliberately per-client; this one is
    deliberately not. Keying it per-client would make it trivially evadable by
    the very behaviour it exists to stop - opening more connections.
    """
    limit = domain_config.max_stream_connections
    _fill(aggregator, limit // 2, prefix="sse")
    _fill(aggregator, limit - limit // 2, prefix="ws")

    with pytest.raises(EventAggregatorError):
        aggregator.add_subscriber("a-wholly-unrelated-client")


def test_re_registering_a_held_client_at_capacity_is_not_refused(
    aggregator: EventAggregator,
) -> None:
    """Replacing a held client's queue must stay possible at capacity.

    Re-registering an existing id swaps that client's queue rather than growing
    the registry, so refusing it would break reconnect traffic without freeing a
    single slot - the same reasoning as the idempotent re-subscribe.
    """
    limit = domain_config.max_stream_connections
    _fill(aggregator, limit)

    queue = aggregator.add_subscriber("client-0")

    assert queue is not None
    assert aggregator.subscriber_count() == limit


def test_removing_a_subscriber_frees_capacity(aggregator: EventAggregator) -> None:
    """The cap bounds concurrent subscribers, not lifetime total."""
    limit = domain_config.max_stream_connections
    _fill(aggregator, limit)
    aggregator.remove_subscriber("client-0")

    aggregator.add_subscriber("a-later-arrival")

    assert aggregator.subscriber_count() == limit


def test_a_refusal_emits_the_operational_counter() -> None:
    """The refusal is observable to operators, not only to the caller.

    Uses the real OTel hook against a real meter rather than a stand-in: it
    registers each counter lazily on first use, so the counter's presence in the
    hook's registry is proof the production path actually recorded it. The
    control below shows the same registry is empty without a refusal, so this
    cannot pass on a counter some other code path registered.
    """
    hook = OTelAggregatorHook()
    aggregator = EventAggregator(telemetry=hook)
    _fill(aggregator, domain_config.max_stream_connections)

    with pytest.raises(EventAggregatorError):
        aggregator.add_subscriber("one-client-too-many")

    assert "aggregator.subscribers_refused" in hook._counters


def test_an_admitted_subscriber_emits_no_refusal_counter() -> None:
    """Control: the counter tracks refusals, not registrations."""
    hook = OTelAggregatorHook()
    aggregator = EventAggregator(telemetry=hook)

    aggregator.add_subscriber("client-0")

    assert "aggregator.subscribers_refused" not in hook._counters
