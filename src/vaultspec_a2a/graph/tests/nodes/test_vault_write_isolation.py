"""Observed-negative proof: the mount path performs zero .vault writes.

No mocks. A continuous filesystem watcher runs across the whole exercise while
the mount node refreshes the vault index and the context mounter reads .vault
docs. The assertion is an observed negative — the watcher records every
create/modify/delete under .vault for the duration and must observe none — not a
no-write-path argument.
"""

import threading
import time
from pathlib import Path

import pytest

from ....thread.state import TeamState, merge_vault_index
from ...nodes.vault_reader import create_context_mounter, create_mount_node

_FEATURE = "mount-isolation"


class _VaultWriteWatcher:
    """Continuous polling watcher recording writes under a directory tree.

    Samples (mtime_ns, size) for every file under ``root`` at a tight interval
    on a background thread, accumulating any created/modified/deleted path
    observed between the start and stop calls. Reads never change mtime or size,
    so read-only mounting produces no events.
    """

    def __init__(self, root: Path, interval: float = 0.005) -> None:
        self._root = root
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.events: list[tuple[str, str]] = []
        self._seen: dict[Path, tuple[int, int]] = {}

    def _snapshot(self) -> dict[Path, tuple[int, int]]:
        snap: dict[Path, tuple[int, int]] = {}
        for path in self._root.rglob("*"):
            if path.is_file():
                try:
                    st = path.stat()
                except OSError:
                    continue
                snap[path] = (st.st_mtime_ns, st.st_size)
        return snap

    def _diff(self, current: dict[Path, tuple[int, int]]) -> None:
        for path, meta in current.items():
            if path not in self._seen:
                self.events.append(("created", str(path)))
            elif self._seen[path] != meta:
                self.events.append(("modified", str(path)))
        for path in self._seen:
            if path not in current:
                self.events.append(("deleted", str(path)))
        self._seen = current

    def _run(self) -> None:
        while not self._stop.is_set():
            self._diff(self._snapshot())
            time.sleep(self._interval)

    def start(self) -> None:
        self._seen = self._snapshot()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        # Final reconcile in case a write landed between the last poll and stop.
        self._diff(self._snapshot())


def _make_workspace(tmp_path: Path) -> Path:
    """Create a workspace with a real .vault/adr document to mount and read."""
    workspace = tmp_path / "ws"
    adr_dir = workspace / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / f"{_FEATURE}-adr.md").write_text(
        "# ADR\n\nBinding decision text.", encoding="utf-8"
    )
    return workspace


def _exec_state() -> TeamState:
    return {
        "messages": [],
        "thread_id": "isolation",
        "active_agent": "coder",
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
        "active_feature": _FEATURE,
        "pipeline_phase": "exec",
        "vault_index": {"adr": [f".vault/adr/{_FEATURE}-adr.md"]},
    }


@pytest.mark.asyncio
async def test_mount_path_performs_zero_vault_writes(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    vault_dir = workspace / ".vault"
    refresh_index = create_mount_node(workspace)
    mounter = create_context_mounter(workspace)

    async def mount(state: TeamState) -> str | None:
        update = await refresh_index(state)
        merged: TeamState = {
            **state,
            "vault_index": merge_vault_index(
                state.get("vault_index") or {}, update.get("vault_index", {})
            ),
        }
        return await mounter(merged)

    watcher = _VaultWriteWatcher(vault_dir)
    watcher.start()
    try:
        # 1. The mount refreshes the index and reads the .vault ADR.
        context = await mount(_exec_state())
        assert context is not None
        assert "Binding decision text." in context  # .vault read succeeded

        # 2. A second pass is served through the mounter's content cache.
        remounted_context = await mount(_exec_state())
        assert remounted_context == context

        # Give the watcher time to observe any stray write before stopping.
        time.sleep(0.05)
    finally:
        watcher.stop()

    assert watcher.events == [], (
        f"Expected zero .vault writes during the mount exercise, "
        f"observed: {watcher.events}"
    )
