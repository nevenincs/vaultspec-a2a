"""A Kimi ACP session's per-session config home is torn down at release.

No mocks: a real ``AcpChatModel`` drives the real ACP protocol simulator as a
subprocess. The per-run isolated ``KIMI_CODE_HOME`` (``kimi_config_home.py``)
must be built fresh for this session and removed once the session releases its
resources - never left for the 24h orphan sweep to reclaim - exactly as the
Codex chat model builds and cleans up its own per-turn config home.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from ...testing import simulator_command
from .. import kimi_config_home
from .._config_home_roots import temp_home_root
from ..acp_chat_model import AcpChatModel

_KIMI_HOME_PREFIX = "vaultspec-kimi-home-"
_BUILDER_LOGGER = kimi_config_home.__name__
_BUILT_MESSAGE = "Kimi isolated config home created at %s"


def _built_homes(caplog: pytest.LogCaptureFixture) -> list[Path]:
    """Return the homes this test's sessions built, from the builder's record."""
    return [
        Path(str(record.args[0]))
        for record in caplog.records
        if record.name == _BUILDER_LOGGER
        and record.msg == _BUILT_MESSAGE
        and isinstance(record.args, tuple)
    ]


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
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A fresh per-session home appears while the session runs, and is gone after.

    The home is built before the simulator is even spawned, so a slow reply
    (``--prompt-delay``) is enough room for a concurrent poll to observe it
    while the session is still open - proving the build happened at all, which
    a model driven directly (bypassing the factory) never did before this fix.
    The home is named by the builder's creation record, never by listing the
    root other test workers share.
    """
    root = temp_home_root()
    seen_during: set[Path] = set()
    with caplog.at_level(logging.DEBUG, logger=_BUILDER_LOGGER):
        task = asyncio.create_task(_drive_one_kimi_session(tmp_path, prompt_delay=0.5))
        try:
            deadline = asyncio.get_running_loop().time() + 5.0
            while not task.done() and asyncio.get_running_loop().time() < deadline:
                live = {home for home in _built_homes(caplog) if home.is_dir()}
                if live:
                    seen_during |= live
                    break
                await asyncio.sleep(0.02)
            await task
        finally:
            if not task.done():
                task.cancel()
        built = _built_homes(caplog)

    assert seen_during, "no per-session Kimi config home appeared during the session"
    assert len(built) == 1, f"one session built {len(built)} Kimi homes"
    for home in built:
        assert home.parent == root
        assert home.name.startswith(_KIMI_HOME_PREFIX)
        assert not home.exists(), f"{home} was not torn down at session release"


@pytest.mark.asyncio
async def test_two_sequential_turns_on_the_same_model_each_get_a_fresh_home(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A model instance invoked for a second turn is not handed a dead home.

    A home baked into ``env_vars`` once, at construction, would still be
    referenced by a second turn on the same model instance after the first
    turn's teardown removed it. Building and tearing down within each session
    call instead means every turn gets its own live home, never a stale path.

    The homes are identified by the builder's own creation record rather than
    by listing the shared root: every test worker in a session creates and
    removes Kimi homes in that same directory, so a before/after listing
    compares this test's turns against other workers' sessions.
    """
    model = AcpChatModel(
        command=simulator_command("--response", "done"),
        env_vars={},
        acp_family="kimi",
        workspace_root=str(tmp_path),
    )
    root = temp_home_root()
    homes: list[Path] = []

    with caplog.at_level(logging.DEBUG, logger=_BUILDER_LOGGER):
        for turn in range(2):
            caplog.clear()
            async for _chunk in model.astream([HumanMessage(content="hi")]):
                pass
            built = _built_homes(caplog)
            assert len(built) == 1, f"turn {turn} built {len(built)} Kimi homes"
            home = built[0]
            assert home.parent == root
            assert home.name.startswith(_KIMI_HOME_PREFIX)
            # Each turn tears its own home down before the astream call returns -
            # nothing from this turn is left for the next one to collide with.
            assert not home.exists(), f"turn {turn} left {home} behind"
            homes.append(home)

    assert homes[0] != homes[1], "the second turn was handed the first turn's home"
