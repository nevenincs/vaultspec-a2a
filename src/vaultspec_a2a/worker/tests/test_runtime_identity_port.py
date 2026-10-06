"""The worker adapter commits provider identity through the real repository."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from ...database.models import ProviderRuntimeIdentityModel
from ...database.runtime_identity_repository import RuntimeIdentityConflictError
from ...database.tests._backends import migrated_session_factory
from ...database.thread_repository import create_thread
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..runtime_identity_port import SqlRuntimeIdentityPort

if TYPE_CHECKING:
    from pathlib import Path

    from ...graph.protocols import RuntimeIdentityRecordArgs


@pytest.mark.asyncio
async def test_runtime_identity_port_commits_once_and_refuses_conflicting_retry(
    tmp_path: Path,
) -> None:
    """A later session sees the identity, and a changed retry cannot replace it."""
    async with migrated_session_factory("sqlite", tmp_path) as (_target, factory):
        async with factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id="run-1",
                status=ThreadStatus.RUNNING,
            )
            await session.commit()

        port = SqlRuntimeIdentityPort(factory)
        evidence: RuntimeIdentityRecordArgs = {
            "thread_id": "run-1",
            "provider_id": "codex",
            "execution_mode": "codex-app-server",
            "runtime_authority": "service_path",
            "adapter_name": "codex-app-server",
            "adapter_version": "1.2.3",
            "adapter_entry_path": "/installed/codex",
            "cli_executable_path": "/installed/codex",
            "cli_version": "1.2.3",
            "node_version": None,
            "auth_mode": "subscription_login",
            "provider_session_id": "native-1",
            "managed_policy_present": None,
        }
        await port.record_identity(**evidence)
        await port.record_identity(**evidence)
        later_session = evidence.copy()
        later_session["provider_session_id"] = "native-2"
        await port.record_identity(**later_session)
        for field, value in (
            ("cli_version", "2.3.4"),
            ("adapter_version", "2.3.4"),
            ("auth_mode", "oauth_token"),
        ):
            changed = evidence.copy()
            changed[field] = value
            with pytest.raises(RuntimeIdentityConflictError):
                await port.record_identity(**changed)

        async with factory() as session:
            rows = (await session.scalars(select(ProviderRuntimeIdentityModel))).all()
        assert len(rows) == 1
        assert rows[0].cli_version == evidence["cli_version"]
        assert rows[0].provider_session_id == "native-1"


@pytest.mark.asyncio
async def test_concurrent_sessions_keep_one_first_identity(tmp_path: Path) -> None:
    """Two research branches can initialize the same lane without losing evidence."""
    async with migrated_session_factory("sqlite", tmp_path) as (_target, factory):
        async with factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id="run-branches",
                status=ThreadStatus.RUNNING,
            )
            await session.commit()
        port = SqlRuntimeIdentityPort(factory)
        common: RuntimeIdentityRecordArgs = {
            "thread_id": "run-branches",
            "provider_id": "codex",
            "execution_mode": "codex-app-server",
            "runtime_authority": "system_cli",
            "adapter_name": "codex-app-server",
            "adapter_version": "1.2.3",
            "adapter_entry_path": "/installed/codex",
            "cli_executable_path": "/installed/codex",
            "cli_version": "1.2.3",
            "node_version": None,
            "auth_mode": "codex_home",
            "provider_session_id": "branch-a",
            "managed_policy_present": None,
        }
        other = common.copy()
        other["provider_session_id"] = "branch-b"
        await asyncio.gather(
            port.record_identity(**common), port.record_identity(**other)
        )

        async with factory() as session:
            rows = (await session.scalars(select(ProviderRuntimeIdentityModel))).all()
        assert len(rows) == 1
        assert rows[0].provider_session_id in {"branch-a", "branch-b"}
