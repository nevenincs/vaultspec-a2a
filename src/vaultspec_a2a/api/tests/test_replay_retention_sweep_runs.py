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

from ...database.permission_repository import create_control_action
from ...database.run_event_repository import RunEventRecord, RunEventStore
from ...database.thread_repository import create_thread
from ...desktop.profile import derive_state_paths
from ...tests._write_authority import make_test_write_authority
from ...tests.gateway_boot import (
    armed_gateway_env,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)
from ...thread.enums import ThreadStatus
from ...thread.idempotency import thread_create_action_key

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

_RUN = "retention-sweep-run"
_ATTACH = "attach-retention-sweep-0123456789abcdef"
_OWNERSHIP = "ownership-retention-sweep-fedcba9876543210"
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
            authority = make_test_write_authority()
            await create_thread(
                session,
                write_authority=authority,
                thread_id=_RUN,
                status=ThreadStatus.COMPLETED,
            )
            await create_control_action(
                session,
                thread_id=_RUN,
                action_type=authority.action_type,
                idempotency_key=thread_create_action_key(_RUN),
                dispatch_id=authority.action_receipt_id,
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
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)
    database_path = derive_state_paths(app_home).database_path
    asyncio.run(_seed_expired_window(database_path))
    assert _retained(database_path) == 3

    log_path = tmp_path / "gateway.log"
    with log_path.open("ab") as handle:

        def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
            return spawn_gateway(
                script=gateway_script(log_level="warning"),
                gateway_port=gateway_port,
                env=armed_gateway_env(
                    app_home,
                    gateway_port=gateway_port,
                    worker_port=worker_port,
                    auto_spawn_worker=False,
                    extra={
                        "VAULTSPEC_A2A_STREAM_REPLAY_RETENTION_HOURS": str(_BOUND_HOURS)
                    },
                ),
                log_handle=handle,
                new_session=True,
            )

        process, _gateway_port, _worker_port, _base = spawn_until_ready(
            _spawn, log_path=log_path
        )
    try:
        deadline = time.monotonic() + 20.0
        remaining = _retained(database_path)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.2)
            remaining = _retained(database_path)
    finally:
        reap_gateway(process)
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        with suppress(OSError):
            log_path.unlink()

    assert remaining == 0, tail
