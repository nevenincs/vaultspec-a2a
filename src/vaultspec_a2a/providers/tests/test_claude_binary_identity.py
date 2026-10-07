"""One Claude CLI answers for the lane, and the run records which one it was.

The probe that qualifies a lane and the turn that runs on it are driven here
through their own production seams, and the environment each hands its child is
read off a REAL child: the capsule path lets a test own the executable the probe
spawns, so what is asserted is the environment that actually left the process
rather than the one a reading of the code predicts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...graph.enums import Provider
from ...testing import armed_environment, initialize_result, settings_override
from ...thread.errors import ConfigError
from ...utils.enums import AcpRequestId
from .._acp_session import initialize_session
from .._factory_commands import (
    capsule_acp_entry,
    capsule_claude_executable,
    capsule_node_executable,
)
from ..acp_chat_model import AcpChatModel
from ..acp_exceptions import AcpError
from ..cli_resolution import (
    CLAUDE_EXECUTABLE_ENV,
    ProviderRuntimeUnavailableError,
    ProviderRuntimeUnavailableReason,
    pin_claude_executable,
    resolve_provider_cli_executable,
    resolve_service_executable,
)
from ..factory import ProviderFactory, _discover_claude_catalog
from ..provider_catalog import CatalogStatus, HealthState, ProviderCatalogKey

if TYPE_CHECKING:
    from ...conftest import ExternalPrerequisiteRule
    from .._acp_types import AcpSessionContext


@pytest.fixture
def service_claude(external_prerequisite: ExternalPrerequisiteRule) -> str:
    """The CLI this service resolves, or its absence: the coupling needs a real one."""
    executable = resolve_provider_cli_executable(Provider.CLAUDE)
    if executable is None:
        external_prerequisite.absent(
            "claude-cli",
            "the two seams cannot be compared against the binary they must agree on",
        )
    return str(Path(executable).resolve())


def _capsule_that_dumps_its_environment(root: Path, report: Path) -> None:
    """Build a capsule whose Node executable records the environment it got."""
    node = capsule_node_executable(root)
    node.parent.mkdir(parents=True, exist_ok=True)
    installed_node = resolve_service_executable("node")
    assert installed_node is not None
    shutil.copy2(installed_node, node)
    entry = capsule_acp_entry(root)
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "require('node:fs').writeFileSync("
        f"{json.dumps(str(report))}, process.env.CLAUDE_CODE_EXECUTABLE || '')\n",
        encoding="utf-8",
    )
    cli = capsule_claude_executable(root)
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("capsule claude\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_a_served_turn_pins_the_service_claude(
    tmp_path: Path, service_claude: str
) -> None:
    """The environment a turn's child receives names the CLI it must run."""
    model = AcpChatModel(
        command=["node", "index.js"],
        env_vars={},
        workspace_root=str(tmp_path),
        acp_family="claude",
    )

    env = await model._acp_environment()

    assert env[CLAUDE_EXECUTABLE_ENV] == service_claude
    assert Path(env[CLAUDE_EXECUTABLE_ENV]).is_absolute()


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

    assert report.read_text(encoding="utf-8") == str(capsule_claude_executable(capsule))


def test_an_operator_pin_is_not_overridden(tmp_path: Path) -> None:
    """A CLI the operator named for the child stays the one that runs."""
    cli = tmp_path / "operator-claude"
    cli.write_text("operator cli\n", encoding="utf-8")
    env: dict[str, str] = {CLAUDE_EXECUTABLE_ENV: str(cli)}

    resolution = pin_claude_executable(env)

    assert resolution.authority == "child_environment"
    assert resolution.path == cli.resolve()
    assert env[CLAUDE_EXECUTABLE_ENV] == str(cli.resolve())


def test_the_pin_reports_what_it_resolved(service_claude: str) -> None:
    """The caller is handed the path, so a session can record what it ran."""
    env: dict[str, str] = {}

    resolution = pin_claude_executable(env)

    assert resolution.authority == "service_path"
    assert str(resolution.path) == env[CLAUDE_EXECUTABLE_ENV]
    assert env[CLAUDE_EXECUTABLE_ENV] == service_claude


@pytest.mark.asyncio
async def test_capsule_cli_outranks_inherited_pin_and_service_path(
    tmp_path: Path,
) -> None:
    """The environment a real child receives names the capsule CLI."""
    capsule = tmp_path / "capsule"
    cli = capsule_claude_executable(capsule)
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("capsule cli\n", encoding="utf-8")
    inherited = tmp_path / "inherited-claude"
    inherited.write_text("inherited cli\n", encoding="utf-8")
    earlier_on_path = tmp_path / ("claude.cmd" if os.name == "nt" else "claude")
    earlier_on_path.write_text("PATH cli\n", encoding="utf-8")
    earlier_on_path.chmod(0o755)
    env = {CLAUDE_EXECUTABLE_ENV: str(inherited)}
    model = AcpChatModel(
        command=["node", "index.js"],
        env_vars=dict(env),
        workspace_root=str(tmp_path),
        acp_family="claude",
    )

    with (
        settings_override(
            capsule_assets_root=capsule, claude_cli_executable=earlier_on_path
        ),
        armed_environment(PATH=str(tmp_path) + os.pathsep + os.environ["PATH"]),
    ):
        assert os.path.normcase(
            resolve_provider_cli_executable(Provider.CLAUDE) or ""
        ) == os.path.normcase(str(earlier_on_path))
        resolution = pin_claude_executable(env)
        served_env = await model._acp_environment()
        observed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; print(os.environ['CLAUDE_CODE_EXECUTABLE'])",
            ],
            env=served_env,
            capture_output=True,
            text=True,
            check=False,
        )

    assert resolution.authority == "capsule"
    assert resolution.path == cli.resolve()
    assert model._state.session.claude_executable == str(cli.resolve())
    assert observed.returncode == 0, observed.stderr
    assert observed.stdout.strip() == str(cli.resolve())


def test_capsule_outranks_explicit_setting(tmp_path: Path) -> None:
    """An armed capsule keeps ownership despite an external explicit path."""
    explicit = tmp_path / "explicit-claude"
    explicit.write_text("explicit cli\n", encoding="utf-8")
    capsule = tmp_path / "capsule"
    cli = capsule_claude_executable(capsule)
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("capsule cli\n", encoding="utf-8")
    env: dict[str, str] = {}

    with settings_override(claude_cli_executable=explicit, capsule_assets_root=capsule):
        resolution = pin_claude_executable(env)

    assert resolution.authority == "capsule"
    assert resolution.path == cli.resolve()
    assert env[CLAUDE_EXECUTABLE_ENV] == str(cli.resolve())


def test_explicit_setting_selects_cli_without_capsule(tmp_path: Path) -> None:
    """The explicit rung still controls non-capsule profiles."""
    explicit = tmp_path / "explicit-claude"
    explicit.write_text("explicit cli\n", encoding="utf-8")
    env: dict[str, str] = {}

    with settings_override(claude_cli_executable=explicit, capsule_assets_root=None):
        resolution = pin_claude_executable(env)

    assert resolution.authority == "explicit_setting"
    assert resolution.path == explicit.resolve()
    assert env[CLAUDE_EXECUTABLE_ENV] == str(explicit.resolve())


def test_missing_capsule_cli_refuses_even_with_explicit_setting(tmp_path: Path) -> None:
    """A desktop repair condition cannot borrow an external configured CLI."""
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    explicit = tmp_path / "explicit-claude"
    explicit.write_text("explicit cli\n", encoding="utf-8")
    env: dict[str, str] = {}

    with (
        settings_override(claude_cli_executable=explicit, capsule_assets_root=capsule),
        pytest.raises(ProviderRuntimeUnavailableError) as refusal,
    ):
        pin_claude_executable(env)

    assert (
        refusal.value.reason is ProviderRuntimeUnavailableReason.CLAUDE_CLI_UNAVAILABLE
    )
    assert "capsule path is unavailable" in str(refusal.value)
    assert CLAUDE_EXECUTABLE_ENV not in env


def test_missing_capsule_cli_never_borrows_an_inherited_path(tmp_path: Path) -> None:
    """An armed capsule with missing CLI bytes refuses the child."""
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    inherited = tmp_path / "inherited-claude"
    inherited.write_text("inherited cli\n", encoding="utf-8")
    env = {CLAUDE_EXECUTABLE_ENV: str(inherited)}

    with (
        settings_override(capsule_assets_root=capsule),
        pytest.raises(ConfigError, match="capsule path is unavailable"),
    ):
        pin_claude_executable(env)

    assert env[CLAUDE_EXECUTABLE_ENV] == str(inherited)


@pytest.mark.parametrize("provider", (Provider.CLAUDE, Provider.ZAI))
def test_factory_refuses_a_missing_selected_cli(
    provider: Provider, tmp_path: Path
) -> None:
    """Both ACP lanes refuse construction when their selected CLI is absent."""
    capsule = tmp_path / "capsule"
    _capsule_that_dumps_its_environment(capsule, tmp_path / "unused-report")
    capsule_claude_executable(capsule).unlink()
    inherited = tmp_path / "inherited-claude"
    inherited.write_text("host CLI\n", encoding="utf-8")

    with (
        settings_override(capsule_assets_root=capsule),
        armed_environment(CLAUDE_CODE_EXECUTABLE=str(inherited)),
        pytest.raises(ProviderRuntimeUnavailableError) as refusal,
    ):
        ProviderFactory().create(provider, model="frozen", workspace_root=tmp_path)

    assert (
        refusal.value.reason is ProviderRuntimeUnavailableReason.CLAUDE_CLI_UNAVAILABLE
    )
    assert "capsule path is unavailable" in str(refusal.value)


@pytest.mark.asyncio
async def test_catalog_reports_a_missing_selected_cli_as_unavailable(
    tmp_path: Path,
) -> None:
    """Catalog discovery gives a typed reason without opening an ACP child."""
    capsule = tmp_path / "capsule"
    report = tmp_path / "unexpected-child.txt"
    _capsule_that_dumps_its_environment(capsule, report)
    capsule_claude_executable(capsule).unlink()
    key = ProviderCatalogKey(Provider.CLAUDE.value, "claude-agent-acp:node")

    with settings_override(capsule_assets_root=capsule):
        discovery = await _discover_claude_catalog(key, tmp_path)

    assert discovery.catalog.state.status is CatalogStatus.UNAVAILABLE
    assert discovery.catalog.state.reason == (
        ProviderRuntimeUnavailableReason.CLAUDE_CLI_UNAVAILABLE.value
    )
    assert discovery.transport is HealthState.UNAVAILABLE
    assert not report.exists()


@pytest.mark.asyncio
async def test_model_refuses_if_cli_disappears_after_construction(
    tmp_path: Path,
) -> None:
    """The launch checks the same selected file again before spawning ACP."""
    capsule = tmp_path / "capsule"
    _capsule_that_dumps_its_environment(capsule, tmp_path / "unused-report")

    with settings_override(capsule_assets_root=capsule):
        model = AcpChatModel(
            command=["node", "index.js"],
            workspace_root=str(tmp_path),
            acp_family="claude",
            provider=Provider.CLAUDE.value,
            version_proof_required=True,
        )
        capsule_claude_executable(capsule).unlink()
        with pytest.raises(ProviderRuntimeUnavailableError) as refusal:
            await model._acp_environment()

    assert (
        refusal.value.reason is ProviderRuntimeUnavailableReason.CLAUDE_CLI_UNAVAILABLE
    )


def test_lock_vendored_cli_is_an_explicit_last_rung(tmp_path: Path) -> None:
    """A host without a Claude command still pins the npm closure's CLI."""
    env: dict[str, str] = {}
    with (
        settings_override(claude_cli_executable=None, capsule_assets_root=None),
        armed_environment(PATH=str(tmp_path)),
    ):
        resolution = pin_claude_executable(env)

    assert resolution.authority == "lock_vendored"
    assert resolution.path.is_file()
    assert env[CLAUDE_EXECUTABLE_ENV] == str(resolution.path)


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
            "result": initialize_result(
                agent_info={
                    "name": "@agentclientprotocol/claude-agent-acp",
                    "title": "Claude Agent",
                    "version": "0.59.0",
                }
            )
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
    service_claude: str,
) -> None:
    """Adapter and CLI are reported together: either alone explains nothing."""
    model = AcpChatModel(
        command=["node", "index.js"],
        env_vars={},
        workspace_root=str(tmp_path),
        acp_family="claude",
    )
    model._state.session.agent_info = {"name": "adapter-under-test", "version": "9.9.9"}
    model._state.session.claude_executable = service_claude

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
    assert recorded[0]["cli_executable"] == service_claude
