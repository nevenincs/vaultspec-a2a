"""ACP line ranges and bounded UTF-8 text reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from ._acp_client_requests import AcpSessionRequest

if TYPE_CHECKING:
    from typing import TextIO

__all__: list[str] = []

_MAX_LINE_RANGE = 2**32 - 1
_READ_CHUNK_CHARACTERS = 4096


class AcpFileReadRange(BaseModel):
    """One-based line selection with an optional non-negative line count."""

    model_config = ConfigDict(strict=True, extra="forbid")

    line: int | None = Field(default=None, ge=1, le=_MAX_LINE_RANGE)
    limit: int | None = Field(default=None, ge=0, le=_MAX_LINE_RANGE)


class AcpFileReadRequest(AcpFileReadRange, AcpSessionRequest):
    """The ACP v1 filesystem read payload."""

    model_config = ConfigDict(strict=True, extra="ignore")

    path: str = Field(min_length=1)


def read_text_lines(handle: TextIO, ranges: AcpFileReadRange, maximum: int) -> str:
    """Select lines without allocating an unbounded line or splitting UTF-8."""
    if maximum == 0 or ranges.limit == 0:
        return ""
    for _ in range((ranges.line or 1) - 1):
        while True:
            chunk = handle.readline(_READ_CHUNK_CHARACTERS)
            if not chunk:
                return ""
            if chunk.endswith("\n"):
                break

    chunks: list[str] = []
    remaining = maximum
    lines_read = 0
    while remaining > 0:
        chunk = handle.readline(min(_READ_CHUNK_CHARACTERS, remaining))
        if not chunk:
            break
        encoded = chunk.encode("utf-8")
        if len(encoded) > remaining:
            chunks.append(encoded[:remaining].decode("utf-8", errors="ignore"))
            break
        chunks.append(chunk)
        remaining -= len(encoded)
        if chunk.endswith("\n"):
            lines_read += 1
            if ranges.limit is not None and lines_read >= ranges.limit:
                break
    return "".join(chunks)
