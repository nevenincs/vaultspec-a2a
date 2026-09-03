"""Real-subprocess proof of what a web-proven lane actually permits at spawn.

No mocks: the worker node drives a real ACP subprocess (the protocol simulator)
through ``AcpChatModel``, and every assertion is made against the ``session/new``
params the CLI genuinely received. The sibling module proves the capability is
DARK while no lane carries proof; this one proves the composition seam behind it
is not merely wired but correct - that the day a lane earns its retrieval proof,
the payload carries the exact built-in names, under the decided bounds, for
exactly the roles the read floor already covers and no others.

The lane proof is constructed here rather than declared, and that is deliberate.
The declaration landed empty, so a test that waited for a real entry could not have
existed until the capability shipped - which is precisely how a seam reaches
production having never once run lit. The verdict therefore arrives as a parameter,
the same shape the Codex posture resolver uses: the test supplies a ``WebLaneProof``
exactly as a live-proof change would record one, and the production composition seam
consumes it unchanged. What the test never does is edit the declaration, reach past
the seam, or set an allowlist field directly.

The supplied-proof shape is KEPT now that real entries exist, rather than retired in
favour of them. It covers a tool set no shipped lane has yet earned in full, so the
seam stays proven for names ahead of any lane's proof; the derivation from the real
declaration is exercised separately, on both stances, at the end of this module.

The names it supplies are not written out; they are read off the egress axis, so a
built-in added to or removed from that declaration changes what this test demands
of the payload instead of quietly falling outside it.

The egress axis is enforced in TWO shapes and this module carries the native one,
so the difference is worth stating rather than discovering. On the registry path
the lane verdict lived inside the composition call, which REFUSED an outward-
reaching server the lane had not earned - loudly, because a harness server is an
explicit declaration a person put in a preset, and silently stripping it would
advertise a capability and then withdraw it out of sight. On the native path the
seam has no lane awareness at all: it refuses only a name that never declared its
reach, and the lane verdict is derived by the caller and arrives as data, so an
unearned lane contributes an empty tuple and composes NOTHING. That silence is the
honest shape here, because a built-in is a property of the lane rather than an
advertisement anybody wrote. The consequence for tests is concrete: the native
counterpart of a refusal is DARKNESS on an unproven lane, and it is asserted below
as darkness, not as a raised error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ....authoring.contract import DOCUMENT_AUTHORING_ROLES
from ....providers._acp_mcp import (
    NATIVE_READ_TOOL_NAMES,
    NATIVE_TOOL_EGRESS,
    NATIVE_WEB_TOOL_BOUNDS,
    NativeToolDomainPosture,
    compose_native_read_tools,
)
from ....providers.lane_admission import (
    PROVEN_TURN_LANES,
    PROVEN_WEB_LANES,
    WebLaneProof,
    is_lane_admissible,
    web_tool_names_for,
)
from ...enums import Provider
from ...nodes.worker import create_worker_node

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from ....thread.state import TeamState

SIMULATOR_PATH = Path(__file__).parent.parent / "acp_simulator.py"
PYTHON_EXE = sys.executable

# The web built-ins, read off the declaration that governs them rather than
# restated. Sorted for a stable payload assertion; the composition seam preserves
# caller order, so the test must fix one.
WEB_TOOL_NAMES: tuple[str, ...] = tuple(
    sorted(name for name, reaches in NATIVE_TOOL_EGRESS.items() if reaches)
)

# The same names written out, and the reason both forms exist. Deriving alone is
# what a test SHOULD do - it tracks the declaration instead of drifting from it -
# but it is also how a test quietly stops testing: withdraw the declaration and the
# derived tuple empties, the proof offers nothing, and every assertion below holds
# vacuously against a payload that is merely the read floor. Each test that depends
# on the offer being real therefore asserts this equality first, so the darkening of
# the capability can never read as the darkness the tests were written to allow.
DECIDED_WEB_TOOL_NAMES: tuple[str, ...] = ("WebFetch", "WebSearch")

# Roles that author no vault-document content. The read floor withholds itself
# from them, and outward reach rides that same predicate, so these must come back
# from the spawn with nothing at all.
NON_DOCUMENT_ROLES: tuple[str, ...] = ("coder", "supervisor")

# A lane proof shaped exactly as a live-proof change records one: the pytest node
# id of the run that watched a real retrieval complete, the one-line claim about
# finished work, and the exact built-in names that retrieval was performed with.
PROVEN_LANE = WebLaneProof(
    test=(
        "src/vaultspec_a2a/graph/tests/nodes/test_worker_web_tool_composition.py"
        "::test_a_proven_lane_permits_the_web_builtins_for_every_document_role"
    ),
    proves="the composition seam admits a proven lane's web built-ins onto the "
    "real spawn payload under the decided bounds",
    tool_names=WEB_TOOL_NAMES,
)


def _make_state() -> TeamState:
    return {
        "active_agent": "worker",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Ground this claim")],
        "next": "",
        "thread_id": "test-thread-web-tool-composition",
        "token_usage": {},
    }


def _model(tmp_path: Path, *, session_new: Path, provider: str = "claude"):
    """A real ACP model on *provider*'s lane, recording what the CLI receives.

    The lane is a parameter because the production derivation now has two answers to
    give - a proven lane's names and an unproven lane's nothing - and both must be
    driven through the same spawn rather than one being argued from the other.
    """
    from ....providers.acp_chat_model import AcpChatModel

    return AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response",
            "grounded",
            "--record-session-new",
            str(session_new),
        ],
        # Armed run: an env auth token so config-home isolation engages, as a real
        # armed run always carries its lane token.
        env_vars={"ANTHROPIC_AUTH_TOKEN": "env-auth-token"},
        workspace_root=str(tmp_path),
        provider=provider,
    )


async def _allowed_tools_at_spawn(
    model: BaseChatModel, *, role: str, record_file: Path, agent_id: str = "worker"
) -> list[str]:
    """Run the worker node for real and return the allowlist the CLI received."""
    node = create_worker_node(
        model=model,
        system_prompt="You are grounding a claim.",
        name=agent_id,
        autonomous=True,
        role=role,
    )
    result = await node(_make_state())
    assert isinstance(result, dict)
    assert result["messages"][0].content == "grounded"

    params = json.loads(record_file.read_text(encoding="utf-8"))
    meta = params.get("_meta", {})
    return meta.get("claudeCode", {}).get("options", {}).get("allowedTools", [])


def test_the_supplied_proof_matches_the_shipped_declaration() -> None:
    """Fixture precondition: the test demands what the declarations actually say.

    Without this the whole module could pass against names nothing else in the
    tree recognises, which is the failure mode a hand-written tool list invites.
    """
    assert PROVEN_LANE.tool_names == WEB_TOOL_NAMES
    assert WEB_TOOL_NAMES == DECIDED_WEB_TOOL_NAMES
    assert set(WEB_TOOL_NAMES) == set(NATIVE_WEB_TOOL_BOUNDS)
    assert not set(WEB_TOOL_NAMES) & set(NATIVE_READ_TOOL_NAMES)


@pytest.mark.parametrize("lane", (*Provider, "not-a-lane", None))
def test_only_a_declared_lane_earns_a_web_builtin(
    lane: Provider | str | None,
) -> None:
    """Deny is the default, and the declaration is the only thing that lifts it.

    The native counterpart of the registry path's refusal, expressed as darkness
    because this path does not refuse. Every ``Provider`` this tree ships is driven,
    not a chosen few, so a lane added later is covered the day it is added rather
    than the day somebody remembers to extend a list. The two non-members matter as
    much as the members: an unrecognised string and a model that declared no lane
    must both land on deny rather than fall through, since an unidentifiable lane is
    exactly a lane with no proof.

    Expectations are read FROM the declaration rather than restated, so this keeps
    saying something as lanes earn their proofs; what it pins is that composition
    and declaration never disagree, in either direction.
    """
    proof = PROVEN_WEB_LANES.get(lane) if isinstance(lane, Provider) else None
    assert web_tool_names_for(lane) == (proof.tool_names if proof else ())


def test_completed_turn_proof_does_not_read_as_completed_retrieval_proof() -> None:
    """A lane that may be SERVED is not thereby a lane that may reach outward.

    The two proofs are separate claims over the same lane, and the failure this
    guards is the quiet one: a lane sliding into web activation on the strength of
    its turn admission. Asserted against a lane that really does hold turn proof
    and really does not hold retrieval proof, so the claim has a live subject
    rather than being true of an empty set.
    """
    turn_only = [lane for lane in PROVEN_TURN_LANES if lane not in PROVEN_WEB_LANES]
    assert turn_only, (
        "every turn-proven lane is now web-proven too, so this claim has no subject; "
        "name a lane deliberately or retire the test with a reason"
    )
    for lane in turn_only:
        assert is_lane_admissible(lane)
        assert web_tool_names_for(lane) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", DOCUMENT_AUTHORING_ROLES)
async def test_a_proven_lane_permits_the_web_builtins_for_every_document_role(
    tmp_path: Path, role: str
) -> None:
    """Every role the read floor covers receives the web built-ins, and no more.

    The widened scope is the claim: the capability follows the document-authoring
    role predicate rather than the two discovery roles, so a synthesist or a
    reviewer can verify the material a researcher grounded on.
    """
    assert WEB_TOOL_NAMES == DECIDED_WEB_TOOL_NAMES, "the offer under test is real"
    record_file = tmp_path / "session_new.json"
    composed = compose_native_read_tools(
        _model(tmp_path, session_new=record_file),
        autonomous=True,
        role=role,
        extra_tool_names=PROVEN_LANE.tool_names,
    )

    allowed = await _allowed_tools_at_spawn(
        composed, role=role, record_file=record_file
    )

    assert allowed == [*NATIVE_READ_TOOL_NAMES, *WEB_TOOL_NAMES]


@pytest.mark.asyncio
async def test_the_permitted_names_carry_the_decided_domain_posture(
    tmp_path: Path,
) -> None:
    """A bare name is the blocklist posture; a domain rule would be the other one.

    The CLI reads an allowlist entry as a permission rule, so the posture is
    genuinely observable in the payload rather than only in the declaration: an
    entry scoped as ``WebFetch(domain:...)`` would permit exactly that domain and
    silently invert the decision to the stricter allowlist posture held in reserve.
    """
    assert WEB_TOOL_NAMES == DECIDED_WEB_TOOL_NAMES, "the offer under test is real"
    record_file = tmp_path / "session_new.json"
    composed = compose_native_read_tools(
        _model(tmp_path, session_new=record_file),
        autonomous=True,
        role="researcher",
        extra_tool_names=PROVEN_LANE.tool_names,
    )

    allowed = await _allowed_tools_at_spawn(
        composed, role="researcher", record_file=record_file
    )

    for name in WEB_TOOL_NAMES:
        assert name in allowed
        assert NATIVE_WEB_TOOL_BOUNDS[name].domain_posture is (
            NativeToolDomainPosture.BLOCKLIST
        )
    # No entry is a scoped permission rule, and none is a wildcard.
    assert not [entry for entry in allowed if "(" in entry or "*" in entry]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", NON_DOCUMENT_ROLES)
async def test_a_non_document_role_receives_no_web_builtin(
    tmp_path: Path, role: str
) -> None:
    """The role predicate holds even when a proven lane offers the names.

    Same proof, same lane, same autonomous run - only the role differs, so a
    failure here can only mean the predicate stopped governing outward reach. The
    coder lanes are the exclusion the decision named and never withdrew.
    """
    assert WEB_TOOL_NAMES == DECIDED_WEB_TOOL_NAMES, "the offer under test is real"
    record_file = tmp_path / "session_new.json"
    composed = compose_native_read_tools(
        _model(tmp_path, session_new=record_file),
        autonomous=True,
        role=role,
        extra_tool_names=PROVEN_LANE.tool_names,
    )

    allowed = await _allowed_tools_at_spawn(
        composed, role=role, record_file=record_file
    )

    assert allowed == []


@pytest.mark.asyncio
async def test_a_supervised_run_receives_no_web_builtin(tmp_path: Path) -> None:
    """Human-in-the-loop keeps its permission prompt, proof or no proof.

    The interrupt is the gate there, and it only gates what was never auto-
    permitted, so a name reaching this payload would bypass the human entirely.
    """
    assert WEB_TOOL_NAMES == DECIDED_WEB_TOOL_NAMES, "the offer under test is real"
    record_file = tmp_path / "session_new.json"
    composed = compose_native_read_tools(
        _model(tmp_path, session_new=record_file),
        autonomous=False,
        role="researcher",
        extra_tool_names=PROVEN_LANE.tool_names,
    )

    node = create_worker_node(
        model=composed,
        system_prompt="You are grounding a claim.",
        name="worker",
        autonomous=False,
        role="researcher",
    )
    await node(_make_state())

    params = json.loads(record_file.read_text(encoding="utf-8"))
    meta = params.get("_meta", {})
    assert meta.get("claudeCode", {}).get("options", {}).get("allowedTools", []) == []


@pytest.mark.asyncio
async def test_the_production_derivation_stays_dark_for_an_unproven_lane(
    tmp_path: Path,
) -> None:
    """The same document role, composed the way production composes it, stays dark.

    The tests above SUPPLY the proof; this one supplies none and drives the node
    exactly as the graph does, on a lane the declaration does not carry. It is what
    keeps the lit assertions from reading as a claim that the capability is on
    everywhere: the seam admits a proven lane's names, this lane has none, so the
    shipped payload is the read floor alone.

    The equality guard distinguishes the two ways this could pass. Darkness because
    the lane has earned no names is the state under test; darkness because the
    names were withdrawn from the tree is a different fact wearing its clothes.
    """
    assert WEB_TOOL_NAMES == DECIDED_WEB_TOOL_NAMES
    unproven = next(
        lane for lane in PROVEN_TURN_LANES if lane not in PROVEN_WEB_LANES
    ).value
    record_file = tmp_path / "session_new.json"

    allowed = await _allowed_tools_at_spawn(
        _model(tmp_path, session_new=record_file, provider=unproven),
        role="researcher",
        record_file=record_file,
    )

    assert web_tool_names_for(unproven) == ()
    assert allowed == list(NATIVE_READ_TOOL_NAMES)


@pytest.mark.asyncio
async def test_the_production_derivation_lights_a_proven_lane(
    tmp_path: Path,
) -> None:
    """The production derivation, with nothing supplied, carries a proven lane's names.

    The counterpart the module lacked while the declaration was empty, and the one
    that matters most now that it is not: no proof is handed in, the lane is read
    off the model exactly as the graph reads it, and the spawned CLI receives the
    read floor PLUS precisely what that lane's own proof recorded. Asserted as the
    declaration's own tuple rather than a literal, so a lane that later earns a
    second built-in is covered without an edit, and a lane whose names were widened
    beyond its proof fails here.
    """
    # Not merely the first declared lane: a lane whose reach is CONFIGURED rather
    # than permitted declares no names at all and would make this observation
    # vacuous. The subject has to be a lane that composes something.
    permitting = [lane for lane, proof in PROVEN_WEB_LANES.items() if proof.tool_names]
    assert permitting, (
        "no declared web lane composes an allowlist name, so a lit production "
        "derivation cannot be observed at this seam; every proven lane today "
        "delivers its reach through configuration instead"
    )
    proven = permitting[0]
    earned = PROVEN_WEB_LANES[proven].tool_names
    record_file = tmp_path / "session_new.json"

    allowed = await _allowed_tools_at_spawn(
        _model(tmp_path, session_new=record_file, provider=proven.value),
        role="researcher",
        record_file=record_file,
    )

    assert allowed == [*NATIVE_READ_TOOL_NAMES, *earned]
