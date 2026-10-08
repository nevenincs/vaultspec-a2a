"""Terminal-owned pipe drains and a bounded, non-consuming UTF-8 tail."""

from __future__ import annotations

import asyncio
import codecs
from dataclasses import dataclass, field

from ._cleanup import cancel_owned_tasks

__all__ = ["MAX_TERMINAL_OUTPUT_BYTES", "AcpTerminalOutput"]

MAX_TERMINAL_OUTPUT_BYTES = 1024 * 1024
_DRAIN_CHUNK_BYTES = 4096
_DRAIN_SETTLE_SECONDS = 1.0


@dataclass(slots=True)
class AcpTerminalOutput:
    """Own both pipes independently from the cancellable session RPC tasks."""

    process: asyncio.subprocess.Process
    byte_limit: int
    truncated: bool = False
    _tail: bytearray = field(default_factory=bytearray, repr=False)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list, repr=False)

    @classmethod
    def capture(
        cls, process: asyncio.subprocess.Process, byte_limit: int
    ) -> AcpTerminalOutput:
        """Start exclusive drains as soon as a terminal is acquired."""
        output = cls(process, byte_limit)
        for reader in (process.stdout, process.stderr):
            if reader is not None:
                output._tasks.append(asyncio.create_task(output._drain(reader)))
        return output

    @property
    def output(self) -> str:
        """Snapshot the captured tail without consuming retained output."""
        return self._tail.decode("utf-8")

    def _append(self, text: str) -> None:
        self._tail.extend(text.encode("utf-8"))
        discard = len(self._tail) - self.byte_limit
        if discard > 0:
            self.truncated = True
            # A byte cut can land inside a character. Remove that character's
            # remaining continuation bytes rather than emit a replacement.
            while discard < len(self._tail) and self._tail[discard] & 0xC0 == 0x80:
                discard += 1
            del self._tail[:discard]

    async def _drain(self, reader: asyncio.StreamReader) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while chunk := await reader.read(_DRAIN_CHUNK_BYTES):
                self._append(decoder.decode(chunk))
        finally:
            self._append(decoder.decode(b"", final=True))

    async def settle(self) -> None:
        """Collect final pipe data without waiting forever on a descendant's EOF."""
        if self._tasks:
            done, _pending = await asyncio.wait(
                self._tasks, timeout=_DRAIN_SETTLE_SECONDS
            )
            for task in done:
                if not task.cancelled():
                    task.result()

    async def close(self) -> None:
        """Finish or cancel and join every drain before terminal release returns."""
        try:
            await self.settle()
        finally:
            await cancel_owned_tasks(self._tasks)
