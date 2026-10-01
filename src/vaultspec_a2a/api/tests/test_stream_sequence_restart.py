"""A run's numbering survives the gateway process that produced it.

This is the property whose absence forced the SSE id to be withdrawn: an id
built on a counter that restarts with its process promises a resumption the
stream cannot serve, and invites a consumer to deduplicate away a restarted
producer's events. Asserting it needs two real gateway processes over one
application home, because an in-process proof can only ever restate the
in-process counter.

So nothing here is simulated. Two production gateways boot in turn under the
armed desktop profile, each minting its own worker interprocess-communication
secret; the frames arrive on the real internal relay route the worker itself
posts to; and the numbers are read back out of the real database through an
independent read-only connection. The relayed frames deliberately carry the
WORKER's own numbering, restarting at one across the boundary exactly as a
respawned worker's would, so the run's own sequence can only be continuous if
the gateway owns it.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ...database.permission_repository import create_control_action
from ...database.thread_repository import create_thread
from ...desktop.credentials import WORKER_IPC_CREDENTIAL_NAME
from ...desktop.profile import derive_state_paths
from ...tests._write_authority import make_test_write_authority
from ...tests.gateway_boot import (
    LOOPBACK_TIMEOUT,
    armed_gateway_env,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

_RUN = "sequence-survives-restart"
_ATTACH = "attach-sequence-restart-0123456789abcdef"
_OWNERSHIP = "ownership-sequence-restart-fedcba9876543210"


def _relay_body(worker_sequences: list[int]) -> dict[str, Any]:
    """One worker batch, numbered as that worker process numbers it."""
    return {
        "events": [
            {
                "thread_id": _RUN,
                "ts": float(index),
                "payload": {
                    "type": "agent_status",
                    "event_type": "agent_status",
                    "thread_id": _RUN,
                    "agent_id": "coder",
                    "state": "working",
                    "sequence": sequence,
                },
            }
            for index, sequence in enumerate(worker_sequences)
        ]
    }


async def _seed_running_thread(database_path: Path) -> None:
    """Put one live run in the seated database, through the real repositories.

    The run carries the action receipt its write authority names, because the
    desktop boot refuses a thread whose authority no accepted action backs -
    seeding the row alone would fail the gateway before readiness.
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
                status=ThreadStatus.RUNNING,
            )
            await create_control_action(
                session,
                thread_id=_RUN,
                action_type=authority.action_type,
                idempotency_key=f"thread-create:{_RUN}",
                dispatch_id=authority.action_receipt_id,
                recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            await session.commit()
    finally:
        await engine.dispose()


def _retained(database_path: Path) -> list[tuple[int, int]]:
    """Return ``(sequence, body sequence)`` for the run's retained frames.

    Read through an independent read-only connection while the gateway still
    owns the database, so the assertion is about what was written rather than
    about what any in-process object believes.
    """
    with sqlite3.connect(
        f"file:{database_path.as_posix()}?mode=ro", uri=True
    ) as connection:
        rows = connection.execute(
            "SELECT sequence, payload_json FROM run_events "
            "WHERE thread_id = ? ORDER BY sequence",
            (_RUN,),
        ).fetchall()
    return [(int(row[0]), int(json.loads(row[1])["sequence"])) for row in rows]


def _worker_secret(app_home: Path) -> str:
    path = derive_state_paths(app_home).credentials_dir / WORKER_IPC_CREDENTIAL_NAME
    return path.read_text(encoding="utf-8").strip()


def _post_worker_batch(base_url: str, secret: str, sequences: list[int]) -> None:
    with httpx.Client(base_url=base_url, timeout=LOOPBACK_TIMEOUT) as client:
        response = client.post(
            "/internal/events/batch",
            json=_relay_body(sequences),
            headers={"Authorization": f"Bearer {secret}"},
        )
    assert response.status_code == 200, response.text


def test_a_restarted_gateway_continues_the_run_sequence(tmp_path: Path) -> None:
    """Two gateway lifetimes, one run, one unbroken and unduplicated sequence."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)
    database_path = derive_state_paths(app_home).database_path
    asyncio.run(_seed_running_thread(database_path))

    log_path = tmp_path / "gateway.log"
    script = gateway_script(log_level="warning")

    def _boot() -> tuple[subprocess.Popen[bytes], str]:
        with log_path.open("ab") as handle:

            def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
                return spawn_gateway(
                    script=script,
                    gateway_port=gateway_port,
                    env=armed_gateway_env(
                        app_home,
                        gateway_port=gateway_port,
                        worker_port=worker_port,
                        # No worker is spawned: the frames below arrive on the
                        # same route a worker would use, and a real agent run
                        # would only add nondeterminism to a proof about
                        # numbering.
                        auto_spawn_worker=False,
                    ),
                    log_handle=handle,
                    new_session=True,
                )

            process, _gateway_port, _worker_port, base = spawn_until_ready(
                _spawn, log_path=log_path
            )
            return process, base

    first, base = _boot()
    try:
        _post_worker_batch(base, _worker_secret(app_home), [1, 2, 3])
        after_first = _retained(database_path)
    finally:
        reap_gateway(first)

    assert [sequence for sequence, _ in after_first] == [1, 2, 3], (
        after_first,
        log_path.read_text(encoding="utf-8", errors="replace")[-4000:],
    )

    second, base = _boot()
    try:
        # A respawned worker numbers from one again; the gateway must not.
        _post_worker_batch(base, _worker_secret(app_home), [1, 2])
        after_second = _retained(database_path)
    finally:
        reap_gateway(second)
        with suppress(OSError):
            log_path.unlink()

    sequences = [sequence for sequence, _ in after_second]
    assert sequences == [1, 2, 3, 4, 5]
    assert len(sequences) == len(set(sequences))
    # The body reports the number the gateway stamped, not the worker's.
    assert [body for _, body in after_second] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("enabled", ["false"])
def test_a_gateway_serving_no_replay_retains_nothing(
    tmp_path: Path, enabled: str
) -> None:
    """The switch is honest in both directions: off, no row and no number."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)
    database_path = derive_state_paths(app_home).database_path
    asyncio.run(_seed_running_thread(database_path))

    log_path = tmp_path / "gateway.log"
    script = gateway_script(log_level="warning")

    with log_path.open("ab") as handle:

        def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
            return spawn_gateway(
                script=script,
                gateway_port=gateway_port,
                env=armed_gateway_env(
                    app_home,
                    gateway_port=gateway_port,
                    worker_port=worker_port,
                    auto_spawn_worker=False,
                    extra={"VAULTSPEC_A2A_STREAM_REPLAY_ENABLED": enabled},
                ),
                log_handle=handle,
                new_session=True,
            )

        process, _gateway_port, _worker_port, base = spawn_until_ready(
            _spawn, log_path=log_path
        )
    try:
        _post_worker_batch(base, _worker_secret(app_home), [1, 2, 3])
        assert _retained(database_path) == []
    finally:
        reap_gateway(process)
