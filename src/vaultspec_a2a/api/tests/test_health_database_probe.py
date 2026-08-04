"""The health surface must PROBE its database, not read a seated engine object.

Every test here drives the real ``/health`` endpoint over a real SQLite file. The
failure being guarded against is specific: an ``AsyncEngine`` attribute survives
its database being deleted, its permissions revoked, or its volume filling, so a
readiness answer derived from that attribute reports READY for a gateway that
cannot execute a single statement.
"""

from __future__ import annotations

import shutil
import sqlite3
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...control.config import settings
from ...control.health import assemble_desktop_readiness
from ...testing import armed_desktop_app_home as _armed_desktop
from .conftest import make_app

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI


async def _armed_health(app: FastAPI) -> dict[str, Any]:
    """Call the real ``/health`` endpoint as an attach-authenticated caller."""
    token = app.state.v1_service_token
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/health", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json())


@pytest.mark.asyncio
async def test_armed_health_probes_a_database_that_has_gone_away(
    tmp_path: Path,
    checkpointer: Any,
) -> None:
    """Armed ``/health`` must report NOT ready once the database is really gone.

    The database is removed from under a still-seated engine - the exact shape of
    a deleted file, a revoked mount, or a store the process can no longer open.
    The same app state is then read two ways in one test: through the endpoint,
    which probes, and through the seated-state fallback, which does not. The
    fallback still answers READY, which is precisely why the endpoint may not use
    it.
    """
    store_dir = tmp_path / "armed-health-store"
    store_dir.mkdir()
    db_file = store_dir / "gateway.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app, _aggregator, _worker, _checkpointer = make_app(factory, checkpointer)
    app.state.db_engine = engine
    app.state.db_session_factory = factory

    with _armed_desktop(tmp_path / "armed-health-home"):
        healthy = await _armed_health(app)
        assert healthy["gateway_readiness"] == "ready"

        # Genuinely remove the store: dispose releases the pooled handles, then
        # the directory itself goes, so a reconnect cannot silently recreate the
        # file the way deleting the file alone would.
        await engine.dispose()
        shutil.rmtree(store_dir)
        assert not db_file.exists()

        probed = await _armed_health(app)

        # The pre-fix expression, evaluated against the very same app state.
        seated_only = assemble_desktop_readiness(app_state=app.state)

    assert probed["gateway_readiness"] == "not_ready"
    assert probed["run_admission"] == "blocked"
    assert "database is not valid" in probed["reasons"]

    assert app.state.db_engine is not None
    assert seated_only.gateway_readiness.value == "ready"


@pytest.mark.asyncio
async def test_armed_liveness_answer_stays_constant_without_the_attach_credential(
    tmp_path: Path,
    checkpointer: Any,
) -> None:
    """An unauthenticated armed caller learns nothing, probe or no probe.

    The probe must not leak through the liveness boundary: a broken database has
    to look identical to a healthy one to a caller with no attach credential, or
    the unauthenticated surface becomes a dependency oracle.
    """
    store_dir = tmp_path / "liveness-store"
    store_dir.mkdir()
    engine = create_async_engine(f"sqlite+aiosqlite:///{store_dir / 'gateway.db'}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app, _aggregator, _worker, _checkpointer = make_app(factory, checkpointer)
    app.state.db_engine = engine
    app.state.db_session_factory = factory
    # The explicit test bypass would authorise every caller; this test is about
    # the unauthenticated branch, so the real gate has to be in force.
    app.state.allow_unauthenticated_v1_for_testing = False

    with _armed_desktop(tmp_path / "liveness-home"):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            healthy = await client.get("/health")

        await engine.dispose()
        shutil.rmtree(store_dir)

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            broken = await client.get("/health")

    assert healthy.status_code == 200
    assert broken.status_code == 200
    assert broken.json() == healthy.json()
    assert "gateway_readiness" not in broken.json()


@pytest.mark.asyncio
async def test_health_reports_live_journal_mode_and_storage_footprint(
    tmp_path: Path,
    checkpointer: Any,
) -> None:
    """``/health`` re-verifies WAL on the live engine and reports disk usage.

    WAL is requested per connection and can be refused silently by the file
    system; nothing else in the process re-checks after connect time. The journal
    mode reported here comes from a real ``PRAGMA journal_mode`` round trip
    against the seated engine, and the storage block from real ``stat`` and
    ``disk_usage`` calls - so an operator can see both a degraded journal and a
    store growing toward a full volume.
    """
    store_dir = tmp_path / "journal-store"
    store_dir.mkdir()
    db_file = store_dir / "gateway.db"
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, payload TEXT)")
        conn.commit()
    finally:
        conn.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app, _aggregator, _worker, _checkpointer = make_app(factory, checkpointer)
    app.state.db_engine = engine
    app.state.db_session_factory = factory

    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health")
    finally:
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["database"]["journal_mode"] == "wal"

    storage = body["storage"]
    if settings.resolved_database_backend == "sqlite":
        assert storage["database"]["size_bytes"] >= 0
        assert storage["volume"]["free_bytes"] > 0
        assert storage["volume"]["total_bytes"] >= storage["volume"]["free_bytes"]
    else:
        # A remote backend's capacity is not this process's filesystem to measure.
        assert storage is None or "database" not in storage
