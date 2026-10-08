"""A retained frame carries the trace that produced it.

``run_events`` has carried nullable ``trace_id`` and ``span_id`` columns since
the table was created, and nothing ever wrote them: the one correlation a
post-hoc reader needs - which request produced this frame - was absent from
every row. The ids are stamped in the same act that stamps the production
time, because that act is the only moment the producing trace is still in
scope; the durable write happens behind the fan-out, in a batch whose own
context says nothing about any one frame in it.

Real throughout: a real SDK tracer and real recording spans (no exporter is
intercepted and no span is faked), the real allocator and recorder, and the
real SQLite replay table read back through the production store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace.span import format_span_id, format_trace_id

from ...database import RunEventStore, create_thread
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..run_event_writer import RunEventWriter
from ..subscribers import RelayHub, RunSequenceAllocator

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from opentelemetry.trace import Tracer
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ...database import RunEventRecord

_RUN = "trace-stamped-run"

#: A cadence no test reaches by waiting, so every write below is one a test
#: asked for.
_IDLE_CADENCE = 30.0


class _Relay:
    """A real store, a real recorder and the hub that numbers frames into them."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.store = RunEventStore(session_factory)
        self.writer = RunEventWriter(
            self.store, window=100, flush_interval_seconds=_IDLE_CADENCE
        )
        self.hub = RelayHub()
        self.hub.bind_sequence_allocator(
            RunSequenceAllocator(self.store), sink=self.writer
        )

    async def relay(self, count: int) -> None:
        """Relay *count* worker frames through the real numbering chokepoint."""
        await self.hub.prepare_run(_RUN)
        for index in range(1, count + 1):
            self.hub.relay_payload(_RUN, _frame(index))

    async def stored(self) -> list[RunEventRecord]:
        return await self.store.read_after(thread_id=_RUN, after_sequence=0, limit=1000)


def _frame(index: int) -> dict[str, Any]:
    return {
        "type": "agent_status",
        "event_type": "agent_status",
        "thread_id": _RUN,
        "agent_id": "coder",
        "state": "working",
        "sequence": index,
    }


@pytest_asyncio.fixture
async def relay(
    migrated_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[_Relay]:
    """A relay over the migrated replay table, with the run it numbers seeded."""
    built = _Relay(migrated_session_factory)
    async with migrated_session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=_RUN,
            status=ThreadStatus.RUNNING,
        )
        await session.commit()
    try:
        yield built
    finally:
        await built.writer.aclose()


@pytest.fixture
def tracer() -> Tracer:
    """A real SDK tracer whose spans record and carry a valid context."""
    provider = TracerProvider(
        resource=Resource.create({"service.name": "run-event-trace-test"})
    )
    return provider.get_tracer(__name__)


@pytest.mark.asyncio
async def test_every_retained_frame_carries_the_producing_trace(
    relay: _Relay, tracer: Tracer
) -> None:
    """Each row names the trace and the span the frame was produced under.

    The ids are compared against the span the test itself holds, not merely
    asserted non-null: a writer that stamped a well-formed id from some other
    context would correlate a frame to the wrong request, which is worse than
    leaving the column empty.
    """
    with tracer.start_as_current_span("relay batch") as span:
        context = span.get_span_context()
        await relay.relay(3)
        await relay.writer.flush()

    rows = await relay.stored()

    assert [row.sequence for row in rows] == [1, 2, 3]
    assert [row.trace_id for row in rows] == [format_trace_id(context.trace_id)] * 3
    assert [row.span_id for row in rows] == [format_span_id(context.span_id)] * 3
    for row in rows:
        assert row.trace_id is not None and len(row.trace_id) == 32
        assert row.span_id is not None and len(row.span_id) == 16


@pytest.mark.asyncio
async def test_frames_produced_under_no_trace_leave_both_columns_empty(
    relay: _Relay,
) -> None:
    """No valid span context, no correlation: NULL rather than a zero id.

    An invalid context formats as all-zero ids, which read as a trace that
    exists. The absence has to look like absence, so a reader joining on these
    columns finds nothing instead of finding a trace nobody recorded.
    """
    await relay.relay(2)
    await relay.writer.flush()

    rows = await relay.stored()

    assert [row.sequence for row in rows] == [1, 2]
    assert [row.trace_id for row in rows] == [None, None]
    assert [row.span_id for row in rows] == [None, None]


@pytest.mark.asyncio
async def test_each_frame_names_the_span_it_was_produced_under(
    relay: _Relay, tracer: Tracer
) -> None:
    """Two batches in two spans of one trace stay distinguishable.

    The stamp is taken per allocation rather than once per run, which is what
    lets a reader tell the request that produced one frame from the request
    that produced the next. Stamping at the durable write instead would give
    every frame of a flush the flush's own context.
    """
    with tracer.start_as_current_span("first batch") as first:
        first_context = first.get_span_context()
        await relay.relay(1)
    with tracer.start_as_current_span("second batch") as second:
        second_context = second.get_span_context()
        await relay.hub.prepare_run(_RUN)
        relay.hub.relay_payload(_RUN, _frame(2))
    await relay.writer.flush()

    rows = await relay.stored()

    assert first_context.span_id != second_context.span_id
    assert [row.span_id for row in rows] == [
        format_span_id(first_context.span_id),
        format_span_id(second_context.span_id),
    ]
    assert [row.trace_id for row in rows] == [
        format_trace_id(first_context.trace_id),
        format_trace_id(second_context.trace_id),
    ]
