"""The Claude lane states its own permission posture on every session.

Two layers, both real. The installed adapter bundle is read to establish what a
client may pin through the session options and what the adapter reassigns
afterwards, and the production session setup is driven over real OS pipes to
prove the posture actually leaves the process.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import pytest_asyncio

from ...team.team_config import load_agent_config
from ...utils.enums import AcpRequestId
from .._acp_session import claude_session_options, setup_session
from .._acp_types import AcpModelConfig, AcpSessionContext, PermissionCallback
from .._claude_tool_policy import (
    AUTONOMOUS_PERMISSION_MODE,
    CLAUDE_DENIED_READ_PATHS,
    CLAUDE_FILE_WRITE_TOOLS,
    CLAUDE_PATH_RULE_TOOLS,
    CLAUDE_TERMINAL_TOOLS,
    MODE_CONFIG_OPTION_ID,
    workspace_scoped_tool_rule,
)
from ..acp_exceptions import AcpSessionError
from ._acp_frames import read_acp_frame
from ._installed_vocabulary import (
    acp_adapter_permission_mode_ids,
    acp_adapter_source,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .._json_contract import JsonObject

_SESSION_ID = "session-under-test"
_TIMEOUT = 10.0

# Echoes each stdin line back on stdout, so the frame a production seam wrote is
# readable from the same context. A real pipe round-trip through a real process.
_ECHO_CHILD = (
    "import sys\n"
    "for line in sys.stdin.buffer:\n"
    "    sys.stdout.buffer.write(line)\n"
    "    sys.stdout.buffer.flush()\n"
)


@pytest_asyncio.fixture
async def echo_context() -> AsyncIterator[AcpSessionContext]:
    """Yield a production context bound to a real echoing child process."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _ECHO_CHILD,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    context = AcpSessionContext(
        process=process,
        stdin=process.stdin,
        stdout=process.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
    )
    try:
        yield context
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()


def _config(
    *,
    agent_id: str,
    workspace_root: Path,
    permission_callback: PermissionCallback | None = None,
) -> AcpModelConfig:
    """Build the real frozen config a claude-family session is set up from."""
    return AcpModelConfig(
        agent_config=load_agent_config(agent_id),
        permission_callback=permission_callback,
        workspace_root=str(workspace_root),
        command=["claude-agent-acp"],
        env_vars={},
        session_id=None,
        mcp_servers=[],
        use_exec=False,
        provider="claude",
        runtime_authority=None,
        acp_backend="node",
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
        acp_family="claude",
    )


def _tool_names(value: object) -> list[str]:
    """Read one wire list of tool names without assuming its element type."""
    assert isinstance(value, list)
    items = cast("list[object]", value)
    names = [item for item in items if isinstance(item, str)]
    assert len(names) == len(items)
    return names


def _session_result(
    *, current_mode: str, available_modes: tuple[str, ...]
) -> JsonObject:
    """An adapter ``session/new`` result advertising modes and a mode option."""
    return {
        "sessionId": _SESSION_ID,
        "modes": {
            "currentModeId": current_mode,
            "availableModes": [{"id": mode} for mode in available_modes],
        },
        "configOptions": [
            {
                "id": MODE_CONFIG_OPTION_ID,
                "category": "mode",
                "currentValue": current_mode,
            }
        ],
    }


def test_session_options_admit_no_ambient_settings_source(tmp_path: Path) -> None:
    """The lane reads none of the operator's or the workspace's settings."""
    options = claude_session_options(
        _config(agent_id="vaultspec-adr-author", workspace_root=tmp_path)
    )

    assert options["settingSources"] == []
    assert options["strictMcpConfig"] is True


@pytest.mark.parametrize(
    ("agent_id", "denied", "permitted"),
    [
        pytest.param(
            "vaultspec-adr-author",
            CLAUDE_FILE_WRITE_TOOLS + CLAUDE_TERMINAL_TOOLS,
            (),
            id="no-write-no-terminal",
        ),
        pytest.param(
            "vaultspec-coder",
            CLAUDE_TERMINAL_TOOLS,
            CLAUDE_FILE_WRITE_TOOLS,
            id="write-but-no-terminal",
        ),
        pytest.param(
            "mock-coder-success",
            (),
            CLAUDE_FILE_WRITE_TOOLS + CLAUDE_TERMINAL_TOOLS,
            id="write-and-terminal",
        ),
    ],
)
def test_session_options_deny_the_built_ins_a_persona_may_not_use(
    tmp_path: Path,
    agent_id: str,
    denied: tuple[str, ...],
    permitted: tuple[str, ...],
) -> None:
    """A persona's declared capabilities reach the CLI's own built-in tools."""
    options = claude_session_options(
        _config(agent_id=agent_id, workspace_root=tmp_path)
    )

    disallowed = _tool_names(options.get("disallowedTools", []))
    assert set(denied) <= set(disallowed)
    assert set(permitted).isdisjoint(disallowed)


def test_installed_adapter_lets_the_client_choose_its_setting_sources() -> None:
    """The adapter defaults to ambient sources and the client's value wins."""
    source = acp_adapter_source()

    default = source.index('settingSources: ["user", "project", "local"]')
    spread = source.index("...userProvidedOptions,", default)
    reassigned = source.index("permissionMode,", default)

    # The client block is merged over the adapter's defaults, so the empty
    # source list this project sends replaces them ...
    assert default < spread
    # ... while the resolved permission mode is assigned after that merge, which
    # is why the mode is pinned by a later configuration call instead.
    assert spread < reassigned


def test_installed_adapter_keeps_the_client_denied_tools() -> None:
    """The adapter appends its own denials to the client's rather than replacing."""
    assert (
        "disallowedTools: [...(userProvidedOptions?.disallowedTools || []), "
        "...disallowedTools]" in acp_adapter_source()
    )


def test_installed_adapter_advertises_the_unattended_permission_mode() -> None:
    """The mode an unattended run asks for is one the adapter can actually serve."""
    assert AUTONOMOUS_PERMISSION_MODE in acp_adapter_permission_mode_ids()


def test_the_pinned_mode_is_the_one_that_still_asks_this_project() -> None:
    """The pin keeps the permission rung in the path, by the adapter's own words.

    The alternative reads as the stricter choice and is the opposite: a mode that
    never asks decides every uncovered call inside the CLI, where this run's
    exact-name allowlist and its cross-project refusal do not exist.
    """
    source = acp_adapter_source()

    assert AUTONOMOUS_PERMISSION_MODE == "default"
    assert f'id: "{AUTONOMOUS_PERMISSION_MODE}",' in source
    assert "prompts for dangerous operations" in source
    assert "Don't prompt for permissions, deny if not pre-approved" in source


@pytest.mark.asyncio
async def test_unattended_session_is_pinned_away_from_an_ambient_mode(
    echo_context: AcpSessionContext, tmp_path: Path
) -> None:
    """An operator default the session arrives in is replaced before any prompt.

    ``acceptEdits`` is the ambient hazard exactly: the adapter resolves it from
    the operator's own settings, and it approves file edits before this project's
    permission rung is consulted.
    """
    config = _config(agent_id="vaultspec-adr-author", workspace_root=tmp_path)
    task = asyncio.create_task(setup_session(echo_context, config, {}, []))

    new_session = await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SETUP, timeout=_TIMEOUT
    )
    assert new_session["method"] == "session/new"
    params = new_session["params"]
    assert isinstance(params, dict)
    meta = params["_meta"]
    assert isinstance(meta, dict)
    claude_code = meta["claudeCode"]
    assert isinstance(claude_code, dict)
    options = claude_code["options"]
    assert isinstance(options, dict)
    assert options["settingSources"] == []
    assert "Bash" in _tool_names(options["disallowedTools"])
    echo_context.response_futures[AcpRequestId.SESSION_SETUP].set_result(
        {
            "result": _session_result(
                current_mode="acceptEdits",
                available_modes=("acceptEdits", AUTONOMOUS_PERMISSION_MODE),
            )
        }
    )

    mode_change = await read_acp_frame(
        echo_context.stdout,
        AcpRequestId.SESSION_SET_CONFIG_OPTION,
        timeout=_TIMEOUT,
    )
    assert mode_change["params"] == {
        "sessionId": _SESSION_ID,
        "configId": MODE_CONFIG_OPTION_ID,
        "value": AUTONOMOUS_PERMISSION_MODE,
    }
    echo_context.response_futures[AcpRequestId.SESSION_SET_CONFIG_OPTION].set_result(
        {
            "result": {
                "configOptions": [
                    {
                        "id": MODE_CONFIG_OPTION_ID,
                        "category": "mode",
                        "currentValue": AUTONOMOUS_PERMISSION_MODE,
                    }
                ]
            }
        }
    )

    result = await task
    assert result.agent_modes["currentModeId"] == AUTONOMOUS_PERMISSION_MODE


@pytest.mark.asyncio
async def test_unattended_session_refuses_a_mode_it_cannot_verify(
    echo_context: AcpSessionContext, tmp_path: Path
) -> None:
    """A session that reports a different mode than it was set to fails the run."""
    config = _config(agent_id="vaultspec-adr-author", workspace_root=tmp_path)
    task = asyncio.create_task(setup_session(echo_context, config, {}, []))

    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SETUP, timeout=_TIMEOUT
    )
    echo_context.response_futures[AcpRequestId.SESSION_SETUP].set_result(
        {
            "result": _session_result(
                current_mode="acceptEdits",
                available_modes=("acceptEdits", AUTONOMOUS_PERMISSION_MODE),
            )
        }
    )
    await read_acp_frame(
        echo_context.stdout,
        AcpRequestId.SESSION_SET_CONFIG_OPTION,
        timeout=_TIMEOUT,
    )
    echo_context.response_futures[AcpRequestId.SESSION_SET_CONFIG_OPTION].set_result(
        {
            "result": {
                "configOptions": [
                    {
                        "id": MODE_CONFIG_OPTION_ID,
                        "category": "mode",
                        "currentValue": "acceptEdits",
                    }
                ]
            }
        }
    )

    with pytest.raises(AcpSessionError, match="permission mode"):
        await task


@pytest.mark.asyncio
async def test_unattended_session_refuses_a_lane_without_the_mode(
    echo_context: AcpSessionContext, tmp_path: Path
) -> None:
    """A lane that advertises modes but cannot deny by default is refused."""
    config = _config(agent_id="vaultspec-adr-author", workspace_root=tmp_path)
    task = asyncio.create_task(setup_session(echo_context, config, {}, []))

    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SETUP, timeout=_TIMEOUT
    )
    echo_context.response_futures[AcpRequestId.SESSION_SETUP].set_result(
        {
            "result": _session_result(
                current_mode="acceptEdits",
                available_modes=("acceptEdits", "dontAsk"),
            )
        }
    )

    with pytest.raises(AcpSessionError, match="cannot run unattended"):
        await task


@pytest.mark.asyncio
async def test_supervised_session_keeps_the_mode_it_negotiated(
    echo_context: AcpSessionContext, tmp_path: Path
) -> None:
    """With a human rung installed the session is left in its negotiated mode."""

    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        return "allow_once"

    config = _config(
        agent_id="vaultspec-adr-author",
        workspace_root=tmp_path,
        permission_callback=callback,
    )
    task = asyncio.create_task(setup_session(echo_context, config, {}, []))

    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SETUP, timeout=_TIMEOUT
    )
    echo_context.response_futures[AcpRequestId.SESSION_SETUP].set_result(
        {
            "result": _session_result(
                current_mode="acceptEdits",
                available_modes=("acceptEdits", AUTONOMOUS_PERMISSION_MODE),
            )
        }
    )

    result = await task
    assert result.agent_modes["currentModeId"] == "acceptEdits"
    assert AcpRequestId.SESSION_SET_CONFIG_OPTION not in echo_context.response_futures


@pytest.mark.asyncio
async def test_unattended_session_survives_an_agent_that_advertises_no_modes(
    echo_context: AcpSessionContext, tmp_path: Path
) -> None:
    """An agent with no mode surface is run and reported, not refused.

    The pinned adapter always advertises its modes, so a session without them is
    another agent of the same family whose posture is its own; there is nothing
    to pin and the run stays bounded by its allowlist and the permission rung.
    """
    config = _config(agent_id="vaultspec-adr-author", workspace_root=tmp_path)
    task = asyncio.create_task(setup_session(echo_context, config, {}, []))

    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SETUP, timeout=_TIMEOUT
    )
    echo_context.response_futures[AcpRequestId.SESSION_SETUP].set_result(
        {"result": {"sessionId": _SESSION_ID}}
    )

    result = await task
    assert result.session_id == _SESSION_ID
    assert AcpRequestId.SESSION_SET_CONFIG_OPTION not in echo_context.response_futures


def test_every_session_denies_the_credential_and_process_trees(
    tmp_path: Path,
) -> None:
    """The paths that hand over a run's own credentials are denied outright.

    Denied whoever is running and whatever the persona may otherwise do: the
    scope rule below bounds where a read is APPROVED, and these name the places
    where one mistake about that is unrecoverable.
    """
    options = claude_session_options(
        _config(agent_id="mock-coder-success", workspace_root=tmp_path)
    )

    disallowed = _tool_names(options["disallowedTools"])
    assert [f"Read({path})" for path in CLAUDE_DENIED_READ_PATHS] == [
        rule for rule in disallowed if rule.startswith("Read(")
    ]
    assert "Read(~/.ssh/**)" in disallowed
    assert "Read(/proc/**)" in disallowed


def test_a_read_grant_names_the_workspace_it_is_for(tmp_path: Path) -> None:
    """A read built-in is permitted inside the run's project, not on the host.

    The bare name is a grant over every file the operator can read. The rule
    carries an absolute pattern because the CLI resolves a relative one against
    a base directory this side does not choose.
    """
    assert workspace_scoped_tool_rule("Read", str(tmp_path)) == f"Read({tmp_path}/**)"
    # A tool whose rule grammar takes no path keeps its bare name rather than
    # carrying an unmatchable one, and so does a run with no workspace to name.
    assert "Grep" not in CLAUDE_PATH_RULE_TOOLS
    assert workspace_scoped_tool_rule("Grep", str(tmp_path)) == "Grep"
    assert workspace_scoped_tool_rule("Read", None) == "Read"


def test_installed_sdk_admits_a_path_pattern_for_every_scoped_tool() -> None:
    """The scoped rules are written in a grammar the installed SDK really has.

    The SDK classifies which tools take a file pattern; a rule for a tool
    outside that set would read as a scope while matching nothing.
    """
    source = (
        Path(__file__).resolve().parents[4]
        / "node_modules"
        / "@anthropic-ai"
        / "claude-agent-sdk"
        / "sdk.mjs"
    ).read_text(encoding="utf-8", errors="replace")
    declaration = source[source.index("filePatternTools:") :][:200]

    for tool in CLAUDE_PATH_RULE_TOOLS:
        assert f'"{tool}"' in declaration, tool
    assert '"Grep"' not in declaration
