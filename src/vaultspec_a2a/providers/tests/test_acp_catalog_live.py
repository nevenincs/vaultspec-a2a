"""Live prompt-free discovery proof against the installed ACP adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
import pytest

from ...control.config import settings
from ...graph.enums import Provider
from ...workspace.environment import resolve_env_vars
from .._claude_tool_policy import claude_bypass_declined_meta
from .._factory_commands import _classify_acp_command, claude_acp_entry
from ..acp_catalog import discover_acp_catalog
from ..cli_resolution import resolve_provider_cli_executable
from ..factory import _discover_claude_catalog, claude_auth_env
from ..provider_catalog import (
    AuthenticationState,
    CatalogStatus,
    ProviderCatalogKey,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _real_adapter_inputs() -> tuple[
    tuple[str, ...], dict[str, str], Mapping[str, object]
]:
    if settings.acp_backend != "binary" and not claude_acp_entry().exists():
        pytest.fail(
            "ACP adapter is not installed; run 'npm install' per the ACP runbook"
        )
    command, metadata = _classify_acp_command(settings.acp_backend)
    workspace = Path.cwd()
    environment = resolve_env_vars(workspace)
    auth_environment, _auth_mode = claude_auth_env()
    environment.update(auth_environment)
    environment.pop("ANTHROPIC_API_KEY", None)
    if claude := resolve_provider_cli_executable(Provider.CLAUDE):
        environment["CLAUDE_CODE_EXECUTABLE"] = claude
    environment.pop("CLAUDECODE", None)
    return tuple(command), environment, metadata


@pytest.mark.service
@pytest.mark.asyncio
async def test_real_adapter_catalog_discovery_reaps_without_prompt() -> None:
    """Drive the production handshake; returning proves cleanup completed."""
    command, environment, metadata = _real_adapter_inputs()
    workspace = Path.cwd()

    discovery = await discover_acp_catalog(
        command,
        env=environment,
        cwd=str(workspace),
        key=ProviderCatalogKey("claude", "acp"),
        metadata=metadata,
        session_meta=claude_bypass_declined_meta(),
    )

    assert discovery.authentication is AuthenticationState.AUTHENTICATED
    assert discovery.catalog.state.status in {
        CatalogStatus.AVAILABLE,
        CatalogStatus.UNAVAILABLE,
    }
    if discovery.catalog.state.status is CatalogStatus.AVAILABLE:
        assert discovery.catalog.models
    else:
        assert discovery.catalog.models == ()
        assert discovery.catalog.state.reason == (
            "provider session did not advertise model enumeration"
        )


@pytest.mark.service
@pytest.mark.asyncio
async def test_the_production_claude_probe_opens_a_session_on_this_host() -> None:
    """The factory's own probe reaches a session, composing its own posture.

    The test above supplies the session meta itself, which proves the adapter
    accepts it but not that production sends it. This drives the production
    assembly end to end instead: whatever posture ``_discover_claude_catalog``
    composes is the posture the real adapter is handed, and a probe that cannot
    open a session reports the lane unavailable - indistinguishable, from the
    gateway, from a lane that is genuinely missing.
    """
    if settings.acp_backend != "binary" and not claude_acp_entry().exists():
        pytest.fail(
            "ACP adapter is not installed; run 'npm install' per the ACP runbook"
        )
    key = ProviderCatalogKey(
        Provider.CLAUDE.value, f"claude-agent-acp:{settings.acp_backend}"
    )

    discovery = await _discover_claude_catalog(key, Path.cwd())

    assert discovery.catalog.state.status is CatalogStatus.AVAILABLE, (
        discovery.catalog.state.reason
    )
    assert discovery.catalog.models


@pytest.mark.service
@pytest.mark.asyncio
async def test_real_adapter_catalog_discovery_reaps_when_cancelled() -> None:
    command, environment, metadata = _real_adapter_inputs()
    workspace = Path.cwd()
    parent = psutil.Process()
    baseline = {child.pid for child in parent.children(recursive=True)}
    task = asyncio.create_task(
        discover_acp_catalog(
            command,
            env=environment,
            cwd=str(workspace),
            key=ProviderCatalogKey("claude", "acp"),
            metadata=metadata,
            session_meta=claude_bypass_declined_meta(),
        )
    )
    deadline = asyncio.get_running_loop().time() + 10.0
    observed: list[psutil.Process] = []
    while not observed and not task.done():
        observed = [
            child
            for child in parent.children(recursive=True)
            if child.pid not in baseline
        ]
        if observed or asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(0.02)
    assert observed, "real adapter spawned no observable contained process"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=20.0)
    _, alive = await asyncio.to_thread(psutil.wait_procs, observed, timeout=10.0)
    assert not alive, [process.pid for process in alive]
