"""Runtime identity is durable, write-once evidence in the migrated store."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, inspect, select

from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..models import ProviderRuntimeIdentityModel
from ..runtime_identity_repository import (
    RuntimeIdentityConflictError,
    record_provider_runtime_identity,
)
from ..thread_repository import create_thread
from ._migration_target import downgrade, empty_database_url, synchronous_url, upgrade

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_RUN = "runtime-identity-proof"
_TABLE = "provider_runtime_identities"


def _table_present(url: str) -> bool:
    engine = create_engine(synchronous_url(url))
    try:
        with engine.connect() as connection:
            return _TABLE in inspect(connection).get_table_names()
    finally:
        engine.dispose()


def _identity(*, version: str = "2.1.286") -> ProviderRuntimeIdentityModel:
    return ProviderRuntimeIdentityModel(
        thread_id=_RUN,
        provider_id="claude",
        execution_mode="claude-acp",
        runtime_authority="lock_vendored",
        adapter_name="claude-agent-acp",
        adapter_version="0.59.0",
        adapter_entry_path="/capsule/acp-agent.js",
        cli_executable_path="/capsule/claude",
        cli_version=version,
        node_version="v22.0.0",
        auth_mode="subscription_login",
        provider_session_id="native-session-1",
        managed_policy_present=False,
    )


def test_runtime_identity_migration_is_reversible(tmp_path: Path) -> None:
    """A real migration adds the table and its predecessor can remove it."""
    url = empty_database_url(tmp_path)
    upgrade(url, "0024")
    assert not _table_present(url)
    upgrade(url, "0025")
    assert _table_present(url)
    downgrade(url, "0024")
    assert not _table_present(url)
    upgrade(url)
    assert _table_present(url)


@pytest.mark.asyncio
async def test_runtime_identity_accepts_exact_retry_and_refuses_changed_evidence(
    migrated_session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """A retry cannot turn one completed run into a different binary claim."""
    async with migrated_session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=_RUN,
            status=ThreadStatus.RUNNING,
        )
        await session.commit()

    async with migrated_session_factory() as session:
        first = await record_provider_runtime_identity(session, _identity())
        assert first.cli_version == "2.1.286"
        await session.commit()

    async with migrated_session_factory() as session:
        repeated = await record_provider_runtime_identity(session, _identity())
        assert repeated.cli_version == "2.1.286"
        with pytest.raises(RuntimeIdentityConflictError):
            await record_provider_runtime_identity(
                session, _identity(version="2.1.287")
            )
        await session.commit()

    async with migrated_session_factory() as session:
        rows = (await session.scalars(select(ProviderRuntimeIdentityModel))).all()
        assert len(rows) == 1
        assert rows[0].cli_version == "2.1.286"
