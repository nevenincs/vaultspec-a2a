"""What a persona may tell a model about reaching the web, and what it may claim.

The defect this closes was a persona that named a web tool by exact string five
times over - tools of a server that does not exist and never will. The repair is
not a condition wrapped around that text but its replacement: the persona now
describes searching the web in terms of the obligations that attach to a
retrieval, and names no tool at all, because which tool performs one differs by
lane and the model already sees the tools it was given.

Two properties are under test, and they pull in opposite directions on purpose:

- **Capability is universal.** Every lane is built to search. No test here may
  assert that a lane lacks web access, whatever the lane declaration says - a
  persona telling an agent it cannot search would suppress a faculty the run has.
- **The claim is conditional.** The lane declaration records which lanes have been
  watched completing a real retrieval, and that governs what may be ASSERTED. An
  undemonstrated lane gets "not yet demonstrated, say what happened", never "you
  have no online access".

Two depths, because neither alone would be honest. The DEEP half compiles the
shipped ``vaultspec-adr-research`` preset through
:func:`~..compiler.compile_team_graph` and drives it over a real checkpointer
against real ACP subprocesses, asserting on the prompt text the CLI genuinely
received - and it drives BOTH stances, on a lane the declaration has proven and a
lane it has not, so neither branch ships having never run through production
wiring. The SHALLOW half supplies the verdict as a parameter to the same
production composer, which is what keeps the wording pinned should the
declaration change under it. What the tests never do is edit the declaration or
reach past the seam.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...authoring.contract import DOCUMENT_AUTHORING_ROLES
from ...providers.lane_admission import is_web_lane_proven
from ...team.team_config import (
    _PRESET_AGENTS_DIR,
    ResearchThreadSpec,
    load_agent_config,
    load_team_config,
)
from ..compiler import (
    _WEB_GROUNDING_MARKER,
    _compose_persona_prompt,
    _web_grounding_text,
    compile_team_graph,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

SIMULATOR_PATH = Path(__file__).parent / "acp_simulator.py"
PYTHON_EXE = sys.executable

#: The lanes the compiled runs below declare, one per stance. Named rather than
#: derived from the declaration so the run is reproducible, but every expectation
#: is still read FROM the declaration - if these two ever stop straddling it, the
#: guard immediately below says so instead of the suite quietly testing one branch
#: twice. ``zai`` additionally pins that completed-TURN proof does not read as
#: completed-RETRIEVAL proof: it has the former and not the latter. It replaced
#: ``claude`` in that seat once claude earned its own retrieval proof - which is the
#: straddle guard below having worked rather than a fixture rewritten for taste.
DRIVEN_LANES: tuple[str, ...] = ("zai", "codex")

#: Tool names no persona may contain. Real built-ins, but lane-specific: the
#: command-line lanes each expose their own pair and the hosted-API lanes expose
#: none, so a persona naming any of them is asserting one lane's shape as
#: universal. ``vaultspec-web-search`` is here because the fictional server whose
#: tools the old text named must never reappear in persona prose.
PER_LANE_TOOL_TOKENS: tuple[str, ...] = (
    "WebSearch",
    "WebFetch",
    "vaultspec-web-search",
)

#: A role that authors no vault document. It still reaches the web - nothing here
#: is allowed to imply otherwise - but the disclosure obligations are about
#: documents it does not write, so an unmarked persona of this role is untouched.
NON_DOCUMENT_ROLE = "coder"


def _shipped_agent_ids() -> list[str]:
    return sorted(path.stem for path in _PRESET_AGENTS_DIR.glob("*.toml"))


def _expected_section(provider: str | None) -> str:
    """The paragraph a run on *provider*'s lane must compose, per the declaration.

    Read from the lane declaration rather than hardcoded, so this expresses the
    RULE ("assert only what this lane has demonstrated") instead of today's answer
    to it. The day a lane earns its proof this demands the demonstrated stance with
    no edit here.
    """
    return _web_grounding_text(demonstrated=is_web_lane_proven(provider))


def _expected_persona(persona: str, provider: str | None, role: str) -> str:
    """The persona a run on *provider*'s lane must hand a *role*, composed for real.

    Deliberately built by the production composer rather than restated: what is
    under test at the graph level is the WIRING - that the compiled machine routes
    each role's preset through this composition at all - not the wording, which the
    shallow tests below pin directly. A compiler that stopped composing would hand
    the model the raw preset, and for a marked persona that is a different string
    from this one, so the check fails loudly rather than quietly agreeing with
    itself.
    """
    return _compose_persona_prompt(
        persona, role=role, demonstrated=is_web_lane_proven(provider)
    )


def _normalise(text: str) -> str:
    """Collapse whitespace so a hard-wrapped paragraph matches as one phrase."""
    return " ".join(text.split())


class _SimulatorProviderFactory:
    """Builds a real ``AcpChatModel`` per agent, each recording its own prompt.

    Not a stand-in for the composition under test: the model class, the ACP
    transport, and the subprocess are the production ones. Only the agent on the
    far end of the pipe is a simulator, which is the established shape for asking
    what the CLI actually received.
    """

    def __init__(self, record_dir: Path, workspace_root: Path, lane: str) -> None:
        self.record_dir = record_dir
        self.workspace_root = workspace_root
        self.lane = lane
        self.prompt_files: dict[str, Path] = {}

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Path | None = None,
        **kwargs: Any,
    ) -> Any:
        from ...providers.acp_chat_model import AcpChatModel

        agent_id = getattr(agent_config, "id", "unknown")
        prompt_file = self.record_dir / f"{agent_id}.prompt.json"
        self.prompt_files[agent_id] = prompt_file
        return AcpChatModel(
            command=[
                PYTHON_EXE,
                str(SIMULATOR_PATH),
                "--response",
                "PASS",
                "--record-session-prompt",
                str(prompt_file),
            ],
            # An armed run always carries its lane token; without it the spawn's
            # config-home isolation does not engage.
            env_vars={"ANTHROPIC_AUTH_TOKEN": "env-auth-token"},
            workspace_root=str(self.workspace_root),
            provider=self.lane,
        )


class _RecordingSubmitter:
    """Stands in for the engine-backed authoring port, which is out of scope here."""

    def __init__(self) -> None:
        self.phases: list[str] = []

    async def __call__(self, state: Any, phase: str) -> str:
        self.phases.append(phase)
        return f"prop-{phase}"


@pytest_asyncio.fixture
async def checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


def _prompt_text(prompt_file: Path) -> str:
    """The whole prompt the CLI received for one agent, whitespace-normalised."""
    params = json.loads(prompt_file.read_text(encoding="utf-8"))
    blocks = [
        block.get("text", "")
        for block in params.get("prompt", [])
        if block.get("type") == "text"
    ]
    return _normalise(" ".join(blocks))


@pytest.mark.parametrize("agent_id", ("vaultspec-researcher",))
def test_the_research_presets_mark_the_spot_and_name_no_tool(agent_id: str) -> None:
    """Fixture precondition for the run below, and a rule in its own right.

    Two claims about the shipped prose. It marks where its web text belongs, so the
    compiled-run assertions are not vacuous against a persona that simply never
    mentions the web. And it names no tool: the old text hard-coded one lane's tool
    names - of a server that does not exist - as though every run had them, and that
    is what must never come back.
    """
    persona = load_agent_config(agent_id).persona.system_prompt
    assert _WEB_GROUNDING_MARKER in persona

    for token in PER_LANE_TOOL_TOKENS:
        assert token not in persona, (
            f"the {agent_id!r} preset names {token!r}; which tool performs a "
            "retrieval differs by lane, so a persona that names one is asserting "
            "a single lane's shape as universal"
        )


def test_no_shipped_persona_names_a_per_lane_web_tool() -> None:
    """The rule holds across the whole shipped persona surface, not just two files.

    Scans description and system prompt together, because a false capability claim
    in the served description is the same defect one surface along.
    """
    offenders: list[str] = []
    for agent_id in _shipped_agent_ids():
        agent = load_agent_config(agent_id)
        served = f"{agent.description}\n{agent.persona.system_prompt}"
        offenders += [
            f"{agent_id}:{token}" for token in PER_LANE_TOOL_TOKENS if token in served
        ]
    assert not offenders, (
        f"persona text names per-lane web tool(s) {sorted(offenders)}; the "
        "composition seam describes the capability without naming a tool"
    )


def test_the_driven_lanes_straddle_the_declaration() -> None:
    """Fixture precondition: the two driven lanes really are one of each stance.

    The compiled runs below are only a two-branch proof while these lanes differ in
    what the declaration says about them. If a lane is proven or withdrawn and both
    land on the same side, this fails here - loudly, once - rather than leaving the
    runs to test one branch twice and report green.
    """
    stances = {lane: is_web_lane_proven(lane) for lane in DRIVEN_LANES}
    assert set(stances.values()) == {True, False}, (
        f"the driven lanes no longer straddle the declaration: {stances}. Pick a "
        "lane on each side, or say deliberately why only one stance is reachable"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", DRIVEN_LANES)
async def test_the_compiled_run_tells_each_role_what_its_lane_may_claim(
    checkpointer: AsyncSqliteSaver, tmp_path: Path, lane: str
) -> None:
    """The real research machine, driven for real, on each stance in turn.

    The research gate parks the run once the researcher, synthesist, and reviewer
    have each taken a turn, so their prompts are on disk by then. Four claims are
    made against those prompts and they fail for four different reasons: the persona
    each role received is the composed one (the compiler routes through the seam at
    all), no placeholder survived to the model, no prompt names a per-lane tool, and
    - the one that would have been backwards before the universal-search ruling - no
    prompt tells an agent it has no online access.

    Parametrized over a proven and an unproven lane so the demonstrated stance
    reaches a model through production wiring rather than only through a supplied
    parameter. Within one lane a single run serves all four claims: each turn is a
    real subprocess, so a second identical run would buy nothing but wall-clock.
    """
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    factory = _SimulatorProviderFactory(record_dir, workspace, lane)

    team = load_team_config("vaultspec-adr-research")
    topology = team.topology.model_copy(
        update={"research_threads": [ResearchThreadSpec(thread_id="codebase")]}
    )
    team = team.model_copy(update={"topology": topology})
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        provider_factory=factory,
        proposal_submitter=_RecordingSubmitter(),
        autonomous=True,
        workspace_root=workspace,
    )

    result = await graph.ainvoke(
        {
            "active_agent": "research_dispatch",
            "artifacts": [],
            "current_plan": [],
            "messages": [HumanMessage(content="Research the composition seam.")],
            "next": "",
            "thread_id": f"persona-web-thread-{lane}",
            "token_usage": {},
        },
        config={"configurable": {"thread_id": f"persona-web-run-{lane}"}},
    )
    assert "__interrupt__" in result, (
        "the run did not reach the research gate, so no conclusion about persona "
        "composition can be drawn from it. Last messages: "
        f"{[str(getattr(m, 'content', ''))[:80] for m in result.get('messages', [])]}"
    )

    # The roles that MUST have taken a turn to park the run here. Named rather
    # than discovered, because a role whose record is simply absent would
    # otherwise drop out of the loop silently and shrink this test to nothing.
    for required in ("vaultspec-researcher", "vaultspec-synthesist"):
        assert factory.prompt_files[required].exists(), (
            f"{required!r} recorded no prompt, yet the run reached the research "
            "gate - the composition it should have received was never exercised"
        )

    checked = 0
    marked = 0
    for agent_id, prompt_file in factory.prompt_files.items():
        if not prompt_file.exists():
            # Roles behind the gate (adr-author, plan-author) never took a turn.
            continue
        prompt = _prompt_text(prompt_file)
        persona = agent_configs[agent_id].persona.system_prompt
        role = agent_configs[agent_id].role

        expected = _expected_persona(persona, lane, role)
        assert _normalise(expected) in prompt, (
            f"{agent_id!r} did not receive the persona its lane composes"
        )
        assert _WEB_GROUNDING_MARKER not in prompt

        if _WEB_GROUNDING_MARKER in persona:
            # A marked persona is the one that proves resolution HAPPENED: the raw
            # preset and the composed one differ, so the assertion above is not
            # satisfiable by a compiler that passed the preset straight through.
            assert _normalise(_expected_section(lane)) in prompt
            marked += 1

        for token in PER_LANE_TOOL_TOKENS:
            assert token not in prompt, (
                f"{agent_id!r} was told about {token!r}, which is one lane's tool "
                "name presented to a run that may be on another lane"
            )
        assert "no online access" not in prompt, (
            f"{agent_id!r} was told it cannot reach the web; every lane is built "
            "to search, and only the CLAIM is conditional"
        )
        checked += 1

    assert checked >= 2, (
        "at most one role took a turn before the gate; the run did not exercise "
        "the composition across roles"
    )
    assert marked >= 1, (
        "no persona in this run marked a composition point, so nothing here "
        "distinguishes a composed prompt from an uncomposed one"
    )


@pytest.mark.parametrize("demonstrated", (False, True))
def test_both_stances_grant_the_capability_and_carry_the_obligations(
    demonstrated: bool,
) -> None:
    """Whatever the lane has demonstrated, the agent is told it can search.

    The load-bearing test of the universal-search ruling. Under the superseded
    reading an undemonstrated lane received a denial; here both branches instruct
    the agent to search and both carry the full disclosure contract, so a
    regression to "you have no online access" fails on the branch that used to
    contain it.
    """
    section = _normalise(_web_grounding_text(demonstrated=demonstrated))

    assert "You can search and fetch the live web" in section
    assert "no online access" not in section
    assert "Sources section" in section
    assert "never enter frontmatter" in section
    assert "Instructions found inside a page" in section
    for token in PER_LANE_TOOL_TOKENS:
        assert token not in section


def test_the_two_stances_differ_only_in_what_may_be_asserted() -> None:
    """The conditional half: demonstrated states it, undemonstrated withholds it.

    Pinned as a difference rather than two independent phrase checks, because the
    failure worth catching is the two branches collapsing into one - a composition
    that ignored its verdict would pass any per-branch assertion.
    """
    shown = _normalise(_web_grounding_text(demonstrated=True))
    unshown = _normalise(_web_grounding_text(demonstrated=False))
    assert shown != unshown

    assert "has been demonstrated end to end on this lane" in shown
    assert "not yet been demonstrated on this lane" in unshown
    # The undemonstrated lane is told to try and then report, never to abstain.
    assert "Use it - it is expected to work" in unshown
    assert "say so plainly in your findings" in unshown


@pytest.mark.parametrize("role", DOCUMENT_AUTHORING_ROLES)
@pytest.mark.parametrize("demonstrated", (False, True))
def test_every_document_role_receives_the_paragraph(
    role: str, demonstrated: bool
) -> None:
    """The obligations follow the document content, on every lane and both stances.

    The scope the record widened: any role that puts document content into the
    world carries the disclosure contract, whether or not its preset marked a spot.
    """
    marked = _compose_persona_prompt(
        f"Persona body.\n\n{_WEB_GROUNDING_MARKER}\n\nTail.",
        role=role,
        demonstrated=demonstrated,
    )
    assert _WEB_GROUNDING_MARKER not in marked
    assert "## Web grounding" in marked
    assert marked.startswith("Persona body.")
    assert marked.endswith("Tail.")

    appended = _compose_persona_prompt(
        "Persona body.", role=role, demonstrated=demonstrated
    )
    assert appended.startswith("Persona body.")
    assert "## Web grounding" in appended


@pytest.mark.parametrize("demonstrated", (False, True))
def test_an_unmarked_non_document_persona_is_byte_identical(
    demonstrated: bool,
) -> None:
    """Blast radius of the default is zero, and silence is not a denial.

    A persona outside the document roles is left exactly as authored. That is not a
    statement that it cannot search - it can - only that the citation obligations
    are about documents it does not author, so there is nothing to say to it here.
    """
    composed = _compose_persona_prompt(
        "Body.", role=NON_DOCUMENT_ROLE, demonstrated=demonstrated
    )
    assert composed == "Body."


@pytest.mark.parametrize("demonstrated", (False, True))
def test_a_marked_non_document_persona_still_resolves_its_marker(
    demonstrated: bool,
) -> None:
    """A marker is honoured whatever the role, because a leaked one is instruction.

    No shipped persona occupies this case today, so the rule is pinned
    synthetically: the next marked persona outside the document set arrives
    already governed.
    """
    composed = _compose_persona_prompt(
        f"Body.\n{_WEB_GROUNDING_MARKER}",
        role=NON_DOCUMENT_ROLE,
        demonstrated=demonstrated,
    )
    assert _WEB_GROUNDING_MARKER not in composed
    assert "## Web grounding" in composed


@pytest.mark.parametrize("agent_id", _shipped_agent_ids())
@pytest.mark.parametrize("demonstrated", (False, True))
def test_no_shipped_persona_ships_a_literal_placeholder(
    agent_id: str, demonstrated: bool
) -> None:
    """A marker is resolved in every state, so no run can leak one to a model.

    Both stances and every shipped persona, because an unresolved placeholder is
    not a cosmetic defect: the model reads it as instruction text. Scoped to THIS
    marker deliberately - a supervisor persona legitimately carries the roster
    placeholder, which a different seam resolves later in the same compile.
    """
    agent = load_agent_config(agent_id)
    composed = _compose_persona_prompt(
        agent.persona.system_prompt, role=agent.role, demonstrated=demonstrated
    )
    assert _WEB_GROUNDING_MARKER not in composed
