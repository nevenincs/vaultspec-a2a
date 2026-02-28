"""Shared fixtures for lib/api/tests/.

Centralises engine, session_factory, session, and _make_app so that all test
modules use the same in-memory SQLite setup and dependency overrides.

API-C1 fix: _make_app now overrides get_checkpointer (using MemorySaver) and
get_task_group (using a test-scoped anyio task group) in addition to get_db,
get_aggregator, and get_graph_registry.  This prevents the real _lifespan from
touching the production vaultspec.db.

API-M7 fix: shared fixtures eliminate duplicate engine/session_factory
definitions across test files.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...core.aggregator import EventAggregator
from ...database.models import Base
from ...database.session import get_db
from ..app import create_app
from ..endpoints import (
    GraphRegistry,
    get_aggregator,
    get_checkpointer,
    get_graph_registry,
    get_task_group,
)


__all__: list[str] = []


# ---------------------------------------------------------------------------
# Engine / Session fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """In-memory async SQLAlchemy engine with all tables created."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Async session factory bound to the in-memory engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(engine):
    """Provide a fresh async session for direct DB assertions."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def make_app(session_factory, aggregator=None, registry=None):
    """Create a test FastAPI app with all dependency overrides applied.

    API-C1: overrides get_checkpointer (MemorySaver) and get_task_group
    (test anyio task group) so the real _lifespan never opens production DB.
    """
    app = create_app()

    if aggregator is None:
        aggregator = EventAggregator()
    if registry is None:
        registry = GraphRegistry()

    # Store singletons in app.state so WebSocket handlers can read them
    app.state.aggregator = aggregator
    app.state.graph_registry = registry

    # In-memory checkpointer — never touches vaultspec.db
    checkpointer = MemorySaver()
    app.state.checkpointer = checkpointer

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def _override_get_checkpointer():
        return checkpointer

    # Provide a simple task group stub via anyio
    class _NullTaskGroup:
        """Minimal task-group stub: start_soon schedules tasks on the event loop."""

        def start_soon(self, coro_fn, *args, **kwargs):
            import asyncio

            _task = asyncio.ensure_future(coro_fn(*args, **kwargs))  # noqa: RUF006

    _null_tg = _NullTaskGroup()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_aggregator] = lambda: aggregator
    app.dependency_overrides[get_graph_registry] = lambda: registry
    app.dependency_overrides[get_checkpointer] = lambda: checkpointer
    app.dependency_overrides[get_task_group] = lambda: _null_tg

    return app, aggregator, registry, checkpointer
