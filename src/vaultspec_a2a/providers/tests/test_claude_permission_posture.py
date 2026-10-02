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
from langchain_core.messages import HumanMessage

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
    claude_rule_path,
    workspace_scoped_tool_rule,
)
from ..acp_chat_model import AcpChatModel
from ..acp_exceptions import AcpSessionError
from ._acp_frames import read_acp_frame
from ._installed_vocabulary import (
    acp_adapter_permission_mode_ids,
    acp_adapter_session_mode_source,
    acp_adapter_shell_tool_names,
    acp_adapter_source,
)

if TYPE_CHECKING:
    from .._json_contract import JsonObject

_SESSION_ID = "session-under-test"
_TIMEOUT = 10.0
_SIMULATOR = (
    Path(__file__).parent.parent.parent / "graph" / "tests" / "acp_simulator.py"
)

# Echoes each stdin line back on stdout, so the frame a production seam wrote is
# readable from the same context. A real pipe round-trip through a real process.


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


def test_installed_adapter_lets_the_client_choose_its_setting_sources(
    installed_acp_adapter: Path,
) -> None:
    """The adapter defaults to ambient sources and the client's value wins."""
    del installed_acp_adapter
    source = acp_adapter_source()

    default = source.index('settingSources: ["user", "project", "local"]')
    spread = source.index("...userProvidedOptions,", default)
    reassigned = source.index("permissionMode: initialPermissionMode,", default)

    # The client block is merged over the adapter's defaults, so the empty
    # source list this project sends replaces them ...
    assert default < spread
    # ... while the resolved permission mode is assigned after that merge, which
    # is why the mode is pinned by a later configuration call instead.
    assert spread < reassigned


def test_installed_adapter_keeps_the_client_denied_tools(
    installed_acp_adapter: Path,
) -> None:
    """The adapter appends its own denials to the client's rather than replacing."""
    del installed_acp_adapter
    assert (
        "disallowedTools: [...(userProvidedOptions?.disallowedTools || []), "
        "...disallowedTools]" in acp_adapter_source()
    )


def test_installed_adapter_advertises_the_unattended_permission_mode(
    installed_acp_adapter: Path,
) -> None:
    """The mode an unattended run asks for is one the adapter can actually serve."""
    del installed_acp_adapter
    assert AUTONOMOUS_PERMISSION_MODE in acp_adapter_permission_mode_ids()


def test_the_pinned_mode_is_the_one_that_still_asks_this_project(
    installed_acp_adapter: Path,
) -> None:
    """The pin keeps the permission rung in the path, by the adapter's own words.

    Every other mode the adapter advertises decides an uncovered call somewhere
    this run's exact-name allowlist and its cross-project refusal do not exist -
    inside the CLI, or inside a classifier model. The pinned mode is the only
    one that routes the call back out to this project's own rung, which is the
    whole reason an unattended session pins a mode at all.
    """
    del installed_acp_adapter
    source = acp_adapter_session_mode_source()

    assert AUTONOMOUS_PERMISSION_MODE == "default"
    assert f'id: "{AUTONOMOUS_PERMISSION_MODE}",' in source
    assert "Always ask before making changes" in source
    # The alternatives, in the adapter's own words. Each of them answers an
    # uncovered call without asking this project: two decide it inside the CLI
    # and one hands the decision to a model.
    assert "Automatically accept all file edits" in source
    assert "Accepts all permissions" in source
    assert "Claude handles permission decisions" in source


def test_the_unattended_mode_is_one_the_adapter_will_actually_accept(
    installed_acp_adapter: Path,
) -> None:
    """The pinned mode is advertised, not merely parseable.

    The adapter still PARSES mode names it no longer offers, and rejects the
    request when one is asked for, so "the adapter knows this name" is not the
    property a pin needs. What it needs is membership of the catalog a session
    reports, which is the list the adapter validates a configuration change
    against.
    """
    del installed_acp_adapter
    advertised = acp_adapter_permission_mode_ids()

    assert AUTONOMOUS_PERMISSION_MODE in advertised
    # Withdrawn from the catalog upstream while the parser still accepts the
    # spelling: asking for it now fails the session rather than pinning it.
    assert "dontAsk" not in advertised
    assert 'case "dontAsk":' in acp_adapter_session_mode_source()


def test_the_session_declines_the_permission_bypass_capability(
    tmp_path: Path,
) -> None:
    """The lane refuses the capability to step around its own permission rung.

    The adapter grants bypass to any session that does not decline it, and a
    granted bypass is both a mode in the catalog and a skip-permissions flag on
    the spawned CLI. Pinning the mode does not withdraw either, so the capability
    is declined where a client can decline it - in the session options block.
    """
    options = claude_session_options(
        _config(agent_id="vaultspec-adr-author", workspace_root=tmp_path)
    )

    assert options["allowDangerouslySkipPermissions"] is False


def test_the_installed_adapter_reads_the_declined_bypass_capability(
    installed_acp_adapter: Path,
) -> None:
    """The option this lane declines is the one the adapter's gate reads.

    The gate is read off the RAW session meta rather than off the merged option
    block, so the key has to be spelled where the adapter looks for it. An
    option sent under a name the gate never reads would leave the capability
    granted while reading, here and in review, as though it were refused.
    """
    del installed_acp_adapter
    source = acp_adapter_source()

    assert (
        "sessionMeta?.claudeCode?.options?.allowDangerouslySkipPermissions !== false"
        in source
    )
    # The same resolved value arms both halves of the capability: the flag the
    # CLI is spawned with, and whether the catalog offers the bypass mode.
    assert "allowDangerouslySkipPermissions: allowBypass," in source
    assert "this.buildAvailableModes(allowBypass)" in acp_adapter_session_mode_source()


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
    task = asyncio.create_task(setup_session(echo_context, config, []))

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
    task = asyncio.create_task(setup_session(echo_context, config, []))

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
    task = asyncio.create_task(setup_session(echo_context, config, []))

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
    task = asyncio.create_task(setup_session(echo_context, config, []))

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
async def test_unattended_session_refuses_an_agent_that_advertises_no_modes(
    echo_context: AcpSessionContext, tmp_path: Path
) -> None:
    """An agent with no mode surface cannot carry an unattended run.

    The pinned adapter always advertises its modes, so a session without them is
    another agent of the same family - and one whose posture is its own is one
    this run never chose. There is nothing to pin and nothing to verify, which
    is the condition the pin exists to prevent rather than a lesser form of it.
    """
    config = _config(agent_id="vaultspec-adr-author", workspace_root=tmp_path)
    task = asyncio.create_task(setup_session(echo_context, config, []))

    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SETUP, timeout=_TIMEOUT
    )
    echo_context.response_futures[AcpRequestId.SESSION_SETUP].set_result(
        {"result": {"sessionId": _SESSION_ID}}
    )

    with pytest.raises(AcpSessionError, match="advertises no permission modes"):
        await task
    assert AcpRequestId.SESSION_SET_CONFIG_OPTION not in echo_context.response_futures


@pytest.mark.asyncio
async def test_supervised_session_still_runs_against_an_agent_without_modes(
    echo_context: AcpSessionContext, tmp_path: Path
) -> None:
    """The refusal is about the missing rung, not about the modes themselves.

    A supervised run has a human at the permission prompt, which is what the
    pinned mode exists to stand in for, so a lane with no mode surface is still
    a lane that run can use.
    """

    async def callback(
        _name: str, _args: JsonObject, _options: list[JsonObject]
    ) -> str:
        return "allow_once"

    config = _config(
        agent_id="vaultspec-adr-author",
        workspace_root=tmp_path,
        permission_callback=callback,
    )
    task = asyncio.create_task(setup_session(echo_context, config, []))

    await read_acp_frame(
        echo_context.stdout, AcpRequestId.SESSION_SETUP, timeout=_TIMEOUT
    )
    echo_context.response_futures[AcpRequestId.SESSION_SETUP].set_result(
        {"result": {"sessionId": _SESSION_ID}}
    )

    result = await task
    assert result.session_id == _SESSION_ID


def _simulator_model(tmp_path: Path, *extra_args: str) -> AcpChatModel:
    """An unattended model over a real ACP subprocess, with no permission rung."""
    return AcpChatModel(
        command=[
            sys.executable,
            str(_SIMULATOR),
            "--response",
            "done",
            *extra_args,
        ],
        env_vars={},
        workspace_root=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_an_unattended_turn_against_a_modeless_lane_never_starts(
    tmp_path: Path,
) -> None:
    """End to end over a real subprocess: no mode surface, no unattended turn.

    The lane is driven through the whole production path - spawn, handshake,
    session - rather than by handing a session result to the setup function, so
    what is proven is that the turn does not happen.
    """
    model = _simulator_model(tmp_path, "--omit-modes")

    with pytest.raises(AcpSessionError, match="advertises no permission modes"):
        async for _ in model.astream([HumanMessage(content="go")]):
            pass


@pytest.mark.asyncio
async def test_the_same_lane_advertising_modes_completes_its_turn(
    tmp_path: Path,
) -> None:
    """Control: the refusal is the missing mode surface and nothing else.

    Identical lane, identical run, one flag apart. Without this the refusal
    above would prove only that an unattended turn against the simulator fails.
    """
    model = _simulator_model(tmp_path)

    served = ""
    async for chunk in model.astream([HumanMessage(content="go")]):
        served += str(chunk.content)

    assert "done" in served


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
    assert [f"Read({claude_rule_path(path)})" for path in CLAUDE_DENIED_READ_PATHS] == [
        rule for rule in disallowed if rule.startswith("Read(")
    ]
    assert "Read(~/.ssh/**)" in disallowed
    # Two slashes, because one anchors the rule at the session's own working
    # directory: `Read(/proc/**)` denies `<workspace>/proc/**`, which is a
    # directory no workspace has, so the process tree stayed readable.
    assert "Read(//proc/**)" in disallowed
    assert "Read(/proc/**)" not in disallowed


def test_every_denied_absolute_path_is_anchored_at_the_filesystem_root() -> None:
    """No deny rule may be written with the anchor that means the workspace.

    Stated over the whole list rather than one entry, because the failure is
    silent: a rule with one slash is accepted, matches a directory that does
    not exist, and reads exactly like the protection it is not.
    """
    for path in CLAUDE_DENIED_READ_PATHS:
        rendered = claude_rule_path(path)
        assert rendered.startswith(("//", "~/")), rendered


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/proc/**", "//proc/**", id="posix-absolute"),
        pytest.param("~/.ssh/**", "~/.ssh/**", id="home-relative-unchanged"),
        pytest.param("~/.claude.json", "~/.claude.json", id="home-relative-file"),
        # The CLI normalises a Windows path to POSIX with the drive as the
        # first segment, lower-cased, before it matches anything.
        pytest.param("C:\\Users\\alice", "//c/Users/alice", id="windows-drive"),
        pytest.param("c:/Users/alice", "//c/Users/alice", id="windows-forward-slash"),
        # Drive-relative, which is not an absolute path and must not be
        # anchored as though it were.
        pytest.param("C:notes.txt", "C:notes.txt", id="drive-relative-unchanged"),
        pytest.param("src/**", "src/**", id="relative-unchanged"),
    ],
)
def test_a_rule_path_is_written_with_the_anchor_the_cli_resolves(
    path: str, expected: str
) -> None:
    """One renderer decides what "this exact path" looks like in a rule."""
    assert claude_rule_path(path) == expected


def test_a_read_grant_names_the_workspace_it_is_for(tmp_path: Path) -> None:
    """A read built-in is permitted inside the run's project, not on the host.

    The bare name is a grant over every file the operator can read. The rule
    carries the CLI's own absolute anchor, because a single leading slash is
    resolved against the session's working directory - so the rule that looked
    like the project's absolute path named a directory beneath it that does not
    exist, and matched nothing at all.
    """
    rule = workspace_scoped_tool_rule("Read", str(tmp_path))

    assert rule == f"Read({claude_rule_path(str(tmp_path))}/**)"
    assert rule.startswith("Read(//")
    # A tool whose rule grammar takes no path keeps its bare name rather than
    # carrying an unmatchable one, and so does a run with no workspace to name.
    assert "Grep" not in CLAUDE_PATH_RULE_TOOLS
    assert workspace_scoped_tool_rule("Grep", str(tmp_path)) == "Grep"
    assert workspace_scoped_tool_rule("Read", None) == "Read"


def test_a_windows_workspace_scope_names_its_drive_the_way_the_cli_does() -> None:
    """A rule for a Windows project renders the same whichever host writes it.

    The lane is served from either, and a rule rendered against the serving
    host's path flavour would be a scope on one and an unmatchable string on
    the other.
    """
    assert (
        workspace_scoped_tool_rule("Read", "C:\\Users\\alice\\project")
        == "Read(//c/Users/alice/project/**)"
    )
    assert workspace_scoped_tool_rule("Glob", "D:\\work") == "Glob(//d/work/**)"


def test_installed_sdk_admits_a_path_pattern_for_every_scoped_tool(
    installed_acp_adapter: Path,
) -> None:
    """The scoped rules are written in a grammar the installed SDK really has.

    The SDK classifies which tools take a file pattern; a rule for a tool
    outside that set would read as a scope while matching nothing.
    """
    del installed_acp_adapter
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


def test_a_terminal_less_persona_is_denied_every_shell_tool_the_adapter_knows(
    installed_acp_adapter: Path,
) -> None:
    """A persona that may not run commands may not run them under any tool name.

    The deny list names the command-execution built-ins one at a time, so it
    goes stale silently: a CLI that grows a second shell tool leaves a persona
    with ``terminal = false`` holding it, and nothing fails. The adapter binds
    every tool whose call is a command line to one shared shell reporter, which
    is its own answer to the same question, so the list is checked against that
    binding rather than against memory.
    """
    del installed_acp_adapter
    denied = set(
        _tool_names(
            claude_session_options(
                _config(agent_id="vaultspec-adr-author", workspace_root=Path.cwd())
            ).get("disallowedTools", [])
        )
    )

    undenied = sorted(acp_adapter_shell_tool_names() - denied)

    assert not undenied, (
        f"the pinned adapter renders {undenied} as shell commands, but a "
        "persona declaring no terminal capability is not denied them"
    )
