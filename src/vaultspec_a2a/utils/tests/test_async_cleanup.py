"""Cancellation cannot abandon a release that already owns resources."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ..async_cleanup import complete_cleanup

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_file_release(tmp_path: Path) -> None:
    resource = tmp_path / "owned-resource"
    resource.write_text("owned", encoding="utf-8")
    started = asyncio.Event()
    release = asyncio.Event()

    async def cleanup() -> None:
        started.set()
        await release.wait()
        resource.unlink()

    task = asyncio.create_task(complete_cleanup(cleanup()))
    await asyncio.wait_for(started.wait(), timeout=5)
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert resource.exists()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    assert not resource.exists()


@pytest.mark.asyncio
async def test_operation_failure_is_preserved() -> None:
    async def cleanup() -> None:
        raise OSError("release failed")

    with pytest.raises(OSError, match="release failed"):
        await complete_cleanup(cleanup())


@pytest.mark.asyncio
async def test_cancelled_release_preserves_failure_cause() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def cleanup() -> None:
        started.set()
        await release.wait()
        raise OSError("release failed")

    task = asyncio.create_task(complete_cleanup(cleanup()))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(task, timeout=5)
    assert isinstance(caught.value.__cause__, OSError)
