"""No shipped persona advertises an outward-reaching tool the run cannot serve.

The defect this closes is a persona that instructs a model to call a web tool the
composition seam never puts in front of it: the agent burns its turn on a tool
that is simply absent, and the served capability claim is false. That is the same
unenforced-rule failure the lane-admission module exists to refuse, one layer up -
there the claim is a served profile's, here it is a persona's prose.

The check derives BOTH halves from the declarations that decide the runtime, so it
self-updates rather than needing an edit each time a capability moves:

- What counts as advertising an outward-reaching tool comes from the two egress
  declarations - :data:`~..._acp_mcp.NATIVE_TOOL_EGRESS` for the CLI's own
  built-ins and the harness registry's ``network_egress`` axis for the stdio
  servers. Membership in either IS the reach declaration, so nothing here restates
  a tool name that the production code does not already declare as egressing.
- What a persona has EARNED comes from where each kind of tool actually originates.
  A native built-in reaches an allowlist only through a lane carrying recorded
  completed-retrieval proof, so :data:`~...providers.lane_admission.PROVEN_WEB_LANES`
  is the earning declaration and today it is empty. An MCP tool reaches a session
  only because a team's ``[team.harness]`` composed its server, so the earning
  declaration is the shipped team presets that employ the agent.

Prove a lane, or serve an egressing server to a team, and the corresponding persona
text becomes permissible here with no edit to this module.
"""

from __future__ import annotations

import pytest

from ...providers._acp_mcp import _KNOWN_MCP_SERVERS, NATIVE_TOOL_EGRESS
from ...providers.lane_admission import PROVEN_WEB_LANES
from ..team_config import (
    _PRESET_AGENTS_DIR,
    _PRESET_TEAMS_DIR,
    load_agent_config,
    load_team_config,
)


def _shipped_agent_ids() -> list[str]:
    """Every bundled agent preset id, so a new persona is covered on arrival."""
    return sorted(path.stem for path in _PRESET_AGENTS_DIR.glob("*.toml"))


def _shipped_team_ids() -> list[str]:
    """Every bundled team preset id."""
    return sorted(path.stem for path in _PRESET_TEAMS_DIR.glob("*.toml"))


def _egressing_servers() -> frozenset[str]:
    """The registry entries that reach outward, per their own declared axis."""
    return frozenset(
        name
        for name, entry in _KNOWN_MCP_SERVERS.items()
        if entry.get("network_egress") is True
    )


def _server_tokens(server: str) -> frozenset[str]:
    """Every string that names *server* or one of its tools in persona prose.

    Both forms are advertisements: the qualified ``mcp__<server>__<tool>`` name is
    the exact string a model would call, and the bare server name is how a
    description tells the reader where the capability comes from. A persona that
    names either is telling the model the server is there.
    """
    tools = _KNOWN_MCP_SERVERS[server].get("tools", ())
    return frozenset({server, *(f"mcp__{server}__{tool}" for tool in tools)})


def _egressing_native_names() -> frozenset[str]:
    """The CLI built-ins the native egress catalog marks as reaching outward."""
    return frozenset(name for name, reaches in NATIVE_TOOL_EGRESS.items() if reaches)


def _web_vocabulary() -> frozenset[str]:
    """Every token whose presence in a persona is a web-tool advertisement."""
    tokens = set(_egressing_native_names())
    for server in _egressing_servers():
        tokens |= _server_tokens(server)
    return frozenset(tokens)


def _earned_by(agent_id: str) -> frozenset[str]:
    """The web tokens *agent_id* may name, derived from what would really compose.

    Native names are earned by lane proof, which is lane-wide and therefore
    persona-independent. MCP tokens are earned per agent: a server reaches a
    session only through the ``[team.harness]`` of a team that actually employs
    this agent as a worker, so an agent no shipped team serves has earned nothing
    regardless of what the registry knows.
    """
    earned = {name for proof in PROVEN_WEB_LANES.values() for name in proof.tool_names}
    egressing = _egressing_servers()
    for team_id in _shipped_team_ids():
        team = load_team_config(team_id)
        if agent_id not in {worker.agent_id for worker in team.workers}:
            continue
        harness = team.effective_harness()
        if harness is None:
            continue
        for server in harness.mcp_servers:
            if server in egressing:
                earned |= _server_tokens(server)
    return frozenset(earned)


def test_the_vocabulary_this_guard_scans_for_is_not_empty() -> None:
    """The scan has something to find, so a pass below is a real pass.

    A subset assertion over an empty candidate set is vacuously true, which would
    make every persona check silently meaningless the moment a derivation broke.
    This pins the derivation to the declarations instead: every natively egressing
    built-in and every egressing registry server's qualified tool names must be in
    the vocabulary, read from those declarations rather than restated here.
    """
    vocabulary = _web_vocabulary()
    assert vocabulary

    # The native half carries the non-vacuity on its own: the CLI built-ins that
    # reach outward are declared independently of the registry, so this guard keeps
    # scanning every persona for real tokens even with no egressing server at all.
    assert _egressing_native_names() <= vocabulary

    # Said here deliberately, which is what the withdrawn-entry case above always
    # asked for. There is no vaultspec-owned egressing MCP server, and there will
    # not be one: the entry that used to sit here put a first-party name on a
    # third-party package for a server that does not exist. So the MCP half of this
    # vocabulary is EMPTY by decision, not by a broken derivation - and an entry
    # appearing here means one arrived on a merge again, which is exactly how the
    # last one got in. Derived from the registry rather than naming what was
    # removed, so the tripwire cannot rot into a check for one dead string.
    # Exact equality rather than a truthiness check, which also pins the
    # derivation's TYPE: a broken ``_egressing_servers`` returning ``None`` or a
    # list would satisfy ``not ...`` and report green, while this fails. The
    # content assertion and the derivation's contract are the same line.
    assert _egressing_servers() == frozenset(), (
        "the registry declares an egressing entry; no vaultspec-owned egressing "
        "MCP server exists or is planned, so this is either a fiction that arrived "
        "on a merge or a real capability that owes this guard an update"
    )


@pytest.mark.parametrize("agent_id", _shipped_agent_ids())
def test_no_shipped_persona_advertises_an_unearned_web_tool(agent_id: str) -> None:
    """A persona names an outward-reaching tool only where one would compose.

    Scans the whole served persona surface - the description the composer renders
    and the system prompt the model receives - because a false capability claim in
    either one is a claim the run cannot honour.
    """
    agent = load_agent_config(agent_id)
    served_text = f"{agent.description}\n{agent.persona.system_prompt}"

    advertised = {token for token in _web_vocabulary() if token in served_text}
    unearned = advertised - _earned_by(agent_id)

    assert not unearned, (
        f"persona {agent_id!r} advertises web tool(s) {sorted(unearned)} that no "
        "lane proof and no shipped team harness would put in front of the model. "
        "Either land the proof that earns them or remove the text - a persona "
        "instructing a model to call an absent tool is a false capability claim"
    )


def test_every_shipped_persona_is_actually_loaded_by_the_scan() -> None:
    """The parametrization covers the bundled set and nothing silently drops out.

    The guard above is only as wide as its parameter list, and that list is
    globbed. A preset directory that fails to resolve would collect zero cases and
    report green, so the width is asserted rather than assumed.
    """
    agent_ids = _shipped_agent_ids()
    assert len(agent_ids) > 1
    assert "vaultspec-researcher" in agent_ids
    for agent_id in agent_ids:
        assert load_agent_config(agent_id).persona.system_prompt
