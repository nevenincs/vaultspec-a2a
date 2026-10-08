"""A Kimi ACP session's per-session config home is torn down at release.

No mocks: a real ``AcpChatModel`` drives the real ACP protocol simulator as a
subprocess. The per-run isolated ``KIMI_CODE_HOME`` (``kimi_config_home.py``)
must be built fresh for this session and removed once the session releases its
resources - never left for the 24h orphan sweep to reclaim - exactly as the
Codex chat model builds and cleans up its own per-turn config home.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ...testing import simulator_command
from .._config_home_roots import temp_home_root
from ..acp_chat_model import AcpChatModel

if TYPE_CHECKING:
    from pathlib import Path

_KIMI_HOME_PREFIX = "vaultspec-kimi-home-"


async def _drive_one_kimi_session(workspace: Path, *, prompt_delay: float) -> None:
    model = AcpChatModel(
        command=simulator_command(
            "--response", "done", "--prompt-delay", str(prompt_delay)
        ),
        env_vars={},
        acp_family="kimi",
        workspace_root=str(workspace),
    )
    async for _ in model.astream([HumanMessage(content="hi")]):
        pass


@pytest.mark.asyncio
async def test_kimi_session_builds_and_tears_down_its_own_config_home(
    tmp_path: Path,
) -> None:
    """A fresh per-session home appears while the session runs, and is gone after.

    The home is built before the simulator is even spawned, so a slow reply
    (``--prompt-delay``) is enough room for a concurrent poll to observe it
    while the session is still open - proving the build happened at all, which
    a model driven directly (bypassing the factory) never did before this fix.
    """
    root = temp_home_root()
    before = set(root.glob(f"{_KIMI_HOME_PREFIX}*"))

    task = asyncio.create_task(_drive_one_kimi_session(tmp_path, prompt_delay=0.5))
    seen_during: set[Path] = set()
    try:
        deadline = asyncio.get_running_loop().time() + 5.0
        while not task.done() and asyncio.get_running_loop().time() < deadline:
            current = set(root.glob(f"{_KIMI_HOME_PREFIX}*")) - before
            if current:
                seen_during |= current
                break
            await asyncio.sleep(0.02)
        await task
    finally:
        if not task.done():
            task.cancel()

    assert seen_during, "no per-session Kimi config home appeared during the session"
    for home in seen_during:
        assert not home.exists(), f"{home} was not torn down at session release"


@pytest.mark.asyncio
async def test_two_sequential_turns_on_the_same_model_each_get_a_fresh_home(
    tmp_path: Path,
) -> None:
    """A model instance invoked for a second turn is not handed a dead home.

    A home baked into ``env_vars`` once, at construction, would still be
    referenced by a second turn on the same model instance after the first
    turn's teardown removed it. Building and tearing down within each session
    call instead means every turn gets its own live home, never a stale path.
    """
    model = AcpChatModel(
        command=simulator_command("--response", "done"),
        env_vars={},
        acp_family="kimi",
        workspace_root=str(tmp_path),
    )
    root = temp_home_root()
    before = set(root.glob(f"{_KIMI_HOME_PREFIX}*"))

    for _ in range(2):
        async for _chunk in model.astream([HumanMessage(content="hi")]):
            pass
        # Each turn tears its own home down before the astream call returns -
        # nothing from this turn is left for the next one to collide with.
        assert set(root.glob(f"{_KIMI_HOME_PREFIX}*")) == before
