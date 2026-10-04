"""Deletion reclaims replay records without permitting identity recreation."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ...testing import settings_override
from .._journal_index import JournalIndex, journal_name
from .._tool_calls import ToolCallJournal, retire_run_tool_calls, tool_call_journal_path

if TYPE_CHECKING:
    from pathlib import Path


async def _build(refs: dict[str, str | None]) -> tuple[dict[str, str | None], str]:
    refs.update(changeset_id="cs:retained", revision="rev-1")
    return {"changeset_id": refs["changeset_id"]}, "idk:retained-key"


@pytest.mark.asyncio
async def test_retirement_compacts_owned_records_and_fences_old_and_new_roles(
    tmp_path: Path,
) -> None:
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        path = tool_call_journal_path("deleted-run", "writer")
        journal = ToolCallJournal(path, "deleted-run", "writer")
        foreign = ToolCallJournal(
            tool_call_journal_path("retained-run", "writer"), "retained-run", "writer"
        )
        await foreign.prepare("pending", "foreign-input", _build)
        for number in range(128):
            call_id = f"call-{number}"
            await journal.prepare(call_id, "f" * 64, _build)
            await journal.complete(call_id, {"revision": f"rev-{number}"})
        before = path.stat().st_size
        await retire_run_tool_calls("deleted-run")
        await retire_run_tool_calls("deleted-run")
        assert path.stat().st_size < before
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT version FROM owner").fetchone() == (2,)
            assert db.execute("SELECT count(*) FROM calls").fetchone() == (0,)
            assert db.execute("SELECT count(*) FROM lifecycle").fetchone() == (0,)
        for replay in (journal, ToolCallJournal(path, "deleted-run", "writer")):
            with pytest.raises(ValueError, match="retired"):
                await replay.prepare("call-1", "f" * 64, _build)
        fresh_path = tool_call_journal_path("deleted-run", "new-role")
        with pytest.raises(ValueError, match="retired"):
            await ToolCallJournal(fresh_path, "deleted-run", "new-role").prepare(
                "new-call", "new-input", _build
            )
        assert not fresh_path.exists()
        assert await foreign.prepare("pending", "foreign-input", _build) == (
            {"changeset_id": "cs:retained"},
            "idk:retained-key",
        )


@pytest.mark.asyncio
async def test_retirement_fences_an_in_flight_prepare(tmp_path: Path) -> None:
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        path = tool_call_journal_path("racing-run", "writer")
        journal = ToolCallJournal(path, "racing-run", "writer")
        started, release = asyncio.Event(), asyncio.Event()

        async def build(
            refs: dict[str, str | None],
        ) -> tuple[dict[str, str | None], str]:
            started.set()
            await release.wait()
            return await _build(refs)

        prepared = asyncio.create_task(journal.prepare("call-1", "input", build))
        await asyncio.wait_for(started.wait(), timeout=5)
        retiring = asyncio.create_task(retire_run_tool_calls("racing-run"))
        try:
            async with asyncio.timeout(5):
                while not tuple(path.parent.glob("*.closed")):
                    await asyncio.sleep(0.01)
            with pytest.raises(ValueError, match="retired"):
                await journal.prepare("other-call", "input", _build)
        finally:
            release.set()
        with pytest.raises(ValueError, match="retired"):
            await prepared
        await retiring
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT version FROM owner").fetchone() == (2,)
            assert db.execute("SELECT count(*) FROM calls").fetchone() == (0,)
        with pytest.raises(ValueError, match="retired"):
            await journal.prepare("call-1", "input", _build)


@pytest.mark.asyncio
async def test_retained_run_cannot_be_compacted(tmp_path: Path) -> None:
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        journal = ToolCallJournal(
            tool_call_journal_path("live-run", "writer"), "live-run", "writer"
        )
        original = await journal.prepare("call-1", "input", _build)
        with pytest.raises(ValueError, match="must be closed"):
            await journal.retire()
        assert await journal.prepare("call-1", "input", _build) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["corrupt", "missing", "hardlink"])
async def test_index_reclaims_damaged_owned_journal_without_reading_foreign_data(
    tmp_path: Path, damage: str
) -> None:
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        path = tool_call_journal_path("damaged-run", "writer")
        journal = ToolCallJournal(path, "damaged-run", "writer")
        await journal.prepare("original-call", "original-input", _build)
        index = JournalIndex(path.parent)
        assert await index.scopes("damaged-run") == ("writer",)
        foreign = tmp_path / "foreign-data.db"
        foreign.write_bytes(b"unrelated contents must survive")
        path.unlink()
        if damage == "corrupt":
            path.write_bytes(b"damaged SQLite payload")
        elif damage == "hardlink":
            os.link(foreign, path)
            os.link(foreign, path.with_name(path.name + "-wal"))
        await retire_run_tool_calls("damaged-run")
        await retire_run_tool_calls("damaged-run")
        assert foreign.read_bytes() == b"unrelated contents must survive"
        assert path.stat().st_nlink == 1
        assert not path.with_name(path.name + "-wal").exists()
        assert await index.scopes("damaged-run") == ()
        with sqlite3.connect(path) as db:
            assert db.execute(
                "SELECT version, run_id, scope FROM owner"
            ).fetchone() == (
                2,
                "damaged-run",
                "writer",
            )
            assert db.execute("SELECT count(*) FROM calls").fetchone() == (0,)
            assert db.execute("SELECT count(*) FROM lifecycle").fetchone() == (0,)
        with pytest.raises(ValueError, match="retired"):
            await journal.prepare("original-call", "original-input", _build)


@pytest.mark.asyncio
async def test_one_time_adoption_preserves_foreign_and_unclassified_files(
    tmp_path: Path,
) -> None:
    # Actual journals created under a previous state home have no index in the
    # adopting installation. This exercises migration without copied schemas.
    store = tmp_path / "historical-store"
    store.mkdir()
    with settings_override(a2a_home=tmp_path / "old-state", workspace_root=None):
        owned = store / journal_name("historical-run", "writer")
        foreign = store / journal_name("foreign-run", "writer")
        for path, run in ((owned, "historical-run"), (foreign, "foreign-run")):
            await ToolCallJournal(path, run, "writer").prepare("call", "input", _build)
    foreign_bytes = foreign.read_bytes()
    corrupt = store / "unrelated.db"
    corrupt.write_bytes(b"unclassifiable historical corruption")
    misplaced = store / "misnamed.db"
    misplaced.write_bytes(foreign_bytes)
    with settings_override(a2a_home=tmp_path / "new-state", workspace_root=None):
        index = JournalIndex(store)
        assert await index.scopes("historical-run") == ("writer",)
        assert await index.scopes("foreign-run") == ("writer",)
        # Once ownership is inventoried, corrupt payloads cannot defeat cleanup.
        owned.write_bytes(b"corruption after historical ownership was established")
        await retire_run_tool_calls("historical-run", directory=store)
        assert await index.scopes("historical-run") == ()
        assert await index.scopes("foreign-run") == ("writer",)
        assert foreign.read_bytes() == foreign_bytes
        assert misplaced.read_bytes() == foreign_bytes
        assert corrupt.read_bytes() == b"unclassifiable historical corruption"
        # A file introduced after adoption is not new deletion authority. A
        # rescan would classify this real journal and compact it incorrectly.
        late = store / journal_name("late-run", "writer")
        with settings_override(a2a_home=tmp_path / "other-index", workspace_root=None):
            await ToolCallJournal(late, "late-run", "writer").prepare(
                "late-call", "late-input", _build
            )
        late_bytes = late.read_bytes()
        await retire_run_tool_calls("late-run", directory=store)
        assert late.read_bytes() == late_bytes


@pytest.mark.asyncio
async def test_corrupt_ownership_index_is_a_real_cleanup_failure(
    tmp_path: Path,
) -> None:
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        path = tool_call_journal_path("index-run", "writer")
        journal = ToolCallJournal(path, "index-run", "writer")
        await journal.prepare("original-call", "original-input", _build)
        index = JournalIndex(path.parent)
        index._path().write_bytes(b"corrupt private ownership inventory")
        original = path.read_bytes()
        with pytest.raises(sqlite3.DatabaseError):
            await retire_run_tool_calls("index-run")
        assert path.read_bytes() == original
        with pytest.raises(ValueError, match="retired"):
            await journal.prepare("original-call", "original-input", _build)


@pytest.mark.asyncio
async def test_concurrent_registration_keeps_every_run_owner(tmp_path: Path) -> None:
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        paths = [
            tool_call_journal_path(f"parallel-{number}", "writer")
            for number in range(8)
        ]
        await asyncio.gather(
            *(
                ToolCallJournal(path, f"parallel-{number}", "writer").prepare(
                    "call", "input", _build
                )
                for number, path in enumerate(paths)
            )
        )
        index = JournalIndex(paths[0].parent)
        for number in range(8):
            assert await index.scopes(f"parallel-{number}") == ("writer",)
        await retire_run_tool_calls("parallel-0")
        assert await index.scopes("parallel-0") == ()
        assert await index.scopes("parallel-1") == ("writer",)


@pytest.mark.asyncio
async def test_retirement_removes_crashed_sqlite_rollback_state(tmp_path: Path) -> None:
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        path = tool_call_journal_path("crashed-run", "writer")
        await ToolCallJournal(path, "crashed-run", "writer").prepare(
            "original-call", "original-input", _build
        )
        # Crash a real writer after dirty-page eviction makes its rollback
        # journal hot. Replacing only the database allows SQLite to restore the
        # old owner and calls when the purportedly compacted file is reopened.
        crashed = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-c",
                "import os,sqlite3,sys; db=sqlite3.connect(sys.argv[1]); "
                "db.execute('PRAGMA cache_size=1'); "
                "db.execute('BEGIN IMMEDIATE'); "
                "db.execute('UPDATE owner SET version=99'); "
                "db.execute('UPDATE calls SET fingerprint=?', ('x'*400000,)); "
                "os._exit(0)",
                str(path),
            ],
            capture_output=True,
            timeout=10,
        )
        assert crashed.returncode == 0, crashed.stderr
        rollback = path.with_name(path.name + "-journal")
        assert rollback.exists()
        assert rollback.read_bytes()[:8] == b"\xd9\xd5\x05\xf9 \xa1c\xd7"
        await retire_run_tool_calls("crashed-run")
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT version FROM owner").fetchone() == (2,)
            assert db.execute("SELECT count(*) FROM calls").fetchone() == (0,)
        assert not rollback.exists()


@pytest.mark.asyncio
async def test_processes_racing_index_publication_preserve_all_owners(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    gate = tmp_path / "release"
    peer = tmp_path / "register_journal.py"
    peer.write_text(
        "import asyncio,sys,time\n"
        "from pathlib import Path\n"
        "from vaultspec_a2a.testing import settings_override\n"
        "from vaultspec_a2a.authoring import _tool_calls as calls\n"
        "async def build(refs): return {},'idk:process-key'\n"
        "with settings_override(a2a_home=Path(sys.argv[1]),workspace_root=None):\n"
        " Path(sys.argv[3]).write_text('ready')\n"
        " while not Path(sys.argv[2]).exists(): time.sleep(0.005)\n"
        " run=sys.argv[4]\n"
        " journal=calls.ToolCallJournal(\n"
        "  calls.tool_call_journal_path(run,'writer'),run,'writer')\n"
        " asyncio.run(journal.prepare('call','input',build))\n"
    )
    processes: list[asyncio.subprocess.Process] = []
    ready = [tmp_path / f"ready-{number}" for number in range(4)]
    with settings_override(a2a_home=state, workspace_root=None):
        path = tool_call_journal_path("process-0", "writer")
        try:
            for number in range(4):
                processes.append(
                    await asyncio.create_subprocess_exec(
                        sys.executable,
                        str(peer),
                        str(state),
                        str(gate),
                        str(ready[number]),
                        f"process-{number}",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                )
            async with asyncio.timeout(30):
                while not all(item.exists() for item in ready):
                    await asyncio.sleep(0.01)
                gate.touch()
                results = await asyncio.gather(
                    *(process.communicate() for process in processes)
                )
            for process, (_stdout, stderr) in zip(processes, results, strict=True):
                assert process.returncode == 0, stderr
            index = JournalIndex(path.parent)
            for number in range(4):
                assert await index.scopes(f"process-{number}") == ("writer",)
        finally:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
