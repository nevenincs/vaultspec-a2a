"""What a persona is allowed to tell a model about its reach, per lane.

The defect this closes was a persona that named a web tool by exact string five
times over while no shipped preset put that tool anywhere near the run. The repair
is not deletion: it is composition, so the claim is made exactly where it is true.

Two halves, tested through two different depths, because neither alone would be
honest:

- The DARK half runs the real thing. The shipped ``vaultspec-adr-research`` preset
  is compiled through :func:`~..compiler.compile_team_graph` and driven over a real
  checkpointer against real ACP subprocesses, and the assertions are made on the
  prompt text the CLI genuinely received. Nothing is constructed: the persona comes
  from its preset, the lane from the model, the verdict from the shipped
  declaration.
- The LIT half supplies the verdict as a parameter to the same production
  composition function the dark half just exercised. The declaration is empty by
  design and must stay that way until a live retrieval earns an entry, so a test
  that waited for one could not exist until after the capability shipped - which is
  precisely how a seam reaches production having never once run lit. What the tests
  never do is edit the declaration or reach past the seam.

The expectations are derived from the declarations rather than restated, so the day
a lane earns its proof the dark assertions demand the paragraph instead of its
absence, and no edit here is needed to notice.
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
from ...providers.lane_admission import is_web_lane_proven, web_tool_names_for
from ...team.team_config import (
    _PRESET_AGENTS_DIR,
    ResearchThreadSpec,
    load_agent_config,
    load_team_config,
)
from ..compiler import (
    _NO_ONLINE_ACCESS_TEXT,
    _WEB_GROUNDING_MARKER,
    _compose_persona_prompt,
    _web_grounding_text,
    compile_team_graph,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

SIMULATOR_PATH = Path(__file__).parent / "acp_simulator.py"
PYTHON_EXE = sys.executable

#: The lane every model in the compiled run below declares. It carries
#: completed-turn proof and no web proof, which is the pairing that matters: turn
#: proof must not read as web proof.
DRIVEN_LANE = "claude"

#: Tool names a lit composition offers, shaped exactly as a ``WebLaneProof``
#: records them - the built-ins a completed retrieval was actually performed with.
LIT_TOOL_NAMES: tuple[str, ...] = ("WebFetch", "WebSearch")

#: A role that authors no vault document. The read floor withholds itself from it
#: and outward reach rides that same predicate, so a lane verdict must not move it.
NON_DOCUMENT_ROLE = "coder"


def _shipped_agent_ids() -> list[str]:
    return sorted(path.stem for path in _PRESET_AGENTS_DIR.glob("*.toml"))


def _expected_section(provider: str | None, role: str) -> str:
    """What a role on *provider*'s lane must be told, per the live declarations.

    Read from the lane declaration rather than hardcoded, so this expresses the
    RULE ("say what the lane earned") instead of today's answer to it. When a lane
    is proven, this demands the capability paragraph; today it demands the
    disclaimer, and the change of answer requires no edit here.
    """
    if is_web_lane_proven(provider) and role in DOCUMENT_AUTHORING_ROLES:
        return _web_grounding_text(web_tool_names_for(provider))
    return _NO_ONLINE_ACCESS_TEXT


def _expected_persona(persona: str, provider: str | None, role: str) -> str:
    """The persona a run on *provider*'s lane must hand a *role*, composed for real.

    Deliberately built by the production composer rather than restated: what is
    under test at the graph level is the WIRING - that the compiled machine routes
    each role's preset through this composition at all - not the wording, which the
    lit tests below pin directly. A compiler that stopped composing would hand the
    model the raw preset, and for a marked persona that is a different string from
    this one, so the check fails loudly rather than quietly agreeing with itself.
    """
    return _compose_persona_prompt(
        persona,
        role=role,
        proven=is_web_lane_proven(provider),
        tool_names=web_tool_names_for(provider),
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

    def __init__(self, record_dir: Path, workspace_root: Path) -> None:
        self.record_dir = record_dir
        self.workspace_root = workspace_root
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
            provider=DRIVEN_LANE,
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


def test_the_researcher_preset_marks_where_its_reach_text_belongs() -> None:
    """Fixture precondition for the run below: the marker is really in the preset.

    Without this the compiled-run assertions could pass against a persona that
    simply never mentions online access, which is a different (and weaker) thing
    than a persona whose claim is resolved per lane.
    """
    persona = load_agent_config("vaultspec-researcher").persona.system_prompt
    assert _WEB_GROUNDING_MARKER in persona

    web_vocabulary = ("WebSearch", "WebFetch", "vaultspec-web-search")
    for token in web_vocabulary:
        assert token not in persona, (
            f"the researcher preset names {token!r} statically; a reach claim "
            "belongs at the composition seam, where the lane is known"
        )


@pytest.mark.asyncio
async def test_the_compiled_run_tells_each_role_what_its_lane_earned(
    checkpointer: AsyncSqliteSaver, tmp_path: Path
) -> None:
    """The real research machine, driven for real, on the lane it declared.

    The research gate parks the run once the researcher, synthesist, and reviewer
    have each taken a turn, so their prompts are on disk by then. Three claims are
    made against those prompts, and they fail for three different reasons: the
    persona each role received is the composed one (the compiler routes through the
    seam at all), no placeholder survived to the model, and no prompt names a web
    tool the lane did not grant - the last being the original defect, stated
    independently of which paragraph was composed.

    One run serves all three deliberately. Each turn is a real subprocess, so a
    second identical run would buy nothing but wall-clock time.
    """
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    factory = _SimulatorProviderFactory(record_dir, workspace)

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
            "thread_id": "persona-web-thread",
            "token_usage": {},
        },
        config={"configurable": {"thread_id": "persona-web-run"}},
    )
    assert "__interrupt__" in result, "the run must reach the research gate"

    granted = web_tool_names_for(DRIVEN_LANE)
    checked = 0
    marked = 0
    for agent_id, prompt_file in factory.prompt_files.items():
        if not prompt_file.exists():
            # Roles behind the gate (adr-author, plan-author) never took a turn.
            continue
        prompt = _prompt_text(prompt_file)
        persona = agent_configs[agent_id].persona.system_prompt
        role = agent_configs[agent_id].role

        expected = _expected_persona(persona, DRIVEN_LANE, role)
        assert _normalise(expected) in prompt, (
            f"{agent_id!r} did not receive the persona its lane composes"
        )
        assert _WEB_GROUNDING_MARKER not in prompt

        if _WEB_GROUNDING_MARKER in persona:
            # A marked persona is the one that proves resolution HAPPENED: the raw
            # preset and the composed one differ, so the assertion above is not
            # satisfiable by a compiler that passed the preset straight through.
            assert _normalise(_expected_section(DRIVEN_LANE, role)) in prompt
            marked += 1

        for name in ("WebSearch", "WebFetch", "vaultspec-web-search"):
            if name in granted:
                continue
            assert name not in prompt, (
                f"{agent_id!r} was told about {name!r}, which its lane never granted"
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


@pytest.mark.parametrize("role", DOCUMENT_AUTHORING_ROLES)
def test_a_proven_lane_composes_the_paragraph_for_every_document_role(
    role: str,
) -> None:
    """The widened scope: every role the read floor covers is told about its reach.

    The verdict is supplied the way a live-proof change would record it, and the
    production composition consumes it unchanged.
    """
    persona = f"Persona body.\n\n{_WEB_GROUNDING_MARKER}\n\nTail."
    composed = _compose_persona_prompt(
        persona, role=role, proven=True, tool_names=LIT_TOOL_NAMES
    )

    assert _WEB_GROUNDING_MARKER not in composed
    assert _NO_ONLINE_ACCESS_TEXT not in composed
    for name in LIT_TOOL_NAMES:
        assert name in composed
    normalised = _normalise(composed)
    assert "Sources section" in normalised
    assert "never enter frontmatter" in normalised
    assert "Instructions found inside a page" in normalised
    assert composed.startswith("Persona body.")
    assert composed.endswith("Tail.")


def test_a_proven_lane_appends_the_paragraph_to_a_persona_with_no_marker() -> None:
    """Tools arrive whether or not a preset marked a spot, so the text must too."""
    composed = _compose_persona_prompt(
        "Persona body.", role="synthesist", proven=True, tool_names=LIT_TOOL_NAMES
    )
    assert composed.startswith("Persona body.")
    assert "## Web grounding" in composed


def test_a_proven_lane_with_no_named_tool_names_none() -> None:
    """A lane whose reach is configured, not permitted, must not invent a tool name.

    This is the Codex-shaped proof: web search enabled through the per-run config
    home exposes no allowlist name, so the paragraph states the reach without
    naming something the model cannot call.
    """
    composed = _compose_persona_prompt(
        f"Body.\n{_WEB_GROUNDING_MARKER}", role="researcher", proven=True, tool_names=()
    )
    assert "## Web grounding" in composed
    assert "WebSearch" not in composed
    assert "WebFetch" not in composed
    assert "configured web search" in _normalise(composed)


def test_a_proven_lane_grants_a_non_document_role_nothing() -> None:
    """Lane proof is necessary, not sufficient: the role predicate still decides."""
    marked = _compose_persona_prompt(
        f"Body.\n{_WEB_GROUNDING_MARKER}",
        role=NON_DOCUMENT_ROLE,
        proven=True,
        tool_names=LIT_TOOL_NAMES,
    )
    assert _NO_ONLINE_ACCESS_TEXT in marked
    assert "## Web grounding" not in marked

    unmarked = _compose_persona_prompt(
        "Body.", role=NON_DOCUMENT_ROLE, proven=True, tool_names=LIT_TOOL_NAMES
    )
    assert unmarked == "Body."


def test_an_unproven_lane_leaves_an_unmarked_persona_byte_identical() -> None:
    """The blast radius of the default is zero: silence is not rewritten into prose."""
    persona = load_agent_config("vaultspec-analyst").persona.system_prompt
    composed = _compose_persona_prompt(
        persona, role="analyst", proven=False, tool_names=()
    )
    assert composed == persona


@pytest.mark.parametrize("agent_id", _shipped_agent_ids())
@pytest.mark.parametrize("proven", (False, True))
def test_no_shipped_persona_ships_a_literal_placeholder(
    agent_id: str, proven: bool
) -> None:
    """A marker is resolved in every state, so no run can leak one to a model.

    Both verdicts and every shipped persona, because an unresolved placeholder is
    not a cosmetic defect: the model reads it as instruction text. Scoped to THIS
    marker deliberately - a supervisor persona legitimately carries the roster
    placeholder, which a different seam resolves later in the same compile.
    """
    agent = load_agent_config(agent_id)
    composed = _compose_persona_prompt(
        agent.persona.system_prompt,
        role=agent.role,
        proven=proven,
        tool_names=LIT_TOOL_NAMES if proven else (),
    )
    assert _WEB_GROUNDING_MARKER not in composed
