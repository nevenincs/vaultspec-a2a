"""One Claude CLI answers for the lane, and the run records which one it was.

The probe that qualifies a lane and the turn that runs on it are driven here
through their own production seams, and the environment each hands its child is
read off a REAL child: the capsule path lets a test own the executable the probe
spawns, so what is asserted is the environment that actually left the process
rather than the one a reading of the code predicts.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...graph.enums import Provider
from ...testing import settings_override
from ...utils.enums import AcpRequestId
from .._acp_session import initialize_session
from .._factory_commands import capsule_acp_entry, capsule_node_executable
from ..acp_chat_model import AcpChatModel
from ..acp_exceptions import AcpError
from ..cli_resolution import (
    CLAUDE_EXECUTABLE_ENV,
    pin_claude_executable,
    resolve_provider_cli_executable,
)
from ..factory import _discover_claude_catalog
from ..provider_catalog import ProviderCatalogKey

if TYPE_CHECKING:
    from .._acp_types import AcpSessionContext


def _service_claude() -> str:
    """The CLI this service resolves, or skip: the coupling needs a real one."""
    executable = resolve_provider_cli_executable(Provider.CLAUDE)
    if executable is None:
        pytest.fail(
            "the Claude CLI is not installed on this host, so the two seams "
            "cannot be compared against the binary they must agree on"
        )
    return executable


def _capsule_that_dumps_its_environment(root: Path, report: Path) -> None:
    """Build a capsule whose Node executable records the environment it got."""
    node = capsule_node_executable(root)
    node.parent.mkdir(parents=True, exist_ok=True)
    node.write_text(f"#!/bin/sh\nprintenv > {report}\nexit 0\n", encoding="utf-8")
    node.chmod(0o755)
    entry = capsule_acp_entry(root)
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("// capsule acp entry\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_a_served_turn_pins_the_service_claude(tmp_path: Path) -> None:
    """The environment a turn's child receives names the CLI it must run."""
    model = AcpChatModel(
        command=["node", "index.js"],
        env_vars={},
        workspace_root=str(tmp_path),
        acp_family="claude",
    )

    env = await model._acp_environment()

    assert env[CLAUDE_EXECUTABLE_ENV] == _service_claude()
    assert Path(env[CLAUDE_EXECUTABLE_ENV]).is_absolute()


@pytest.mark.skipif(
    os.name != "posix", reason="the capsule executable is a POSIX shell script"
)
@pytest.mark.asyncio
async def test_the_catalog_probe_pins_the_same_claude(tmp_path: Path) -> None:
    """The probe's own child carries the same pin, read off the real spawn.

    Unpinned, the adapter falls back to its vendored CLI - so this is the
    assertion that the catalog describes the binary the lane will serve rather
    than a second one nobody chose. The probe's own outcome is irrelevant here
    and this capsule cannot satisfy it: what is under test is the environment
    that reached the child, which the child itself writes down.
    """
    report = tmp_path / "probe-env.txt"
    capsule = tmp_path / "capsule"
    _capsule_that_dumps_its_environment(capsule, report)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with settings_override(capsule_assets_root=capsule), suppress(AcpError):
        await _discover_claude_catalog(
            ProviderCatalogKey(
                provider_id=Provider.CLAUDE.value,
                execution_mode="claude-agent-acp:node",
            ),
            workspace,
        )

    spawned = report.read_text(encoding="utf-8").splitlines()
    assert f"{CLAUDE_EXECUTABLE_ENV}={_service_claude()}" in spawned


def test_an_operator_pin_is_not_overridden() -> None:
    """A CLI the operator named for the child stays the one that runs."""
    env: dict[str, str] = {
        CLAUDE_EXECUTABLE_ENV: os.path.join(os.sep, "opt", "operator", "claude")
    }

    assert pin_claude_executable(env) == env[CLAUDE_EXECUTABLE_ENV]
    assert env[CLAUDE_EXECUTABLE_ENV] == os.path.join(
        os.sep, "opt", "operator", "claude"
    )


def test_the_pin_reports_what_it_resolved() -> None:
    """The caller is handed the path, so a session can record what it ran."""
    env: dict[str, str] = {}

    assert pin_claude_executable(env) == env.get(CLAUDE_EXECUTABLE_ENV)
    assert env[CLAUDE_EXECUTABLE_ENV] == _service_claude()


@pytest.mark.asyncio
async def test_the_handshake_identity_is_carried_off_the_wire(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    """The adapter names itself once, in initialize, and the run keeps it."""
    config = AcpChatModel(
        command=["node", "index.js"],
        env_vars={},
        workspace_root=str(tmp_path),
        acp_family="claude",
    )._state.config
    task = asyncio.create_task(initialize_session(acp_session_context, config))
    while AcpRequestId.INITIALIZE not in acp_session_context.response_futures:
        await asyncio.sleep(0)
    acp_session_context.response_futures[AcpRequestId.INITIALIZE].set_result(
        {
            "result": {
                "protocolVersion": 1,
                "agentCapabilities": {},
                "authMethods": [],
                "agentInfo": {
                    "name": "@agentclientprotocol/claude-agent-acp",
                    "title": "Claude Agent",
                    "version": "0.59.0",
                },
            }
        }
    )

    result = await task

    assert result.agent_info["name"] == "@agentclientprotocol/claude-agent-acp"
    assert result.agent_info["version"] == "0.59.0"


@pytest.mark.asyncio
async def test_the_run_reports_both_halves_of_what_it_ran(
    acp_session_context: AcpSessionContext,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Adapter and CLI are reported together: either alone explains nothing."""
    model = AcpChatModel(
        command=["node", "index.js"],
        env_vars={},
        workspace_root=str(tmp_path),
        acp_family="claude",
    )
    model._state.session.agent_info = {"name": "adapter-under-test", "version": "9.9.9"}
    model._state.session.claude_executable = _service_claude()

    with caplog.at_level(logging.INFO, logger="vaultspec_a2a.providers"):
        model._record_provider_identity(acp_session_context)

    recorded = [
        vars(record)
        for record in caplog.records
        if record.message == "ACP provider identity"
    ]
    assert recorded, caplog.messages
    assert recorded[0]["agent_name"] == "adapter-under-test"
    assert recorded[0]["agent_version"] == "9.9.9"
    assert recorded[0]["cli_executable"] == _service_claude()
