"""The harness registry's root-pin axis, its refusal, and the per-run pin seam.

Real objects only, no mocks: composition runs against a production
``AcpChatModel``, the registry entries a refusal is shown are built through the
production construction seam, and the pin channel itself is exercised against the
real search server over a real MCP stdio session.

Two things are deliberately NOT claimed here. The live case proves the declared
channel is the SERVER's own root authority and outranks the working directory it
was launched in; it does not prove the strict claude lane delivers that value to
the spawned server, because the lane placeholder-substitutes registry env values
and hoists only the authoring bridge's real values into the spawn environment. And
composition pins only when a caller states a project: no test here asserts that a
run reaches this seam with one, because that wiring lives outside this module and
asserting it from inside would prove nothing about the run.
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ...thread.errors import ConfigError
from .._acp_authoring import AUTHORING_MCP_SERVER_NAME
from .._acp_mcp import (
    _KNOWN_MCP_SERVERS,
    _declare_registry,
    _launch_spec,
    _require_root_pin,
    _require_trust_root,
    codex_mcp_server_specs,
    compose_harness_mcp_servers,
    harness_server_root_pin,
    harness_spawn_env,
    pin_harness_mcp_servers,
    resolve_harness_mcp_servers,
)
from .._acp_session import session_surface_mcp_servers
from .._acp_types import AcpModelConfig
from .._json_contract import JsonObject
from ..acp_chat_model import AcpChatModel

if TYPE_CHECKING:
    from .._json_contract import FrozenJsonObject, JsonObject, JsonValue

RAG = "vaultspec-rag"
RAG_PIN_VARIABLE = "VAULTSPEC_RAG_ROOT"

# A live stdio handshake plus one tool call against the runtime-acquired search
# server. Warm it is seconds; the ceiling covers a cold `uvx` acquisition without
# letting a wedged handshake hang the suite.
_LIVE_PROBE_TIMEOUT_SECONDS = 120.0


def _declared_entry(name: str, root_pin: str | None) -> FrozenJsonObject:
    """Build one registry entry through the production construction seam.

    The registry is closed and frozen by design and its single shipped entry is
    pinnable, so a guard that only ever saw ``_KNOWN_MCP_SERVERS`` could never be
    shown the case it exists to refuse. Declaring an entry through
    :func:`_declare_registry` gives the guards a REAL entry - constructor-
    validated, frozen, identical in kind to a shipped one - rather than a stand-in
    for one, which is what keeps the refusal tests honest without reaching for a
    patch.
    """
    registry = _declare_registry(
        {
            name: {
                "name": name,
                "command": "uvx",
                "args": ["--from", "example", "example-mcp"],
                "tools": ["search"],
                "read_only": True,
                "network_egress": False,
                "root_pin": root_pin,
                "exact_surface": False,
            }
        }
    )
    entry = registry[name]
    assert isinstance(entry, MappingProxyType)
    return entry


def _shipped_entry(name: str) -> FrozenJsonObject:
    """Return one entry of the closed registry, narrowed as the readers narrow it."""
    entry = _KNOWN_MCP_SERVERS[name]
    assert isinstance(entry, MappingProxyType)
    return entry


def test_every_registry_entry_declares_the_root_pin_axis() -> None:
    """No shipped entry may reach a run with its project binding unstated."""
    for name, entry in _KNOWN_MCP_SERVERS.items():
        assert isinstance(entry, MappingProxyType)
        assert "root_pin" in entry, f"{name} declares no root-pin axis"
        pin = entry["root_pin"]
        assert pin is None or (isinstance(pin, str) and pin), (
            f"{name} declares a malformed root pin: {pin!r}"
        )


def test_the_search_server_declares_its_own_root_channel() -> None:
    # The variable is the server's, not a convention invented here: it is the
    # root authority the installed server itself honours (proven live below).
    assert harness_server_root_pin(RAG) == RAG_PIN_VARIABLE


def test_registry_construction_refuses_an_omitted_root_pin() -> None:
    """Omission must not read as permission, exactly as for the other two axes."""
    with pytest.raises(ConfigError) as excinfo:
        _declare_registry(
            {
                "probe": {
                    "name": "probe",
                    "command": "uvx",
                    "args": [],
                    "read_only": True,
                    "network_egress": False,
                }
            }
        )
    message = str(excinfo.value)
    assert "root_pin" in message
    assert "probe" in message


@pytest.mark.parametrize("declared", [True, "", 7, []])
def test_registry_construction_refuses_a_malformed_root_pin(
    declared: JsonValue,
) -> None:
    # The axis names a channel; a boolean, an empty string, or any other shape
    # cannot be acted on, so it is refused where entries are written.
    with pytest.raises(ConfigError):
        _declare_registry(
            {
                "probe": {
                    "name": "probe",
                    "command": "uvx",
                    "args": [],
                    "read_only": True,
                    "network_egress": False,
                    "root_pin": declared,
                    "exact_surface": False,
                }
            }
        )


def test_registry_construction_admits_an_explicitly_unpinnable_entry() -> None:
    """Declaring unpinnable is constructible; SURFACING it is what is refused.

    The same division the read-only axis draws: the constructor enforces that the
    axis was declared, and the composition guards decide what a declared value may
    do. Without this the refusal below would be unreachable and the axis would
    collapse into a constructor check.
    """
    entry = _declared_entry("unpinnable", None)
    assert entry["root_pin"] is None


def test_the_root_pin_axis_stays_registry_metadata() -> None:
    # Like ``tools``, the axis is registry metadata and not part of the advertised
    # stdio shape; a run must never advertise its own trust declarations.
    spec = resolve_harness_mcp_servers([RAG])[0]
    assert "root_pin" not in spec
    assert set(spec) <= {"name", "command", "args", "env"}


def test_launch_spec_rendering_refuses_an_unpinnable_server() -> None:
    """The single ACP spec renderer refuses rather than surfacing unpinned.

    Both public ACP paths - ``resolve_harness_mcp_servers`` and the composition
    seam - render through this function, so the refusal cannot be reached by one
    and missed by the other.
    """
    with pytest.raises(ConfigError) as excinfo:
        _launch_spec("unpinnable", _declared_entry("unpinnable", None))
    message = str(excinfo.value)
    assert "unpinnable" in message
    assert "root pin" in message
    # The shipped entry renders through the same call unchanged.
    rendered = _launch_spec(RAG, _shipped_entry(RAG))
    assert rendered["name"] == RAG


def test_the_trust_root_holds_the_pin_axis_with_the_other_two() -> None:
    # The guard both delivery shapes share: the shipped entry satisfies all three
    # axes, and an unpinnable entry is refused by the same pin guard the trust
    # root calls.
    _require_trust_root(RAG)
    with pytest.raises(ConfigError):
        _require_root_pin("unpinnable", _declared_entry("unpinnable", None))
    assert _require_root_pin(RAG, _shipped_entry(RAG)) == RAG_PIN_VARIABLE


def test_pin_carries_the_bound_project_through_the_declared_channel(
    tmp_path: Path,
) -> None:
    project = str(tmp_path)
    [spec] = pin_harness_mcp_servers(
        resolve_harness_mcp_servers([RAG]), project_root=project
    )
    assert spec["env"] == [{"name": RAG_PIN_VARIABLE, "value": project}]
    # The pin is additive: what to launch is unchanged, only which project it
    # serves is now stated.
    assert spec["command"] == "uvx"
    assert spec["args"] == ["--from", "vaultspec-rag[mcp]", "vaultspec-search-mcp"]


def test_pin_returns_fresh_specs_and_mutates_no_input(tmp_path: Path) -> None:
    resolved = resolve_harness_mcp_servers([RAG])
    pinned = pin_harness_mcp_servers(resolved, project_root=str(tmp_path))
    assert "env" not in resolved[0]
    assert pinned[0] is not resolved[0]


def test_pin_leaves_a_non_registry_spec_untouched(tmp_path: Path) -> None:
    """The run's own bridge travels in the same list and is not this seam's call.

    Whether a non-registry spec belongs in the surface at all is the declared-
    surface allowlist's question; silently pinning one here would apply a registry
    server's channel to something the registry never reviewed.
    """
    bridge: JsonObject = {
        "name": "vaultspec-authoring",
        "command": "python",
        "args": ["-m", "example"],
        "env": [{"name": "VAULTSPEC_AUTHORING_RUN_ID", "value": "run-1"}],
    }
    pinned = pin_harness_mcp_servers([bridge], project_root=str(tmp_path))
    assert pinned[0]["env"] == [
        {"name": "VAULTSPEC_AUTHORING_RUN_ID", "value": "run-1"}
    ]


def test_pin_refuses_an_environment_expansion_marker() -> None:
    """The literals rule survives the seam that takes an outside value.

    A ``${...}`` in an env value is expanded by whatever parses the surfacing
    config, so a pin carrying one would bind the server to the serving process's
    environment rather than to the run's project.
    """
    with pytest.raises(ConfigError) as excinfo:
        pin_harness_mcp_servers(
            resolve_harness_mcp_servers([RAG]), project_root="${PROJECT_ROOT}"
        )
    assert "${" in str(excinfo.value)


@pytest.mark.parametrize("project_root", ["", "   ", "relative/project"])
def test_pin_refuses_a_project_root_that_binds_nothing(project_root: str) -> None:
    # A blank pin names no project; a relative one is resolved against the
    # launched server's working directory, which is the undeclared inheritance
    # the pin exists to replace.
    with pytest.raises(ConfigError):
        pin_harness_mcp_servers(
            resolve_harness_mcp_servers([RAG]), project_root=project_root
        )


def test_pin_refuses_a_spec_that_already_declares_the_variable(
    tmp_path: Path,
) -> None:
    # Two statements of the run's project are a disagreement, not a default.
    [spec] = pin_harness_mcp_servers(
        resolve_harness_mcp_servers([RAG]), project_root=str(tmp_path)
    )
    with pytest.raises(ConfigError) as excinfo:
        pin_harness_mcp_servers([spec], project_root=str(tmp_path))
    assert RAG_PIN_VARIABLE in str(excinfo.value)


def test_compose_pins_the_advertised_server_to_the_run_project(
    tmp_path: Path,
) -> None:
    """The real composition seam: what an ACP session would advertise."""
    project = str(tmp_path)
    model = AcpChatModel(command=["echo"], env_vars={})
    composed = compose_harness_mcp_servers(model, [RAG], project_root=project)
    assert isinstance(composed, AcpChatModel)
    [spec] = composed.mcp_servers
    assert spec["name"] == RAG
    assert spec["env"] == [{"name": RAG_PIN_VARIABLE, "value": project}]


def test_compose_pins_beside_an_existing_bridge_without_touching_it(
    tmp_path: Path,
) -> None:
    model = AcpChatModel(
        command=["echo"],
        env_vars={},
        mcp_servers=[
            {
                "name": "vaultspec-authoring",
                "command": "python",
                "env": [{"name": "VAULTSPEC_AUTHORING_RUN_ID", "value": "run-1"}],
            }
        ],
    )
    composed = compose_harness_mcp_servers(model, [RAG], project_root=str(tmp_path))
    assert isinstance(composed, AcpChatModel)
    by_name = {spec["name"]: spec for spec in composed.mcp_servers}
    assert by_name["vaultspec-authoring"]["env"] == [
        {"name": "VAULTSPEC_AUTHORING_RUN_ID", "value": "run-1"}
    ]
    assert by_name[RAG]["env"] == [{"name": RAG_PIN_VARIABLE, "value": str(tmp_path)}]


def test_composition_never_invents_a_project_pin() -> None:
    """A caller that states no project gets no pin - not a derived one.

    Deriving the pin from the working directory would restate the undeclared
    inheritance the axis exists to replace, spelled as a default and therefore
    invisible. The seam either carries a project a caller stated or carries none.
    """
    model = AcpChatModel(command=["echo"], env_vars={})
    composed = compose_harness_mcp_servers(model, [RAG])
    assert isinstance(composed, AcpChatModel)
    [spec] = composed.mcp_servers
    assert "env" not in spec


def test_codex_specs_carry_the_pin_in_that_transports_env_shape(
    tmp_path: Path,
) -> None:
    # One registry, two serializations: the Codex config.toml block models env as
    # a flat mapping where the ACP stdio shape models it as name/value pairs, so
    # the same declared channel is rendered twice rather than pinned once.
    project = str(tmp_path)
    [spec] = codex_mcp_server_specs([RAG], project_root=project)
    assert spec["env"] == {RAG_PIN_VARIABLE: project}
    [unpinned] = codex_mcp_server_specs([RAG])
    assert unpinned["env"] == {}


@pytest.mark.parametrize("project_root", ["${PROJECT_ROOT}", "relative/project", ""])
def test_codex_specs_refuse_an_unusable_pin(project_root: str) -> None:
    with pytest.raises(ConfigError):
        codex_mcp_server_specs([RAG], project_root=project_root)


@pytest.mark.asyncio
async def test_the_declared_channel_is_the_servers_own_root_authority(
    tmp_path: Path,
) -> None:
    """Live: the pinned server addresses the pin, not the directory it launched in.

    The whole axis rests on this being true of the real server rather than assumed
    of it, so the composed spec is handed to a real MCP stdio session: the server
    is launched IN this repository - itself a resolvable workspace - and pinned to
    a directory that is not one. A tool call naming no project of its own must then
    fail naming the PIN, which it can only do if the declared channel outranks the
    working directory the run would otherwise have inherited.

    The spawn environment is built the way the transport builds it: the pin rides
    the spec, and the launching host lifts the spec's env into the child's. That
    hoist is what a session delivery must perform; this test performs it explicitly
    rather than asserting any lane already does.
    """
    launch_root = Path(__file__).resolve().parents[4]
    assert (launch_root / ".vaultspec").is_dir(), (
        "the launch root must itself resolve as a workspace for this test to "
        "distinguish the pin from the working directory"
    )
    project = str(tmp_path)
    assert not (tmp_path / ".vaultspec").exists()

    [spec] = pin_harness_mcp_servers(
        resolve_harness_mcp_servers([RAG]), project_root=project
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST_") and key != RAG_PIN_VARIABLE
    }
    spec_env = spec["env"]
    assert isinstance(spec_env, list)
    for item in spec_env:
        assert isinstance(item, dict)
        name = item["name"]
        value = item["value"]
        assert isinstance(name, str) and isinstance(value, str)
        env[name] = value
    assert env[RAG_PIN_VARIABLE] == project

    command = spec["command"]
    args = spec["args"]
    assert isinstance(command, str)
    assert isinstance(args, list)
    params = StdioServerParameters(
        command=command,
        args=[arg for arg in args if isinstance(arg, str)],
        env=env,
        cwd=launch_root,
    )
    # A real on-disk temporary file, text-wrapped: the stdio client hands the
    # handle to the OS as the child's stderr, so it needs a true file descriptor
    # (the runner's captured stderr has none), and a wedged launch stays
    # diagnosable rather than silent.
    with io.TextIOWrapper(
        tempfile.TemporaryFile(), encoding="utf-8", errors="replace"
    ) as captured_stderr:
        async with asyncio.timeout(_LIVE_PROBE_TIMEOUT_SECONDS):
            async with (
                stdio_client(params, errlog=captured_stderr) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    "search_vault", {"query": "project binding"}
                )
    reported = "\n".join(
        text
        for block in result.content
        if isinstance(text := getattr(block, "text", None), str)
    )
    assert result.is_error, (
        f"the pinned server resolved a project it should not have: {reported}"
    )
    assert project in reported, reported
    assert str(launch_root) not in reported, reported


def _strict_config(specs: list[JsonObject]) -> AcpModelConfig:
    """A minimal claude-family config, which is what makes the surface strict."""
    return AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=None,
        command=["claude"],
        env_vars={},
        session_id=None,
        mcp_servers=specs,
        use_exec=False,
        provider="claude",
        runtime_authority=None,
        acp_backend="node",
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
    )


class TestThePinReachesTheSpawnedChild:
    """The pin is only real if the value arrives where the server reads it.

    On the strict claude lane the advertised surface carries ``${NAME}``
    references rather than values, because the surface is serialized onto the
    CLI argv. The CLI expands each reference from its own process environment at
    config parse time, so a reference whose value was never hoisted expands to
    nothing and the server starts with its pin unset - falling back to the
    directory it inherited while the spec still looks pinned.
    """

    def test_the_hoist_carries_the_pinned_value_the_surface_only_references(
        self, tmp_path: Path
    ) -> None:
        variable = harness_server_root_pin(RAG)
        assert variable is not None

        pinned = pin_harness_mcp_servers(
            [_launch_spec(RAG, _shipped_entry(RAG))], project_root=str(tmp_path)
        )
        surface = session_surface_mcp_servers(_strict_config(pinned))
        first = surface[0]
        assert isinstance(first, dict)
        advertised_env = first["env"]
        assert isinstance(advertised_env, list)
        advertised: dict[str, str] = {}
        for item in advertised_env:
            assert isinstance(item, dict)
            name, value = item["name"], item["value"]
            assert isinstance(name, str) and isinstance(value, str)
            advertised[name] = value
        assert advertised[variable] == f"${{{variable}}}", (
            "the strict surface must carry a reference, never the value"
        )

        hoisted = harness_spawn_env(pinned, exclude=AUTHORING_MCP_SERVER_NAME)
        assert hoisted[variable] == str(tmp_path), (
            "the reference the CLI expands must resolve to the run's project"
        )

    def test_the_authoring_bridge_is_left_to_its_own_gatekeeper(self) -> None:
        """Its values are split off by the validator that admits it."""
        bridge: JsonObject = {
            "name": AUTHORING_MCP_SERVER_NAME,
            "command": "python",
            "args": ["-m", "whatever"],
            "env": [{"name": "VAULTSPEC_AUTHORING_TOKEN", "value": "a-real-token"}],
        }
        hoisted = harness_spawn_env([bridge], exclude=AUTHORING_MCP_SERVER_NAME)
        assert hoisted == {}, "the bridge hoists through its own authority"

    def test_an_unpinned_composition_hoists_nothing(self) -> None:
        """No project means no pin, and therefore no value to carry."""
        unpinned = [_launch_spec(RAG, _shipped_entry(RAG))]
        assert harness_spawn_env(unpinned, exclude=AUTHORING_MCP_SERVER_NAME) == {}
