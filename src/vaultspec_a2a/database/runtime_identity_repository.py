"""Write-once provider runtime evidence for each run and catalog lane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import ProviderRuntimeIdentityModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["RuntimeIdentityConflictError", "record_provider_runtime_identity"]

_EVIDENCE_FIELDS = (
    "runtime_authority",
    "adapter_name",
    "adapter_version",
    "adapter_entry_path",
    "cli_executable_path",
    "cli_version",
    "node_version",
    "auth_mode",
    "provider_session_id",
    "managed_policy_present",
)


class RuntimeIdentityConflictError(RuntimeError):
    """A run lane already recorded a different runtime identity."""


async def record_provider_runtime_identity(
    session: AsyncSession,
    identity: ProviderRuntimeIdentityModel,
    *,
    allow_later_session: bool = False,
) -> ProviderRuntimeIdentityModel:
    """Persist first evidence and refuse changed stable runtime claims.

    The caller owns the surrounding transaction. Both supported backends use a
    conflict-ignored insert so concurrent retries cannot poison that transaction.
    The stored row is then read back and compared before the caller may commit.
    A live per-call lane may open later native sessions with new IDs; the first
    session remains recorded while every other runtime field must still match.
    """
    key = (identity.thread_id, identity.provider_id, identity.execution_mode)
    values = {
        "thread_id": identity.thread_id,
        "provider_id": identity.provider_id,
        "execution_mode": identity.execution_mode,
        **{field: getattr(identity, field) for field in _EVIDENCE_FIELDS},
    }
    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        statement = sqlite_insert(ProviderRuntimeIdentityModel).on_conflict_do_nothing()
    elif bind.dialect.name == "postgresql":
        statement = postgres_insert(
            ProviderRuntimeIdentityModel
        ).on_conflict_do_nothing()
    else:
        raise RuntimeError("runtime identity requires SQLite or PostgreSQL")
    await session.execute(statement.values(**values))
    stored = await session.get(ProviderRuntimeIdentityModel, key)
    if stored is None:
        raise RuntimeError("runtime identity insert produced no row")
    compared_fields = (
        tuple(field for field in _EVIDENCE_FIELDS if field != "provider_session_id")
        if allow_later_session
        else _EVIDENCE_FIELDS
    )
    if any(getattr(stored, field) != values[field] for field in compared_fields):
        raise RuntimeIdentityConflictError(
            "run lane already recorded a different provider runtime identity"
        )
    return stored
