"""Worker SQL adapter for write-once provider runtime evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Unpack

from ..database import ProviderRuntimeIdentityModel, record_provider_runtime_identity

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..graph.protocols import RuntimeIdentityRecordArgs

__all__ = ["SqlRuntimeIdentityPort"]


class SqlRuntimeIdentityPort:
    """Short-lived-session adapter shared by concurrent graph runs."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_identity(
        self, **kwargs: Unpack[RuntimeIdentityRecordArgs]
    ) -> None:
        """Commit the first run/lane identity and refuse changed evidence."""
        async with self._session_factory() as session:
            await record_provider_runtime_identity(
                session,
                ProviderRuntimeIdentityModel(
                    thread_id=kwargs["thread_id"],
                    provider_id=kwargs["provider_id"],
                    execution_mode=kwargs["execution_mode"],
                    runtime_authority=kwargs["runtime_authority"],
                    adapter_name=kwargs["adapter_name"],
                    adapter_version=kwargs["adapter_version"],
                    adapter_entry_path=kwargs["adapter_entry_path"],
                    cli_executable_path=kwargs["cli_executable_path"],
                    cli_version=kwargs["cli_version"],
                    node_version=kwargs["node_version"],
                    auth_mode=kwargs["auth_mode"],
                    provider_session_id=kwargs["provider_session_id"],
                    managed_policy_present=kwargs["managed_policy_present"],
                ),
            )
            await session.commit()
