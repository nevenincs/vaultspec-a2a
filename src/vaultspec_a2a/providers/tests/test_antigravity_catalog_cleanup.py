"""Catalog CLI discovery owns its real processes, descendants, and pipe budget."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from typing import TYPE_CHECKING

import pytest

from ...utils.process import kill_pid_tree_async, pid_is_live
from .._subprocess import kill_process_tree, spawn_acp_process
from ..antigravity_catalog import _read_listing, discover_antigravity_catalog
from ..provider_catalog import AuthenticationState, ProviderCatalogKey

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_catalog_discovery_reaps_descendants(
    tmp_path: Path, cancel: bool
) -> None:
    (tmp_path / "models").write_text(
        "import os, pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(120)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL)\n"
        "pathlib.Path('pids').write_text(str(os.getpid()) + ' ' + str(child.pid))\n"
        "print('model-id\\tModel name', flush=True)\n"
        f"time.sleep({120 if cancel else 0})\n",
        encoding="utf-8",
    )
    task = asyncio.create_task(
        discover_antigravity_catalog(
            ProviderCatalogKey("antigravity", "cli"),
            tmp_path,
            cli_path=sys.executable,
        )
    )
    pids: list[int] = []
    try:
        async with asyncio.timeout(10):
            while not (tmp_path / "pids").exists():
                await asyncio.sleep(0.01)
        pids = [int(value) for value in (tmp_path / "pids").read_text().split()]
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=15)
        else:
            catalog, authentication = await asyncio.wait_for(task, timeout=15)
            assert authentication is AuthenticationState.AUTHENTICATED
            assert [model.provider_value for model in catalog.models] == ["model-id"]
        assert not any(pid_is_live(pid) for pid in pids)
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        for pid in pids:
            await kill_pid_tree_async(pid, term_timeout=1, kill_timeout=2)


@pytest.mark.asyncio
async def test_catalog_drains_both_pipes_with_bounded_retention(tmp_path: Path) -> None:
    process = await spawn_acp_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'a' * (2 << 20)); "
            "sys.stderr.buffer.write(b'b' * (2 << 20))",
        ],
        os.environ.copy(),
        str(tmp_path),
        use_exec=True,
    )
    try:
        output = await _read_listing(process, timeout=10)
        assert len(output) == 1 << 20
        assert process.returncode == 0
    finally:
        await kill_process_tree(process)


@pytest.mark.asyncio
async def test_catalog_pipe_wait_has_a_deadline(tmp_path: Path) -> None:
    process = await spawn_acp_process(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        os.environ.copy(),
        str(tmp_path),
        use_exec=True,
    )
    try:
        with pytest.raises(TimeoutError):
            await _read_listing(process, timeout=0.05)
    finally:
        await kill_process_tree(process)
    assert process.returncode is not None
