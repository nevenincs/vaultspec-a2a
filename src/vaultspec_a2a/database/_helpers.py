"""Shared helpers used by the domain-specific repository modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, override

from sqlalchemy import and_

if TYPE_CHECKING:
    from enum import StrEnum

    from sqlalchemy import CursorResult, Result
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

    from ..thread import RunWriteAuthority

from .models import Base, ControlActionModel

__all__ = [
    "_UNSET",
    "_UnsetType",
    "_coerce",
    "_journal_row_for",
    "affected_rows",
    "save_model",
]


async def save_model[M: Base](session: AsyncSession, model: M) -> M:
    """Persist any database model instance."""
    session.add(model)
    await session.flush()
    return model


def affected_rows(result: Result[Any]) -> int:
    """Return how many rows a conditional write matched.

    A DML execution always yields a cursor result; only the declared return
    type of ``Session.execute`` is the wider ``Result``, which carries no
    ``rowcount``.
    """
    return cast("CursorResult[Any]", result).rowcount


def _journal_row_for(
    thread_id: str, authority: RunWriteAuthority
) -> ColumnElement[bool]:
    """Match the journal row whose receipt names *authority*'s action on a run."""
    return and_(
        ControlActionModel.thread_id == thread_id,
        ControlActionModel.action_type == authority.action_type.value,
        ControlActionModel.dispatch_id == authority.action_receipt_id,
    )


class _UnsetType:
    """Typed sentinel for distinguishing 'not provided' from ``None``."""

    _instance: _UnsetType | None = None

    def __new__(cls) -> _UnsetType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @override
    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _UnsetType()


def _coerce[E: StrEnum](enum: type[E], value: E | str, *, label: str) -> E:
    """Return *value* as a member of *enum*, naming *label* when it is not one.

    Constructing a ``StrEnum`` from one of its own members returns that member,
    so a member and its stored value take the same path.
    """
    try:
        return enum(value)
    except ValueError:
        valid = ", ".join(member.value for member in enum)
        msg = f"Invalid {label}: {value!r}. Must be one of: {valid}"
        raise ValueError(msg) from None
