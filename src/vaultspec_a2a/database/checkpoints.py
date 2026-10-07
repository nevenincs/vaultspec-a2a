"""LangGraph checkpointer factory helpers."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import CheckpointTuple
    from langgraph.checkpoint.serde.base import SerializerProtocol

from ..control.config import settings
from ..domain_config import domain_config
from ..utils.coercion import coerce_object_mapping
from .checkpoint_schema import checkpoint_pragmas

logger = logging.getLogger(__name__)

__all__ = [
    "CheckpointRead",
    "CheckpointReadStatus",
    "Checkpointer",
    "open_checkpointer",
    "read_latest_checkpoint",
    "surviving_transcript",
]


class CheckpointReadStatus(StrEnum):
    """What one bounded read of a thread's checkpoint found."""

    PRESENT = "present"
    ABSENT = "absent"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CheckpointRead:
    """One bounded checkpoint read: the tuple, or why there is none.

    ``ABSENT`` is a store that answered and holds nothing for the thread.
    ``TIMEOUT`` and ``ERROR`` are a store that did not answer, which proves
    nothing about the thread either way. ``error`` is set exactly for those
    two, so a caller whose contract is to raise can raise what the store did.
    """

    status: CheckpointReadStatus
    checkpoint_tuple: CheckpointTuple | None = None
    error: Exception | None = None

    @property
    def unreadable(self) -> bool:
        """Whether the store failed to answer, as opposed to holding nothing."""
        return self.status in {CheckpointReadStatus.TIMEOUT, CheckpointReadStatus.ERROR}

    @property
    def channel_values(self) -> dict[str, object]:
        """The checkpoint's channel values, or an empty mapping without any.

        Durable storage is untrusted despite the saver's declared types, so a
        checkpoint or channel map that is not a plain dict reads as empty.
        """
        checkpoint = coerce_object_mapping(
            getattr(self.checkpoint_tuple, "checkpoint", None)
        )
        if checkpoint is None:
            return {}
        return coerce_object_mapping(checkpoint.get("channel_values")) or {}

    def tuple_or_raise(self) -> CheckpointTuple | None:
        """Return the tuple, ``None`` when absent, or raise the read's failure."""
        if self.error is not None:
            raise self.error
        return self.checkpoint_tuple


async def read_latest_checkpoint(
    checkpointer: Checkpointer,
    thread_id: str,
    *,
    timeout: float | None = None,
    checkpoint_id: str | None = None,
) -> CheckpointRead:
    """Read a thread's latest checkpoint tuple once, bounded by *timeout*.

    Non-raising: a timed-out or failed read is an outcome, logged here, so
    each caller decides what an unanswered store means for it. Cancellation
    still propagates. *timeout* defaults to
    ``domain_config.aget_state_timeout_seconds``, read per call so an operator
    bound applies to every reader alike. *checkpoint_id* reads that checkpoint
    of the thread instead of its latest.
    """
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    config: RunnableConfig = {"configurable": configurable}
    bound = domain_config.aget_state_timeout_seconds if timeout is None else timeout
    try:
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config), timeout=bound
        )
    except TimeoutError as exc:
        logger.warning("Checkpoint read timed out for thread %s", thread_id)
        return CheckpointRead(CheckpointReadStatus.TIMEOUT, error=exc)
    except Exception as exc:
        logger.warning("Checkpoint read failed for thread %s", thread_id, exc_info=True)
        return CheckpointRead(CheckpointReadStatus.ERROR, error=exc)
    if checkpoint_tuple is None:
        return CheckpointRead(CheckpointReadStatus.ABSENT)
    return CheckpointRead(CheckpointReadStatus.PRESENT, checkpoint_tuple)


async def surviving_transcript(
    checkpointer: Checkpointer, thread_id: str, depth: int
) -> list[HumanMessage | AIMessage] | None:
    """Read a settled run's retained final conversation from its checkpoint."""
    checkpoint = await read_latest_checkpoint(checkpointer, thread_id)
    if checkpoint.tuple_or_raise() is None:
        return None
    values = checkpoint.channel_values
    raw_messages: object = values.get("messages")
    if not isinstance(raw_messages, list):
        return None
    messages = cast("list[object]", raw_messages)
    transcript = [
        message
        for message in messages
        if isinstance(message, (HumanMessage, AIMessage))
        and isinstance(message.content, str)
        and message.content
    ]
    return transcript[-depth:] or None


def strict_checkpoint_serde() -> SerializerProtocol:
    """Return the serializer that reads back only the safe set of types.

    Deserialization is where a checkpoint store becomes an execution surface.
    The permissive default imports and calls whatever type a stored value names,
    so anything able to write the store chooses what this process constructs on
    load; it only logs that it did so. An empty allowlist - which is how the
    library states strict mode - leaves its own safe set, and that set already
    covers every type this graph checkpoints: JSON primitives and LangChain
    messages.

    Configured on each saver rather than through ``LANGGRAPH_STRICT_MSGPACK``,
    so the posture belongs to the store this package opens and not to whichever
    process happens to host it.

    Strict deserialization DEGRADES rather than refuses: a blocked value comes
    back as the raw argument its type was built from - a plain string where an
    enum member was written - and is logged. Writing plain values in the first
    place is what keeps that substitution from reaching a node.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=None)


# Type alias: every LangGraph checkpointer (SQLite, in-memory) is a
# BaseCheckpointSaver subclass.  Using the concrete base rather than a Protocol
# lets ty verify structural compatibility without manual casting.
Checkpointer = BaseCheckpointSaver[Any]


@asynccontextmanager
async def open_checkpointer() -> AsyncGenerator[Checkpointer]:
    """Open the SQLite checkpoint store with the concurrency posture it needs."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    connection = settings.checkpoint_connection_string
    if connection != ":memory:":
        # The store's directory is part of the state layout, not something an
        # operator creates first - the same courtesy the application database
        # engine extends to its own file.
        settings.prepare_state_dir(Path(connection).parent)
    async with AsyncSqliteSaver.from_conn_string(connection) as checkpointer:
        # ``from_conn_string`` owns the connection but forwards no
        # serializer, so the posture is set on the saver it yields; the
        # saver derives nothing from ``serde`` at construction.
        checkpointer.serde = strict_checkpoint_serde()
        # Desktop profile boot must not mutate schema: ``setup()`` creates the
        # checkpointer tables, so it is suppressed when the profile is armed.
        # The staged-generation migration entrypoint runs setup instead, and
        # ordinary armed boot has already validated the schema is present.
        if settings.desktop_profile_armed:
            # Not calling setup() does not prevent it: the saver runs it
            # itself before its first read or write, so skipping the call
            # here only deferred the same DDL to the first checkpoint.
            # ``is_setup`` is how the saver records that it has nothing to
            # create, and the validation that ran before this said so.
            checkpointer.is_setup = True
        else:
            await checkpointer.setup()
        await _apply_sqlite_concurrency_pragmas(checkpointer)
        yield checkpointer


async def _apply_sqlite_concurrency_pragmas(checkpointer: Any) -> None:
    """Put the SQLite store in WAL mode, and say so when it refuses.

    WAL lets the gateway's status reads run concurrently with the worker's
    checkpoint writes on the shared file, instead of blocking on a writer's
    lock (the recurring checkpoint_unavailable/missing degradations);
    busy_timeout bounds any residual lock wait rather than failing fast.
    """
    for statement in checkpoint_pragmas(settings.sqlite_busy_timeout_ms):
        await checkpointer.conn.execute(statement)
    journal_row = await (
        await checkpointer.conn.execute("PRAGMA journal_mode")
    ).fetchone()
    if journal_row is None or str(journal_row[0]).lower() != "wal":
        logger.warning(
            "Failed to enable WAL journal mode on the checkpoint store; "
            "actual mode: %r. Gateway status reads will contend with "
            "worker checkpoint writes.",
            None if journal_row is None else journal_row[0],
        )
