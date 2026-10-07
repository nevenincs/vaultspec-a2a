"""Seat the gateway's replay recorder on the app that relays into it.

The pieces live below this module - the store in the database package, the
ring and its batch in the streaming package - and only the API boundary holds
the app state that binds them to one gateway. Assembling them here keeps that
dependency pointing the right way and keeps the relay route to a few lines.

Seated lazily on first relay rather than at startup, deliberately: the
recorder needs the relay hub and the application session factory, both of
which the lifespan seats, and reaching for them when the first frame arrives
avoids a second startup ordering to get wrong.
"""

from __future__ import annotations

from typing import Any, cast

from ..control.config import settings
from ..database.run_event_repository import RunEventStore
from ..streaming import RunEventWriter, RunSequenceAllocator

__all__ = ["replay_writer_seat", "seated_replay_writer"]

_STATE_ATTRIBUTE = "run_event_writer"


def replay_writer_seat(app: Any) -> RunEventWriter | None:
    """Return the app's replay recorder if one is seated, seating nothing.

    The read-only companion to :func:`seated_replay_writer`, for the stream
    that serves a replay rather than records one. Seating binds the run
    numbering authority as a side effect, which belongs to the relay that
    writes frames and not to a viewer that reads them: a gateway with no
    recorder has retained nothing in memory, so a resume reads the table and
    is complete.
    """
    return cast("RunEventWriter | None", getattr(app.state, _STATE_ATTRIBUTE, None))


def seated_replay_writer(app: Any, session_factory: Any) -> RunEventWriter | None:
    """Return the app's replay recorder, seating it on first use.

    ``None`` whenever the feature is off or the app has nothing to write
    into - a host embedding the relay router without a store, or a gateway
    whose lifespan has not seated its relay hub yet. The numbering authority
    is bound in the same act, so a gateway either numbers and retains or does
    neither, and never hands out an id it cannot resume from.

    Every frame crossing the gateway's fan-out is a relayed worker payload,
    already projected onto the positive progress catalog, so the recorder's
    default retains each as it stands.

    *session_factory* is the one the relay already resolved, rather than one
    resolved again here: an app that declared it has no database must not have
    the process database opened behind it by a second resolution.
    """
    if not settings.stream_replay_enabled:
        return None
    seated = getattr(app.state, _STATE_ATTRIBUTE, None)
    if seated is not None:
        return cast("RunEventWriter", seated)

    relay_hub = getattr(app.state, "relay_hub", None)
    if session_factory is None or relay_hub is None:
        return None

    store = RunEventStore(session_factory)
    writer = RunEventWriter(store, window=settings.stream_replay_window_events)
    relay_hub.bind_sequence_allocator(RunSequenceAllocator(store), sink=writer)
    setattr(app.state, _STATE_ATTRIBUTE, writer)
    return writer
