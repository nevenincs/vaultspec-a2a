"""LangGraph checkpointer factory helpers."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, override

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import (
        ChannelVersions,
        Checkpoint,
        CheckpointMetadata,
        CheckpointTuple,
    )
    from langgraph.checkpoint.serde.base import SerializerProtocol

from ..control.config import settings
from ..domain_config import domain_config
from ..thread import checkpoint_tuple_id
from ..utils.coercion import coerce_object_mapping
from .checkpoint_schema import checkpoint_pragmas
from .session import retry_contended_write

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
    def strict_channel_values(self) -> dict[str, object] | None:
        """The checkpoint's channel values, or ``None`` when its shape is foreign.

        Durable storage is untrusted despite the saver's declared types. A
        checkpoint, or a channel map, that is not a plain dict is refused here
        rather than read as empty, for a caller whose answer depends on telling
        a malformed checkpoint from one that holds nothing. A checkpoint with
        no channel map at all holds no channels.
        """
        checkpoint = coerce_object_mapping(
            getattr(self.checkpoint_tuple, "checkpoint", None)
        )
        if checkpoint is None:
            return None
        if "channel_values" not in checkpoint:
            return {}
        return coerce_object_mapping(checkpoint["channel_values"])

    @property
    def channel_values(self) -> dict[str, object]:
        """The checkpoint's channel values, or an empty mapping without any.

        A checkpoint or channel map that is not a plain dict reads as empty.
        """
        return self.strict_channel_values or {}

    @property
    def checkpoint_id(self) -> str | None:
        """The id the stored checkpoint answers to, or ``None`` without one.

        The id the checkpoint records, falling back to the one its config names.
        """
        return checkpoint_tuple_id(self.checkpoint_tuple)

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

_CHECKPOINT_STORE = "the checkpoint store"
"""The store a contention refusal from the checkpoint saver names."""


class _ContendedCheckpointSaver(AsyncSqliteSaver):
    """The SQLite saver with the store's write-contention policy on its writes.

    The saver it extends lets a refused write out as the bare driver error and
    leaves its own transaction open behind it. Both halves are hazards, and the
    second is the worse one.

    The error alone fails a whole run over a condition the store recovers from by
    itself - another writer held the lock for a moment - where every ``/v1`` verb
    already refuses the same condition as retryable. So each write is retried
    under the one policy both stores share.

    The open transaction outlives the write that left it. The connection is
    shared by every read and write this saver makes, so the next READ joins that
    transaction and pins a write-ahead-log snapshot nothing ever commits: the log
    can no longer be checkpointed, and every later write on the connection is
    refused the instant it asks, without ``busy_timeout`` being consulted at all.
    One moment of contention becomes a store this process can never write again.
    :mod:`vaultspec_a2a.database.checkpoint_retention` rolls its own prune
    statements back for exactly that reason; these are the saver's own writes
    under the same discipline.
    """

    async def _retry[T](self, attempt: Callable[[], Awaitable[T]]) -> T:
        return await retry_contended_write(
            attempt, reset=self._discard_refused_transaction, store=_CHECKPOINT_STORE
        )

    async def _discard_refused_transaction(self) -> None:
        """Leave the shared connection with no transaction after a refusal.

        Taken under the saver's own lock, which is what makes the rollback safe:
        every write the saver makes is serialised by that lock, so inside it
        there is no other write's transaction to discard. Shielded because a
        cancellation that skipped the rollback would leave behind exactly the
        pinned snapshot this exists to prevent.
        """
        async with self.lock:
            await asyncio.shield(self.conn.rollback())

    @override
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Save a checkpoint, retrying while a competing writer refuses it."""

        async def attempt() -> RunnableConfig:
            return await AsyncSqliteSaver.aput(
                self, config, checkpoint, metadata, new_versions
            )

        return await self._retry(attempt)

    @override
    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Save a task's writes, retrying while a competing writer refuses them."""

        async def attempt() -> None:
            await AsyncSqliteSaver.aput_writes(self, config, writes, task_id, task_path)

        await self._retry(attempt)

    @override
    async def adelete_thread(self, thread_id: str) -> None:
        """Delete a run's checkpoints, retrying while a writer refuses the delete."""

        async def attempt() -> None:
            await AsyncSqliteSaver.adelete_thread(self, thread_id)

        await self._retry(attempt)


@asynccontextmanager
async def open_checkpointer() -> AsyncGenerator[Checkpointer]:
    """Open the SQLite checkpoint store with the concurrency posture it needs."""
    connection = settings.checkpoint_connection_string
    if connection != ":memory:":
        # The store's directory is part of the state layout, not something an
        # operator creates first - the same courtesy the application database
        # engine extends to its own file.
        settings.prepare_state_dir(Path(connection).parent)
    async with _ContendedCheckpointSaver.from_conn_string(connection) as checkpointer:
        # ``from_conn_string`` owns the connection but forwards no
        # serializer, so the posture is set on the saver it yields; the
        # saver derives nothing from ``serde`` at construction.
        checkpointer.serde = strict_checkpoint_serde()
        # Before ``setup()``, because setup's DDL is the saver's FIRST WRITE and
        # the configured lock wait has to be in force for it. Applied after, the
        # connection spent that write at whatever default the driver opened it
        # with, so an operator who widened or narrowed the budget had no say
        # over the one write that creates the store.
        await _apply_sqlite_concurrency_pragmas(checkpointer)
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
