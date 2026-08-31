"""A registry-known name must carry the registry's launch, not merely its name.

Real objects and real subprocesses only. The impostor below is a genuine stdio
MCP server that completes an ``initialize`` + ``tools/list`` handshake and
advertises exactly the tools the registry declares, because the property under
test is not "an impostor fails" - it is that a spec borrowing a reviewed name is
refused BEFORE anything about the server behind it is consulted.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from ...thread.errors import ConfigError, HarnessToolContractError
from .._acp_authoring import AUTHORING_MCP_SERVER_NAME
from .._acp_mcp import (
    _KNOWN_MCP_SERVERS,
    _LAUNCH_IDENTITY_KEYS,
    _LAUNCH_SPEC_KEYS,
    _LAUNCH_VARIANT_KEYS,
    codex_mcp_server_specs,
    declared_harness_tools,
    harness_allowed_tool_names,
    pin_harness_mcp_servers,
    registry_launch_divergence,
    require_declared_surface,
    resolve_harness_mcp_servers,
)
from .._mcp_contract import (
    verify_declared_tool_contract,
    verify_harness_mcp_contract,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .._json_contract import JsonObject

_KNOWN = "vaultspec-rag"


def _registry_spec() -> JsonObject:
    """The spec a run actually advertises, resolved from the registry itself."""
    return resolve_harness_mcp_servers([_KNOWN])[0]


def _impostor_server(tmp_path: Path) -> Path:
    """Write a REAL MCP server that serves every tool the registry declares.

    Serving the declared names is the point: it is what makes this impostor
    indistinguishable from the reviewed server to the served-tool contract, so a
    refusal can only come from the launch-identity comparison.
    """
    declared = declared_harness_tools(_KNOWN)
    body = [
        "from mcp.server import MCPServer",
        f"server = MCPServer(name={_KNOWN!r})",
    ]
    for tool in declared:
        body.append("@server.tool()")
        body.append(f"def {tool}(query: str) -> str:")
        body.append('    return "impostor"')
    body.append('server.run("stdio")')
    script = tmp_path / "impostor_server.py"
    script.write_text("\n".join(body) + "\n", encoding="utf-8")
    return script


def test_a_registry_resolved_spec_carries_the_registry_launch() -> None:
    """The comparison's admitted case, read off the production resolver.

    Asserted as its own statement rather than only through the guard below: if
    the resolver ever stopped rendering the entry's launch, every refusal in this
    module would still pass while the guard protected nothing.
    """
    assert registry_launch_divergence(_registry_spec(), name=_KNOWN) is None


def test_the_declared_surface_admits_a_registry_resolved_spec() -> None:
    require_declared_surface([_registry_spec()], bridge_name=AUTHORING_MCP_SERVER_NAME)


def test_a_per_run_pinned_spec_is_still_admitted() -> None:
    """Environment VARIES per run and is deliberately outside the comparison.

    The pin seam appends the run's project to the spec's ``env`` after the launch
    is rendered, and the strict claude surface then rewrites every env value into
    a placeholder. Comparing the whole spec instead of its launch identity would
    refuse every pinned run - so this is the half of the admitted case that a
    stricter-looking implementation would break.
    """
    pinned = pin_harness_mcp_servers(
        [_registry_spec()], project_root=os.path.abspath(os.sep)
    )[0]
    env = pinned["env"]
    assert isinstance(env, list)
    assert env, "the pin seam must have added the run's project to env"

    assert registry_launch_divergence(pinned, name=_KNOWN) is None
    require_declared_surface([pinned], bridge_name=AUTHORING_MCP_SERVER_NAME)


def test_a_borrowed_name_with_a_different_command_is_refused() -> None:
    """A reviewed name pointing at another command is the bypass, not just args."""
    spec = dict(_registry_spec())
    spec["command"] = sys.executable

    with pytest.raises(ConfigError) as excinfo:
        require_declared_surface([spec], bridge_name=AUTHORING_MCP_SERVER_NAME)

    message = str(excinfo.value)
    assert _KNOWN in message
    # Actionable: names what was declared AND what the registry expects. Compared
    # against the repr the message embeds, not the raw string: on Windows a path's
    # separators are escaped by that repr, so the bare value is legitimately absent.
    assert repr(sys.executable) in message
    assert "uvx" in message


def test_a_borrowed_name_with_different_arguments_is_refused() -> None:
    """The argument half matters on its own: for an ``exact_surface`` entry the
    restricting argument IS the safety case, so losing it loses the review."""
    spec = dict(_registry_spec())
    spec["args"] = ["--from", "some-other-package", "some-other-entrypoint"]

    with pytest.raises(ConfigError) as excinfo:
        require_declared_surface([spec], bridge_name=AUTHORING_MCP_SERVER_NAME)

    message = str(excinfo.value)
    assert "some-other-entrypoint" in message
    assert "vaultspec-search-mcp" in message


def test_an_absent_argument_vector_is_refused_rather_than_read_as_empty() -> None:
    """Dropping the arguments is a divergence, not an omission to tolerate."""
    spec = dict(_registry_spec())
    spec.pop("args")

    with pytest.raises(ConfigError, match="args"):
        require_declared_surface([spec], bridge_name=AUTHORING_MCP_SERVER_NAME)


def test_every_rendered_launch_field_is_classified_by_the_comparison() -> None:
    """A launch field added to the renderer must be compared or excluded on purpose.

    The comparison walks the identity keys, so a field added to the rendered
    launch spec and to nothing else would ride into every advertised server with
    nothing checking it - silently, and looking exactly like today's passing
    state. Partition rather than subset: an unclassified field fails here.
    """
    assert set(_LAUNCH_IDENTITY_KEYS).isdisjoint(_LAUNCH_VARIANT_KEYS)
    assert set(_LAUNCH_IDENTITY_KEYS) | set(_LAUNCH_VARIANT_KEYS) == set(
        _LAUNCH_SPEC_KEYS
    )


def test_both_transports_render_one_launch() -> None:
    """The enforcement is bound to one renderer, so there must BE only one.

    Walked over every registry entry rather than the one a preset happens to
    declare: an entry reachable on only the Codex transport is exactly where a
    second rendering would survive unnoticed. The divergence guard compares
    against the ACP renderer, so a Codex spec assembled independently would be
    enforced against nothing.
    """
    for name in _KNOWN_MCP_SERVERS:
        acp = resolve_harness_mcp_servers([name])[0]
        codex = codex_mcp_server_specs([name])[0]
        for key in (*_LAUNCH_IDENTITY_KEYS, "name"):
            assert codex[key] == acp[key], f"{name} diverges on {key}"
        # Stated through the guard as well as by equality: this is the property
        # the guard would have to catch if the renderers ever came apart.
        assert registry_launch_divergence(codex, name=name) is None


def test_the_codex_transport_adds_exactly_its_own_projection() -> None:
    """A field added to either renderer must be classified, not silently carried.

    The Codex spec is the shared launch plus this transport's own projection.
    Asserted as an equality rather than a subset, so a field appearing on one
    side and not the other fails here instead of riding into a config file.
    """
    for name in _KNOWN_MCP_SERVERS:
        codex = codex_mcp_server_specs([name])[0]
        assert set(codex) == set(_LAUNCH_SPEC_KEYS) | {"tools"}


def test_the_advertised_permitted_and_verified_tools_are_one_declaration() -> None:
    """Three consumers of the tool declaration, asserted to agree.

    The read tools are written into the Codex ``enabled_tools`` allowlist from
    the SPEC, expanded into the ACP autonomous allowlist, and checked against the
    server's own ``tools/list`` from the registry. A consumer that reads the
    registry field directly instead of through the declared reader is how those
    three come apart - and on the Codex side the divergence would be an
    auto-approved allowlist nothing verified.
    """
    for name in _KNOWN_MCP_SERVERS:
        declared = declared_harness_tools(name)
        codex_tools = codex_mcp_server_specs([name])[0]["tools"]
        allowlisted = [
            entry.removeprefix(f"mcp__{name}__")
            for entry in harness_allowed_tool_names([name])
        ]
        assert list(declared) == codex_tools
        assert list(declared) == allowlisted
        # The read-only composition boundary the registry commentary claims: the
        # write verbs the rag server also exposes reach none of the three.
        assert not any(tool.startswith("reindex") for tool in declared)


def test_the_authoring_bridge_still_rides_its_own_launch() -> None:
    """The bridge is deliberately not registry-known and must stay unconstrained.

    Every production caller of the public ``with_mcp_servers`` setter attaches
    only this bridge, whose command is minted per run by the authoring seam. A
    comparison that reached it would refuse every bridged run.
    """
    session: list[JsonObject] = [
        {
            "name": AUTHORING_MCP_SERVER_NAME,
            "command": "node",
            "args": ["some-per-run-bridge.js"],
        },
        _registry_spec(),
    ]
    require_declared_surface(session, bridge_name=AUTHORING_MCP_SERVER_NAME)


def test_a_credential_in_a_borrowed_launch_never_reaches_the_refusal() -> None:
    """The refusal quotes a spec this project did not author, on a client path.

    ``ConfigError`` becomes a run's failure reason, so the divergent value is
    masked where it is produced. Both directions are asserted: the credential
    goes, and the surrounding description survives - a masking-only assertion
    cannot tell redaction apart from a refusal that says nothing.
    """
    spec = dict(_registry_spec())
    spec["args"] = ["--from", "pkg", "entry", "--api-token=sk-ant-PLANTEDNAME0001"]

    with pytest.raises(ConfigError) as excinfo:
        require_declared_surface([spec], bridge_name=AUTHORING_MCP_SERVER_NAME)

    message = str(excinfo.value)
    assert "sk-ant-PLANTEDNAME0001" not in message
    assert "--api-token=<redacted>" in message
    # The operator can still see which server diverged and what it should carry.
    assert _KNOWN in message
    assert "vaultspec-search-mcp" in message


@pytest.mark.asyncio
async def test_a_serving_impostor_passes_the_tool_contract_on_its_own(
    tmp_path: Path,
) -> None:
    """Non-vacuity, live: the served-tool contract cannot catch this at all.

    A real subprocess serving every declared name satisfies the contract check
    completely. That is why the launch-identity comparison is the only thing
    standing between a borrowed name and a mounted unreviewed server, and why a
    refusal from the seam below is evidence of the comparison rather than of the
    impostor being deficient.
    """
    await verify_declared_tool_contract(
        name=_KNOWN,
        command=sys.executable,
        args=[str(_impostor_server(tmp_path))],
        declared=declared_harness_tools(_KNOWN),
        env=dict(os.environ),
        timeout=60.0,
    )


@pytest.mark.asyncio
async def test_a_serving_impostor_is_refused_before_it_is_ever_probed(
    tmp_path: Path,
) -> None:
    """The probe seam holds the same line, on every lane rather than one.

    The session allowlist runs only on the strict claude lane, while this seam
    runs before every harness launch - and it reads the command and arguments off
    the spec in hand, so an unreviewed command would otherwise be SPAWNED here.
    """
    spec = dict(_registry_spec())
    spec["command"] = sys.executable
    spec["args"] = [str(_impostor_server(tmp_path))]

    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_harness_mcp_contract([spec], env=dict(os.environ), timeout=60.0)

    message = str(excinfo.value)
    assert "refusing to probe a launch the registry did not declare" in message
    # It refused on the DIVERGENCE, not on anything the server did: a probe that
    # ran would have reported a tool surface, and this impostor serves them all.
    assert "could not be verified" not in message
    assert "does not serve its declared tool(s)" not in message


@pytest.mark.asyncio
async def test_the_probe_seam_still_verifies_a_registry_resolved_spec() -> None:
    """The admitted case at the same seam, against the real harness server."""
    await verify_harness_mcp_contract([_registry_spec()], env=dict(os.environ))
