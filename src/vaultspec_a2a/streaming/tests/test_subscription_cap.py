"""A single client must not be able to demand unbounded fan-out work.

The gateway's connection limit bounds how many stream clients exist. It says
nothing about what each one costs: every subscription a client holds is matched
against every broadcast event, so an authenticated caller could previously issue
one `subscribe` with an arbitrarily long thread list and multiply the gateway's
per-event work without opening a second connection.

These drive the real aggregator at its real shipped default rather than a
tuned-down one, so the limit under test is the value operators actually run.
"""

from __future__ import annotations

import pytest

from ...domain_config import domain_config
from ...telemetry.aggregator_hook import OTelAggregatorHook
from ...thread.errors import EventAggregatorError
from ..aggregator import EventAggregator


@pytest.fixture
def aggregator() -> EventAggregator:
    """Return a fresh EventAggregator for each test."""
    return EventAggregator()


def _threads(start: int, count: int) -> list[str]:
    return [f"thread-{n}" for n in range(start, start + count)]


def test_a_client_may_hold_subscriptions_up_to_the_cap(
    aggregator: EventAggregator,
) -> None:
    """The limit admits exactly its configured number, not one fewer."""
    limit = domain_config.max_subscriptions_per_client
    aggregator.add_subscriber("client-1")

    aggregator.subscribe("client-1", _threads(0, limit))

    assert len(aggregator.get_subscriptions("client-1")) == limit


def test_the_request_that_would_cross_the_cap_is_refused(
    aggregator: EventAggregator,
) -> None:
    """One past the limit raises rather than silently extending the fan-out."""
    limit = domain_config.max_subscriptions_per_client
    aggregator.add_subscriber("client-1")
    aggregator.subscribe("client-1", _threads(0, limit))

    with pytest.raises(EventAggregatorError, match="per-client limit"):
        aggregator.subscribe("client-1", ["one-thread-too-many"])


def test_a_refused_request_leaves_the_existing_subscriptions_intact(
    aggregator: EventAggregator,
) -> None:
    """Refusal is all-or-nothing.

    A partially applied subscription is worse than a refusal: the client is told
    nothing and believes it is watching threads the gateway never registered.
    """
    limit = domain_config.max_subscriptions_per_client
    aggregator.add_subscriber("client-1")
    aggregator.subscribe("client-1", _threads(0, limit))
    before = aggregator.get_subscriptions("client-1")

    with pytest.raises(EventAggregatorError):
        aggregator.subscribe("client-1", _threads(limit, 50))

    after = aggregator.get_subscriptions("client-1")
    assert after == before
    assert not any(t in after for t in _threads(limit, 50))


def test_one_oversized_request_is_refused_outright(
    aggregator: EventAggregator,
) -> None:
    """The cap holds against a single huge list, not just incremental growth.

    This is the shape the finding names - one `subscribe` carrying an unbounded
    thread list - so it must be refused on the first call rather than only after
    a client has walked up to the limit.
    """
    limit = domain_config.max_subscriptions_per_client
    aggregator.add_subscriber("client-1")

    with pytest.raises(EventAggregatorError):
        aggregator.subscribe("client-1", _threads(0, limit * 4))

    assert aggregator.get_subscriptions("client-1") == frozenset()


def test_resubscribing_to_held_threads_at_the_cap_is_not_refused(
    aggregator: EventAggregator,
) -> None:
    """Re-sending a subscription must stay idempotent.

    Counting duplicates against the cap would break ordinary reconnect traffic,
    where a client replays the set it already holds.
    """
    limit = domain_config.max_subscriptions_per_client
    aggregator.add_subscriber("client-1")
    held = _threads(0, limit)
    aggregator.subscribe("client-1", held)

    aggregator.subscribe("client-1", held)

    assert len(aggregator.get_subscriptions("client-1")) == limit


def test_the_cap_is_per_client_not_global(aggregator: EventAggregator) -> None:
    """A second client is unaffected by the first reaching its limit.

    The global bound on client count is the connection limit's job; conflating
    the two here would refuse legitimate clients.
    """
    limit = domain_config.max_subscriptions_per_client
    aggregator.add_subscriber("client-1")
    aggregator.add_subscriber("client-2")
    aggregator.subscribe("client-1", _threads(0, limit))

    aggregator.subscribe("client-2", _threads(0, limit))

    assert len(aggregator.get_subscriptions("client-2")) == limit


def test_a_refusal_emits_the_operational_counter() -> None:
    """The refusal is observable to operators, not just to the caller.

    Uses the real OTel hook against a real meter rather than a stand-in: it
    registers each counter lazily on first use, so the counter's presence in the
    hook's registry is proof the production path actually recorded it. The
    control below shows the same registry is empty without a refusal, so this
    cannot pass on a counter registered by some other code path.
    """
    hook = OTelAggregatorHook()
    aggregator = EventAggregator(telemetry=hook)
    limit = domain_config.max_subscriptions_per_client
    aggregator.add_subscriber("client-1")

    with pytest.raises(EventAggregatorError):
        aggregator.subscribe("client-1", _threads(0, limit + 1))

    assert "aggregator.subscriptions_refused" in hook._counters


def test_an_accepted_subscription_emits_no_refusal_counter() -> None:
    """Control: the counter tracks refusals, not subscribe calls."""
    hook = OTelAggregatorHook()
    aggregator = EventAggregator(telemetry=hook)
    aggregator.add_subscriber("client-1")

    aggregator.subscribe("client-1", _threads(0, 5))

    assert "aggregator.subscriptions_refused" not in hook._counters


def test_unsubscribing_frees_capacity_again(aggregator: EventAggregator) -> None:
    """The cap bounds concurrent held subscriptions, not lifetime total."""
    limit = domain_config.max_subscriptions_per_client
    aggregator.add_subscriber("client-1")
    aggregator.subscribe("client-1", _threads(0, limit))
    aggregator.unsubscribe("client-1", _threads(0, 10))

    aggregator.subscribe("client-1", _threads(limit, 10))

    assert len(aggregator.get_subscriptions("client-1")) == limit
