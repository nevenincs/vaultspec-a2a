"""Unit proofs for the per-path provider write lock.

Real locks on the running test loop, real paths on disk: the key minting, the
mutual exclusion it produces, and the self-cleaning that keeps a long run's
registry from growing one entry per file ever written.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from .._write_lock import ProviderWriteLock, provider_write_lock


@pytest.mark.asyncio
async def test_two_spellings_of_one_file_share_a_lock(tmp_path: Path) -> None:
    """A traversal spelling and the direct one name one file, so one lock.

    Minting the key inside the lock is what makes this true: two writers must
    not be ordered by whether each normalized its own path first.
    """
    (tmp_path / "sub").mkdir()
    direct = tmp_path / "target.txt"
    traversed = tmp_path / "sub" / ".." / "target.txt"
    assert ".." in traversed.parts

    write_lock = ProviderWriteLock()
    entered = asyncio.Event()

    async def second_writer() -> None:
        async with write_lock.hold(traversed):
            entered.set()

    async with write_lock.hold(direct):
        waiter = asyncio.create_task(second_writer())
        await asyncio.sleep(0.05)
        assert not entered.is_set()

    await asyncio.wait_for(waiter, timeout=5)
    assert entered.is_set()


@pytest.mark.asyncio
async def test_distinct_files_are_not_ordered(tmp_path: Path) -> None:
    """One lock per file, so holding two files at once is not a deadlock.

    A single mutex covering the workspace would hang here, which is the state
    this replaced.
    """
    write_lock = ProviderWriteLock()
    async with (
        write_lock.hold(tmp_path / "one.txt"),
        write_lock.hold(tmp_path / "two.txt"),
    ):
        assert len(write_lock._entries) == 2


@pytest.mark.asyncio
async def test_a_relative_path_is_refused() -> None:
    """A relative key would resolve against the serving process's directory."""
    write_lock = ProviderWriteLock()
    with pytest.raises(ValueError, match="absolute file path"):
        async with write_lock.hold(Path("target.txt")):
            pass


@pytest.mark.asyncio
async def test_the_registry_empties_once_every_writer_leaves(tmp_path: Path) -> None:
    write_lock = ProviderWriteLock()
    target = tmp_path / "counted.txt"
    held = asyncio.Event()
    release = asyncio.Event()

    async def writer() -> None:
        async with write_lock.hold(target):
            held.set()
            await release.wait()

    first = asyncio.create_task(writer())
    await asyncio.wait_for(held.wait(), timeout=5)
    second = asyncio.create_task(writer())
    await asyncio.sleep(0)

    # Two writers, one entry: the second is queued on the first's lock.
    assert len(write_lock._entries) == 1

    release.set()
    await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
    assert write_lock._entries == {}


@pytest.mark.asyncio
async def test_a_failing_writer_releases_its_entry(tmp_path: Path) -> None:
    write_lock = ProviderWriteLock()
    with pytest.raises(RuntimeError, match="writer failed"):
        async with write_lock.hold(tmp_path / "broken.txt"):
            raise RuntimeError("writer failed")
    assert write_lock._entries == {}


def test_every_config_default_shares_one_registry() -> None:
    """The default reach covers every writer of a file in this process.

    Two roles of one run are separate model instances over one workspace, so a
    registry minted per config would let both replace one file at once.
    """
    assert provider_write_lock() is provider_write_lock()
