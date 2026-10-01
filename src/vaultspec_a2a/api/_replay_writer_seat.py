"""Seat the gateway's replay recorder on the app that relays into it.

The pieces live below this module - the store in the database package, the
ring and its batch in the streaming package - and only the API boundary knows
how to project an in-process domain event onto the wire, which is the one
thing the recorder cannot work out for itself. Assembling them here keeps that
dependency pointing the right way and keeps the relay route to a few lines.

Seated lazily on first relay rather than at startup, deliberately: the
recorder needs the aggregator and the application session factory, both of
which the lifespan seats, and reaching for them when the first frame arrives
avoids a second startup ordering to get wrong.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ..control.config import settings
from ..database.run_event_repository import RunEventStore
from ..streaming import RunEventWriter, RunSequenceAllocator, SequencedEvent
from .event_adapter import sequenced_to_positive_payload

__all__ = ["seated_replay_writer"]

_STATE_ATTRIBUTE = "run_event_writer"


def _outgoing_frame_body(frame: object) -> Mapping[str, object] | None:
    """Return the body a subscriber was handed, for the frame to be retained.

    Both producer shapes cross the chokepoint. A relayed worker payload has
    already been projected onto the positive progress catalog, so it is stored
    as it stands. An in-process domain event has not, and is projected through
    the same boundary the stream itself uses - which is what keeps the stored
    row free of prompts, document bodies, edit diffs and provider payloads by
    construction rather than by review.
    """
    if isinstance(frame, Mapping):
        return cast("Mapping[str, object]", frame)
    if isinstance(frame, SequencedEvent):
        return sequenced_to_positive_payload(frame)
    return None


def seated_replay_writer(app: Any, session_factory: Any) -> RunEventWriter | None:
    """Return the app's replay recorder, seating it on first use.

    ``None`` whenever the feature is off or the app has nothing to write
    into - a host embedding the relay router without a store, or a gateway
    whose lifespan has not seated its aggregator yet. The numbering authority
    is bound in the same act, so a gateway either numbers and retains or does
    neither, and never hands out an id it cannot resume from.

    *session_factory* is the one the relay already resolved, rather than one
    resolved again here: an app that declared it has no database must not have
    the process database opened behind it by a second resolution.
    """
    if not settings.stream_replay_enabled:
        return None
    seated = getattr(app.state, _STATE_ATTRIBUTE, None)
    if seated is not None:
        return cast("RunEventWriter", seated)

    aggregator = getattr(app.state, "aggregator", None)
    if session_factory is None or aggregator is None:
        return None

    store = RunEventStore(session_factory)
    writer = RunEventWriter(
        store,
        window=settings.stream_replay_window_events,
        project=_outgoing_frame_body,
    )
    aggregator.bind_sequence_allocator(RunSequenceAllocator(store), sink=writer)
    setattr(app.state, _STATE_ATTRIBUTE, writer)
    return writer
