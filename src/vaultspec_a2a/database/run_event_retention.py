"""Age retention for the bounded per-run progress replay log.

The replay log has two bounds and this module owns the second of them. The
row bound belongs to the writer, which trims each run to its newest N in the
same batch that appends to it; nothing here can see a run the writer never
touched again. The age bound is this sweep: a window kept for a run nobody
will resume is storage with no reader, and a run that ended yesterday has no
reader at all.

This retention is the replay log's OWN and is independent of checkpoint
retention in both directions. Nothing here reads or deletes a checkpoint -
the sweep runs on the application session factory and names one table - and
the settled-checkpoint prune reads and deletes no replay row. The two are
easy to conflate because both are triggered by a run settling, and conflating
them would make a checkpoint's lifetime decide how long a stream stays
resumable, which is a coupling neither side wants.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .run_event_repository import RunEventStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["sweep_replay_log", "sweep_replay_log_periodically"]

logger = logging.getLogger(__name__)

#: How often the gateway sweeps while it is up. Tuning, not contract: the
#: bound the sweep enforces is a setting, and this only decides how promptly
#: an expired row stops occupying space. Short enough that a long-lived
#: gateway collects steadily, long enough that it is not a background write
#: load on a database shared with a worker.
DEFAULT_SWEEP_INTERVAL_SECONDS = 900.0


async def sweep_replay_log(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_hours: float,
    now: datetime | None = None,
) -> int:
    """Delete the replay rows past their age bound and return how many.

    Two deletes under one bound, because the row that each one reaches alone
    is different. The first removes everything a run settled long ago still
    holds, including a frame stamped after its terminal. The second removes
    anything produced before the cutoff, which is what bounds a run that is
    still going: a week-long run must not accumulate a week of frames just
    because it has not ended.

    *now* is injected so a caller can state the moment the bound is measured
    from rather than racing the clock; production passes nothing and gets the
    real one.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=retention_hours)
    store = RunEventStore(session_factory)
    deleted = await store.delete_for_runs_settled_before(cutoff)
    deleted += await store.delete_produced_before(cutoff)
    if deleted:
        logger.info(
            "Replay retention removed %d progress frame(s) produced or settled "
            "before %s",
            deleted,
            cutoff.isoformat(),
            extra={"action": "run_event_retention_swept", "deleted": deleted},
        )
    return deleted


async def sweep_replay_log_periodically(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_hours: float,
    interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
) -> None:
    """Sweep now and then every *interval_seconds*, until cancelled.

    Sweeping BEFORE the first wait is what makes the bound hold on a gateway
    that restarts more often than it sweeps; waiting first would let a short
    lifetime collect nothing at all, forever.

    A failed sweep is logged and the cadence continues. Retention falling
    behind costs storage; a background task that dies on one bad pass costs
    the bound entirely, and the next pass deletes what this one could not.
    """
    while True:
        try:
            await sweep_replay_log(session_factory, retention_hours=retention_hours)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Replay retention sweep failed; the next pass will try again",
                exc_info=True,
                extra={"action": "run_event_retention_failed"},
            )
        await asyncio.sleep(interval_seconds)
