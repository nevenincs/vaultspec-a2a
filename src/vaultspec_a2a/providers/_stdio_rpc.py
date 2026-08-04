"""The one-shot half of a JSON-RPC-over-stdio client, declared once.

Reading a single response frame off a subprocess's stdout - bounded frame count,
bounded frame size, charged against an output budget, matched on request id,
skipping anything that will not parse - was written out independently by the ACP
and Codex catalog-discovery lanes. The two implementations differed only in
DIALECT: the name of a constant, and which typed error they raise. The mechanism
was identical, including the order of its guards.

What stays a caller-side argument is exactly that dialect. Each lane raises its
own error type carrying its own vocabulary, because a Codex caller reading an
ACP-shaped protocol error would be told something untrue about which transport
failed. Passing an error factory keeps that difference explicit where a shared
error type would have flattened it.

Deliberately scoped to the ONE-SHOT call shape - a single in-flight request, no
pending-id map, no notification stream. The long-lived multiplexed session used
by the live ACP and Codex chat models is the same primitive at a larger scope,
and folding the two together here would force these callers to carry session
bookkeeping they never use. That consolidation is a separate step with its own
tests; this module is where it would land.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from pydantic import TypeAdapter, ValidationError

from ._json_contract import JsonObject
from ._subprocess import kill_process_tree

if TYPE_CHECKING:
    from collections.abc import Mapping

_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)

MAX_OUTPUT_BYTES: Final = 1_048_576


class OutputBudgetLike(Protocol):
    """The subset of an output budget this reader charges against."""

    def charge(self, size: int) -> None:
        """Account for *size* bytes read from the child's stream."""
        ...


class ProtocolErrorFactory(Protocol):
    """Builds the caller's own typed protocol error from a message."""

    def __call__(self, message: str) -> Exception:
        """Return the error this lane raises for a protocol fault."""
        ...


@dataclass(slots=True)
class OutputBudget:
    """One aggregate byte allowance shared by every reader of a child's streams.

    Discovery reads stdout and stderr concurrently, so the bound has to be a
    single running total rather than a per-stream cap: a child that stays under
    the limit on each stream separately can still flood the process by using
    both. The refusal names the DEFAULT bound, which is why *limit* exists as a
    field but is not something callers are expected to vary.
    """

    protocol_error: ProtocolErrorFactory
    limit: int = MAX_OUTPUT_BYTES
    consumed: int = 0

    def charge(self, size: int) -> None:
        """Account for *size* bytes, refusing once the aggregate bound is past."""
        self.consumed += size
        if self.consumed > self.limit:
            raise self.protocol_error("discovery output exceeds one MiB")


async def cancel_task[T](task: asyncio.Task[T]) -> None:
    """Cancel *task* and absorb the resulting cancellation.

    Generic in the task's result because the drain tasks it reaps differ in what
    they return - one accumulates the child's stderr, another discards it - and
    that difference is irrelevant to cancelling: the result is never read on this
    path. Pinning it to one concrete type is what pushed a third caller into
    writing its own copy.
    """
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def drain_stderr(
    stderr: asyncio.StreamReader | None,
    process: asyncio.subprocess.Process,
    metadata: Mapping[str, object] | None,
    output_budget: OutputBudgetLike,
) -> None:
    """Consume the child's stderr against *output_budget*, reaping it on refusal.

    Draining is not optional bookkeeping: a child that fills its stderr pipe
    blocks on write, so a discovery that never reads it can deadlock against a
    process that is merely being chatty.

    The budget refusal is caught broadly rather than per-lane because ``charge``
    is the only raising call inside the guard - the read sits outside it - so
    naming each lane's own protocol-error type here would select nothing that
    ``Exception`` does not. Cancellation is a ``BaseException`` and so still
    passes through without reaping, which is what teardown depends on: the drain
    task is cancelled on the ordinary path and must not kill a healthy child.
    """
    if stderr is None:
        return
    while chunk := await stderr.read(65_536):
        try:
            output_budget.charge(len(chunk))
        except Exception:
            await kill_process_tree(process, metadata)
            raise


async def read_response(
    stdout: asyncio.StreamReader,
    *,
    request_id: int,
    timeout: float,
    output_budget: OutputBudgetLike,
    max_frames: int,
    max_frame_bytes: int,
    protocol_error: ProtocolErrorFactory,
) -> JsonObject:
    """Read frames until one carries *request_id*, or refuse.

    An unparseable frame is SKIPPED rather than fatal: a child may interleave
    diagnostics with protocol output, and one noisy line must not lose a
    response that arrives after it. An oversized frame is refused outright,
    because a frame that large is evidence the stream is not what this reader
    thinks it is, and charging it to the budget would be too late.
    """
    for _ in range(max_frames):
        raw = await asyncio.wait_for(stdout.readline(), timeout=timeout)
        if not raw:
            break
        if len(raw) > max_frame_bytes:
            raise protocol_error("discovery frame exceeds one MiB")
        output_budget.charge(len(raw))
        try:
            value = _JSON_OBJECT.validate_json(raw)
        except (ValidationError, UnicodeDecodeError):
            continue
        if value.get("id") == request_id:
            return value
    raise protocol_error(f"discovery received no response for request {request_id}")
