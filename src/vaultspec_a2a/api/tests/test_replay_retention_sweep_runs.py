"""A real gateway sweeps the replay log, without being asked to.

The sweep is correct in isolation and worth nothing unseated, so this boots a
production gateway over a seeded application database and watches the expired
rows go. Nothing in the test calls the sweep: the only thing that can delete
these rows is the gateway's own background task, which is the claim.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ...database import RunEventRecord, RunEventStore
from ...testing import (
    armed_gateway_env,
    booted_gateway,
    gateway_script,
    log_tail,
    seat_app_home,
    seed_journaled_thread,
)
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    from pathlib import Path

_RUN = "retention-sweep-run"
#: Three and a half seconds, expressed as the hours the setting takes. Small
#: enough that an hour-old row is long expired, positive because a retention
#: of zero would be a different posture than the one under test.
_BOUND_HOURS = 0.001


async def _seed_expired_window(database_path: Path) -> None:
    """Put one settled run and its long-expired frames in the seated database.

    Written through the production repositories, including the action receipt
    the desktop boot refuses a thread without, so the gateway below starts
    against a database it recognises rather than one assembled by hand.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await seed_journaled_thread(
                session,
                thread_id=_RUN,
                status=ThreadStatus.COMPLETED,
                recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            await session.commit()
        produced = datetime.now(UTC) - timedelta(hours=1)
        await RunEventStore(factory).append(
            [
                RunEventRecord(
                    thread_id=_RUN,
                    sequence=sequence,
                    event_type="agent_status",
                    payload_json=f'{{"type":"agent_status","sequence":{sequence}}}',
                    created_at=produced,
                )
                for sequence in (1, 2, 3)
            ]
        )
    finally:
        await engine.dispose()


def _retained(database_path: Path) -> int:
    """Count the run's rows through an independent read-only connection."""
    with sqlite3.connect(
        f"file:{database_path.as_posix()}?mode=ro", uri=True
    ) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM run_events WHERE thread_id = ?", (_RUN,)
            ).fetchone()[0]
        )


def test_a_running_gateway_expires_the_replay_window_on_its_own(
    tmp_path: Path,
) -> None:
    """Boot, and the expired rows are gone with no request made of the gateway."""
    app_home = tmp_path / "app-home"
    database_path = seat_app_home(app_home).database_path
    asyncio.run(_seed_expired_window(database_path))
    assert _retained(database_path) == 3

    log_path = tmp_path / "gateway.log"
    try:
        with booted_gateway(
            armed_gateway_env(
                app_home,
                auto_spawn_worker=False,
                extra={
                    "VAULTSPEC_A2A_STREAM_REPLAY_RETENTION_HOURS": str(_BOUND_HOURS)
                },
            ),
            log_path=log_path,
            script=gateway_script(log_level="warning"),
            detached=True,
        ):
            deadline = time.monotonic() + 20.0
            remaining = _retained(database_path)
            while remaining and time.monotonic() < deadline:
                time.sleep(0.2)
                remaining = _retained(database_path)
    finally:
        tail = log_tail(log_path)
        with suppress(OSError):
            log_path.unlink()

    assert remaining == 0, tail
