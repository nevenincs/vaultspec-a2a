"""Deletion reclaims replay records without permitting identity recreation."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING

import pytest

from ...testing import settings_override
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
        try:
            await retire_run_tool_calls("racing-run")
        finally:
            release.set()
        with pytest.raises(ValueError, match="retired"):
            await prepared
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
