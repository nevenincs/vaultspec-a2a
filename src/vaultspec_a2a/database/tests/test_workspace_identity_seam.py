"""Workspace identity must be normalized by one shared formula, not two copies.

The write seam projects a workspace into the durable selector and the read seam
applies the same formula to an incoming query; both then hash the result. Two
hand-copied formulas would desynchronise silently on any edit - discovery would
return nothing, with no error to notice - so these tests drive a real database
through the production write and read seams rather than setting columns
directly, which would pass even if the two sides had drifted apart.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...control import run_discovery_service
from ...control.run_discovery_service import discover_active_runs
from ...thread.enums import ThreadStatus
from ..models import Base
from ..thread_repository import (
    _workspace_key,
    create_thread,
    normalize_workspace_identity,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    database = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as database_session:
        yield database_session


def test_both_seams_share_one_normalizer_object() -> None:
    """The read seam must reference the repository's function, not a copy of it.

    Identity, not equality: a second hand-copied formula would satisfy any
    behavioural assertion today and still drift tomorrow. This is the assertion
    that fails if the duplicate ever comes back.
    """
    assert (
        run_discovery_service.normalize_workspace_identity
        is normalize_workspace_identity
    )


@pytest.mark.asyncio
async def test_write_and_read_hashes_agree_for_an_uncanonical_spelling(
    session: AsyncSession, tmp_path: Path
) -> None:
    """A run written under one spelling is discoverable under another.

    Both spellings denote the same directory but differ textually, so they hash
    equal only if the write seam and the read seam applied the same formula.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # Same directory, spelled with a redundant current-directory segment that
    # ``realpath`` collapses. Neither seam is handed the canonical form.
    written_as = str(workspace.parent / "." / workspace.name)
    queried_as = workspace.parent / "." / "." / workspace.name

    await create_thread(
        session,
        thread_id="run-workspace-identity",
        status=ThreadStatus.RUNNING,
        metadata=json.dumps({"workspace_root": written_as, "feature_tag": "a2a"}),
    )
    await session.commit()

    result = await discover_active_runs(session, workspace_root=queried_as)

    assert [run.run_id for run in result.runs] == ["run-workspace-identity"]


@pytest.mark.asyncio
async def test_durable_key_matches_the_read_side_key(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The hash the write seam persisted is the hash the read seam looks up.

    Asserted on the durable column the query filters against, so a divergence
    between the two normalizations shows up here as unequal hashes rather than
    as an empty, errorless result somewhere downstream.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    written_as = str(workspace.parent / "." / workspace.name)

    thread = await create_thread(
        session,
        thread_id="run-workspace-key",
        status=ThreadStatus.RUNNING,
        metadata=json.dumps({"workspace_root": written_as, "feature_tag": "a2a"}),
    )
    await session.commit()

    read_side_key = _workspace_key(normalize_workspace_identity(workspace))

    assert thread.workspace_root == normalize_workspace_identity(written_as)
    assert thread.workspace_key == read_side_key
